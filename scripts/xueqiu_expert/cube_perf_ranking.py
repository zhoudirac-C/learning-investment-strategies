#!/usr/bin/env python3
"""C 渠道组合主理人 业绩排名（胜率×收益，2026-10-11 用户拍板需求）。

背景：文本轨 TOP20 的 C 类是"会发帖的组合主理人"，不代表组合能力；
组合轨回测分（提前布局命中）区分度差（97 人仅 6 人有分）。
本脚本用净值曲线直接度量组合业绩，重新排名。

口径：
- 范围 = candidates.json 中 source 以 C 开头且有 cube_symbol 的全部候选（97 人）。
- 数据 = /cubes/nav_daily/all.json 日净值（缓存 data/xueqiu/cube_nav/{symbol}.json，
  24h 内复用）。
- 指标（统一近 12 个月窗口，不足 120 个交易日标 low_confidence）：
  - ann_return_12m：窗口 CAGR（%）
  - total_return：成立以来总收益（%，仅展示）
  - monthly_win_rate：月胜率 = 上涨月份数/总月份数（%）
  - weekly_win_rate：周胜率（%，仅展示）
  - max_drawdown：窗口内最大回撤（%，正数）
  - volatility：日收益年化波动（%，仅展示）
- 综合分 = 0.50×年化分位 + 0.35×月胜率分位 + 0.15×(1−回撤分位)，分位在 C 池内计算。
- cube 回测命中分（eye_score）只展示不入分。
产出：data/xueqiu/cube_perf_ranking.json
"""
from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "data" / "xueqiu"
CAND = DATA / "candidates.json"
NAV_DIR = DATA / "cube_nav"
CUBE_RANKING = DATA / "cube_expert_ranking.json"
OUT = DATA / "cube_perf_ranking.json"
SLEEP = 5.0
GLOBAL_COOLDOWN = 600
MAX_COOLDOWNS = 3
CACHE_TTL = 24 * 3600
WINDOW_DAYS = 365
MIN_TRADING_DAYS = 120

W_ANN, W_WIN, W_DD = 0.50, 0.35, 0.15


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def cookie_header() -> str:
    cookies = json.loads((Path.home() / "xq_cookies.json").read_text(encoding="utf-8"))
    return "; ".join(f"{c['name']}={c['value']}" for c in cookies if "xueqiu" in (c.get("domain") or ""))


class RateLimited(RuntimeError):
    pass


def fetch_nav(symbol: str) -> list[dict]:
    """返回 [{date, value}] 日净值序列（缓存 24h）。"""
    path = NAV_DIR / f"{symbol}.json"
    if path.exists() and time.time() - path.stat().st_mtime < CACHE_TTL:
        return json.loads(path.read_text(encoding="utf-8"))
    hosts = ["www.xueqiu.com", "xueqiu.com"]
    backoffs = [0, 60, 120, 180]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
        "Referer": "https://www.xueqiu.com/",
        "Cookie": cookie_header(),
    }
    now = int(time.time() * 1000)
    since = now - 800 * 86400 * 1000
    for attempt in range(1, 5):
        host = hosts[(attempt - 1) % len(hosts)]
        url = f"https://{host}/cubes/nav_daily/all.json?cube_symbol={symbol}&since={since}&until={now}"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read().decode("utf-8"))
            items = data if isinstance(data, list) else (data.get("list") or data.get("items") or [])
            series: list[dict] = []
            for blk in items:
                # 第一块是组合本身，其余是基准（如沪深300）
                if str(blk.get("symbol", "")).upper() == symbol.upper():
                    series = blk.get("list") or []
                    break
            if not series and items:
                series = items[0].get("list") or []
            series = [{"date": p["date"], "value": float(p["value"])} for p in series if p.get("value")]
            NAV_DIR.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(series, ensure_ascii=False), encoding="utf-8")
            time.sleep(SLEEP)
            return series
        except urllib.error.HTTPError as e:  # noqa: BLE001
            body = e.read().decode("utf-8", errors="replace")[:300]
            if e.code == 400 and "110017" in body:
                if attempt < 4:
                    log(f"{symbol} 限流 110017（{host}），{backoffs[attempt]}s 后重试")
                    time.sleep(backoffs[attempt])
                    continue
                raise RateLimited(f"{symbol} 持续限流 110017")
            raise RuntimeError(f"HTTP {e.code} {body[:120]}")
    raise RuntimeError("unreachable")


