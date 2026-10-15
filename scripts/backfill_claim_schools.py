#!/usr/bin/env python3
"""一次性回填：为存量 claims YAML 写入 school 字段（由 up_id 推导）。

双学派架构 P1（docs/design/dual-school-architecture.md）。

实现方式：YAML 结构级读写（safe_load → 改 dict → safe_dump），
避免文本级插入破坏缩进/锚点。会保留 key 顺序（sort_keys=False）。

- 只新增 school 字段，不动其他内容
- 幂等：重复运行结果一致
- 未登记 up_id 跳过并打印

用法：
    python scripts/backfill_claim_schools.py --dry-run
    python scripts/backfill_claim_schools.py
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from qing_investment.schools import school_of_up  # noqa: E402

CLAIMS_DIR = Path(__file__).resolve().parents[1] / "knowledge" / "claims"


class _Dumper(yaml.SafeDumper):
    """保持字面块风格的中文长文本可读性。"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    stats: Counter[str] = Counter()
    unknown: Counter[str] = Counter()
    changed_files = 0
    errors: list[str] = []

    for path in sorted(CLAIMS_DIR.rglob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            errors.append(f"{path.name}: YAML 解析失败 {exc}")
            continue

        is_wrapped = isinstance(data, dict) and "claims" in data
        claims = data["claims"] if is_wrapped else data
        if not isinstance(claims, list) or not claims:
            continue

        changed = False
        for c in claims:
            if not isinstance(c, dict):
                continue
            up_id = str(c.get("up_id", "") or "")
            if c.get("school"):
                stats["already"] += 1
                continue
            sid = school_of_up(up_id)
            if sid is None:
                unknown[up_id] += 1
                stats["unknown"] += 1
                continue
            c["school"] = sid
            stats[sid] += 1
            changed = True

        if changed and not args.dry_run:
            path.write_text(
                yaml.dump(
                    data,
                    Dumper=_Dumper,
                    allow_unicode=True,
                    sort_keys=False,
                    default_flow_style=False,
                    width=1000,
                ),
                encoding="utf-8",
            )
        if changed:
            changed_files += 1

    print("── 回填统计 ──")
    for k, v in stats.most_common():
        print(f"  {k}: {v}")
    print(f"  改动文件数: {changed_files}")
    if unknown:
        print("── 未登记 up_id（需补 config/schools.yaml）──")
        for k, v in unknown.most_common():
            print(f"  {k}: {v}")
    if errors:
        print("── 解析错误 ──")
        for e in errors[:10]:
            print(f"  {e}")
    if args.dry_run:
        print("(dry-run，未写入)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
