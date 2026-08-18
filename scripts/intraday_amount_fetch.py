#!/usr/bin/env python
"""分时量能落盘入口（建议 cron 工作日 15:35 收盘后调用）。

用 TDX 拉 sh000001+sz399001 的 60min K 线，算四点曲线（10:30/11:30/14:00/15:00
累计成交额 + 预估全天 + 形态分档），落盘 infra/data/intraday_amount/{yyyymmdd}.json，
供盲判包历史回放读取（与 dataset._load_intraday_amount 实时拉取同款计算）。
非交易时段跑：TDX 返回最近交易日的 4 根 K 线，--date 缺省时按数据实际交易日落盘。
幂等：目标文件已存在则跳过，--force 覆盖重算。
退出码：0 成功；1 TDX 不可达或当日数据不足。

手动: .venv/bin/python scripts/intraday_amount_fetch.py [--date 2026-08-17]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from investment_engine import intraday_amount


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="分时量能落盘（TDX 60min 四点曲线）")
    parser.add_argument("--date", default=None,
                        help="YYYY-MM-DD（默认取数据实际交易日，cron 收盘后跑即当日）")
    parser.add_argument("--out-root", default="infra/data/intraday_amount")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    data = intraday_amount.compute_intraday_amount()
    if data is None:
        print("[intraday-amount] TDX 不可达或当日 60min K 线不足，未落盘",
              file=sys.stderr)
        return 1
    day = args.date or data["date"]
    out_root = Path(args.out_root)
    target = out_root / f"{day.replace('-', '')}.json"
    if target.exists() and not args.force:
        print(f"[intraday-amount] 已存在，跳过: {target}")
        return 0
    path = intraday_amount.save_intraday_amount(day, data, out_root)
    print(f"[intraday-amount] 分时量能 → {path}  数据日={data['date']}"
          f" 尾盘实际={data['尾盘实际全天_亿']:.0f}亿 形态={data['形态']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
