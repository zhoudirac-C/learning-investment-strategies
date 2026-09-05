#!/usr/bin/env python3
"""sh512400 日线双引擎 + 30/60min 七轨（快速版，缠论只跑日线）"""
import sys, json, subprocess
sys.path.insert(0, "/home/ubuntu/learning-investment-strategies/src")
sys.path.insert(0, "/home/ubuntu/learning-investment-strategies/third_party/chanpy")
sys.path.insert(0, "/home/ubuntu/.hermes/skills/finance/bollinger-7track/scripts")
from chan_engine.core.engine import RecursionEngine
from chan_engine.spec.model import Bar
from boll7 import calc_boll7

FEE = 0.0001
START = "2024-10-08"
END = "2026-09-04"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

def fetch_qfq(code, n=800):
    out = subprocess.run(["curl","-s","--max-time","10","-A",UA,
        f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,{n},qfq"], capture_output=True)
    d = json.loads(out.stdout)["data"][code]
    k = d.get("qfqday") or d.get("day")
    return [{"date": r[0], "open": float(r[1]), "close": float(r[2]),
             "high": float(r[3]), "low": float(r[4]), "volume": float(r[5]) if len(r)>5 else 0.0} for r in k]

def run_engine(rows):
    bars = [Bar(ts=i, o=r["open"], h=r["high"], l=r["low"], c=r["close"],
                vol=r.get("volume") or 0.0) for i, r in enumerate(rows)]
    return RecursionEngine().run(bars)

def bsp_keys(chart):
    return {(x.idx, str(x.dir), x.bstype) for x in chart.bsp if x.sure}

# ---------- 日线缠论 ----------
def bt_chan_day(rows):
    dates = [r["date"] for r in rows]
    win = [i for i, d in enumerate(dates) if START <= d <= END]
    i0, i1 = win[0], win[-1]
    cash, shares = 1_000_000.0, 0
    entry = defense = None
    trades = []
    seen = bsp_keys(run_engine(rows[:i0+1]))
    for t in range(i0, i1):
        chart = run_engine(rows[:t+1])
        cur = bsp_keys(chart)
        new = cur - seen
        seen = cur
        buy = [k for k in new if "DOWN" in k[1] and k[2] in (1,2,3)]
        sell = [k for k in new if "UP" in k[1] and k[2] in (1,2,3)]
        stop = shares > 0 and rows[t]["close"] < defense
        nt = t + 1
        o = rows[nt]["open"]
        if buy and shares == 0:
            idx = buy[0][0]
            shares = int(cash*(1-FEE)/o/100)*100
            cash -= shares*o*(1+FEE)
            entry, defense = o, rows[idx]["low"]
            trades.append(("BUY", rows[nt]["date"], o, f"b{buy[0][2]}", defense))
        elif shares > 0 and (sell or stop):
            cash += shares*o*(1-FEE)
            trades.append(("SELL_sig" if sell else "SELL_stop", rows[nt]["date"], o, entry, (o/entry-1)*100))
            shares = 0
    end_px = rows[i1]["close"]
    return (cash + shares*end_px)/1e6 - 1, end_px/rows[i0]["close"] - 1, trades, dates[i0], dates[i1]

# ---------- 七轨（任意周期） ----------
def bt_boll(rows, mode):
    tracks_l = calc_boll7(rows, n=20)
    off = len(rows) - len(tracks_l)
    for i, tr in enumerate(tracks_l):
        tr["low"] = rows[i+off]["low"]
    tracks = [None]*off + tracks_l
    dates = [r["date"] for r in rows]
    win = [i for i, d in enumerate(dates) if START <= d[:10] <= END]
    i0, i1 = win[0], win[-1]
    cash, shares = 1_000_000.0, 0
    entry = None
    trades = []
    c2 = c3 = 0
    for t in range(i0, i1):
        tr = tracks[t]
        if tr is None: continue
        buy_sig = sell_sig = False
        if mode == "strong":
            if shares == 0:
                if t > 0 and tracks[t-1] is not None and tr["close"] > tr["t2"] \
                   and tracks[t-1]["close"] > tracks[t-1]["t2"] \
                   and tr["low"] <= tr["t2"] and tr["close"] >= tr["t2"]:
                    buy_sig = True
            else:
                c2 = c2 + 1 if tr["close"] < tr["t2"] else 0
                c3 = c3 + 1 if tr["close"] < tr["mid"] else 0
                if c2 >= 2 or c3 >= 3:
                    sell_sig = True
                    c2 = c3 = 0
        else:
            if shares == 0 and tr["close"] < tr["b5"]:
                buy_sig = True
            elif shares > 0 and tr["close"] >= tr["mid"]:
                sell_sig = True
        nt = t + 1
        if nt > i1: break
        o = rows[nt]["open"]
        if buy_sig and shares == 0:
            shares = int(cash*(1-FEE)/o/100)*100
            cash -= shares*o*(1+FEE)
            entry = o
            trades.append(("BUY", rows[nt]["date"][:16], o, "二轨接" if mode=="strong" else "五轨接"))
        elif shares > 0 and sell_sig:
            cash += shares*o*(1-FEE)
            trades.append(("SELL", rows[nt]["date"][:16], o, ("二轨失守/破中轨" if mode=="strong" else "回升中轨"), (o/entry-1)*100))
            shares = 0
    end_px = rows[i1]["close"]
    return (cash + shares*end_px)/1e6 - 1, end_px/rows[i0]["close"] - 1, trades, dates[i0], dates[i1]

# ============ 日线 ============
day = fetch_qfq("sh512400")
ret, base, trades, d0, d1 = bt_chan_day(day)
print(f"\n===== sh512400 日线 缠论  {d0}→{d1} =====")
for t in trades:
    if t[0]=="BUY":
        print(f"  {t[1]} BUY @{t[2]:.3f} ({t[3]}, 防={t[4]:.3f})")
    else:
        print(f"  {t[1]} {t[0]} @{t[2]:.3f} 盈亏{t[4]:+.2f}%")
nb = len([x for x in trades if x[0]=="BUY"])
print(f"  {nb}笔 | 缠论 {ret*100:+.2f}% vs 持有 {base*100:+.2f}%")

for mode, name in (("strong","A二轨接"),("oversold","B五轨接")):
    ret, base, trades, d0, d1 = bt_boll(day, mode)
    nb = len([x for x in trades if x[0]=="BUY"])
    pnls = [x[4] for x in trades if x[0]=="SELL"]
    wr = sum(1 for p in pnls if p>0)/len(pnls)*100 if pnls else 0
    print(f"\n== 日线 七轨{name} ==")
    for t in trades:
        if t[0]=="BUY":
            print(f"  {t[1]} BUY @{t[2]:.3f} ({t[3]})")
        else:
            print(f"  {t[1]} SELL @{t[2]:.3f} ({t[3]}) 盈亏{t[4]:+.2f}%")
    print(f"  {nb}笔 胜率{wr:.0f}% | 策略 {ret*100:+.2f}% vs 持有 {base*100:+.2f}%")

# ============ 30/60min 七轨（快） ============
for cat in ("30", "60"):
    data = json.load(open(f"/tmp/tdx_{cat}m/sh512400_qfq.json"))
    for mode, name in (("strong","A二轨接"),("oversold","B五轨接")):
        ret, base, trades, d0, d1 = bt_boll(data, mode)
        nb = len([x for x in trades if x[0]=="BUY"])
        pnls = [x[4] for x in trades if x[0]=="SELL"]
        wr = sum(1 for p in pnls if p>0)/len(pnls)*100 if pnls else 0
        print(f"\n== {cat}min 七轨{name} ({nb}笔 胜率{wr:.0f}%) | 策略 {ret*100:+.2f}% vs 持有 {base*100:+.2f}%")
        for t in trades[:12]:
            if t[0]=="BUY":
                print(f"  {t[1]} BUY @{t[2]:.3f} ({t[3]})")
            else:
                print(f"  {t[1]} SELL @{t[2]:.3f} 盈亏{t[4]:+.2f}%")
        if nb > 12:
            print(f"  ... 共{nb}笔")
