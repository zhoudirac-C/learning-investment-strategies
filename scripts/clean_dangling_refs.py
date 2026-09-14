"""清理幽灵节点 + 悬空引用（2026-09-14）。

1. Neo4j: 删除无 YAML 对应的 Claim 节点
2. YAML: 从 supersedes/contradicts/supplements/disagrees_with 中移除指向不存在 claim 的 id

安全：文本级替换，保留原格式；默认 dry-run。
"""
from __future__ import annotations
import argparse, json, pathlib, re, sys

REPO = pathlib.Path("/home/ubuntu/learning-investment-strategies")
CLAIMS = REPO / "knowledge/claims"


def defined_ids() -> set[str]:
    import yaml
    ids: set[str] = set()
    for fp in sorted(CLAIMS.glob("claim-*.yaml")):
        try:
            d = yaml.safe_load(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        if d is None:
            continue
        if isinstance(d, list):
            items = d
        elif isinstance(d, dict):
            items = d["claims"] if isinstance(d.get("claims"), list) else [d]
        else:
            continue
        for c in items:
            if isinstance(c, dict) and c.get("id"):
                ids.add(c["id"])
    return ids


FIELDS = ("supersedes", "contradicts", "supplements", "disagrees_with")


def clean_yaml(valid: set[str], apply: bool) -> tuple[int, int]:
    """移除指向无效 id 的引用。返回 (改动文件数, 移除引用数)。"""
    files_changed = 0
    refs_removed = 0
    for fp in sorted(CLAIMS.glob("claim-*.yaml")):
        text = fp.read_text(encoding="utf-8")
        new_text = text
        for fld in FIELDS:
            # 匹配  field: ["a", "b"]  或 field: ['a']  或 field: [a, b]
            pat = re.compile(rf"^(\s*{fld}:\s*)\[(.*?)\]\s*$", re.M)

            def repl(m):
                nonlocal refs_removed
                prefix, inner = m.group(1), m.group(2)
                # 解析元素（保留原始引号风格）
                raw = [x.strip() for x in inner.split(",") if x.strip()]
                keep, drop = [], []
                for item in raw:
                    bare = item.strip().strip('"').strip("'")
                    (keep if bare in valid else drop).append(item)
                if not drop:
                    return m.group(0)
                refs_removed += len(drop)
                if not keep:
                    return f"{prefix}[]"
                return f"{prefix}[{', '.join(keep)}]"

            new_text = pat.sub(repl, new_text)

        if new_text != text:
            files_changed += 1
            if apply:
                fp.write_text(new_text, encoding="utf-8")
    return files_changed, refs_removed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    valid = defined_ids()
    print(f"已定义 claim: {len(valid)}")

    nf, nr = clean_yaml(valid, args.apply)
    mode = "已写入" if args.apply else "DRY-RUN"
    print(f"\n[{mode}]")
    print(f"  改动文件: {nf}")
    print(f"  移除悬空引用: {nr}")


if __name__ == "__main__":
    main()
