#!/usr/bin/env python3
"""缠论结构分析：K线包含处理 → 分型 → 笔 → 中枢 → 背驰 → 买卖点

用法:
  python3 chan_analysis.py sh000001 sh000688 sh515980 ...        # 日线（腾讯，默认）
  python3 chan_analysis.py --60m sh000688 sz399006 ...           # 60分钟（新浪）
  python3 chan_analysis.py --30m sh512400 ...                    # 30分钟（新浪）
  python3 chan_analysis.py --scale 15 sh512400 ...               # 任意分钟周期（新浪）
  python3 chan_analysis.py --day sh512400 ...                    # 显式日线
  python3 chan_analysis.py --fresh --30m sh512400 ...            # 强制绕过缓存重拉

数据源:
  日线: https://ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,260,qfq
    必须 curl + 完整 UA "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"，python urllib 默认 UA 被限流返回 data:[]
  分钟线(30m/60m/15m...): https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData
    ?symbol={sym}&scale={N}&ma=no&datalen=260
    腾讯分钟线接口不可用（mkline 301 / fqkline m60 param error），必须新浪

缓存: /tmp/klines/{code}[_{N}m].json
  - 分钟线缓存默认 TTL=300s（盘中 5 分钟过期自动重拉，避免用到旧 bar）
  - 日线缓存默认 TTL=8h
  - --fresh 强制绕过缓存重拉（批量预拉推荐 curl 存盘再跑，规避限流）

输出: 控制台摘要 + /tmp/chan_results.json
"""
import json, os, subprocess, sys, time

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
CACHE = "/tmp/klines"
TTL_MIN = 300       # 分钟线缓存有效期（秒）
TTL_DAY = 28800     # 日线缓存有效期（秒）8h

# ---------- 降级链支持：TDX ----------
_TDX = None
def _get_tdx():
    """懒加载 TdxMarket（pytdx 直连）。失败返回 None，跳过该降级层。"""
    global _TDX
    if _TDX is not None:
        return _TDX if _TDX is not False else None
    try:
        sys.path.insert(0, os.path.expanduser("~/learning-investment-strategies/src"))
        from qing_investment.tdx_market.market import TdxMarket
        _TDX = TdxMarket()
    except Exception as e:
        print(f"[WARN] TDX 不可用，跳过该降级层: {e}")
        _TDX = False
    return _TDX

def resolve_symbol(code):
    """ETF/指数补前缀：6/9开头→sh，0/3开头→sz。已带前缀原样返回"""
    if code[:2] in ("sh", "sz"):
        return code
    return ("sh" if code[0] in "69" else "sz") + code

def _norm_tdx_kline(rows):
    """TDX rows → 统一 kline dict（date 截到分钟，与新浪格式对齐）"""
    out = []
    for r in rows:
        dt = r.get("datetime") or str(r.get("date", ""))
        out.append({"date": dt, "open": float(r["open"]), "close": float(r["close"]),
                    "high": float(r["high"]), "low": float(r["low"]),
                    "vol": float(r.get("volume", r.get("vol", 0)))})
    return out

def curl_json(url):
    out = subprocess.run(["curl", "-s", "--max-time", "10", "-A", UA, url], capture_output=True)
    return json.loads(out.stdout.decode("utf-8", errors="replace"))

def _cache_valid(path, ttl):
    if not os.path.exists(path):
        return False
    return (time.time() - os.path.getmtime(path)) < ttl

def _save_cache(path, data):
    os.makedirs(CACHE, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)

def _stale_fallback(path, label):
    """降级末级：过期缓存仍可用（标注警告），否则抛错"""
    if os.path.exists(path):
        with open(path) as f:
            data = json.load(f)
        age_min = (time.time() - os.path.getmtime(path)) / 60
        print(f"[WARN] {label} 数据源全失败，使用 stale 缓存（age={age_min:.0f}min）——盘中勿当实时结构判断")
        return data
    raise RuntimeError(f"{label} 所有数据源失败且无缓存")

