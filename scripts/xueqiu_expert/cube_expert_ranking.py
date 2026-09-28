#!/usr/bin/env python3
"""C 渠道组合主理人评估：用组合调仓历史而不是发帖，衡量是否提前布局启动板块。

口径 v1（2026-09-28）：
- 事件库沿用 P1 sector_launches.json：启动日前 3~21 天为预判窗口（强=7~21 / 中=3~6）。
- 一次调仓内，同一板块相关股票的 target_weight-prev_weight 增量合计 >=5 个百分点，记一次有效加仓。
- 同一 cube 对同一板块同一启动事件只计最早一次有效加仓；lead=启动日-调仓日。
- 分数沿用文本轨结构：眼力=强×3+中×1；持续力=命中板块数；密度=命中事件数/调仓次数；综合=眼力×0.5+持续×0.3+密度×0.2。cube_annualized 只展示不入分。
产出：data/xueqiu/cubes/{cube_symbol}.json + data/xueqiu/cube_expert_ranking.json
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "data" / "xueqiu"
CAND = DATA / "candidates.json"
CUBE_DIR = DATA / "cubes"
OUT = DATA / "cube_expert_ranking.json"
MAPPING = REPO / "config" / "stock_monitor" / "stock_sector_mapping.json"
MIN_WEIGHT_INCR = 5.0  # 百分点
SLEEP = 2.0
COUNT = 20  # 雪球该端点 count>20 会 400；且高频会触发 110017，需要慢速+退避


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def norm_code(symbol: str) -> str:
    m = re.search(r"(\d{6})", symbol or "")
    return m.group(1) if m else ""


def load_events():
    launches = json.loads((DATA / "sector_launches.json").read_text(encoding="utf-8"))
    events = launches if isinstance(launches, list) else (launches.get("launches") or launches.get("events"))
    by_sector = {}
    for e in events:
        by_sector.setdefault(e["sector"], []).append(e)
    for v in by_sector.values():
        v.sort(key=lambda e: e["launch_date"])
    return by_sector


def load_mapping():
    m = json.loads(MAPPING.read_text(encoding="utf-8"))
    mp = m.get("mapping", m)
    out = {}
    for code, boards in mp.items():
        if str(code).startswith("_"):
            continue
        names = {b.get("name", "") for b in boards or [] if b.get("name")}
        if names:
            out[str(code)] = names
    return out


def cookie_header() -> str:
    cookies = json.loads((Path.home() / "xq_cookies.json").read_text(encoding="utf-8"))
    return "; ".join(f"{c['name']}={c['value']}" for c in cookies if "xueqiu" in (c.get("domain") or ""))


class RateLimited(RuntimeError):
    pass


def fetch_cube(symbol: str) -> dict:
    path = CUBE_DIR / f"{symbol}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    url = f"https://xueqiu.com/cubes/rebalancing/history.json?cube_symbol={symbol}&count={COUNT}&page=1"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
        "Referer": "https://xueqiu.com/",
        "Cookie": cookie_header(),
    }
    for attempt in range(1, 3):  # 最多2次；持续限流时快速熔断，避免 cron 900s 空转
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read().decode("utf-8"))
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            time.sleep(SLEEP)
            return data
        except urllib.error.HTTPError as e:  # noqa: BLE001
            body = e.read().decode("utf-8", errors="replace")[:300]
            if e.code == 400 and "110017" in body:
                if attempt == 1:
                    log(f"{symbol} 触发限流 110017，60s 后再试一次")
                    time.sleep(60)
                    continue
                raise RateLimited(f"雪球组合接口仍限流 110017（{symbol}）")
            raise RuntimeError(f"HTTP {e.code} {body}")
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(str(e))
    raise RuntimeError("unreachable")


def parse_day(ms) -> str | None:
    if not ms:
        return None
    try:
        return datetime.fromtimestamp(int(ms) / 1000).strftime("%Y-%m-%d")
    except Exception:  # noqa: BLE001
        return None


def score_cube(cube: dict, by_sector: dict, s2s: dict) -> dict:
    hist = cube.get("rebalancing_histories") or cube.get("list") or []
    hits = []
    rebal_events = 0
    for h in hist:
        day = parse_day(h.get("created_at") or h.get("updated_at"))
        if not day:
            continue
        rebal_events += 1
        rb = h.get("rebalancing_histories") or h.get("holdings") or []
        inc_by_sector = {}
        for s in rb:
            code = norm_code(s.get("stock_symbol") or "")
            if not code:
                continue
            prev = s.get("prev_weight") or 0.0
            tgt = s.get("target_weight") or 0.0
            try:
                inc = float(tgt) - float(prev)
            except Exception:  # noqa: BLE001
                continue
            if inc <= 0:
                continue
            for sec in s2s.get(code, set()):
                inc_by_sector[sec] = inc_by_sector.get(sec, 0.0) + inc
        for sec, inc in inc_by_sector.items():
            if inc < MIN_WEIGHT_INCR:
                continue
            for e in by_sector.get(sec, []):
                launch = e.get("launch_date")
                if not launch:
                    continue
                lead = (datetime.fromisoformat(launch) - datetime.fromisoformat(day)).days
                if 3 <= lead <= 21:
                    hits.append({
                        "sector": sec, "launch_date": launch, "rebal_date": day,
                        "lead_days": lead, "tier": "strong" if lead >= 7 else "mid",
                        "weight_increase": round(inc, 3),
                        "max_gain_20d": e.get("max_gain_20d"),
                    })
                    break
    # 同一 cube+sector+launch 只保留最早
    uniq = {}
    for h in hits:
        key = (h["sector"], h["launch_date"])
        if key not in uniq or h["rebal_date"] < uniq[key]["rebal_date"]:
            uniq[key] = h
    hits = sorted(uniq.values(), key=lambda h: (h["launch_date"], h["sector"]))
    strong = sum(1 for h in hits if h["tier"] == "strong")
    mid = sum(1 for h in hits if h["tier"] == "mid")
    eye = strong * 3 + mid
    persist = len({h["sector"] for h in hits})
    density = len(hits) / rebal_events if rebal_events else 0.0
    return {
        "rebal_events": rebal_events,
        "hits": hits,
        "hit_events": len(hits),
        "strong": strong,
        "mid": mid,
        "persist": persist,
        "density": round(density, 6),
        "eye_score": eye,
        "composite": round(eye * 0.5 + persist * 0.3 + density * 0.2, 6),
    }


def main() -> None:
    CUBE_DIR.mkdir(parents=True, exist_ok=True)
    by_sector = load_events()
    s2s = load_mapping()
    cands = json.loads(CAND.read_text(encoding="utf-8"))["with_uid"]
    cubes = [c for c in cands if c.get("source", "").startswith("C") and c.get("cube_symbol")]
    log(f"C渠道组合 {len(cubes)} 个")
    rows = []
    for i, c in enumerate(cubes, 1):
        sym = c["cube_symbol"]
        try:
            cube = fetch_cube(sym)
            sc = score_cube(cube, by_sector, s2s)
            rows.append({
                "uid": str(c["uid"]), "screen_name": c.get("screen_name", ""),
                "cube_symbol": sym, "cube_annualized": c.get("cube_annualized"),
                "followers_count": c.get("followers_count"), **sc,
            })
        except RateLimited as e:
            # 持续限流：整轮快速退出（exit 0），由外层决定是否稍后重跑，避免 97 个组合逐个空转。
            print(f"RATE_LIMITED {e}")
            return
        except Exception as e:  # noqa: BLE001
            rows.append({"uid": str(c["uid"]), "screen_name": c.get("screen_name", ""),
                         "cube_symbol": sym, "error": str(e)[:200]})
        if i % 20 == 0:
            log(f"进度 {i}/{len(cubes)}")
    rows.sort(key=lambda r: r.get("composite", 0), reverse=True)
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    OUT.write_text(json.dumps({
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "rule": f"rebalance sector weight increase >= {MIN_WEIGHT_INCR}pp within launch-21..-3; strong>=7d mid=3-6d",
        "experts_evaluated": len(rows),
        "top": rows,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"完成 → {OUT}")
    for r in rows[:20]:
        if "error" in r:
            print(f"#{r['rank']:>2} {r['screen_name']:<12} {r['cube_symbol']} ERROR {r['error']}")
            continue
        print(f"#{r['rank']:>2} {r['screen_name']:<12} {r['cube_symbol']} 综合{r['composite']:.3f} 眼力{r['eye_score']} 强{r['strong']}/中{r['mid']} 板块{r['persist']} 年化{r.get('cube_annualized')}")


if __name__ == "__main__":
    main()
