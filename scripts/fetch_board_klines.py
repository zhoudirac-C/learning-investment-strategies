#!/usr/bin/env python3
"""THS 板块指数日K拉取（产业链量价快照的数据层）。

读取 config/stock_monitor/chain_board_map.yaml 的链→板块映射，
经 akshare 拉同花顺板块指数日K（概念 stock_board_concept_index_ths /
行业 stock_board_industry_index_ths），增量合并落盘到
infra/data/board_klines/<type>_<board>.json。

bar 格式: {"date","open","high","low","close","volume","amount"}（date 升序）。
断点续拉：每次固定拉最近 ~150 个自然日再按 date 去重合并。
失败纪律：单板块失败只记 warn 不中断；全部失败 exit 1（cron 侧可见）。

手动: .venv/bin/python scripts/fetch_board_klines.py [--only BOARD ...]
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
MAP_PATH = ROOT / "config" / "stock_monitor" / "chain_board_map.yaml"
OUT_DIR = ROOT / "infra" / "data" / "board_klines"
LOOKBACK_DAYS = 150
SLEEP_S = 1.2
RETRY = 2


def load_map() -> dict:
    import yaml
    with open(MAP_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)["chains"]


def out_path(board_type: str, board: str) -> Path:
    safe = board.replace("/", "_").replace("(", "_").replace(")", "_")
    return OUT_DIR / f"{board_type}_{safe}.json"


def fetch_board(board: str, board_type: str) -> list[dict]:
    import akshare as ak
    end = dt.date.today()
    start = end - dt.timedelta(days=LOOKBACK_DAYS)
    sd, ed = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
    if board_type == "concept":
        df = ak.stock_board_concept_index_ths(symbol=board, start_date=sd, end_date=ed)
    else:
        df = ak.stock_board_industry_index_ths(symbol=board, start_date=sd, end_date=ed)
    bars = []
    for _, r in df.iterrows():
        bars.append({
            "date": str(r["日期"])[:10],
            "open": float(r["开盘价"]), "high": float(r["最高价"]),
            "low": float(r["最低价"]), "close": float(r["收盘价"]),
            "volume": float(r["成交量"]), "amount": float(r["成交额"]),
        })
    bars.sort(key=lambda b: b["date"])
    return bars


def merge(old: list[dict], new: list[dict]) -> list[dict]:
    by_date = {b["date"]: b for b in old}
    by_date.update({b["date"]: b for b in new})
    return [by_date[d] for d in sorted(by_date)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=None, help="只拉指定板块名")
    args = ap.parse_args()

    chain_map = load_map()
    # 板块去重（多链可共享同一板块）
    boards: dict[tuple[str, str], list[str]] = {}
    for cid, m in chain_map.items():
        key = (m["type"], m["board"])
        boards.setdefault(key, []).append(cid)
    if args.only:
        boards = {k: v for k, v in boards.items() if k[1] in args.only}

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ok, failed = 0, []
    for (btype, board), cids in sorted(boards.items()):
        bars = None
        for attempt in range(RETRY + 1):
            try:
                bars = fetch_board(board, btype)
                break
            except Exception as e:  # noqa: BLE001
                print(f"[warn] {board} 第{attempt+1}次拉取失败: {e!r}"[:180], flush=True)
                time.sleep(3)
        if not bars:
            failed.append(board)
            continue
        p = out_path(btype, board)
        old = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
        merged = merge(old, bars)
        p.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[ok] {board}({btype}) bars={len(merged)} 最新={merged[-1]['date']} "
              f"← 链: {','.join(cids)}", flush=True)
        ok += 1
        time.sleep(SLEEP_S)

    print(f"[done] 成功 {ok}/{ok+len(failed)}" + (f" 失败: {failed}" if failed else ""))
    if ok == 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
