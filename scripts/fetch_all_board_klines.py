#!/usr/bin/env python3
"""全量 THS 行业板块日K拉取（板块情绪温度计的数据层）。

akshare stock_board_industry_name_ths() 拿 90 个行业板块名单，
stock_board_industry_index_ths 逐个拉日K，增量合并落盘
infra/data/board_klines_all/industry_<name>.json。

首跑回填 500 自然日（≈340 交易日，够 250 日分位用）；之后每次拉 150 自然日增量。
与产业链的 infra/data/board_klines/ 目录隔离，互不影响。
手动: .venv/bin/python scripts/fetch_all_board_klines.py [--backfill] [--backfill-days N] [--only 板块名 ...]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "infra" / "data" / "board_klines_all"
SLEEP_S = 1.2
RETRY = 2


def list_boards() -> list[str]:
    import akshare as ak
    df = ak.stock_board_industry_name_ths()
    return [str(n) for n in df["name"].tolist()]


def out_path(board: str) -> Path:
    safe = board.replace("/", "_").replace("(", "_").replace(")", "_")
    return OUT_DIR / f"industry_{safe}.json"


def fetch_board(board: str, lookback_days: int) -> list[dict]:
    import akshare as ak
    end = dt.date.today()
    start = end - dt.timedelta(days=lookback_days)
    df = ak.stock_board_industry_index_ths(
        symbol=board, start_date=start.strftime("%Y%m%d"), end_date=end.strftime("%Y%m%d"))
    return [{"date": str(r["日期"])[:10], "open": float(r["开盘价"]),
             "high": float(r["最高价"]), "low": float(r["最低价"]),
             "close": float(r["收盘价"]), "volume": float(r["成交量"]),
             "amount": float(r["成交额"])} for _, r in df.iterrows()]


def merge(path: Path, new_bars: list[dict]) -> int:
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    by_date = {b["date"]: b for b in old}
    for b in new_bars:
        by_date[b["date"]] = b
    merged = [by_date[k] for k in sorted(by_date)]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged, ensure_ascii=False), encoding="utf-8")
    return len(merged)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true", help="回填模式（默认 500 自然日，--backfill-days 可改）")
    ap.add_argument("--backfill-days", type=int, default=500)
    ap.add_argument("--only", nargs="*", default=None)
    args = ap.parse_args()
    lookback = args.backfill_days if args.backfill else 150

    boards = list_boards()
    if args.only:
        boards = [b for b in boards if b in set(args.only)]
    print(f"板块数: {len(boards)}, lookback={lookback}d", file=sys.stderr)

    ok = fail = 0
    for i, b in enumerate(boards, 1):
        err = None
        for _ in range(RETRY + 1):
            try:
                bars = fetch_board(b, lookback)
                n = merge(out_path(b), bars)
                ok += 1
                print(f"[{i}/{len(boards)}] {b}: {n} bars", file=sys.stderr)
                break
            except Exception as e:  # noqa: BLE001
                err = e
                time.sleep(3)
        else:
            fail += 1
            print(f"[{i}/{len(boards)}] {b}: WARN {str(err)[:80]}", file=sys.stderr)
        time.sleep(SLEEP_S)
    print(f"完成: ok={ok} fail={fail}", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
