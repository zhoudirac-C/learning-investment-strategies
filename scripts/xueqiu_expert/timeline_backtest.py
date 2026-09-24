#!/usr/bin/env python3
"""雪球大牛回测 P3：候选人时间线批量回测

设计：docs/design/xueqiu-expert-backtest-design.md §4.3
驱动：playwright connect_over_cdp(localhost:9222) 复用 headless Chrome 登录态
（urllib 直连被 aliyun WAF 动态 challenge 拦截，静态 cookie 无效——2026-09-23 实测）

用法：
  python scripts/xueqiu_expert/timeline_backtest.py --limit 3   # 试跑 3 人
  python scripts/xueqiu_expert/timeline_backtest.py             # 全量（断点续跑）
  python scripts/xueqiu_expert/timeline_backtest.py --source B  # 只跑某渠道
产出：
  data/xueqiu/posts/{uid}.json   # 每人原创帖：created_at/title/description/target
  data/xueqiu/posts/_progress.json  # 断点与状态
限速：10s/页 + 每 20 页休 120s；WAF 检测（非 JSON）→ 休 300s 重试 1 次 → 记 error
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CANDIDATES = REPO / "data" / "xueqiu" / "candidates.json"
POSTS_DIR = REPO / "data" / "xueqiu" / "posts"
PROGRESS = POSTS_DIR / "_progress.json"
CDP_URL = "http://localhost:9222"
CUTOFF = "2024-09-01"          # 回测截止：翻到此日期前的帖子为止
PAGE_SLEEP = 15                # 2026-09-23 实测：5s/页把IP打进WAF封禁窗口，降到15s
MAX_PAGES = 30                 # 页数封顶：高频用户(数千帖)记 partial，诚实标注覆盖不足
BATCH_SIZE = 10
BATCH_SLEEP = 300
WAF_SLEEP = 300
COUNT = 20                     # 实测 count 上限=20（30+ 返回空）


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def fetch_page(page, uid: str, page_no: int):  # -> dict | str("waf") | None
    """导航一页 v4/user_timeline API（全部发言：原创长文+讨论区短帖）。

    2026-09-23 实测：/statuses/original/timeline.json 只含原创长文——渠道A
    讨论区作者大面积为空（"不可方物的铁拳"0帖）；v4 端点覆盖全部发言。"""
    url = (f"https://xueqiu.com/v4/statuses/user_timeline.json"
           f"?user_id={uid}&page={page_no}&count={COUNT}")
    try:
        page.goto(url, timeout=30000)
        time.sleep(1.2)
        txt = page.evaluate("document.body.innerText")
    except Exception as e:  # noqa: BLE001
        log(f"  uid={uid} p{page_no}: 导航异常 {type(e).__name__}，30s 后重试一次")
        time.sleep(30)
        try:
            page.goto(url, timeout=30000)
            time.sleep(1.2)
            txt = page.evaluate("document.body.innerText")
        except Exception:  # noqa: BLE001
            return None
    txt = (txt or "").strip()
    if not txt.startswith("{"):
        return "waf"
    try:
        return json.loads(txt)
    except Exception:  # noqa: BLE001
        return "waf"


def backtest_user(page, uid: str, name: str) -> dict:
    """翻完一个用户的 2 年原创帖。返回 {status, posts, pages, oldest}。"""
    all_posts: list[dict] = []
    page_no = 1
    oldest = None
    waf_retried = False
    while True:
        d = fetch_page(page, uid, page_no)
        if d == "waf":
            if waf_retried:
                return {"status": "waf_blocked", "posts": all_posts,
                        "pages": page_no - 1, "oldest": oldest}
            waf_retried = True
            log(f"  uid={uid} p{page_no}: 触发WAF，休 {WAF_SLEEP}s 后重试一次")
            time.sleep(WAF_SLEEP)
            continue
        if d is None:
            return {"status": "nav_error", "posts": all_posts,
                    "pages": page_no - 1, "oldest": oldest}
        items = d.get("statuses") or d.get("list") or []
        if not items:
            break
        for p in items:
            ts = p.get("created_at")
            if not ts:
                continue
            date = datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d")
            all_posts.append({
                "date": date, "created_at": ts,
                "title": p.get("title") or "",
                "description": (p.get("description") or "")[:500],
                "target": p.get("target") or f"/{uid}/{p.get('id')}",
                "retweet": bool(p.get("retweeted_status")),
            })
            oldest = date
        # 到截止期 → 收工
        if oldest and oldest <= CUTOFF:
            break
        max_page = d.get("maxPage") or ((d.get("total") or 0) + COUNT - 1) // COUNT
        if page_no >= max_page:
            break
        if page_no >= MAX_PAGES:
            # 高频用户页数封顶：partial 状态，诚实标注覆盖不足
            return {"status": f"partial(>{MAX_PAGES}页,仅覆盖至{oldest})",
                    "posts": all_posts, "pages": page_no, "oldest": oldest}
        page_no += 1
        time.sleep(PAGE_SLEEP)
    return {"status": "ok", "posts": all_posts, "pages": page_no, "oldest": oldest}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--source", type=str, default="")
    args = ap.parse_args()

    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    cands = json.loads(CANDIDATES.read_text())["with_uid"]
    if args.source:
        # 支持多渠道："B,C" = 渠道B+C（2026-09-24 拍板：砍掉渠道A，只做B 44+C 97=141人）
        wanted = {s.strip() for s in args.source.split(",")}
        cands = [c for c in cands if c.get("source", "")[:1] in wanted]
    progress = json.loads(PROGRESS.read_text()) if PROGRESS.exists() else {}
    todo = [c for c in cands if str(c["uid"]) not in progress]
    if args.limit:
        todo = todo[:args.limit]
    log(f"候选人 {len(cands)}，已完成 {len(progress)}，本批 {len(todo)}")

    from playwright.sync_api import sync_playwright
    import urllib.request
    cookies = json.loads((Path.home() / "xq_cookies.json").read_text())
    pw_cookies = [{"name": c["name"], "value": c["value"],
                   "domain": c.get("domain", ".xueqiu.com"),
                   "path": c.get("path", "/")}
                  for c in cookies if "xueqiu" in (c.get("domain") or "")]
    with sync_playwright() as pw:
        # 自起实例 + 注入登录 cookie（Chrome152 对 CDP ws origin 校验 ECONNRESET，
        # 无法 connect 9222；WAF JS challenge 会被真实浏览器自动执行通过）
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir="/home/ubuntu/.config/chromium",
            headless=True,
            executable_path="/usr/bin/google-chrome-stable",
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/152.0.0.0 Safari/537.36"),
            args=["--disable-blink-features=AutomationControlled",
                  "--window-size=1560,1000"])
        ctx.add_cookies(pw_cookies)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        n_ok = n_err = 0
        consec_waf = 0
        for i, c in enumerate(todo, 1):
            uid = str(c["uid"])
            name = c.get("screen_name", "")
            t0 = time.time()
            res = backtest_user(page, uid, name)
            (POSTS_DIR / f"{uid}.json").write_text(json.dumps(
                {"uid": uid, "screen_name": name, "source": c.get("source"),
                 "status": res["status"], "pages": res["pages"],
                 "oldest": res["oldest"], "posts": res["posts"]},
                ensure_ascii=False))
            progress[uid] = {"status": res["status"], "posts": len(res["posts"]),
                             "oldest": res["oldest"], "ts": int(time.time())}
            PROGRESS.write_text(json.dumps(progress, ensure_ascii=False, indent=1))
            tag = "✓" if res["status"] == "ok" else "✗"
            log(f"{tag} [{i}/{len(todo)}] {name}: {len(res['posts'])} 帖 "
                f"({res['pages']}页, 最早{res['oldest']}, {time.time()-t0:.0f}s)")
            if res["status"] == "ok":
                n_ok += 1
                consec_waf = 0
            elif res["status"] == "waf_blocked":
                n_err += 1
                consec_waf += 1
                # IP级封禁保护：连续2人WAF即熔断中止（继续跑=全员空转）
                if consec_waf >= 2:
                    log(f"🚨 连续 {consec_waf} 人 WAF 封禁，判定 IP 封禁窗口未过，熔断中止。"
                        f"进度已保存，冷却 30-60 分钟后重启续跑。")
                    break
            else:
                n_err += 1
                consec_waf = 0
            if i % BATCH_SIZE == 0 and i < len(todo):
                log(f"  —— 已 {i} 人，批间休息 {BATCH_SLEEP}s ——")
                time.sleep(BATCH_SLEEP)
            else:
                time.sleep(PAGE_SLEEP)
    log(f"完成: {n_ok} 成功 / {n_err} 失败，进度文件 {PROGRESS}")


if __name__ == "__main__":
    main()
