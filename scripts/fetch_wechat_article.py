#!/usr/bin/env python3
"""
从 we-mp-rss（Docker, ~/we-mp-rss/data/db.db）拉取公众号文章，落盘
sources/original/wechat/<date>-<title>.md，仿 fetch_bilibili_up_v2 模式。

用法:
    sudo python3 scripts/fetch_wechat_article.py            # 增量拉取
    sudo python3 scripts/fetch_wechat_article.py --check-only
    sudo python3 scripts/fetch_wechat_article.py --backfill 3  # 回看最近N篇

输出:
    - 无新文章: 静默
    - 有新文章: stdout 每行 "NEW_ARTICLE: <文件路径>"

说明:
    - we-mp-rss DB 为 root 属主，脚本需 sudo 运行（cron 同理）
    - 状态文件 ~/.hermes/wechat_mp_state.json 记录已导出 article id
    - 正文优先取 content（纯文本/HTML→markdown 近似），空则留 TODO 由
      content 补抓任务（容器内 fetch_articles_without_content）稍后补
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(os.environ.get("HERMES_REPO_ROOT", "/home/ubuntu/learning-investment-strategies"))

DB_PATH = Path("/home/ubuntu/we-mp-rss/data/db.db")
STATE_FILE = Path("/home/ubuntu/.hermes/wechat_mp_state.json")
REPO_ROOT = Path(os.environ.get("HERMES_REPO_ROOT", "/home/ubuntu/learning-investment-strategies"))
OUT_DIR = REPO_ROOT / "sources/original/wechat"

# 统一 up_id：公众号 + B站 是同一人「像鳄鱼一样思考」（2026-10-15 合并）
# 公众号采集通道 id 保留在 config/schools.yaml 的 platforms 里
UP_ID = "gator-ecyu-0001"
UP_NAME = "像鳄鱼一样思考"


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"exported_ids": []}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    # 状态文件保持用户可读写（脚本常以 sudo 跑）
    try:
        import pwd
        ubuntu = pwd.getpwnam("ubuntu")
        os.chown(STATE_FILE, ubuntu.pw_uid, ubuntu.pw_gid)
    except Exception:
        pass


def probe_weread_cookie() -> tuple[bool, str]:
    """探测微信读书 Cookie 是否仍有效（直连 weread cover 接口）。

    返回 (ok, detail)。cookie 失效时 weread 会以 HTTP 200 返回业务错误
    errcode=-2010/-2012（"用户不存在"/"登录超时"），必须看 errcode，
    否则会把登录态失效误判成"没有新文章"而静默跳过。
    """
    cookie = ""
    for src in (Path("/home/ubuntu/we-mp-rss/.env"),):
        if not src.exists():
            continue
        for line in src.read_text(encoding="utf-8").splitlines():
            if line.startswith("WEREAD_COOKIE="):
                cookie = line.split("=", 1)[1].strip()
                break
    if not cookie:
        return False, "no_cookie_found"
    try:
        import requests
        h = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
            "Cookie": cookie,
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://weread.qq.com",
            "Referer": "https://weread.qq.com/",
        }
        r = requests.get(
            "https://weread.qq.com/api/mp/cover",
            params={"bookId": "MP_WXS_3922514597"},
            headers=h,
            timeout=20,
        )
        d = r.json()
        errcode = d.get("errcode", d.get("errCode"))
        if r.status_code != 200:
            return False, f"http_{r.status_code}"
        if errcode in (-2010, -2012, -2041):
            return False, f"errcode_{errcode}:{d.get('errmsg') or d.get('errlog') or ''}"
        if d.get("reviewId"):
            return True, d.get("title", "")
        return False, "no_reviewId"
    except Exception as exc:  # 网络/解析异常都算探测失败
        return False, f"probe_error:{type(exc).__name__}"


def html_to_text(raw: str) -> str:
    """轻量 HTML→文本（无外部依赖，够 claim 提取用）。"""
    if not raw:
        return ""
    t = raw
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", t, flags=re.S | re.I)
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
    t = re.sub(r"</p\s*>|</div\s*>|</section\s*>|</h\d>", "\n\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def safe_filename(title: str) -> str:
    t = re.sub(r'[\\/:*?"<>|\s]+', "-", title).strip("-.")
    return t[:80]


def ts_to_dt(ts) -> str:
    try:
        return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d")
    except Exception:
        return datetime.now().strftime("%Y-%m-%d")


def export_article(row: dict, out_dir: Path) -> Path:
    title = row["title"] or "untitled"
    date = ts_to_dt(row["publish_time"])
    fname = f"{date}-{safe_filename(title)}.md"
    path = out_dir / fname
    body = html_to_text(row["content"] or "")
    if not body:
        body = f"> [TODO] 正文未抓到（content 空），检查容器内文章补抓任务后重跑本脚本"
    fm = (
        "---\n"
        f'source: "wechat_mp"\n'
        f'up_id: "{UP_ID}"\n'
        f'up_name: "{UP_NAME}"\n'
        f'article_id: "{row["id"]}"\n'
        f'pub_time: "{datetime.fromtimestamp(int(row["publish_time"])).strftime("%Y-%m-%d %H:%M") if row["publish_time"] else "unknown"}"\n'
        f'fetch_time: "{datetime.now().isoformat()}"\n'
        f'url: "{row["url"] or ""}"\n'
        f"unprocessed: true\n"
        "---\n\n"
        f"> 来源：公众号 [{UP_NAME}]({row['url'] or ''})\n\n"
    )
    path.write_text(fm + body + "\n", encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-only", action="store_true")
    ap.add_argument("--backfill", type=int, default=0, help="额外回看最近N篇（含已导出）")
    args = ap.parse_args()

    if not DB_PATH.exists():
        print(f"ERROR: we-mp-rss DB 不存在: {DB_PATH}", file=sys.stderr)
        return 1

    # Cookie 存活探测：失效时**必须告警**，不能静默。
    # 历史事故：2026-10-16~10-22 cookie 失效（errcode -2010），
    # 采集器返回"暂无需要获取内容的文章"，抓取钩子"先写标记再调用"
    # 也不重试 → 连续 7 天零入库、零告警，直到人工发现。
    ok, detail = probe_weread_cookie()
    if not ok:
        print(
            f"WEREAD_COOKIE_INVALID: {detail} — 微信读书登录态失效，"
            f"公众号采集已中断，需重新扫码授权"
            f"（容器内 wx.lic + WEREAD_COOKIE 环境变量都要更新）"
        )
        if args.check_only:
            return 2
        # 非 check-only 也继续尝试（可能只是网络抖动），但显式告警
        print("WARN: 继续尝试采集，但 cookie 可能已失效", file=sys.stderr)
    elif args.check_only:
        print(f"COOKIE_OK: latest={detail}")

    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id, title, url, content, publish_time FROM articles "
        "ORDER BY publish_time DESC LIMIT 200"
    ).fetchall()
    con.close()

    state = load_state()
    exported = set(state["exported_ids"])

    new_rows = [dict(r) for r in rows if r["id"] not in exported]
    if args.check_only:
        print(f"PENDING: {len(new_rows)}")
        return 0

    if not new_rows and args.backfill == 0:
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # sudo 场景下保证产物归 ubuntu
    try:
        import pwd
        u = pwd.getpwnam("ubuntu")
        os.chown(OUT_DIR, u.pw_uid, u.pw_gid)
    except Exception:
        pass

    # 回看模式：把最近 N 篇（无论是否导出过）重写落盘，但不打印 NEW（避免重复提 claim）
    for r in rows[: args.backfill] if args.backfill else []:
        export_article(r, OUT_DIR)

    written: list[Path] = []
    for r in new_rows:
        p = export_article(r, OUT_DIR)
        written.append(p)
        try:
            import pwd
            u = pwd.getpwnam("ubuntu")
            os.chown(p, u.pw_uid, u.pw_gid)
        except Exception:
            pass
        state["exported_ids"].append(r["id"])

    # 状态文件只保留最近 500 个 id，防膨胀
    state["exported_ids"] = state["exported_ids"][-500:]
    save_state(state)

    for p in written:
        print(f"NEW_ARTICLE: {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
