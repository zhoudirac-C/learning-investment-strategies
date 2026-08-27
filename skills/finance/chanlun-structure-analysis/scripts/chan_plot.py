#!/usr/bin/env python3
"""缠论结构图绘制：K线 + 笔 + 中枢 + 背驰 + 买卖点 + MACD

用法:
  python3 chan_plot.py sh512400                      # 日线
  python3 chan_plot.py --60m sh512400                # 60分钟
  python3 chan_plot.py --30m sh512400 -o /tmp/x.png  # 30分钟，指定输出
  python3 chan_plot.py --scale 15 sh512400 --fresh   # 任意分钟 + 强制重拉

依赖: 同目录 chan_analysis.py 的底层算法（import 复用，保证结构口径一致）
输出: PNG（默认 /tmp/{code}[_{N}m].png）
"""
import os, sys, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chan_analysis as ca
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from datetime import datetime

plt.rcParams['font.sans-serif'] = ['WenQuanYi Zen Hei', 'Noto Sans CJK SC', 'SimHei']
plt.rcParams['axes.unicode_minus'] = False


def x_of(klines, dt):
    """按日期字符串定位K线索引（分钟数据 date 形如 '2026-08-27 11:30:00'）"""
    key = dt[:16]
    for i, k in enumerate(klines):
        if k["date"].startswith(key):
            return i
    return None


def plot(klines, label, out):
    merged = ca.merge_inclusion(klines)
    fracs = ca.find_fractals(merged)
    bi = ca.find_bi(fracs)
    dif, dea, hist = ca.calc_macd(klines)
    zs = ca.identify_zhongshu(bi)
    bt = ca.detect_backtension(bi, merged, hist)
    pts = ca.classify_buy_points(bi, zs, bt)

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

    # ---- 笔连线：bi.idx 是合并K线索引，映射到原始K线位置 ----
    def orig_x(m):
        return merged[m]["idx"][0]
    bx = [orig_x(b["idx"]) for b in bi]
    by = [b["price"] for b in bi]
    ax1.plot(bx, by, color="#1d3557", linewidth=1.2, zorder=3, marker="o", markersize=3)

    # ---- 中枢矩形（ZD=上沿底, ZG=下沿顶）----
    for z in zs:
        zx0 = orig_x(bi[z["start"]]["idx"])
        zx1 = orig_x(bi[z["end"]]["idx"])
        ax1.add_patch(Rectangle((zx0, z["zd"]), max(zx1 - zx0, 1), max(z["zg"] - z["zd"], 1e-6),
                                facecolor="orange", alpha=0.16, edgecolor="darkorange",
                                linewidth=1.0, zorder=2))

    # ---- 买卖点标注 ----
    sym = {"一买": "v", "二买": "^", "三买": "D"}
    for p in pts:
        key = p["kind"][:2]
        x = x_of(klines, p["date"])
        if x is None:
            continue
        ax1.scatter([x], [p["price"]], marker=sym.get(key, "o"), s=95, color="magenta", zorder=5)
        off = -13 if key == "一买" else 10
        ax1.annotate(p["kind"].split("(")[0], (x, p["price"]), textcoords="offset points",
                     xytext=(0, off), fontsize=8, color="magenta", zorder=6)

    # ---- 背驰点 ----
    for b in bt:
        x = x_of(klines, b["date"])
        if x is None:
            continue
        ax1.scatter([x], [b["price"]], marker="x", s=75, color="brown", zorder=5)
        ax1.annotate("背驰", (x, b["price"]), textcoords="offset points",
                     xytext=(7, 7), fontsize=7, color="brown", zorder=6)

    # ---- 最近中枢 ZG/ZD 标注 ----
    if zs:
        z = zs[-1]
        ax1.text(2, z["zg"] + 0.001 * (z["zg"] or 1), f"ZG {z['zg']:.3f}", fontsize=8, color="darkorange")
        ax1.text(2, z["zd"] - 0.001 * (z["zd"] or 1), f"ZD {z['zd']:.3f}", fontsize=8, color="darkorange")

    ax1.set_ylabel("价格"); ax1.grid(alpha=0.3); ax1.set_title(f"{label} 结构", fontsize=10)

    # ---- 副图 MACD ----
    ax2.bar(range(n), [h if h is not None else 0 for h in hist],
            color=["#e63946" if (h or 0) >= 0 else "#2a9d8f" for h in hist], width=0.6)
    ax2.plot(range(n), [d if d is not None else 0 for d in dif], color="#1d3557", linewidth=0.8, label="DIF")
    ax2.plot(range(n), [d if d is not None else 0 for d in dea], color="#f4a261", linewidth=0.8, label="DEA")
    ax2.axhline(0, color="gray", linewidth=0.5)
    ax2.set_ylabel("MACD"); ax2.grid(alpha=0.3); ax2.legend(loc="upper left", fontsize=8)

    # ---- x 轴稀疏日期刻度 ----
    step = max(n // 8, 1)
    tick_pos = list(range(0, n, step))
    ax2.set_xticks(tick_pos)
    ax2.set_xticklabels([klines[i]["date"][:10] for i in tick_pos], rotation=45, ha="right", fontsize=7)

    plt.tight_layout()
    plt.savefig(out, dpi=130)
    print(f"saved {out}  ({n} bars, 中枢={len(zs)}, 买点={len(pts)})")


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
