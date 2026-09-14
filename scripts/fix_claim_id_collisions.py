"""修复 claim id 冲突（2026-09-14）。

背景：同一天多个 source 文件各自从 001 编号 + 提取时 id 计数器未递增，
导致 82 个 id 冲突 / 83 条 claim 被覆盖（Neo4j/Qdrant 后写覆盖先写）。

策略（用户拍板）：
- 冲突 id 中保留原名者：**优先"文件名 stem 与 id 前缀一致"的 claim**
  （口径B，语义归属正确）；无归属文件时退回国文件名序（最先出现）
- 其余按该顺序加 -dup1 / -dup2 后缀
- 引用方全部指向"保留原名"那条 → YAML 引用字段无需改动

实现：文本级替换，只改 id 定义行。默认 dry-run。
"""
from __future__ import annotations
import argparse, json, pathlib, re
from collections import defaultdict

REPO = pathlib.Path("/home/ubuntu/learning-investment-strategies")
CLAIMS = REPO / "knowledge/claims"


def iter_claims(fp):
    import yaml
    try:
        d = yaml.safe_load(fp.read_text(encoding="utf-8"))
    except Exception:
        return []
    if d is None:
        return []
    if isinstance(d, list):
        items = d
    elif isinstance(d, dict):
        items = d["claims"] if isinstance(d.get("claims"), list) else [d]
    else:
        return []
    return [(i, c) for i, c in enumerate(items) if isinstance(c, dict) and c.get("id")]


def sort_key(cid: str, item):
    """口径B：归属文件优先，其次文件名字典序。"""
    fname, idx, _c = item
    stem = pathlib.Path(fname).stem
    prefix = cid.rsplit("-", 1)[0]
    is_home = 1 if (stem == prefix or stem.startswith(prefix)) else 0
    return (0 if is_home else 1, fname, idx)


def build_plan():
    occ = defaultdict(list)
    for fp in sorted(CLAIMS.glob("claim-*.yaml")):
        for idx, c in iter_claims(fp):
            occ[c["id"]].append((fp.name, idx, c))

    dupes = {k: v for k, v in occ.items() if len(v) > 1}

    # 每条待改 claim：以 (file, idx, old_id) 为键，避免同文件同 id 歧义
    plan = defaultdict(list)   # filename -> [(idx, old, new)]
    for cid, lst in dupes.items():
        ordered = sorted(lst, key=lambda it: sort_key(cid, it))
        for i, (fname, idx, c) in enumerate(ordered):
            if i == 0:
                continue
            plan[fname].append((idx, cid, f"{cid}-dup{i}"))

    total = sum(len(v) for v in plan.values())
    return plan, len(dupes), total, dupes


ID_LINE = re.compile(r"^(\s*-?\s*id:\s*)([\"']?)([^\"'\s#]+)([\"']?)(\s*(?:#.*)?)$")


def apply_plan(plan, apply: bool):
    """按 (file, claim序号) 精确替换 id 行。

    做法：解析文件得到 claim 顺序 -> 逐行扫描 id 定义行 -> 按出现序号映射。
    """
    import yaml
    files_changed = 0
    total = 0

    for fname, changes in sorted(plan.items()):
        fp = CLAIMS / fname
        text = fp.read_text(encoding="utf-8")

        # 该文件内：claim 序号 -> 新 id
        idx2new = {idx: new for (idx, old, new) in changes}
        # 该文件内的旧 id 集合（用于识别）
        olds = {old for (_, old, _) in changes}

        new_lines = text.split("\n")
        claim_seq = -1
        n_local = 0

        for i, line in enumerate(new_lines):
            m = ID_LINE.match(line)
            if m:
                claim_seq += 1          # 每遇到一个 id 定义行，claim 序号 +1
                if claim_seq not in idx2new:
                    continue
                prefix, q1, val, q2, tail = m.groups()
                if val not in olds:
                    continue            # 安全检查：值必须匹配期望的旧 id
                new_val = idx2new[claim_seq]
                new_lines[i] = f"{prefix}{q1}{new_val}{q2}{tail}"
                total += 1
                n_local += 1

        changed = "\n".join(new_lines)
        if changed != text:
            files_changed += 1
            if apply:
                fp.write_text(changed, encoding="utf-8")
        elif idx2new:
            print(f"  ⚠️ {fname}: 计划改 {len(idx2new)} 条但未命中任何行")

    return files_changed, total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    plan, n_ids, n_claims, dupes = build_plan()
    print(f"冲突 id: {n_ids} | 待重编号 claim: {n_claims} | 涉及文件: {len(plan)}")

    # 展示归属判定结果（对照口径A的差异数）
    import pathlib as _p
    diff = 0
    for cid, lst in dupes.items():
        a = sorted(lst, key=lambda it: it[0])[0]
        b = sorted(lst, key=lambda it: sort_key(cid, it))[0]
        if (a[0], a[1]) != (b[0], b[1]):
            diff += 1
    print(f"（口径B 与 口径A 结果不同的冲突 id: {diff}）")

    if not args.apply:
        print("\n=== DRY-RUN 预览（前12条）===")
        shown = 0
        for fname, changes in sorted(plan.items()):
            for (idx, old, new) in changes:
                print(f"  {fname} #{idx}: {old} -> {new}")
                shown += 1
                if shown >= 12:
                    break
            if shown >= 12:
                break

    nf, nt = apply_plan(plan, args.apply)
    mode = "已写入" if args.apply else "DRY-RUN（未写）"
    print(f"\n[{mode}] 改动文件: {nf} | 重编号 claim: {nt}")


if __name__ == "__main__":
    main()