def fetch_tencent_daily(code, n=260, ttl=TTL_DAY, fresh=False):
    path = f"{CACHE}/{code}.json"
    data = None
    if not fresh and _cache_valid(path, ttl):
        with open(path) as f:
            data = json.load(f)
    else:
        # L1 腾讯
        try:
            url = f"https://ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,{n},qfq"
            data = curl_json(url)
            d = data["data"][list(data["data"].keys())[0]]
            assert d.get("qfqday") or d.get("day")
        except Exception as e:
            print(f"[WARN] 腾讯日线失败({e})，尝试 TDX")
            data = None
        # L2 TDX 日K
        if data is None:
            tdx = _get_tdx()
            if tdx:
                sym = resolve_symbol(code)
                for p in ("daily", "day"):
                    try:
                        rows = tdx.get_kline(sym, p, count=n)
                        if rows:
                            klines = _norm_tdx_kline(rows)
                            # 缓存成腾讯格式，末段解析逻辑统一消费
                            _save_cache(path, {"data": {code: {"day": [
                                [k["date"][:10], str(k["open"]), str(k["close"]),
                                 str(k["high"]), str(k["low"]), str(k["vol"])] for k in klines]}}})
                            print(f"[INFO] 日线来自 TDX: {sym} (period={p})")
                            data = json.load(open(path))
                            break
                    except Exception as e2:
                        print(f"[WARN] TDX {p} 失败: {e2}")
        # L3 stale
        if data is None:
            data = _stale_fallback(path, f"日线{code}")
    d = data["data"]
    key = list(d.keys())[0]
    rows = d[key].get("qfqday") or d[key].get("day")
    return [{"date": r[0], "open": float(r[1]), "close": float(r[2]),
             "high": float(r[3]), "low": float(r[4]), "vol": float(r[5]) if len(r) > 5 else 0}
            for r in rows]

def fetch_sina(code, scale, n=260, ttl=TTL_MIN, fresh=False):
    """新浪分钟K线，scale=30/60/15/5...，缓存按 {code}_{N}m.json，TTL 默认 300s。
    降级链: 新浪 → TDX(N分钟或近似) → stale 缓存"""
    path = f"{CACHE}/{code}_{scale}m.json"
    data = None
    if not fresh and _cache_valid(path, ttl):
        with open(path) as f:
            data = json.load(f)
    else:
        # L1 新浪
        try:
            url = (f"https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData"
                   f"?symbol={code}&scale={scale}&ma=no&datalen={n}")
            raw = curl_json(url)
            if isinstance(raw, list) and raw and "close" in raw[0]:
                data = raw
                _save_cache(path, data)
            else:
                raise RuntimeError(f"空数据/异常响应: {str(raw)[:80]}")
        except Exception as e:
            print(f"[WARN] 新浪{scale}m失败({e})，尝试 TDX")
            data = None
        # L2 TDX 分钟线
        if data is None:
            tdx = _get_tdx()
            if tdx:
                sym = resolve_symbol(code)
                mname = f"{scale}min" if scale in (5, 15, 30, 60) else None
                if mname:
                    try:
                        rows = tdx.get_kline(sym, mname, count=n)
                        if rows:
                            data = _norm_tdx_kline(rows)
                            _save_cache(path, data)
                            print(f"[INFO] {scale}m 来自 TDX: {sym}")
                    except Exception as e2:
                        print(f"[WARN] TDX {mname} 失败: {e2}")
        # L3 stale
        if data is None:
            data = _stale_fallback(path, f"{scale}m {code}")
    if data and isinstance(data[0], dict) and "close" in data[0]:
        key = "day" if "day" in data[0] else "date"
        return [{"date": r[key], "open": float(r["open"]), "close": float(r["close"]),
                 "high": float(r["high"]), "low": float(r["low"]),
                 "vol": float(r.get("volume", r.get("vol", 0)))} for r in data]
    return data

