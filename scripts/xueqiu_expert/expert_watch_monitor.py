#!/usr/bin/env python3
"""雪球大牛 TOP20 新帖监控（每日增量 → 飞书）。

口径（2026-09-28 用户拍板）：TOP20 全部推送；无新增则静默（no_agent stdout 空）。
数据来源：www.xueqiu.com/v4/statuses/user_timeline.json（复用 P3 登录态/绕 WAF 口径）。
状态：data/xueqiu/expert_watch_state.json 记录每 uid 已推送最大 created_at；首次运行用
data/xueqiu/posts/{uid}.json 作为基线，避免把历史帖当增量刷屏。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "data" / "xueqiu"
RANKING = DATA / "expert_ranking.json"
POSTS_DIR = DATA / "posts"
STATE = DATA / "expert_watch_state.json"
TOP_N = 20
MAX_LINES_PER_USER = 5
MAX_TOTAL_LINES = 80

sys.path.insert(0, str(Path(__file__).resolve().parent))
from timeline_backtest import fetch_page  # noqa: E402


def log_err(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def load_top() -> list[dict]:
    data = json.loads(RANKING.read_text(encoding="utf-8"))
    return data.get("top20", [])[:TOP_N]


def load_state() -> dict[str, int]:
    if STATE.exists():
        try:
            return {str(k): int(v) for k, v in json.loads(STATE.read_text(encoding="utf-8")).items()}
        except Exception:  # noqa: BLE001
            return {}
    return {}


def baseline_created_at(uid: str) -> int:
    """已有 P3 posts 作为首次运行基线；没有则 0（由首轮抓取建立基线）。"""
    p = POSTS_DIR / f"{uid}.json"
    if not p.exists():
        return 0
    try:
        posts = json.loads(p.read_text(encoding="utf-8")).get("posts", [])
    except Exception:  # noqa: BLE001
        return 0
    return max((int(x.get("created_at") or 0) for x in posts), default=0)


def fmt_post(uid: str, name: str, p: dict) -> str:
    ts = int(p.get("created_at") or 0)
    dt = datetime.fromtimestamp(ts / 1000).strftime("%m-%d %H:%M") if ts else "unknown"
    text = ((p.get("title") or "") + " " + (p.get("description") or "")).strip()
    text = " ".join(text.split())[:150]
    target = p.get("target") or f"/{uid}/"
    url = "https://www.xueqiu.com" + target if str(target).startswith("/") else str(target)
    prefix = "[转] " if p.get("retweet") else ""
    return f"- [{dt}] {name}: {prefix}{text} <{url}>"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="不启动浏览器，只核对名单/状态/基线")
    args = ap.parse_args()

    top = load_top()
    state = load_state()
    if args.dry_run:
        print(f"TOP{len(top)} 监控名单 / state {len(state)}")
        for e in top:
            uid = str(e["uid"])
            base = state.get(uid) or baseline_created_at(uid)
            print(e["rank"], e["screen_name"], uid, "baseline", base)
        return

    # 首次基线：已有 P3 覆盖到哪，就从哪之后开始推；没有 P3 的 uid 由本轮抓取建立基线。
    for e in top:
        uid = str(e["uid"])
        if uid not in state:
            state[uid] = baseline_created_at(uid)

    cookies_path = Path.home() / "xq_cookies.json"
    if not cookies_path.exists():
        print("⚠️ 雪球监控缺少 /home/ubuntu/xq_cookies.json，无法抓 timeline")
        return
    cookies = json.loads(cookies_path.read_text(encoding="utf-8"))
    pw_cookies = [{"name": c["name"], "value": c["value"],
                   "domain": c.get("domain", ".xueqiu.com"), "path": c.get("path", "/")}
                  for c in cookies if "xueqiu" in (c.get("domain") or "")]

    from playwright.sync_api import sync_playwright
    lines: list[str] = []
    errors: list[str] = []
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir="/home/ubuntu/.config/chromium",
            headless=True,
            executable_path="/usr/bin/google-chrome-stable",
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/152.0.0.0 Safari/537.36"),
            args=["--disable-blink-features=AutomationControlled", "--window-size=1560,1000"])
        try:
            ctx.add_cookies(pw_cookies)  # type: ignore[arg-type]  # playwright 接受该 dict 列表，Pyright 误报
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            for e in top:
                uid = str(e["uid"])
                name = e.get("screen_name") or uid
                d = fetch_page(page, uid, 1)
                if d == "waf" or d is None:
                    errors.append(f"⚠️ {name}({uid}) 抓取失败/WAF")
                    continue
                items = d.get("statuses") or d.get("list") or []
                posts = []
                max_seen = state.get(uid, 0)
                for p in items:
                    ts = p.get("created_at")
                    if not ts:
                        continue
                    ts = int(ts)
                    max_seen = max(max_seen, ts)
                    posts.append({
                        "created_at": ts,
                        "title": p.get("title") or "",
                        "description": (p.get("description") or "")[:500],
                        "target": p.get("target") or f"/{uid}/{p.get('id')}",
                        "retweet": bool(p.get("retweeted_status")),
                    })
                new_posts = [p for p in posts if p["created_at"] > state.get(uid, 0)]
                state[uid] = max_seen
                new_posts.sort(key=lambda x: x["created_at"])
                for p in new_posts[:MAX_LINES_PER_USER]:
                    lines.append(fmt_post(uid, name, p))
                if len(new_posts) > MAX_LINES_PER_USER:
                    lines.append(f"- {name}: 另有 {len(new_posts) - MAX_LINES_PER_USER} 条新帖未展开")
        finally:
            ctx.close()

    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    if not lines and not errors:
        return
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    out = [f"雪球大牛 TOP{len(top)} 新帖监控（{now}）"]
    out.extend(errors)
    out.extend(lines[:MAX_TOTAL_LINES])
    if len(lines) > MAX_TOTAL_LINES:
        out.append(f"…其余 {len(lines) - MAX_TOTAL_LINES} 条省略")
    print("\n".join(out), flush=True)


if __name__ == "__main__":
    main()
