#!/usr/bin/env python3
"""七轨布林线：MID±{3,2,1}×DEV 七层轨道 + 信号判定 + 打法标签

用法:
  python3 boll7.py sh512400 sz159381          # 日线（腾讯，降级TDX）
  python3 boll7.py --30m sh512400             # 30分钟
  python3 boll7.py --n 20 --fresh sh000688    # 自定义N/强制重拉

口径: MID=MA(C,N), STD0=STD(C,N), DEV=MA(STD0,5)（5日标准差均值，UP口径）
数据源: 复用 chan_analysis.py 的 fetch_tencent_daily/fetch_sina（含 TDX/stale 降级）
输出: 控制台报告；结果同时打印为 JSON
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.expanduser(
    "~/.hermes/skills/finance/chanlun-structure-analysis/scripts"))
# 复用缠论脚本的数据源与降级链（本目录无 chan_analysis.py 时自动回退 skill 目录）
from chan_analysis import fetch_sina, fetch_tencent_daily, _parse_cli  # noqa: E402


def calc_boll7(klines, n=20):
    closes = [k["close"] for k in klines]
    mid, dev = [], []
    for i in range(len(closes)):
        if i < n - 1:
            mid.append(None); dev.append(None); continue
        w = closes[i - n + 1:i + 1]
        m = sum(w) / n
        var = sum((c - m) ** 2 for c in w) / n  # 总体STD，同通达信
        mid.append(m)
        # DEV = MA(STD,5)：当前及前4根的STD均值
        stds = []
        for j in range(max(n - 1, i - 4), i + 1):
            wj = closes[j - n + 1:j + 1]
            mj = sum(wj) / n
            stds.append((sum((c - mj) ** 2 for c in wj) / n) ** 0.5)
        dev.append(sum(stds) / len(stds))
    rows = []
    for i, k in enumerate(klines):
        if mid[i] is None:
            continue
        d = dev[i]
        rows.append({
            "date": k["date"], "close": k["close"], "mid": round(mid[i], 4),
            "top": round(mid[i] + 3 * d, 4), "t1": round(mid[i] + 2 * d, 4),
            "t2": round(mid[i] + d, 4), "b4": round(mid[i] - d, 4),
            "b5": round(mid[i] - 2 * d, 4), "bot": round(mid[i] - 3 * d, 4),
            "band_pct": round((mid[i] + 3 * d - (mid[i] - 3 * d)) / mid[i] * 100, 2),
        })
    return rows


def classify(r):
    """位置归类"""
    c = r["close"]
    if c > r["t1"]:
        return "超买区(一轨上方)"
    if c > r["t2"]:
        return "强势区(顶轨~二轨)"
    if c > r["b4"]:
        return "中轨带(±1DEV内)"
    if c > r["b5"]:
        return "弱势区(四轨~五轨)"
    return "超卖区(五轨下方)"


def signals(rows, n_back=5):
    r = rows[-1]
    sig, pcts = [], [x["band_pct"] for x in rows[-60:] if x["band_pct"]]
    pct_rank = sum(1 for p in pcts if p <= r["band_pct"]) / len(pcts) * 100 if pcts else 50
    if pct_rank < 20:
        sig.append(f"收敛度: 带宽{r['band_pct']}% 处近60bar第{pct_rank:.0f}百分位 → 收敛(关注突破)")
    elif pct_rank > 80:
        sig.append(f"收敛度: 带宽{r['band_pct']}% 第{pct_rank:.0f}百分位 → 发散(波动放大)")
    else:
        sig.append(f"收敛度: 带宽{r['band_pct']}% 常态")
    # 二轨测试/失守（close口径，影线不算破）
    below = [x for x in rows[-n_back:] if x["close"] < x["t2"]]
    if len(below) == n_back and all(x["close"] < x["t2"] for x in rows[-n_back:]):
        sig.append(f"⚠ 二轨失守: 近{n_back}bar收盘全在二轨下方 → 强势股打法失效条件触发")
    elif any(abs(x["close"] - x["t2"]) / x["t2"] < 0.01 for x in rows[-n_back:]):
        near = min(rows[-n_back:], key=lambda x: abs(x["close"] - x["t2"]))
        sig.append(f"二轨测试: {near['date']} 收{near['close']} 距二轨{near['t2']}"
                   f"(价差{(near['close']/near['t2']-1)*100:+.1f}%)")
    return sig, pct_rank


def play_tag(r, pct_rank, klines):
    c = r["close"]
    if c >= r["bot"] * 1.01 and c <= r["b4"]:
        return "超卖反弹候选: 底轨/五轨区域+低档确认信号可试探建仓"
    if c > r["t2"] and pct_rank < 30:
        return "收敛突破候选: 强势区+带宽收敛, 放量破顶轨跟进"
    if c >= r["t2"]:
        return "强势股打法: 回踩二轨不破继续持有/加仓; 摸顶轨兑现"
    if c >= r["mid"]:
        return "趋势观察: 中轨~二轨之间, 破中轨2-3天不拉回则离场"
    return "偏弱观望: 四轨附近或以下, 不符合UP三类打法的介入结构"


def main():
    codes, scale, fresh = _parse_cli(sys.argv[1:])
    n = 20
    if "--n" in codes:
        i = codes.index("--n"); n = int(codes[i + 1]); del codes[i:i + 2]
    if not codes:
        print(__doc__); sys.exit(1)
    for code in codes:
        try:
            if scale == "day":
                k = fetch_tencent_daily(code, fresh=fresh)
                label = f"{code} day"
            else:
                k = fetch_sina(code, scale, fresh=fresh)
                label = f"{code} {scale}m"
            rows = calc_boll7(k, n=n)
            r = rows[-1]
            pos = classify(r)
            sig, pr = signals(rows)
            tag = play_tag(r, pr, k)
            print("=" * 60)
            print(f"{label}  最新({r['date']}): 收 {r['close']}  位置: {pos}")
            print("七轨价位:")
            print(f"  顶轨(+3D) {r['top']} | 一轨(+2D) {r['t1']} | 二轨(+1D) {r['t2']}")
            print(f"  中轨(MA{n}) {r['mid']}")
            print(f"  四轨(-1D) {r['b4']} | 五轨(-2D) {r['b5']} | 底轨(-3D) {r['bot']}")
            for s in sig:
                print("  •", s)
            print("  打法:", tag)
            import json as _j
            print(_j.dumps(r, ensure_ascii=False))
        except Exception as e:
            print(f"[FAIL] {code}: {e}")
        import time
        time.sleep(2.0)


if __name__ == "__main__":
    main()
