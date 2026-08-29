#!/usr/bin/env python3
"""缠论结构图绘制：K线 + 笔 + 中枢 + 买卖点 + MACD

用法:
  python3 chan_plot.py sh512400                      # 日线
  python3 chan_plot.py --60m sh512400                # 60分钟
  python3 chan_plot.py --30m sh512400 -o /tmp/x.png  # 30分钟，指定输出
  python3 chan_plot.py --scale 15 sh512400 --fresh   # 任意分钟 + 强制重拉

结构口径（2026-08-29 M7-5 移植）：RecursionEngine（claims 校准口径）输出——
  笔=归一 bi 表端点（原始 K 线索引，无合并映射）、中枢=zs 表（zd/zg + bar 区间）、
  买卖点=bsp 表（一二三类，含 backchi_type 标注）；MACD=chan_engine.core.macd
  （与旧 chan_analysis.calc_macd 逐位一致）。
依赖: 同目录 chan_analysis.py 的数据源函数（fetch_tencent_daily/fetch_sina）与路径设置。
输出: PNG（默认 /tmp/{code}[_{N}m].png）
"""
import os, sys, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chan_analysis as ca  # 模块级已设置 src / third_party/chanpy 路径
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from chan_engine.core.engine import RecursionEngine
from chan_engine.core.macd import calc_macd
from chan_engine.report.skill_adapter import bsp_name
from chan_engine.spec.model import Bar, Direction

plt.rcParams['font.sans-serif'] = ['WenQuanYi Zen Hei', 'Noto Sans CJK SC', 'SimHei']
plt.rcParams['axes.unicode_minus'] = False


def _bi_points(chart, bars):
    """笔折线端点：[(bar_idx, price)]（端点即分型极值：上笔终点高/下笔终点低）。"""
    pts = []
    for b in chart.bi:
        if b.dir is Direction.UP:
            pts.append((b.start_idx, bars[b.start_idx].l))
            pts.append((b.end_idx, bars[b.end_idx].h))
        else:
            pts.append((b.start_idx, bars[b.start_idx].h))
            pts.append((b.end_idx, bars[b.end_idx].l))
    # 相邻笔共享端点，去重保序
    dedup = [pts[0]] if pts else []
    for p in pts[1:]:
        if p[0] != dedup[-1][0]:
            dedup.append(p)
    return dedup


