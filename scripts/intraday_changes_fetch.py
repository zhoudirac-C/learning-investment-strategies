#!/usr/bin/env python
"""盘中异动拉取入口（cron 工作日 15:40 调用）：akshare 22 种异动类型落盘。

幂等：当日目标文件已存在则跳过，--force 覆盖重拉。
退出码：0 成功；1 拉取失败（全部类型失败才判失败，部分失败如实标注）。

手动: .venv/bin/python scripts/intraday_changes_fetch.py [--date 2026-08-12]
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from investment_engine import intraday_changes as ic


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="盘中异动拉取（akshare 东财盘口异动）")
    parser.add_argument("--date", default=date.today().strftime("%Y%m%d"),
                        help="YYYYMMDD（默认今日）")
    parser.add_argument("--out-root", default="infra/data/intraday_changes")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    out_root = Path(args.out_root)
    target = out_root / f"{args.date}.json"
    if target.exists() and not args.force:
        print(f"[changes] 已存在，跳过: {target}")
        return 0

    try:
        data = ic.build_intraday_changes(args.date)
    except Exception as e:
        print(f"[changes] 拉取失败: {e}", file=sys.stderr)
        return 1
    path = ic.save_intraday_changes(data, out_root, args.date)
    counts = data["counts"]
    ok = sum(1 for v in counts.values() if isinstance(v, int))
    failed = [k for k, v in counts.items() if v is None]
    tail = f" 失败类型={','.join(failed)}" if failed else ""
    print(f"[changes] 盘中异动 → {path}  类型={ok}/{len(ic.CHANGE_TYPES)}  "
          f"总条目={data['total']}{tail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
