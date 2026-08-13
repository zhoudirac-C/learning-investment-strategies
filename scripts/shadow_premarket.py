#!/usr/bin/env python
"""M2 影子双轨早盘盲判入口（cron 工作日 9:28 调用）。

盘前预测当日：用前一交易日收盘数据 + 隔夜外盘，落盘
evals/shadow/predictions/{day}-pre.json。stage_hit 由当日复盘盲判（22:00）回填。

手动: python scripts/shadow_premarket.py --date 2026-08-13
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from investment_engine.shadow.premarket import run_predict_premarket
from qing_investment.kline_cache import init_db


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="影子双轨早盘盲判任务")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--config-dir", default="config/stock_monitor")
    parser.add_argument("--db", default="infra/data/kline_cache.db")
    parser.add_argument("--overnight-root", default="infra/data/overnight_us")
    args = parser.parse_args(argv)

    db = Path(args.db)
    init_db(db_path=db)

    rec = run_predict_premarket(
        args.date, config_dir=args.config_dir, db_path=db,
        overnight_root=args.overnight_root)
    print("[premarket]", rec)
    return 0 if rec.get("status") != "error" else 1


if __name__ == "__main__":
    raise SystemExit(main())
