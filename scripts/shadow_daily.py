#!/usr/bin/env python
"""M2 影子双轨每日入口（cron 15:40 调用）。

自含：补当日指数 K → 等 K 线就绪（3 次 × 2 分钟）→ daily.run(当日)。
节假日/无新数据自然退出 0。手动补跑: python scripts/shadow_daily.py --date 2026-08-07
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from investment_engine.shadow.daily import run
from investment_engine.shadow.predict import has_fresh_data
from qing_investment.kline_cache import init_db, save_klines
from scripts.fetch_index_klines import INDEXES, fetch_index_tencent


def ensure_indexes(db_path=None) -> None:
    for alias, full_code in INDEXES.items():
        kl = fetch_index_tencent(full_code)
        if kl:
            save_klines(alias, kl, db_path=db_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="影子双轨每日任务")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--config-dir", default="config/stock_monitor")
    parser.add_argument("--db", default="infra/data/kline_cache.db")
    parser.add_argument("--wait-retries", type=int, default=3)
    args = parser.parse_args(argv)

    db = Path(args.db)
    init_db(db_path=db)
    ensure_indexes(db_path=db)

    for attempt in range(1, args.wait_retries + 1):
        if has_fresh_data(args.date, db_path=db):
            break
        print(f"[wait] {args.date} 尚无新 K 线（{attempt}/{args.wait_retries}）")
        if attempt < args.wait_retries:
            time.sleep(120)
    else:
        print(f"[skip] {args.date} 无新数据（节假日或拉取失败），退出")
        return 0

    summary = run(args.date, config_dir=Path(args.config_dir), db_path=db)
    print("[daily]", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
