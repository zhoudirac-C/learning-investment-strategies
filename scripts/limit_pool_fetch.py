#!/usr/bin/env python
"""涨停梯队拉取入口（cron 工作日 15:37 调用）：涨停池+炸板池+晋级率/反包+断板推导。

幂等：当日目标文件已存在则跳过，--force 覆盖重拉。
退出码：0 成功；1 拉取失败。

手动: .venv/bin/python scripts/limit_pool_fetch.py [--date 2026-08-11]
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from investment_engine import limit_pool


def _prev_calendar_day(day: str) -> str:
    d = datetime.strptime(day, "%Y%m%d") - timedelta(days=1)
    return d.strftime("%Y%m%d")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="涨停梯队拉取（东财涨停池/炸板池）")
    parser.add_argument("--date", default=date.today().strftime("%Y%m%d"),
                        help="YYYYMMDD（默认今日）")
    parser.add_argument("--out-root", default="infra/data/limit_pool")
    parser.add_argument("--prev", default=None,
                        help="前一交易日 YYYYMMDD（用于晋级率/反包；默认自动取落盘中最近一日）")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    out_root = Path(args.out_root)
    target = out_root / f"{args.date}.json"
    if target.exists() and not args.force:
        print(f"[limit] 已存在，跳过: {target}")
        return 0

    prev = args.prev
    if not prev:
        # 自动找落盘中最近的上一日（<= 前推 7 天）
        d = _prev_calendar_day(args.date)
        for _ in range(7):
            if (out_root / f"{d}.json").exists():
                prev = d
                break
            d = _prev_calendar_day(d)

    try:
        data = limit_pool.build_limit_pool(args.date, out_root, prev_day=prev)
    except limit_pool.LimitPoolError as e:
        print(f"[limit] 拉取失败: {e}", file=sys.stderr)
        return 1
    # C5 断板推导：有前一日落盘则填充 broken_boards（akshare 失败不阻断）
    limit_pool.add_broken_boards(data, out_root, args.date, prev_day=prev)
    path = limit_pool.save_limit_pool(data, out_root, args.date)
    cmp_ = data["compare"]
    tail = ""
    if cmp_.get("promotion_rate") is not None:
        tail = f"  晋级率={cmp_['promotion_rate']:.0%} 反包={len(cmp_['fanbao'])}只"
    bb = data.get("broken_boards")
    bb_txt = (f" 断板={len(bb)}只" if bb is not None
              else f" 断板=NA({data.get('broken_boards_note', '')})")
    print(f"[limit] 涨停梯队 → {path}  涨停={data['zt_count']} 炸板={data['zb_count']}"
          f" 高度={data['max_lbc']}板 竞价一字={len(data['auction_sealed'])}只{tail}{bb_txt}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