def plot(klines, label, out):
    bars = [Bar(ts=i, o=k["open"], h=k["high"], l=k["low"], c=k["close"],
                vol=k.get("vol", 0) or 0) for i, k in enumerate(klines)]
    chart = RecursionEngine().run(bars)
    dif, dea, hist = calc_macd([k["close"] for k in klines])

    closes = [k["close"] for k in klines]
    n = len(klines)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 9), sharex=True,
                                   gridspec_kw={"height_ratios": [3, 1]})
    fig.suptitle(f"{label}   最新 {klines[-1]['date']}  收 {closes[-1]}", fontsize=13)

    # ---- 主图：K线蜡烛 ----
    for i, k in enumerate(klines):
        color = "#e63946" if k["close"] >= k["open"] else "#2a9d8f"
        ax1.plot([i, i], [k["low"], k["high"]], color=color, linewidth=0.7, zorder=1)
        ax1.add_patch(Rectangle((i - 0.35, min(k["open"], k["close"])), 0.7,
                                max(abs(k["close"] - k["open"]), 1e-9),
                                facecolor=color, edgecolor=color, zorder=2))

    # ---- 笔连线（引擎 bi 表，原始 K 线索引）----
    pts = _bi_points(chart, bars)
    if pts:
        ax1.plot([p[0] for p in pts], [p[1] for p in pts], color="#1d3557",
                 linewidth=1.2, zorder=3, marker="o", markersize=3)

    # ---- 中枢矩形（[ZD, ZG]，level 越深颜色越深）----
    for z in chart.zs:
        alpha = 0.16 if z.level <= 1 else 0.24
        ax1.add_patch(Rectangle((z.start_idx, z.zd), max(z.end_idx - z.start_idx, 1),
                                max(z.zg - z.zd, 1e-6),
                                facecolor="orange", alpha=alpha, edgecolor="darkorange",
                                linewidth=1.0, zorder=2))

    # ---- 买卖点标注（一二三类；一买/一卖附背驰类型）----
    sym = {1: "v", 2: "^", 3: "D"}
    for b in chart.bsp:
        price = bars[b.idx].l if b.dir is Direction.UP else bars[b.idx].h
        color = "magenta" if b.dir is Direction.UP else "darkgreen"
        marker = sym.get(b.bstype, "o")
        ax1.scatter([b.idx], [price], marker=marker, s=95,
                    color=color, zorder=5,
                    alpha=1.0 if b.sure else 0.4)
        name = bsp_name(b)
        if b.bstype == 1 and b.backchi_type:
            name += f"({'趋势' if b.backchi_type == 'trend_div' else '盘整'}背驰)"
        off = -13 if b.dir is Direction.UP else 10
        ax1.annotate(name, (b.idx, price), textcoords="offset points",
                     xytext=(0, off), fontsize=8, color=color, zorder=6)

    # ---- 最近中枢 ZG/ZD 标注 ----
    if chart.zs:
        z = chart.zs[-1]
        ax1.text(2, z.zg + 0.001 * (z.zg or 1), f"ZG {z.zg:.3f}", fontsize=8, color="darkorange")
        ax1.text(2, z.zd - 0.001 * (z.zd or 1), f"ZD {z.zd:.3f}", fontsize=8, color="darkorange")

    ax1.set_ylabel("价格"); ax1.grid(alpha=0.3); ax1.set_title(f"{label} 结构", fontsize=10)

    # ---- 副图 MACD ----
    ax2.bar(range(n), hist,
            color=["#e63946" if h >= 0 else "#2a9d8f" for h in hist], width=0.6)
    ax2.plot(range(n), dif, color="#1d3557", linewidth=0.8, label="DIF")
    ax2.plot(range(n), dea, color="#f4a261", linewidth=0.8, label="DEA")
    ax2.axhline(0, color="gray", linewidth=0.5)
    ax2.set_ylabel("MACD"); ax2.grid(alpha=0.3); ax2.legend(loc="upper left", fontsize=8)

    # ---- x 轴稀疏日期刻度 ----
    step = max(n // 8, 1)
    tick_pos = list(range(0, n, step))
    ax2.set_xticks(tick_pos)
    ax2.set_xticklabels([klines[i]["date"][:10] for i in tick_pos], rotation=45, ha="right", fontsize=7)

    plt.tight_layout()
    plt.savefig(out, dpi=130)
    print(f"saved {out}  ({n} bars, 中枢={len(chart.zs)}, 买点={len(chart.bsp)})")


def main():
    ap = argparse.ArgumentParser(description="缠论结构图")
    ap.add_argument("codes", nargs="+")
    ap.add_argument("--30m", dest="m30", action="store_true")
    ap.add_argument("--60m", dest="m60", action="store_true")
    ap.add_argument("--scale", type=int)
    ap.add_argument("--fresh", action="store_true")
    ap.add_argument("-o", "--out", help="输出PNG路径")
    a = ap.parse_args()
    scale = "day"
    if a.scale:
        scale = a.scale
    elif a.m30:
        scale = 30
    elif a.m60:
        scale = 60
    for code in a.codes:
        try:
            if scale == "day":
                k = ca.fetch_tencent_daily(code, fresh=a.fresh)
                lab = code
                out = a.out or f"/tmp/{code}.png"
            else:
                k = ca.fetch_sina(code, scale, fresh=a.fresh)
                lab = f"{code} {scale}m"
                out = a.out or f"/tmp/{code}_{scale}m.png"
            plot(k, lab, out)
        except Exception as e:
            print(f"[FAIL] {code}: {e}")


if __name__ == "__main__":
    main()
