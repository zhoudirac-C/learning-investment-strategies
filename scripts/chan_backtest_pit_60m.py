#!/usr/bin/env python3
"""30min 缠论 point-in-time 回测（每日收盘 30min bar 截断重跑）"""
import sys, json
sys.path.insert(0, "/home/ubuntu/learning-investment-strategies/src")
sys.path.insert(0, "/home/ubuntu/learning-investment-strategies/third_party/chanpy")
from chan_engine.core.engine import RecursionEngine
from chan_engine.spec.model import Bar

FEE = 0.0001
STARTS = {"sz159381": "2025-03-24", "sh515980": "2024-10-08"}
END = "2026-09-04"

def run_engine(rows):
    bars = [Bar(ts=i, o=r["open"], h=r["high"], l=r["low"], c=r["close"],
                vol=r.get("volume") or 0.0) for i, r in enumerate(rows)]
    return RecursionEngine().run(bars)

def bsp_keys(chart):
    return {(x.idx, str(x.dir), x.bstype) for x in chart.bsp if x.sure}

code = sys.argv[1]
rows = json.load(open(f"/tmp/tdx_60m/{code}_qfq.json"))
dates = [r["date"] for r in rows]
win = [i for i, d in enumerate(dates) if STARTS[code] <= d[:10] <= END]
i0, i1 = win[0], win[-1]

# 每日收盘 30min bar 索引
day_end = {t for t in range(i0, i1) if rows[t + 1]["date"][:10] != rows[t]["date"][:10]}
day_end.add(i1 - 1)

cash, shares = 1_000_000.0, 0
entry = defense = None
trades = []
seen = bsp_keys(run_engine(rows[:i0 + 1]))
print(f"start {code}: {i0}~{i1}, day_end={len(day_end)}", flush=True)
for t in range(i0, i1):
    if t not in day_end:
        continue
    chart = run_engine(rows[:t + 1])
    cur = bsp_keys(chart)
    new = cur - seen
    seen = cur
    buy = [k for k in new if "DOWN" in k[1] and k[2] in (1, 2, 3)]
    sell = [k for k in new if "UP" in k[1] and k[2] in (1, 2, 3)]
    stop = shares > 0 and rows[t]["close"] < defense
    nt = t + 1
    o = rows[nt]["open"]
    if buy and shares == 0:
        idx = buy[0][0]
        shares = int(cash * (1 - FEE) / o / 100) * 100
        cash -= shares * o * (1 + FEE)
        entry, defense = o, rows[idx]["low"]
        trades.append(("BUY", dates[nt], o, f"b{buy[0][2]}", defense))
    elif shares > 0 and (sell or stop):
        cash += shares * o * (1 - FEE)
        trades.append(("SELL_sig" if sell else "SELL_stop", dates[nt], o, entry, (o / entry - 1) * 100))
        shares = 0

end_px = rows[i1]["close"]
final = (cash + shares * end_px) / 1e6 - 1
base = end_px / rows[i0]["close"] - 1
print(f"\n===== {code} 30min 缠论  {dates[i0][:10]} → {dates[i1][:10]} =====")
for t in trades:
    if t[0] == "BUY":
        print(f"  {t[1]}  BUY @{t[2]:.3f} ({t[3]}, 防守线={t[4]:.3f})")
    else:
        print(f"  {t[1]}  {t[0]} @{t[2]:.3f}  盈亏 {t[4]:+.2f}%")
nb = len([x for x in trades if x[0] == "BUY"])
print(f"交易{nb}笔 | 缠论: {final*100:+.2f}% vs 持有 {base*100:+.2f}% | 差 {(final-base)*100:+.2f}pct")
