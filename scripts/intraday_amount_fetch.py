#!/usr/bin/env python
"""分时量能落盘入口（建议 cron 工作日 15:35 收盘后调用）。

用**统一数据源模块** `qing_investment.marketdata` 拉 sh000001+sz399001 的 60min
K 线（东财优先——腾讯/新浪 bar 的 amount 恒为 0.0），算四点曲线
（10:30/11:30/14:00/15:00 累计成交额 + 预估全天 + 形态分档），
落盘 infra/data/intraday_amount/{yyyymmdd}.json，
供盲判包历史回放读取（与 dataset._load_intraday_amount 实时拉取同款计算）。

数据源变更（2026-09-23）：原直连 TDX `get_kline`，而 TDX `CapMainKline`
已被服务端按接口粒度封禁 → 本脚本长期 exit 1 未落盘，是 pre-run 量能字段
缺失（进而被 LLM 拼出 87173482 亿）的根因。现走统一模块。

非交易时段跑：数据源返回最近交易日的 4 根 K 线，--date 缺省时按数据实际交易日落盘。
幂等：目标文件已存在则跳过，--force 覆盖重算。
退出码：0 成功；1 全源不可达/成交额全空/当日数据不足。

手动: .venv/bin/python scripts/intraday_amount_fetch.py [--date 2026-08-17]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from investment_engine import intraday_amount


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="分时量能落盘（统一模块 60min 四点曲线）")
    parser.add_argument("--date", default=None,
                        help="YYYY-MM-DD（默认取数据实际交易日，cron 收盘后跑即当日）")
    parser.add_argument("--out-root", default="infra/data/intraday_amount")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    data = intraday_amount.compute_intraday_amount(day=args.date)
    if data is None:
        print("[intraday-amount] 全源不可达/成交额全空/当日 60min K 线不足，未落盘"
              "（数据源：marketdata 统一模块；东财间歇封禁时会落到此分支）",
              file=sys.stderr)
        return 1
    day = data["date"]
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
