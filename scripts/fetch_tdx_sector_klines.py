#!/usr/bin/env python3
"""从 TDX 增量拉取板块成分股 K 线落库（供盲判方向识别 + 评分使用）。

背景：盲判方向识别已切到 TDX 概念板块（269 个），但评分需要成分股的
历史 K 线算 5 日超额。本地 kline_cache 只覆盖 stock_pool 的 ~200 只，
对 TDX 成分股覆盖率仅 4%。本脚本用 TDX get_kline 增量补齐。

策略（避免一次性 5364 只 × 2s ≈ 180 分钟）：
  1. 只拉「盲判方向池」实际会用到的板块成分股（默认全部概念板块去重）
  2. 断点续拉：已拉过且最新日期 >= 阈值的跳过
  3. 单连接复用，失败重试，支持 --limit 限制本次只数

用法:
    PYTHONPATH=src .venv/bin/python scripts/fetch_tdx_sector_klines.py --limit 300

产物: 写入 infra/data/kline_cache.db（stocks_kline 表）
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from qing_investment.kline_cache import save_klines, init_db  # noqa: E402
from qing_investment.tdx_market import TdxMarket  # noqa: E402

DAYS = 90  # 每只拉 90 根日 K（覆盖评分 horizon=5 的需求）
DELAY = 0.2  # 单只间隔（TDX 单连接复用，实测 ~2s/只，这里不加长延迟）


def _load_target_codes(sector_json: Path, db_path: Path, only_codes=None) -> list[str]:
    """目标股票码 = sector_members.json 全部成分股去重，排除本地已有最新数据的。"""
    import json
    import sqlite3

    if only_codes:
        codes = sorted(set(only_codes))
    else:
        d = json.loads(sector_json.read_text(encoding="utf-8"))
        codes = sorted({c for v in d.get("concept", {}).values() for c in v})

    # 已有数据且最新交易日足够新的跳过（断点续拉）
    conn = sqlite3.connect(str(db_path))
    existing = {}
    for code, max_date in conn.execute(
        "SELECT code, MAX(trade_date) FROM stocks_kline GROUP BY code"
    ).fetchall():
        existing[code.split(".")[0]] = max_date
    conn.close()

    todo = []
    skipped = 0
    for c in codes:
        md = existing.get(c)
        # 有数据且最新日期在最近 10 天内 → 跳过
        if md and md >= "2026-08-01":
            skipped += 1
            continue
        todo.append(c)
    print(f"[tdx-klines] 目标 {len(codes)} 只，已最新 {skipped} 只，待拉 {len(todo)} 只")
    return todo


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="本次最多拉取只数（0=全部）")
    ap.add_argument("--only", nargs="*", default=None, help="只拉指定代码（空格分隔）")
    args = ap.parse_args()

    repo = Path(__file__).resolve().parent.parent
    sector_json = repo / "config" / "stock_monitor" / "sector_members.json"
    db_path = repo / "infra" / "data" / "kline_cache.db"

    init_db(db_path=db_path)
    codes = _load_target_codes(sector_json, db_path, args.only)
    if args.limit:
        codes = codes[: args.limit]

    mkt = TdxMarket()
    ok = fail = 0
    t0 = time.time()
    for i, code in enumerate(codes):
        try:
            klines = mkt.get_kline(code, category="daily", count=DAYS)
            if klines:
                save_klines(code, klines, db_path=db_path)
                ok += 1
            else:
                fail += 1
        except Exception as e:  # noqa: BLE001
            fail += 1
            if fail <= 5:
                print(f"  ❌ {code}: {str(e)[:60]}")
        if (i + 1) % 50 == 0:
            el = time.time() - t0
            print(f"  [{i+1}/{len(codes)}] 成功{ok} 失败{fail} 耗时{el:.0f}s")
        time.sleep(DELAY)

    el = time.time() - t0
    print(f"[tdx-klines] 完成: 成功 {ok} 失败 {fail} / 共 {len(codes)}，耗时 {el:.0f}s")
    return 0 if ok > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
