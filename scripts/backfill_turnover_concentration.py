#!/usr/bin/env python3
"""回补历史日期的全A成交集中度快照（东财日K接口逐股拉取）。

背景：fetch_turnover_concentration.py 只能拉「当日」clist 快照，
10-14 / 10-15 因网络中断失败且无法用当日接口回补。

方案：用 push2his 日K接口（klt=101, fqt=0, fields2=f51,f57）逐股拉历史成交额，
口径已实测与 clist 的 f6 完全一致（0.000% 差异，400 只比对）。

用法：
    .venv/bin/python scripts/backfill_turnover_concentration.py --dates 2026-10-14 2026-10-15
    .venv/bin/python scripts/backfill_turnover_concentration.py --dates 2026-10-14 --force
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "infra" / "data" / "turnover_concentration"

# 与 fetch_turnover_concentration.py 保持完全一致的股票池口径
# （沪深主板+创业板+科创板；不含北交所）
CLIST_URL = ("https://push2.eastmoney.com/api/qt/clist/get?pn={pn}&pz=100&po=1&np=1"
             "&fltt=2&invt=2&fid=f6&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
             "&fields=f12,f13")
KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"

MIN_COVERAGE = 4000  # 与 fetch 脚本一致的覆盖度护栏


def fetch_universe() -> list[dict]:
    """取股票池代码表（用当日 clist 的 total/diff 拿到全量 code+mkt）。"""
    rows: list[dict] = []
    pn, total = 1, None
    while True:
        r = requests.get(CLIST_URL.format(pn=pn), timeout=20)
        r.raise_for_status()
        data = r.json().get("data") or {}
        if total is None:
            total = data.get("total", 0)
        page = data.get("diff") or []
        if not page:
            break
        rows.extend(page)
        if len(rows) >= total:
            break
        pn += 1
        time.sleep(0.3)
    return rows


def fetch_hist_amount(secid: str, day: str) -> float | None:
    """拉单只股票某日成交额（元）。"""
    try:
        r = requests.get(
            KLINE_URL,
            params={"secid": secid, "klt": 101, "fqt": 0,
                    "beg": day.replace("-", ""), "end": day.replace("-", ""),
                    "fields1": "f1", "fields2": "f51,f57"},
            timeout=15,
        )
        kl = (r.json().get("data") or {}).get("klines") or []
        if not kl:
            return None
        return float(kl[0].split(",")[1])
    except Exception:
        return None


def compute(amounts: list[float], top_pct: float = 0.05) -> dict | None:
    """top_pct 口径集中度（与 shadow/concentration.py 同算法）。"""
    vals = sorted([a for a in amounts if a and a > 0], reverse=True)
    if not vals:
        return None
    n = len(vals)
    top_n = max(1, int(n * top_pct))
    total = sum(vals)
    top = sum(vals[:top_n])
    return {
        "n_stocks": n,
        "top_n": top_n,
        "top_amount_yi": round(top / 1e8, 1),
        "total_amount_yi": round(total / 1e8, 1),
        "concentration_pct": round(top / total * 100, 2),
    }


def backfill_day(day: str, universe: list[dict], force: bool) -> int:
    out = OUT_DIR / f"{day}.json"
    if out.exists() and not force:
        print(f"已存在，跳过: {out}")
        return 0

    secids = [f"{x['f13']}.{x['f12']}" for x in universe]
    print(f"{day}: 拉取 {len(secids)} 只股票历史成交额 ...")
    amounts: list[float] = []
    fails = 0
    with ThreadPoolExecutor(max_workers=12) as ex:
        for amt in ex.map(lambda s: fetch_hist_amount(s, day), secids):
            if amt is None:
                fails += 1
            else:
                amounts.append(amt)

    result = compute(amounts)
    if result is None:
        print(f"ERROR: {day} 无有效数据", file=sys.stderr)
        return 1
    print(f"  成功 {len(amounts)} / 失败 {fails} / 覆盖 {result['n_stocks']}")
    if result["n_stocks"] < MIN_COVERAGE:
        print(f"ERROR: 覆盖异常 n={result['n_stocks']}（预期 {MIN_COVERAGE}+），拒绝落盘",
              file=sys.stderr)
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"date": day, **result}, ensure_ascii=False), encoding="utf-8")
    print(f"✅ {day}: 集中度 {result['concentration_pct']}% "
          f"(top{result['top_n']}/{result['n_stocks']}, 全市场 {result['total_amount_yi']}亿)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", nargs="+", required=True, help="YYYY-MM-DD，可多个")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    universe = fetch_universe()
    print(f"股票池: {len(universe)} 只")
    rc = 0
    for day in args.dates:
        rc |= backfill_day(day, universe, args.force)
    return rc


if __name__ == "__main__":
    sys.exit(main())
