#!/usr/bin/env python3
"""30min 长周期数据拼接：TDX 分页拉取 → 缓存 /tmp/tdx_30m/{code}.json"""
import sys, os, json
sys.path.insert(0, "/home/ubuntu/learning-investment-strategies/src")
from qing_investment.tdx_market.market import TdxMarket

os.makedirs("/tmp/tdx_30m", exist_ok=True)
m = TdxMarket()

def fetch_30m(code, pages=8, per=800):
    out = []
    for p in range(pages):
        rows = m.get_kline(code, "30min", count=800, start=p*800)
        if not rows:
            break
        out = rows + out  # start 越大越早
        print(f"  page {p}: {rows[0]['datetime']} ~ {rows[-1]['datetime']} ({len(rows)})")
    # 去重排序
    seen, dedup = set(), []
    for r in out:
        if r["datetime"] not in seen:
            seen.add(r["datetime"])
            dedup.append({"date": r["datetime"], "open": float(r["open"]), "close": float(r["close"]),
                          "high": float(r["high"]), "low": float(r["low"]), "volume": float(r["volume"] or 0)})
    dedup.sort(key=lambda x: x["date"])
    return dedup

for code in ("sh515980", "sz159381"):
    print(f"== {code} ==")
    data = fetch_30m(code, pages=8)
    json.dump(data, open(f"/tmp/tdx_30m/{code}.json", "w"))
    print(f"  total {len(data)}: {data[0]['date']} ~ {data[-1]['date']}")