def fetch_sina_60m(code, n=260, fresh=False):
    """向后兼容：等价 fetch_sina(code, 60)"""
    return fetch_sina(code, 60, n=n, fresh=fresh)

# ---------- 缠论核心 ----------

def merge_inclusion(klines):
    """K线包含处理：按趋势方向合并。向上取高高，向下取低低"""
    if not klines:
        return []
    merged = [{"high": klines[0]["high"], "low": klines[0]["low"],
               "date": klines[0]["date"], "idx": [0], "close": klines[0]["close"]}]
    direction = 1
    for i in range(1, len(klines)):
        k = klines[i]
        last = merged[-1]
        contained = (k["high"] <= last["high"] and k["low"] >= last["low"]) or \
                    (k["high"] >= last["high"] and k["low"] <= last["low"])
        if contained:
            if direction == 1:
                new_high = max(k["high"], last["high"]); new_low = max(k["low"], last["low"])
            else:
                new_high = min(k["high"], last["high"]); new_low = min(k["low"], last["low"])
            last["high"] = new_high; last["low"] = new_low
            last["idx"].append(i); last["date"] = k["date"]; last["close"] = k["close"]
        else:
            direction = 1 if k["high"] > last["high"] else -1
            merged.append({"high": k["high"], "low": k["low"], "date": k["date"],
                           "idx": [i], "close": k["close"]})
    return merged

def find_fractals(merged):
    """分型：顶=high最高且low最高，底=low最低且high最低（合并K线上）"""
    fracs = []
    for i in range(1, len(merged) - 1):
        a, b, c = merged[i-1], merged[i], merged[i+1]
        if b["high"] > a["high"] and b["high"] > c["high"] and b["low"] > a["low"] and b["low"] > c["low"]:
            fracs.append({"type": "top", "idx": i, "price": b["high"], "date": b["date"]})
        elif b["low"] < a["low"] and b["low"] < c["low"] and b["high"] < a["high"] and b["high"] < c["high"]:
            fracs.append({"type": "bottom", "idx": i, "price": b["low"], "date": b["date"]})
    return fracs

def find_bi(fracs):
    """笔：顶底交替；异型分型 idx 间隔≥3（合并后）；同型取更极端"""
    bi = []
    for f in fracs:
        if not bi:
            bi.append(f); continue
        last = bi[-1]
        if f["type"] == last["type"]:
            if f["type"] == "top" and f["price"] > last["price"]:
                bi[-1] = f
            elif f["type"] == "bottom" and f["price"] < last["price"]:
                bi[-1] = f
        else:
            if f["idx"] - last["idx"] >= 3:
                bi.append(f)
    return bi

def calc_macd(klines, fast=12, slow=26, signal=9):
    n = len(klines)
    ema_f = [None]*n; ema_s = [None]*n; dif = [None]*n; dea = [None]*n; hist = [None]*n
    kf, ks, kd = 2/(fast+1), 2/(slow+1), 2/(signal+1)
    for i in range(n):
        c = klines[i]["close"]
        ema_f[i] = c if i == 0 else c*kf + ema_f[i-1]*(1-kf)
        ema_s[i] = c if i == 0 else c*ks + ema_s[i-1]*(1-ks)
        dif[i] = ema_f[i] - ema_s[i]
        dea[i] = dif[i] if i == 0 else dif[i]*kd + dea[i-1]*(1-kd)
        hist[i] = (dif[i] - dea[i]) * 2
    return dif, dea, hist

