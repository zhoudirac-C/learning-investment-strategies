#!/usr/bin/env python3
"""P2 因子评分：方向池内标的排序（动量40% + 波动率30% + 缠论结构30%）

用法：
  cd ~/learning-investment-strategies
  .venv/bin/python scripts/factor_rank.py                  # 全方向池排序
  .venv/bin/python scripts/factor_rank.py --theme ai_pcb   # 单方向排序
  .venv/bin/python scripts/factor_rank.py --top 10         # 只看前10

数据源：
  - chan_bars.db 日线（涨幅/ATR/vol）
  - chan_engine analyze_code（中枢结构/买卖点/背驰类型）
  - boll7（band_pct）
  - watchlist.yaml（方向池标的列表）

注意：
  - 不挂 cron，手动/事件驱动触发（遵循用户偏好）
  - 大单净流入数据不稳定（东财），默认跳过，降级为动量+波动率+缠论结构三因子
  - 权重 40/30/30 为初始值，后续可回测校准
"""
import sys, os, json, argparse
from pathlib import Path
from datetime import datetime

REPO = os.environ.get("HERMES_REPO_ROOT") or os.path.expanduser("~/learning-investment-strategies")
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "skills/finance/chanlun-course/scripts"))
sys.path.insert(0, os.path.expanduser("~/.hermes/skills/finance/bollinger-7track/scripts"))

from chan_engine.data.store import load_daily
from boll7 import calc_boll7
from chan_analysis import analyze_code, fetch_tencent_daily

# ---------- 因子计算 ----------

def momentum_score(closes):
    """动量因子：20日涨幅 rank + 60日涨幅 rank（越高越好）"""
    if len(closes) < 60:
        return None, None
    chg20 = (closes[-1] / closes[-21] - 1) * 100
    chg60 = (closes[-1] / closes[-61] - 1) * 100
    return chg20, chg60

def volatility_score(highs, lows, closes, band_pct=None):
    """波动率因子：ATR14/close（越低越好）+ band_pct 近60日分位（越低=越收敛=变盘临近）"""
    if len(closes) < 20:
        return None, None
    trs = []
    for i in range(1, len(closes)):
        tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
        trs.append(tr)
    atr14 = sum(trs[-14:]) / 14 if len(trs) >= 14 else None
    atr_pct = atr14 / closes[-1] * 100 if atr14 and closes[-1] else None
    return atr_pct, band_pct

def chan_structure_score(state_plan, backchi, entry_points):
    """缠论结构因子：中枢位置 + 买卖点类型 + 背驰类型（越高越好）

    评分规则：
    - 中枢位置：60m中枢上方=3 / 中枢内=1 / 中枢下方=0（30m同权，日线半权）
    - 买卖点：一买=3 / 二买=2 / 三买=1 / 无=0
    - 背驰类型：trend_div=2 / consolidation_div=1 / 无=0
    """
    score = 0
    reasons = []

    # 中枢位置（60m权重最高）
    pos_map = {"中枢上方": 3, "中枢内": 1, "中枢下方": 0}
    for tf, w in (("60m", 1.0), ("30m", 0.8), ("日线", 0.5)):
        st = state_plan.get(tf, {})
        pos = st.get("position", "")
        s = pos_map.get(pos, 0) * w
        score += s
        if s > 0:
            reasons.append(f"{tf}{pos}({s:.1f})")

    # 买卖点
    if entry_points:
        best_ep = max(entry_points, key=lambda e: {"一买":3,"二买":2,"三买":1}.get(e.get("type",""), 0))
        ep_score = {"一买":3,"二买":2,"三买":1}.get(best_ep.get("type",""), 0)
        score += ep_score
        reasons.append(f"{best_ep['type']}@{best_ep.get('level','')}({ep_score})")

    # 背驰类型
    if backchi:
        for lv, bk in backchi.items():
            bk_type = bk.get("backchi_type","")
            if bk_type == "trend_div":
                score += 2
                reasons.append(f"{lv}趋势背驰(+2)")
            elif bk_type == "consolidation_div":
                score += 1

    return score, reasons