def metrics(series: list[dict]) -> dict | None:
    if len(series) < 2:
        return None
    series = sorted(series, key=lambda p: p["date"])
    full_ret = (series[-1]["value"] / series[0]["value"] - 1) * 100
    # 近 12 个月窗口
    cutoff = datetime.fromtimestamp(time.time() - WINDOW_DAYS * 86400).strftime("%Y-%m-%d")
    win = [p for p in series if p["date"] >= cutoff]
    if len(win) < 2:
        win = series
    days = len(win)
    low_conf = days < MIN_TRADING_DAYS
    span_days = max((datetime.fromisoformat(win[-1]["date"]) - datetime.fromisoformat(win[0]["date"])).days, 1)
    ann = ((win[-1]["value"] / win[0]["value"]) ** (365 / span_days) - 1) * 100
    # 日收益
    rets = [win[i]["value"] / win[i - 1]["value"] - 1 for i in range(1, len(win))]
    vol = (math.sqrt(250) * (sum((r - sum(rets) / len(rets)) ** 2 for r in rets) / max(len(rets) - 1, 1)) ** 0.5 * 100) if len(rets) > 1 else 0.0
    # 最大回撤
    peak = win[0]["value"]
    mdd = 0.0
    for p in win:
        peak = max(peak, p["value"])
        mdd = max(mdd, (peak - p["value"]) / peak)
    # 月胜率 / 周胜率
    def period_wr(keyfn):
        groups: dict[str, list[float]] = {}
        for p in win:
            groups.setdefault(keyfn(p["date"]), []).append(p["value"])
        ups = tot = 0
        for vals in groups.values():
            if len(vals) >= 1:
                tot += 1
                if vals[-1] > vals[0]:
                    ups += 1
        return (ups / tot * 100) if tot else 0.0
    m_wr = period_wr(lambda d: d[:7])
    w_wr = period_wr(lambda d: datetime.fromisoformat(d).strftime("%G-W%V"))
    return {
        "trading_days": days, "low_confidence": low_conf,
        "ann_return_12m": round(ann, 2), "total_return": round(full_ret, 2),
        "monthly_win_rate": round(m_wr, 1), "weekly_win_rate": round(w_wr, 1),
        "max_drawdown": round(mdd * 100, 2), "volatility": round(vol, 2),
        "window_start": win[0]["date"], "window_end": win[-1]["date"],
    }


def pct_ranks(rows: list[dict], key: str, reverse: bool = True) -> dict[str, float]:
    """池内分位（1=最好）。reverse=True 时值越大越好。"""
    vals = sorted((r[key] for r in rows if key in r), reverse=reverse)
    n = len(vals)
    out = {}
    for r in rows:
        if key in r:
            rank = vals.index(r[key])  # 同分取首个，可接受
            out[r["cube_symbol"]] = 1 - rank / max(n - 1, 1)
    return out


def main() -> None:
    NAV_DIR.mkdir(parents=True, exist_ok=True)
    cands = json.loads(CAND.read_text(encoding="utf-8"))["with_uid"]
    cubes = [c for c in cands if c.get("source", "").startswith("C") and c.get("cube_symbol")]
    log(f"C渠道组合 {len(cubes)} 个")
    eye_by_uid = {}
    if CUBE_RANKING.exists():
        for r in json.loads(CUBE_RANKING.read_text(encoding="utf-8")).get("top", []):
            eye_by_uid[str(r.get("uid"))] = r.get("eye_score")
    rows = []
    cooldowns = 0
    i = 0
    while i < len(cubes):
        c = cubes[i]
        sym = c["cube_symbol"]
        try:
            series = fetch_nav(sym)
            m = metrics(series)
            row = {"uid": str(c["uid"]), "screen_name": c.get("screen_name", ""),
                   "cube_symbol": sym, "cube_annualized": c.get("cube_annualized"),
                   "followers_count": c.get("followers_count"),
                   "eye_score": eye_by_uid.get(str(c["uid"]))}
            if m:
                row.update(m)
            else:
                row["error"] = "净值数据不足"
            rows.append(row)
            i += 1
        except RateLimited as e:
            cooldowns += 1
            if cooldowns > MAX_COOLDOWNS:
                print(f"RATE_LIMITED {e}（已冷却 {cooldowns - 1} 次，退出；缓存可续跑）")
                return
            log(f"{sym} 持续限流，全局冷却 {GLOBAL_COOLDOWN}s（第 {cooldowns}/{MAX_COOLDOWNS} 次）")
            time.sleep(GLOBAL_COOLDOWN)
            continue
        except Exception as e:  # noqa: BLE001
            rows.append({"uid": str(c["uid"]), "screen_name": c.get("screen_name", ""),
                         "cube_symbol": sym, "error": str(e)[:200]})
            i += 1
        if i % 10 == 0:
            log(f"进度 {i}/{len(cubes)}")
    scored = [r for r in rows if "ann_return_12m" in r]
    pa = pct_ranks(scored, "ann_return_12m")
    pw = pct_ranks(scored, "monthly_win_rate")
    pd_ = pct_ranks(scored, "max_drawdown", reverse=False)
    for r in scored:
        r["composite"] = round(W_ANN * pa[r["cube_symbol"]] + W_WIN * pw[r["cube_symbol"]]
                               + W_DD * pd_[r["cube_symbol"]], 4)
    scored.sort(key=lambda r: r["composite"], reverse=True)
    for k, r in enumerate(scored, 1):
        r["rank"] = k
    failed = [r for r in rows if "ann_return_12m" not in r]
    OUT.write_text(json.dumps({
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "rule": f"composite = {W_ANN}*ann_return_12m_pct + {W_WIN}*monthly_win_rate_pct + {W_DD}*(1-max_drawdown_pct); window=12m; min_days={MIN_TRADING_DAYS}",
        "experts_evaluated": len(rows), "scored": len(scored), "failed": len(failed),
        "top": scored, "errors": failed,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"完成 → {OUT}（scored {len(scored)} / failed {len(failed)}）")
    for r in scored[:20]:
        lc = " ⚠️低置信" if r.get("low_confidence") else ""
        print(f"#{r['rank']:>2} {r['screen_name']:<14} {r['cube_symbol']} "
              f"综合{r['composite']:.3f} 年化12M {r['ann_return_12m']:>7.1f}% 月胜率 {r['monthly_win_rate']:>5.1f}% "
              f"回撤 {r['max_drawdown']:>5.1f}% 总收益 {r['total_return']:>7.1f}% 眼力 {r.get('eye_score')}{lc}")


if __name__ == "__main__":
    main()
