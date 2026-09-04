#!/usr/bin/env python3
"""七轨布林 3 个月 point-in-time 回测 v1（qfq 复权日线）：sz159381 / sh515980。

UP 口径规则（bollinger-7track skill）：
- 策略A 强势股打法：
  入场=二轨接：low 触及二轨(t2) 且 close ≥ t2（影线刺穿不算破）→ T+1 开盘全仓买
  离场=① close 连续 2 日 < t2（二轨失守）② close 连续 3 日 < mid（破中轨不拉回）→ T+1 开盘卖
- 策略B 超卖反弹：close < b5（五轨下方）当日 → T+1 开盘买；离场=close ≥ mid → T+1 开盘卖
- 费率单边 0.01%；区间 2026-06-05 ~ 2026-09-04；与缠论回测同基准
"""
import sys, json, subprocess
sys.path.insert(0, "/home/ubuntu/.hermes/skills/finance/bollinger-7track/scripts")
from boll7 import calc_boll7

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
FEE = 0.0001
START, END = "2026-06-05", "2026-09-04"


def fetch_qfq(code, n=800):
    out = subprocess.run(["curl", "-s", "--max-time", "10", "-A", UA,
        f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,{n},qfq"],
        capture_output=True)
    d = json.loads(out.stdout)["data"][code]
    k = d.get("qfqday") or d.get("day")
    return [{"date": r[0], "open": float(r[1]), "close": float(r[2]),
             "high": float(r[3]), "low": float(r[4])} for r in k]


def run_strategy(rows, tracks, mode):
    dates = [r["date"] for r in rows]
    win = [i for i, d in enumerate(dates) if START <= d <= END]
    i0, i1 = win[0], win[-1]
    cash, shares = 1_000_000.0, 0
    entry = None
    trades = []
    below_t2_cnt = below_mid_cnt = 0

    for t in range(i0, i1):
        tr = tracks[t]
        buy_sig = sell_sig = False
        if mode == "strong":
            if shares == 0:
                # 二轨接：昨日在二轨上方（强势区），今日 low 触二轨但 close 收回
                if t > 0 and tracks[t-1]["close"] > tracks[t-1]["t2"] \
                   and tr["low"] <= tr["t2"] and tr["close"] >= tr["t2"]:
                    buy_sig = True
            else:
                below_t2_cnt = below_t2_cnt + 1 if tr["close"] < tr["t2"] else 0
                below_mid_cnt = below_mid_cnt + 1 if tr["close"] < tr["mid"] else 0
                if below_t2_cnt >= 2 or below_mid_cnt >= 3:
                    sell_sig = True
                    below_t2_cnt = below_mid_cnt = 0
        else:  # oversold
            if shares == 0 and tr["close"] < tr["b5"]:
                buy_sig = True
            elif shares > 0 and tr["close"] >= tr["mid"]:
                sell_sig = True

        nt = t + 1
        if nt > i1:
            break
        o = rows[nt]["open"]
        if buy_sig and shares == 0:
            shares = int(cash * (1 - FEE) / o / 100) * 100
            cash -= shares * o * (1 + FEE)
            entry = o
            reason = "二轨接" if mode == "strong" else "五轨超卖接"
            trades.append(("BUY", dates[nt], o, reason))
        elif shares > 0 and sell_sig:
            cash += shares * o * (1 - FEE)
            pnl = (o / entry - 1) * 100
            why = "二轨失守" if below_t2_cnt >= 2 else ("破中轨3日" if mode == "strong" else "回升中轨")
            trades.append(("SELL", dates[nt], o, why, pnl))
            shares = 0
            entry = None

    end_px = rows[i1]["close"]
    final = cash + shares * end_px
    ret = final / 1_000_000 - 1
    base = end_px / rows[i0]["close"] - 1
    return ret, base, trades, dates[i0], dates[i1], rows[i0]["close"], end_px


for code in ("sz159381", "sh515980"):
    rows = fetch_qfq(code)
    closes = [{"date": r["date"], "close": r["close"], "open": r["open"],
               "high": r["high"], "low": r["low"], "vol": 0} for r in rows]
    tracks = calc_boll7(closes, n=20)
    # calc_boll7 丢掉了前19根，对齐：tracks[i] 对应 rows[i+19]；补 low/high 供二轨接判定
    off = len(rows) - len(tracks)
    for i, tr in enumerate(tracks):
        src = rows[i + off]
        tr["low"] = src["low"]
        tr["high"] = src["high"]
    t_full = [None] * off + tracks
    print(f"\n########## {code} ##########")
    for mode, name in (("strong", "策略A 强势股打法(二轨接/二轨失守或破中轨3日离场)"),
                       ("oversold", "策略B 超卖反弹(五轨下方接/回升中轨离场)")):
        ret, base, trades, d0, d1, p0, p1 = run_strategy(rows, t_full, mode)
        print(f"\n== {name}  {d0} → {d1} ==")
        for t in trades:
            if t[0] == "BUY":
                print(f"  {t[1]}  BUY @{t[2]:.3f} ({t[3]})")
            else:
                print(f"  {t[1]}  SELL @{t[2]:.3f} ({t[3]})  盈亏 {t[4]:+.2f}%")
        if not trades:
            print("  （区间内无触发交易，全程空仓）")
        print(f"  策略收益: {ret*100:+.2f}%   |   买入持有: {base*100:+.2f}%   |   差值: {(ret-base)*100:+.2f}pct")
