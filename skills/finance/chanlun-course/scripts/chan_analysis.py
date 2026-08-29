#!/usr/bin/env python3
"""缠论结构分析 CLI（M7-5 薄壳）：多周期级别引擎 + skill 输出惯例。

用法:
  python3 chan_analysis.py sh000001 sh512400 ...        # 多周期（日线+60m+30m，默认）
  python3 chan_analysis.py --60m sh000688 ...           # 日线 + 60m
  python3 chan_analysis.py --30m sh512400 ...           # 日线 + 30m
  python3 chan_analysis.py --day sh512400 ...           # 仅日线
  python3 chan_analysis.py --decomp --60m sh512400      # 同级别分解视角（G8）
  python3 chan_analysis.py --fresh ...                  # 兼容保留（chan_bars.db 每次运行即刷新，实为 no-op）
  python3 chan_analysis.py --scale N ...                # N 仅支持 30/60（30m 已是最细）

管线（2026-08-29 M7-5：算法管线已替换为 chan_engine 多周期级别引擎，仲裁⑥无 legacy）:
  chan_engine.data（akshare/baostock 日线 + 新浪/TDX 分钟线 → infra/data/chan_bars.db，
  双源皆挂时复读库内快照=stale 层）→ RecursionEngine（claims 校准口径）
  → multi_tf.analyze_nested（区间套：全序列引擎+窗口归属）
  → report.skill_adapter（防守线/反转确认位/仓位性质/失效条件/入场点/背驰类型/级别三问）

数据源经验保留（boll7 等同目录脚本 import 依赖，签名不动）：
  fetch_tencent_daily / fetch_sina / fetch_sina_60m / _parse_cli / resolve_symbol
  （腾讯日线/新浪分钟/TDX 降级链、/tmp/klines 缓存 TTL、UA 坑——仅供 boll7 等
  未迁移脚本使用；本 CLI 自身数据走 chan_engine.data 数据层）。

输出: 控制台摘要 + /tmp/chan_results.json（list 形态保持，每项含 report 全字段）
"""
import json, os, subprocess, sys, time
from pathlib import Path

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
CACHE = "/tmp/klines"
TTL_MIN = 300       # 分钟线缓存有效期（秒）
TTL_DAY = 28800     # 日线缓存有效期（秒）8h
OUT_JSON = Path("/tmp/chan_results.json")


def _repo_root() -> Path:
    """仓库根：HERMES_REPO_ROOT 优先；否则向上找 src/chan_engine；最后回退默认路径
    （skill 可能被复制到 ~/.hermes/skills 下运行）。"""
    env = os.environ.get("HERMES_REPO_ROOT")
    if env:
        return Path(env)
    for p in Path(__file__).resolve().parents:
        if (p / "src" / "chan_engine").is_dir():
            return p
    return Path(os.path.expanduser("~/learning-investment-strategies"))


