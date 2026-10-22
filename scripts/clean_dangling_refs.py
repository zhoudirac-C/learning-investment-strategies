"""清理幽灵节点 + 悬空引用（2026-09-14）。

1. YAML: 从 supersedes/contradicts/supplements/disagrees_with 中移除指向不存在 claim 的 id
2. Neo4j: 删除无 YAML 对应的 Claim 节点（--neo4j 开启；默认仅报告）

安全：文本级替换，保留原格式；默认 dry-run。

2026-10-22 修复：原实现只匹配行内数组 `field: [a, b]`，而库内主流写法是
block sequence（`field:` + 缩进 `- id`），导致悬空引用统计长期恒为 0（假阴性）。
本次补齐 block sequence 支持，并修正 docstring 与实现不符的问题。
"""
from __future__ import annotations
import argparse, json, pathlib, re, sys

REPO = pathlib.Path("/home/ubuntu/learning-investment-strategies")
CLAIMS = REPO / "knowledge/claims"
ARCHIVE = REPO / "archive/schools"


def _iter_claim_items(d) -> list:
    """兼容仓库内三种 YAML 结构：
    1. claims: 包装
    2. 顶层 list
    3. 单 claim 裸 dict
    """
    if d is None:
        return []
    if isinstance(d, list):
        items = d
    elif isinstance(d, dict):
        items = d["claims"] if isinstance(d.get("claims"), list) else ([d] if "id" in d else [])
    else:
        items = []
    return [c for c in items if isinstance(c, dict) and c.get("id")]