def factor_rank(codes, top_n=None):
    """对标的列表计算因子评分并排序"""
    results = []

    for item in codes:
        code_full = item["code"]
        name = item.get("name", "")
        theme = item.get("theme_name", "")

        # 代码格式转换：002409.SZ → sz002409
        code_num = code_full.split(".")[0]
        mkt = "sh" if code_full.endswith(".SH") else "sz"
        code = mkt + code_num

        entry = {"code": code_full, "name": name, "theme": theme}

        try:
            # --- 日线数据（优先 chan_bars.db，fallback 腾讯日线） ---
            rows = load_daily(code)
            if not rows or len(rows) < 60:
                # fallback: 腾讯日线
                k = fetch_tencent_daily(code)
                if k and len(k) >= 60:
                    rows = [{"trade_date": r["date"], "open": r["open"], "high": r["high"],
                             "low": r["low"], "close": r["close"], "volume": r.get("vol", 0)}
                            for r in k]
                else:
                    entry["error"] = "数据不足"
                    results.append(entry)
                    continue

            closes = [float(r["close"]) for r in rows]
            highs  = [float(r["high"]) for r in rows]
            lows   = [float(r["low"]) for r in rows]

            # --- 动量 ---
            chg20, chg60 = momentum_score(closes)
            entry["chg20"] = round(chg20, 2) if chg20 is not None else None
            entry["chg60"] = round(chg60, 2) if chg60 is not None else None

            # --- 波动率 ---
            atr_pct, _ = volatility_score(highs, lows, closes)
            entry["atr_pct"] = round(atr_pct, 2) if atr_pct else None

            # band_pct
            try:
                k = fetch_tencent_daily(code)
                boll_rows = calc_boll7(k)
                entry["band_pct"] = round(boll_rows[-1].get("band_pct", 0), 2)
            except Exception:
                entry["band_pct"] = None

            # --- 缠论结构（仅 chan_bars.db 有分钟线数据的标的可算） ---
            try:
                report = analyze_code(code, None, False)
                sp = report.get("state_plan", {})
                bk = report.get("backchi", {})
                ep = report.get("entry_points", [])
                cs, reasons = chan_structure_score(sp, bk, ep)
                entry["chan_score"] = round(cs, 1)
                entry["chan_reasons"] = reasons[:3]
                entry["chan_60m_pos"] = sp.get("60m",{}).get("position","?")
            except Exception as e:
                # 无分钟线数据→缠论不可用，给中性分
                entry["chan_score"] = 0
                entry["chan_reasons"] = ["无分钟线数据"]
                entry["chan_60m_pos"] = "N/A"

        except Exception as e:
            entry["error"] = str(e)[:60]

        results.append(entry)

    # --- 排名（三维度分别 rank 后加权） ---
    valid = [e for e in results if "error" not in e and e.get("chg20") is not None]
    if not valid:
        return results

    # 动量 rank（越高越好→降序排名）
    valid.sort(key=lambda x: x["chg20"] or -999, reverse=True)
    for i, e in enumerate(valid):
        e["rank_chg20"] = i + 1
    valid.sort(key=lambda x: x["chg60"] or -999, reverse=True)
    for i, e in enumerate(valid):
        e["rank_chg60"] = i + 1

    # 波动率 rank（越低越好→升序排名=越小排越前）
    valid.sort(key=lambda x: x["atr_pct"] or 999)
    for i, e in enumerate(valid):
        e["rank_atr"] = i + 1
    valid.sort(key=lambda x: x.get("band_pct") or 999)
    for i, e in enumerate(valid):
        e["rank_band"] = i + 1

    # 缠论结构 rank（越高越好）
    valid.sort(key=lambda x: x.get("chan_score", 0), reverse=True)
    for i, e in enumerate(valid):
        e["rank_chan"] = i + 1

    # 综合评分：动量40% + 波动率30% + 缠论30%
    # 用排名的倒数（排名越小越好→转换为分数）
    n = len(valid)
    for e in valid:
        mom_score = (n - e["rank_chg20"] + 1) / n * 50 + (n - e["rank_chg60"] + 1) / n * 50
        vol_score = (n - e["rank_atr"] + 1) / n * 50 + (n - e["rank_band"] + 1) / n * 50
        chan_score = (n - e["rank_chan"] + 1) / n * 100
        e["momentum_score"] = round(mom_score, 1)
        e["volatility_score"] = round(vol_score, 1)
        e["chan_struct_score"] = round(chan_score, 1)
        e["total_score"] = round(mom_score * 0.4 + vol_score * 0.3 + chan_score * 0.3, 1)

    valid.sort(key=lambda x: x["total_score"], reverse=True)
    for i, e in enumerate(valid):
        e["rank_total"] = i + 1

    if top_n:
        valid = valid[:top_n]

    return valid + [e for e in results if "error" in e or e.get("chg20") is None]


def main():
    ap = argparse.ArgumentParser(description="P2 因子评分排序")
    ap.add_argument("--theme", help="只排序指定方向（theme id）")
    ap.add_argument("--top", type=int, default=None, help="只输出前N名")
    ap.add_argument("--json", action="store_true", help="输出JSON格式")
    args = ap.parse_args()

    # 读 watchlist
    import yaml
    with open(os.path.join(REPO, "config/stock_monitor/watchlist.yaml")) as f:
        wl = yaml.safe_load(f)

    themes = wl.get("themes", [])
    stocks = []
    for t in themes:
        if args.theme and t.get("id") != args.theme:
            continue
        for s in t.get("stocks", []):
            if isinstance(s, dict) and s.get("code"):
                stocks.append({"code": s["code"], "name": s.get("name",""),
                               "theme": t.get("id",""), "theme_name": t.get("name","")[:20]})

    # 去重（同一标的可能在多个方向）
    seen = set()
    unique = []
    for s in stocks:
        if s["code"] not in seen:
            seen.add(s["code"])
            unique.append(s)

    print(f"方向池标的: {len(unique)} 只" + (f" (theme={args.theme})" if args.theme else ""))
    print(f"数据时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")

    results = factor_rank(unique, top_n=args.top)

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return

    # 表格输出
    header = f"{'排名':>3} {'代码':<10} {'名称':<10} {'方向':<16} {'20日%':>7} {'60日%':>7} {'ATR%':>6} {'band%':>6} {'缠论':>5} {'动量':>5} {'波动':>5} {'总分':>6}  缠论结构"
    print(header)
    print("-" * len(header))
    for e in results:
        if "error" in e:
            print(f"{'--':>3} {e['code']:<10} {e['name']:<10} {e.get('theme',''):<16} ERROR: {e['error']}")
            continue
        reasons = "; ".join(e.get("chan_reasons", []))
        print(f"{e['rank_total']:>3} {e['code']:<10} {e['name']:<10} {e.get('theme',''):<16} "
              f"{e.get('chg20',0):>+6.1f} {e.get('chg60',0):>+6.1f} {e.get('atr_pct',0):>5.1f} "
              f"{e.get('band_pct',0):>5.1f} {e.get('chan_score',0):>4.1f} "
              f"{e.get('momentum_score',0):>5.1f} {e.get('volatility_score',0):>5.1f} {e.get('total_score',0):>5.1f}  {reasons}")


if __name__ == "__main__":
    main()
