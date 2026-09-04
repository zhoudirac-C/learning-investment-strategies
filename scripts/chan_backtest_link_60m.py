#!/usr/bin/env python3
"""两级别联动缠论回测 v3：修正窗口起点=日线信号分型日（次级别买点先于大级别确认出现的区间套特性）。
规则：
- 日线逐日收盘重跑：新确认 DOWN 买点（b1/b2/b3）且确认价>分型low →
  开放联动窗口 [分型日, 窗口关闭]；防守线=分型low
- 窗口关闭条件：日线收盘 < 防守线，或 60min 一买已触发
- 窗口内 60min 新确认一买（bstype=1）且确认价>防守线 → 下一根60min bar开盘买
- HOLD：离场=60min UP 卖点 / 日线收盘破防守线 / 日线收盘破日线中枢下沿 → 下一根60min开盘卖
"""
import sys, json, subprocess
sys.path.insert(0, "/home/ubuntu/learning-investment-strategies/src")
sys.path.insert(0, "/home/ubuntu/learning-investment-strategies/third_party/chanpy")
from chan_engine.core.engine import RecursionEngine
from chan_engine.spec.model import Bar

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
FEE = 0.0001
STARTS = {"sz159381": "2025-03-24", "sh515980": "2024-10-08"}
END = "2026-09-04"


def fetch_qfq(code, n=800):
    out = subprocess.run(["curl", "-s", "--max-time", "10", "-A", UA,
        f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,{n},qfq"],
        capture_output=True)
    d = json.loads(out.stdout)["data"][code]
    k = d.get("qfqday") or d.get("day")
    return [{"trade_date": r[0], "open": float(r[1]), "close": float(r[2]),
             "high": float(r[3]), "low": float(r[4])} for r in k]


def run_engine(rows):
    bars = [Bar(ts=i, o=r["open"], h=r["high"], l=r["low"], c=r["close"],
                vol=r.get("volume") or 0.0) for i, r in enumerate(rows)]
    return RecursionEngine().run(bars)


def bsp_keys(chart):
    return {(x.idx, str(x.dir), x.bstype) for x in chart.bsp if x.sure}


def zs_bottom(chart):
    zs = [z for z in chart.zs if z.sure]
    return zs[-1].zd if zs else None


code = sys.argv[1]
day = fetch_qfq(code)
m60 = json.load(open(f"/tmp/tdx_60m/{code}_qfq.json"))
ddates = [r["trade_date"] for r in day]
d60 = [r["date"] for r in m60]
d60_day = [d[:10] for d in d60]
bars_of_day = {}
for i, dd in enumerate(d60_day):
    bars_of_day.setdefault(dd, []).append(i)

dwin = [i for i, d in enumerate(ddates) if STARTS[code] <= d <= END]
i0, i1 = dwin[0], dwin[-1]

cash, shares = 1_000_000.0, 0
entry = defense = None
state = "IDLE"  # IDLE / WINDOW / HOLD
trades = []
seen_d = bsp_keys(run_engine(day[:i0 + 1]))
m60_start = bars_of_day.get(ddates[i0], [0])[0]
seen_60 = bsp_keys(run_engine(m60[:m60_start + 1]))
# 60min seen 的 idx 语义与逐日截断长度相关，需按"截断到bi"重算——改为滚动重算基线不可行，
# 简化：60min 信号每次以当前截断全量重跑后的 cur - prev 比较（prev 随 bi 递增）
prev_60_keys = bsp_keys(run_engine(m60[:m60_start + 1]))
print(f"{code}: day[{i0}..{i1}]", flush=True)

pending_defense = None   # 窗口开启时的防守线
window_origin = None     # 分型日
zs_zd = None
last_60_bi = m60_start

for di in range(i0, i1):
    dstr = ddates[di]
    chart_d = run_engine(day[:di + 1])
    cur_d = bsp_keys(chart_d)
    new_d = cur_d - seen_d
    seen_d = cur_d
    close = day[di]["close"]
    zs_zd = zs_bottom(chart_d)

    # 日线信号 → 开窗口
    if state == "IDLE":
        buys = [k for k in new_d if "DOWN" in k[1]]
        if buys:
            idx = buys[0][0]
            low = day[idx]["low"]
            if close > low:
                pending_defense = low
                window_origin = day[idx]["trade_date"]
                state = "WINDOW"

    # 该日 60min bars 逐根推进
    idxs = bars_of_day.get(dstr, [])
    for bi in idxs:
        if bi <= last_60_bi:
            continue
        if state == "IDLE":
            last_60_bi = bi
            continue
        chart_60 = run_engine(m60[:bi + 1])
        cur_60 = bsp_keys(chart_60)
        new_60 = cur_60 - prev_60_keys
        prev_60_keys = cur_60
        last_60_bi = bi

        if state == "WINDOW":
            b1 = [k for k in new_60 if "DOWN" in k[1] and k[2] == 1]
            if b1:
                ni = bi + 1
                if ni < len(m60):
                    o = m60[ni]["open"]
                    if o > pending_defense:
                        shares = int(cash * (1 - FEE) / o / 100) * 100
                        cash -= shares * o * (1 + FEE)
                        entry = o
                        defense = pending_defense
                        state = "HOLD"
                        trades.append(("BUY", m60[ni]["date"], o,
                                       f"日分型{window_origin}→60m一买", defense))
                    else:
                        state = "IDLE"  # 确认价已破防守线，弃用
                    pending_defense = None
        elif state == "HOLD":
            sells = [k for k in new_60 if "UP" in k[1]]
            if sells:
                ni = bi + 1
                if ni < len(m60):
                    o = m60[ni]["open"]
                    cash += shares * o * (1 - FEE)
                    trades.append(("SELL", m60[ni]["date"], o, "60m卖点", (o / entry - 1) * 100))
                    shares = 0
                    state = "IDLE"

    # 日线收盘检查（窗口失效/持仓防守线）在 60min 推进后判定
    if state == "WINDOW" and close < pending_defense:
        state = "IDLE"
        pending_defense = None
    elif state == "HOLD":
        if close < defense or (zs_zd and close < zs_zd):
            # 次日首根60min bar开盘卖
            nxt = None
            for dii in range(di + 1, i1 + 1):
                b2 = bars_of_day.get(ddates[dii])
                if b2:
                    nxt = b2[0]
                    break
            if nxt is not None and nxt < len(m60):
                o = m60[nxt]["open"]
                cash += shares * o * (1 - FEE)
                trades.append(("SELL", m60[nxt]["date"], o,
                               "日线防守线" if close < defense else "日线中枢下沿",
                               (o / entry - 1) * 100))
                shares = 0
                state = "IDLE"
                # 推进 60min 指针
                last_60_bi = max(last_60_bi, nxt)

end_px = day[i1]["close"]
final = (cash + shares * end_px) / 1e6 - 1
base = end_px / day[i0]["close"] - 1
print(f"\n===== {code} 联动v3（日线信号分型日起窗口+60m一买确认） {ddates[i0]} → {ddates[i1]} =====")
for t in trades:
    if t[0] == "BUY":
        print(f"  {t[1]}  BUY @{t[2]:.3f} ({t[3]}, 防守线={t[4]:.3f})")
    else:
        print(f"  {t[1]}  SELL @{t[2]:.3f} ({t[3]})  盈亏 {t[4]:+.2f}%")
nb = len([x for x in trades if x[0] == "BUY"])
print(f"交易{nb}笔 | 联动: {final*100:+.2f}% vs 持有 {base*100:+.2f}% | 差 {(final-base)*100:+.2f}pct")