def identify_zhongshu(bi):
    """中枢：连续3笔（顶底交替）重叠区间 [ZD,ZG]；相邻重叠中枢合并"""
    zs_list = []
    i = 0
    while i <= len(bi) - 3:
        p1, p2, p3 = bi[i], bi[i+1], bi[i+2]
        if p1["type"] == p2["type"] or p2["type"] == p3["type"]:
            i += 1; continue
        seg1_lo, seg1_hi = min(p1["price"], p2["price"]), max(p1["price"], p2["price"])
        seg2_lo, seg2_hi = min(p2["price"], p3["price"]), max(p2["price"], p3["price"])
        zd = max(seg1_lo, seg2_lo); zg = min(seg1_hi, seg2_hi)
        if zd < zg:
            zs_list.append({"start": i, "end": i+2, "zd": zd, "zg": zg,
                            "center": (zd+zg)/2, "start_date": p1["date"], "end_date": p3["date"]})
        i += 1
    if not zs_list:
        return []
    merged_zs = [zs_list[0]]
    for z in zs_list[1:]:
        last = merged_zs[-1]
        if z["start"] <= last["end"] + 1 and (z["zd"] < last["zg"] and z["zg"] > last["zd"]):
            last["end"] = max(last["end"], z["end"])
            last["zd"] = max(last["zd"], z["zd"])
            last["zg"] = min(last["zg"], z["zg"])
            last["end_date"] = z["end_date"]
        else:
            merged_zs.append(z)
    return merged_zs

def bi_macd_area(merged, hist, bi, i, j):
    """第i..j笔间 MACD 柱面积（|hist| 求和）。bi 的 idx 是合并K线索引，映射回原始K线"""
    s_orig = merged[bi[i]["idx"]]["idx"][0]
    e_orig = merged[bi[j]["idx"]]["idx"][-1]
    lo, hi = min(s_orig, e_orig), max(s_orig, e_orig)
    return sum(abs(v) for v in hist[lo:hi+1] if v is not None)

def detect_backtension(bi, merged, hist):
    """背驰：同向笔（隔一笔）MACD 面积 a2 < a1×0.9 且价格延伸"""
    bt = []
    for i in range(2, len(bi)):
        prev, cur = bi[i-2], bi[i]
        if prev["type"] == cur["type"]:
            a1 = bi_macd_area(merged, hist, bi, i-2, i-1)
            a2 = bi_macd_area(merged, hist, bi, i-1, i)
            if a2 < a1 * 0.9:
                if cur["type"] == "bottom" and cur["price"] <= prev["price"] + 1e-9:
                    bt.append({"type": "bottom_div", "idx": i, "price": cur["price"],
                               "date": cur["date"], "area_prev": round(a1, 2), "area_cur": round(a2, 2)})
                elif cur["type"] == "top" and cur["price"] >= prev["price"] - 1e-9:
                    bt.append({"type": "top_div", "idx": i, "price": cur["price"],
                               "date": cur["date"], "area_prev": round(a1, 2), "area_cur": round(a2, 2)})
    return bt

def classify_buy_points(bi, zs_list, bt_list):
    """买卖点：一买(底背驰)/二买(回调不创新低)/三买(突破ZG后回调不回中枢)"""
    points = []
    for b in bt_list:
        if b["type"] == "bottom_div":
            points.append({"kind": "一买(趋势底背驰)", "price": b["price"], "date": b["date"]})
    if zs_list:
        last_zs = zs_list[-1]
        for k in range(len(bi)-1, 0, -1):
            if bi[k]["type"] == "top" and bi[k]["price"] > last_zs["zg"] and bi[k]["idx"] > last_zs["end"]:
                if k+1 < len(bi) and bi[k+1]["type"] == "bottom" and bi[k+1]["price"] > last_zs["zg"]:
                    points.append({"kind": "三买(回调不破中枢)", "price": bi[k+1]["price"],
                                   "date": bi[k+1]["date"],
                                   "ref_zs_zd": round(last_zs["zd"], 3), "ref_zs_zg": round(last_zs["zg"], 3)})
                break
    if bt_list:
        last_bt = bt_list[-1]
        if last_bt["type"] == "bottom_div":
            for k in range(len(bi)-1, 0, -1):
                if bi[k]["type"] == "bottom" and bi[k]["idx"] > last_bt["idx"] and bi[k]["price"] > last_bt["price"]:
                    points.append({"kind": "二买(回调不创新低)", "price": bi[k]["price"],
                                   "date": bi[k]["date"], "ref_low": last_bt["price"]})
                    break
    return points