_ROOT = _repo_root()
for _p in (str(_ROOT / "src"), str(_ROOT / "third_party" / "chanpy")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from chan_engine.data import (  # noqa: E402
    DEFAULT_DB, fetch_daily, fetch_minute, load_daily, load_minute,
    save_daily, save_minute,
)
from chan_engine.data.fetch import DataFetchError  # noqa: E402
from chan_engine.core.engine import RecursionEngine  # noqa: E402
from chan_engine.multi_tf import TFAligner, analyze_nested  # noqa: E402
from chan_engine.multi_tf.nested import _rows_to_bars  # noqa: E402
from chan_engine.report.skill_adapter import (  # noqa: E402
    WINDOW_NOTE, build_decomp, build_report,
)
from chan_engine.spec.model import Bar  # noqa: E402

TF_OF_SCALE = {60: "60m", 30: "30m"}


# ---------- 降级链支持：TDX（旧拉取函数保留，供 boll7 等未迁移脚本） ----------
_TDX = None
def _get_tdx():
    """懒加载 TdxMarket（pytdx 直连）。失败返回 None，跳过该降级层。"""
    global _TDX
    if _TDX is not None:
        return _TDX if _TDX is not False else None
    try:
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
    """（保留供 boll7 等）腾讯日线 → TDX → stale。本 CLI 自身走 chan_engine.data。"""
    path = f"{CACHE}/{code}.json"
    data = None
    if not fresh and _cache_valid(path, ttl):
        with open(path) as f:
            data = json.load(f)
    else:
        try:
            url = f"https://ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,{n},qfq"
            data = curl_json(url)
            d = data["data"][list(data["data"].keys())[0]]
            assert d.get("qfqday") or d.get("day")
        except Exception as e:
            print(f"[WARN] 腾讯日线失败({e})，尝试 TDX")
            data = None
        if data is None:
            tdx = _get_tdx()
            if tdx:
                sym = resolve_symbol(code)
                for p in ("daily", "day"):
                    try:
                        rows = tdx.get_kline(sym, p, count=n)
                        if rows:
                            klines = _norm_tdx_kline(rows)
                            _save_cache(path, {"data": {code: {"day": [
                                [k["date"][:10], str(k["open"]), str(k["close"]),
                                 str(k["high"]), str(k["low"]), str(k["vol"])] for k in klines]}}})
                            print(f"[INFO] 日线来自 TDX: {sym} (period={p})")
                            data = json.load(open(path))
                            break
                    except Exception as e2:
                        print(f"[WARN] TDX {p} 失败: {e2}")
        if data is None:
            data = _stale_fallback(path, f"日线{code}")
    d = data["data"]
    key = list(d.keys())[0]
    rows = d[key].get("qfqday") or d[key].get("day")
    return [{"date": r[0], "open": float(r[1]), "close": float(r[2]),
             "high": float(r[3]), "low": float(r[4]), "vol": float(r[5]) if len(r) > 5 else 0}
            for r in rows]

def fetch_sina(code, scale, n=260, ttl=TTL_MIN, fresh=False):
    """（保留供 boll7 等）新浪分钟K线。降级链: 新浪 → TDX(N分钟) → stale 缓存"""
    path = f"{CACHE}/{code}_{scale}m.json"
    data = None
    if not fresh and _cache_valid(path, ttl):
        with open(path) as f:
            data = json.load(f)
    else:
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


# ---------- M7-5 薄壳：chan_engine 多周期管线 ----------

def _daily_rows(code: str) -> list[dict]:
    """日线：抓取→落库→复读；双源皆挂 → 库内快照（stale 层）；库空 → DataFetchError。"""
    try:
        rows, source = fetch_daily(code)
        save_daily(code, rows, source=source, db_path=DEFAULT_DB)
    except DataFetchError as e:
        print(f"[WARN] {code} 日线抓取失败（{e}），复读库内快照")
    rows = load_daily(code, db_path=DEFAULT_DB)
    if not rows:
        raise DataFetchError(f"{code} 日线无数据（源失败且库为空）")
    return rows


def _minute_rows(code: str, tf: int) -> list[dict]:
    """分钟线：同日线纪律（库内快照即 stale 层）。"""
    try:
        rows, source = fetch_minute(code, tf)
        save_minute(code, tf, rows, source=source, db_path=DEFAULT_DB)
    except DataFetchError as e:
        print(f"[WARN] {code} {tf}m 抓取失败（{e}），复读库内快照")
    rows = load_minute(code, tf, db_path=DEFAULT_DB)
    if not rows:
        raise DataFetchError(f"{code} {tf}m 无数据（源失败且库为空）")
    return rows


def analyze_code(code: str, scale, decomp: bool) -> dict:
    """单标的多周期管线 → report dict（skill 输出惯例）。"""
    daily_rows = _daily_rows(code)
    daily_dates = [r["trade_date"] for r in daily_rows]
    daily_bars = [Bar(ts=i, o=r["open"], h=r["high"], l=r["low"], c=r["close"],
                      vol=r["volume"] or 0.0) for i, r in enumerate(daily_rows)]

    if scale == "day":
        tfs: dict[str, int] = {}
    elif scale in TF_OF_SCALE:
        tfs = {TF_OF_SCALE[scale]: scale}
    else:
        tfs = {"60m": 60, "30m": 30}
    sub_rows = {label: _minute_rows(code, tf) for label, tf in tfs.items()}

    daily_chart = RecursionEngine().run(daily_bars)
    mtc = analyze_nested(daily_chart, daily_dates, sub_rows) if sub_rows else None
    if mtc is None:
        from chan_engine.multi_tf.model import MultiTimeframeChart
        mtc = MultiTimeframeChart(daily=daily_chart)

    # adapter 的 sub bars/stamps 必须与 analyze_nested 内部过滤后的行对齐
    if sub_rows:
        al = TFAligner(daily_dates, sub_rows)
        sub_bars = {tf: _rows_to_bars(al.sub_rows[tf]) for tf in al.sub_rows}
        sub_stamps = {tf: [r["dt"] for r in al.sub_rows[tf]] for tf in al.sub_rows}
    else:
        sub_bars, sub_stamps = {}, {}
    report = build_report(mtc, code, daily_bars, daily_dates, sub_bars, sub_stamps)
    if decomp:
        levels = list(tfs) or ["日线"]
        for lv in levels:
            chart = mtc.sub.get(lv) if lv != "日线" else daily_chart
            bars = sub_bars.get(lv) if lv != "日线" else daily_bars
            if chart is not None and bars:
                report.setdefault("decomp", {})[lv] = build_decomp(
                    chart, lv, float(bars[-1].c))
    report["label"] = code
    return report


def render_console(r: dict) -> None:
    """报告 → 控制台摘要（skill 输出惯例）。"""
    print(f"\n{'=' * 60}")
    asof = r["asof"]
    print(f"{r['label']}  数据基准: " + " / ".join(
        f"{k} {v}" for k, v in asof.items()))
    pn = r["position_nature"]
    print(f"仓位性质（{pn['basis']}）: {pn['label']} —— {pn['reason']}")
    if r["defense_lines"]:
        print("防守线: " + " | ".join(
            f"[{d['level']}] {d['price']}（{d['ref']}）" for d in r["defense_lines"]))
    if r["reversal_confirm"]:
        rc = r["reversal_confirm"]
        print(f"反转确认位（{rc['level']}）: {rc['price']}（{rc['ref']}）")
    if r["entry_points"]:
        print("入场点（次级别）:")
        for e in r["entry_points"]:
            print(f"  [{e['level']}] {e['type']} L{e['level_n']} @{e['dt']} 价 {e['price']}"
                  f"{'（未确认）' if not e['sure'] else ''}")
    if r["backchi"]:
        print("背驰类型: " + " | ".join(
            f"[{lv}] {b['backchi_type']}（{b['ref']}）" for lv, b in r["backchi"].items()))
    if r["invalidation"]:
        print("失效条件:")
        for line in r["invalidation"]:
            print(f"  {line}")
    for lv, st in r.get("state_plan", {}).items():
        print(f"分类状态[{lv}]: {st['position']} / {st['state']} → {st['plan']}")
    for lv, d in r.get("decomp", {}).items():
        cur = d["current_segment"] or {}
        zs_txt = f"[{d['current_zs']['zd']}, {d['current_zs']['zg']}]" if d["current_zs"] else "无"
        print(f"同级别分解[{lv}]: 当前中枢 {zs_txt}，当前段 {cur.get('dir')}"
              f"（{'已确认' if cur.get('sure') else '未确认'}），位置 {d['position']}")
    if r["small_to_large_alerts"]:
        print("小转大候选（须人工与大级别背驰确认）: "
              + ", ".join(f"{a['tf']} 笔{a['bi_ref']}" for a in r["small_to_large_alerts"]))
    print(f"窗口声明: {WINDOW_NOTE}")


def _parse_cli(argv):
    """返回 (codes, scale, fresh)。scale: 'day' 或分钟数 int（boll7 依赖此三元组）"""
    fresh = "--fresh" in argv
    args = [a for a in argv if a != "--fresh"]
    scale = "day"
    # 顺序：--scale N 优先，其次 --30m/--60m/--day 等命名 flag
    if "--scale" in args:
        i = args.index("--scale")
        try:
            scale = int(args[i + 1])
            del args[i:i + 2]
        except (ValueError, IndexError):
            print("--scale 需要整数分钟数，如 --scale 30"); sys.exit(1)
    elif "--day" in args:
        args.remove("--day"); scale = "day"
    else:
        for name, s in (("--30m", 30), ("--60m", 60), ("--15m", 15), ("--5m", 5)):
            if name in args:
                scale = s; args.remove(name); break
    return args, scale, fresh


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    decomp = "--decomp" in argv
    day_only = "--day" in argv
    argv = [a for a in argv if a not in ("--decomp", "--day")]
    codes, scale, _fresh = _parse_cli(argv)
    if day_only:
        scale = "day"  # 显式 --day → 仅日线；无 flag 默认多周期（§8.1）
    elif scale == "day":
        scale = None   # 无 flag → multi_tf（日线+60m+30m）
    if not codes:
        print(__doc__)
        return 1
    if scale is not None and scale != "day" and scale not in TF_OF_SCALE:
        print(f"[FAIL] --scale {scale} 不支持：多周期引擎仅 60m/30m"
              f"（30m 已是最细，设计 §2.2 非目标）")
        return 1
    results = []
    failed = 0
    for i, code in enumerate(codes):
        try:
            r = analyze_code(code, scale, decomp)
            results.append(r)
            render_console(r)
        except Exception as e:
            failed += 1
            print(f"[FAIL] {code}: {e}")
        if i < len(codes) - 1:
            time.sleep(2.5)
    OUT_JSON.write_text(json.dumps(results, ensure_ascii=False, indent=1, default=str))
    print(f"\nsaved {OUT_JSON}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
