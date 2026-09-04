#!/usr/bin/env python3
"""缠论 3 个月 point-in-time 回测 v2（qfq 复权日线，修复 159381 分拆除权）。

规则：
- 每个交易日 T 收盘后用截至 T 的 qfq 日线重跑 RecursionEngine（无前视）
- 买入：dir=DOWN, bstype∈{1,2,3}, sure=True 且新出现 → T+1 开盘全仓买入
- 卖出：① dir=UP 信号新出现 ② 收盘 < 防守线（买点分型低点）→ T+1 开盘卖出
- 费率单边 0.01%；区间 2026-06-05 ~ 2026-09-04；起点前既有信号不追
"""
import sys, json, subprocess
sys.path.insert(0, "/home/ubuntu/learning-investment-strategies/src")
sys.path.insert(0, "/home/ubuntu/learning-investment-strategies/third_party/chanpy")
from chan_engine.core.engine import RecursionEngine
from chan_engine.spec.model import Bar

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
FEE = 0.0001
START, END = "2026-06-05", "2026-09-04"


def fetch_qfq(code, n=800):
    out = subprocess.run(["curl", "-s", "--max-time", "10", "-A", UA,
        f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,{n},qfq"],
        capture_output=True)
    d = json.loads(out.stdout)["data"][code]
    k = d.get("qfqday") or d.get("day")
    return [{"trade_date": r[0], "open": float(r[1]), "close": float(r[2]),
             "high": float(r[3]), "low": float(r[4]),
             "volume": float(r[5]) if len(r) > 5 else 0.0} for r in k]


def run_engine(rows):
    bars = [Bar(ts=i, o=r["open"], h=r["high"], l=r["low"], c=r["close"],
                vol=r["volume"] or 0.0) for i, r in enumerate(rows)]
    return RecursionEngine().run(bars)


def bsp_keys(chart):
    return {(x.idx, str(x.dir), x.bstype) for x in chart.bsp if x.sure}


def backtest(code):
    rows = fetch_qfq(code)
    dates = [r["trade_date"] for r in rows]
    win = [i for i, d in enumerate(dates) if START <= d <= END]
    i0, i1 = win[0], win[-1]

    cash, shares = 1_000_000.0, 0
    entry = defense = None
    trades = []
    seen = bsp_keys(run_engine(rows[:i0 + 1]))

    for t in range(i0, i1):
        chart = run_engine(rows[:t + 1])
        cur = bsp_keys(chart)
        new = cur - seen
        seen = cur
        buy_sig = sorted([k for k in new if "DOWN" in k[1] and k[2] in (1, 2, 3)])
        sell_sig = [k for k in new if "UP" in k[1] and k[2] in (1, 2, 3)]
        stop = shares > 0 and rows[t]["close"] < defense

        nt = t + 1
        if nt > i1:
            break
        o = rows[nt]["open"]
        if buy_sig and shares == 0:
            idx = buy_sig[0][0]
            shares = int(cash * (1 - FEE) / o / 100) * 100
            cash -= shares * o * (1 + FEE)
            entry = o
            defense = rows[idx]["low"]
            trades.append(("BUY", dates[nt], o, rows[idx]["low"], buy_sig[0][2]))
        elif shares > 0 and (sell_sig or stop):
            cash += shares * o * (1 - FEE)
            pnl = (o / entry - 1) * 100
            trades.append(("SELL_sig" if sell_sig else "SELL_stop", dates[nt], o, entry, pnl))
            shares = 0

    end_px = rows[i1]["close"]
    final = cash + shares * end_px
    ret = final / 1_000_000 - 1
    base = end_px / rows[i0]["close"] - 1
    # 持仓日统计
    held_days = sum(1 for t in trades if t[0] == "BUY")  # 粗略
    return code, ret, base, trades, dates[i0], dates[i1], rows[i0]["close"], end_px


results = {}
for code in ("sz159381", "sh515980"):
    code, ret, base, trades, d0, d1, p0, p1 = backtest(code)
    results[code] = (ret, base, trades)
    print(f"\n===== {code}  {d0} → {d1}  首收 {p0:.3f} / 末收 {p1:.3f} =====")
    for t in trades:
        if t[0] == "BUY":
            print(f"  {t[1]}  BUY @{t[2]:.3f} (bstype={t[4]}, 防守线={t[3]:.3f})")
        else:
            print(f"  {t[1]}  {t[0]} @{t[2]:.3f} (入场={t[3]:.3f})  盈亏 {t[4]:+.2f}%")
    if not trades:
        print("  （区间内无触发交易，全程空仓）")
    print(f"  缠论策略: {ret*100:+.2f}%   |   买入持有: {base*100:+.2f}%   |   差值: {(ret-base)*100:+.2f}pct")