def run_chan(klines, label):
    merged = merge_inclusion(klines)
    fracs = find_fractals(merged)
    bi = find_bi(fracs)
    dif, dea, hist = calc_macd(klines)
    zs_list = identify_zhongshu(bi)
    bt_list = detect_backtension(bi, merged, hist)
    points = classify_buy_points(bi, zs_list, bt_list)
    last = klines[-1]
    pos_in_zs = None
    if zs_list:
        z = zs_list[-1]
        if z["zd"] <= last["close"] <= z["zg"]:
            pos_in_zs = "中枢内"
        elif last["close"] > z["zg"]:
            pos_in_zs = "中枢上方"
        else:
            pos_in_zs = "中枢下方"
    return {"label": label, "last_date": last["date"], "last_close": last["close"],
            "bars": len(klines), "position": pos_in_zs,
            "bi": [{"type": b["type"], "price": b["price"], "date": b["date"]} for b in bi],
            "zhongshu": [{"zd": round(z["zd"], 3), "zg": round(z["zg"], 3),
                          "start": z["start_date"], "end": z["end_date"]} for z in zs_list],
            "backtension": bt_list, "buy_points": points,
            "macd_last": {"dif": round(dif[-1], 3) if dif[-1] is not None else None,
                          "dea": round(dea[-1], 3) if dea[-1] is not None else None,
                          "hist": round(hist[-1], 3) if hist[-1] is not None else None}}

def summarize(r):
    print(f"\n{'='*60}")
    print(f"{r['label']}  最新: {r['last_date']} 收 {r['last_close']}  位置: {r['position']}")
    print(f"MACD: dif={r['macd_last']['dif']} dea={r['macd_last']['dea']} hist={r['macd_last']['hist']}")
    print("最近6笔:")
    for b in r['bi'][-6:]:
        print(f"  {b['type']:6s} {b['price']:>10.2f}  {b['date']}")
    print("最近中枢:")
    for z in r['zhongshu'][-2:]:
        print(f"  [{z['zd']:.3f}, {z['zg']:.3f}]  {z['start']} ~ {z['end']}")
    print(f"背驰: {r['backtension'][-2:] if r['backtension'] else '无'}")
    print(f"买点: {r['buy_points'][-2:] if r['buy_points'] else '无'}")

def _parse_cli(argv):
    """返回 (codes, scale, fresh)。scale: 'day' 或分钟数 int"""
    fresh = "--fresh" in argv
    args = [a for a in argv if a != "--fresh"]
    scale = "day"
    # 顺序：--scale N 优先，其次 --30m/--60m/--day 等命名 flag
    if "--scale" in args:
        i = args.index("--scale")
        try:
            scale = int(args[i+1])
            del args[i:i+2]
        except (ValueError, IndexError):
            print("--scale 需要整数分钟数，如 --scale 30"); sys.exit(1)
    elif "--day" in args:
        args.remove("--day"); scale = "day"
    else:
        for name, s in (("--30m", 30), ("--60m", 60), ("--15m", 15), ("--5m", 5)):
            if name in args:
                scale = s; args.remove(name); break
    return args, scale, fresh

if __name__ == "__main__":
    codes, scale, fresh = _parse_cli(sys.argv[1:])
    if not codes:
        print(__doc__); sys.exit(1)
    results = []
    for i, code in enumerate(codes):
        try:
            if scale == "day":
                k = fetch_tencent_daily(code, fresh=fresh)
                r = run_chan(k, code)
            else:
                k = fetch_sina(code, scale, fresh=fresh)
                r = run_chan(k, f"{code} {scale}m")
            results.append(r); summarize(r)
        except Exception as e:
            print(f"[FAIL] {code}: {e}")
        if i < len(codes) - 1:
            time.sleep(2.5)
    with open("/tmp/chan_results.json", "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    print("\nsaved /tmp/chan_results.json")