def defined_ids(include_archive: bool = True) -> set[str]:
    """主库 + archive 中已定义的 claim id。

    archive 是学派隔离区（watchlist school），其 claim 仍存在于仓库，
    引用它们不算悬空；但它们也不在主库，Neo4j/Qdrant 不应有对应节点。
    """
    import yaml
    ids: set[str] = set()
    paths = sorted(CLAIMS.glob("claim-*.yaml"))
    if include_archive:
        paths += sorted(ARCHIVE.glob("**/*.yaml"))
    for fp in paths:
        try:
            d = yaml.safe_load(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        for c in _iter_claim_items(d):
            ids.add(c["id"])
    return ids


def main_library_ids() -> set[str]:
    """仅主库 knowledge/claims/ 中的 id（用于 Neo4j 幽灵判定）。"""
    return defined_ids(include_archive=False)


FIELDS = ("supersedes", "contradicts", "supplements", "disagrees_with")


def _split_inline(inner: str) -> list[str]:
    """拆分行内数组内容，保留原始引号风格。"""
    return [x.strip() for x in inner.split(",") if x.strip()]


def _bare(item: str) -> str:
    return item.strip().strip('"').strip("'")


def clean_inline(valid: set[str], text: str, fld: str) -> tuple[str, int]:
    """处理  field: ["a", "b"]  行内数组形式。"""
    pat = re.compile(rf"^(\s*{fld}:\s*)\[(.*?)\]\s*$", re.M)
    removed = 0

    def repl(m):
        nonlocal removed
        prefix, inner = m.group(1), m.group(2)
        keep, drop = [], []
        for item in _split_inline(inner):
            (keep if _bare(item) in valid else drop).append(item)
        if not drop:
            return m.group(0)
        removed += len(drop)
        if not keep:
            return f"{prefix}[]"
        return f"{prefix}[{', '.join(keep)}]"

    new_text = pat.sub(repl, text)
    return new_text, removed


def clean_block(valid: set[str], text: str, fld: str) -> tuple[str, int]:
    """处理 block sequence 形式：

        supersedes:
          - claim-20260817-002
          - claim-20260817-003

    这是库内主流写法（block sequence 远多于行内数组），
    2026-09 前的实现只匹配行内数组，导致悬空引用统计长期为 0（假阴性）。
    """
    # 匹配 field: 后跟 0 个或多个 "  - item" 行，直到遇到非列表行
    pat = re.compile(
        rf"^(\s*){fld}:\s*\n((?:[ \t]*-[ \t]+[^\n]*\n?)+)", re.M
    )

    def repl(m):
        indent, block = m.group(1), m.group(2)
        lines = block.splitlines(keepends=True)
        keep_lines = []
        for ln in lines:
            stripped = ln.strip()
            if not stripped.startswith("-"):
                keep_lines.append(ln)
                continue
            item = stripped[1:].strip()
            if not item or _bare(item) in valid:
                keep_lines.append(ln)
        if len(keep_lines) == len(lines):
            return m.group(0)
        if not keep_lines:
            return ""  # 整个列表清空 → 删掉 field 行及其列表
        return f"{indent}{fld}:\n" + "".join(keep_lines)

    new_text = pat.sub(repl, text)
    removed_total = 0
    for m in pat.finditer(text):
        for ln in m.group(2).splitlines():
            stripped = ln.strip()
            if stripped.startswith("-"):
                item = stripped[1:].strip()
                if item and _bare(item) not in valid:
                    removed_total += 1
    return new_text, removed_total


def clean_yaml(valid: set[str], apply: bool) -> tuple[int, int]:
    """移除指向无效 id 的引用。返回 (改动文件数, 移除引用数)。"""
    files_changed = 0
    refs_removed = 0
    for fp in sorted(CLAIMS.glob("claim-*.yaml")):
        text = fp.read_text(encoding="utf-8")
        new_text = text
        for fld in FIELDS:
            new_text, n_inline = clean_inline(valid, new_text, fld)
            new_text, n_block = clean_block(valid, new_text, fld)
            refs_removed += n_inline + n_block

        if new_text != text:
            files_changed += 1
            if apply:
                fp.write_text(new_text, encoding="utf-8")
    return files_changed, refs_removed


def clean_neo4j_ghosts(valid_main: set[str], apply: bool) -> tuple[int, int, int]:
    """删除 Neo4j 中无主库 YAML 对应的 Claim 节点。

    返回 (幽灵数, 已删除数, 剩余 Claim 节点数)；依赖不可用时返回 (-1, 0, -1)。
    archive 中的 claim 属于学派隔离区，不在主库 → 在 Neo4j 中即为幽灵。
    """
    try:
        import sys
        sys.path.insert(0, str(REPO / "src"))
        from qing_investment.agent.config import settings
        from neo4j import GraphDatabase
    except Exception as e:
        print(f"  [Neo4j] 跳过（依赖不可用: {e}）")
        return -1, 0, -1

    try:
        drv = GraphDatabase.driver(
            settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))
        with drv.session() as s:
            ids = [r["id"] for r in s.run("MATCH (c:Claim) RETURN c.id AS id").data()]
            ghosts = [i for i in ids if i not in valid_main]
            if apply and ghosts:
                for i in range(0, len(ghosts), 500):
                    chunk = ghosts[i:i + 500]
                    s.run("MATCH (c:Claim) WHERE c.id IN $ids DETACH DELETE c", ids=chunk)
            after = s.run("MATCH (c:Claim) RETURN count(*) AS c").single()["c"]
        drv.close()
        return len(ghosts), (len(ghosts) if apply else 0), after
    except Exception as e:
        print(f"  [Neo4j] 跳过（连接失败: {e}）")
        return -1, 0, -1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--neo4j", action="store_true",
                    help="同时检查/清理 Neo4j 幽灵节点（默认仅报告）")
    ap.add_argument("--no-archive", action="store_true",
                    help="不把 archive 中的 claim 视为已定义（archive 引用也视为悬空）")
    args = ap.parse_args()

    valid = defined_ids(include_archive=not args.no_archive)
    main_ids = main_library_ids()
    print(f"已定义 claim（主库+archive）: {len(valid)}")
    print(f"  主库 knowledge/claims: {len(main_ids)}")

    nf, nr = clean_yaml(valid, args.apply)
    mode = "已写入" if args.apply else "DRY-RUN"
    print(f"\n[{mode}] YAML 悬空引用")
    print(f"  改动文件: {nf}")
    print(f"  移除悬空引用: {nr}")

    if args.neo4j:
        ghosts, deleted, after = clean_neo4j_ghosts(main_ids, args.apply)
        print(f"\n[{mode}] Neo4j 幽灵节点")
        if ghosts >= 0:
            print(f"  幽灵节点: {ghosts}")
            print(f"  已删除: {deleted}")
            print(f"  剩余 Claim 节点: {after}")


if __name__ == "__main__":
    main()
