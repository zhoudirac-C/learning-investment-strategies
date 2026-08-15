#!/usr/bin/env python
"""M2 影子双轨复盘盲判入口（cron 工作日 22:00 调用）。

自含：补当日指数 daily 收盘价（index_klines 表）→ 等个股 K 线就绪
（3 次 × 2 分钟）→ daily.run(当日)。
节假日/无新数据自然退出 0。手动补跑: python scripts/shadow_daily.py --date 2026-08-12
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
from investment_engine.shadow.status import write_status
from qing_investment.kline_cache import init_db


def ensure_indexes(db_path=None) -> None:
    """补齐当日指数 daily 收盘价到 index_klines 表（东财→腾讯兜底）。

    盲判指数统一读 index_klines 表（2026-08-13 起），故此处不再写
    stocks_kline 的 IDX 别名，改调 update_index_klines_intraday 的 daily 更新。
    """
    from scripts.update_index_klines_intraday import INDICES, update_one

    for code in INDICES:
        try:
            update_one(code, "daily")
        except Exception as e:  # noqa: BLE001 - 单指数失败不阻断
            print(f"[warn] 指数 {code} daily 补齐失败: {str(e)[:80]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="影子双轨复盘盲判任务")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--config-dir", default="config/stock_monitor")
    parser.add_argument("--db", default="infra/data/kline_cache.db")
    parser.add_argument("--wait-retries", type=int, default=3)
    parser.add_argument("--force", action="store_true",
                        help="强制重跑当日盲判（数据修复场景）；会作废该日旧归因并 retract 其 open 提案")
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

    summary = run(args.date, config_dir=Path(args.config_dir), db_path=db,
                  force=args.force)
    print("[daily]", summary)
    print("[status]", write_status())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
