#!/usr/bin/env python3
"""gator 公众号历史文章回补（we-mp-rss cover 增量通道取不到历史，只能走 mp 原文直抓）。

背景：
  we-mp-rss 的 `weread_mp` 采集模式走 `/api/mp/cover`，**只返回最新一篇**
  （见容器内 core/wx/model/weread_mp.py 的 get_Articles 注释：无法回补历史文章列表）。
  所以 cookie 修好后只能拿到"最新一篇"，10-16~10-21 的历史文章仍缺失。

  但正文抓取走的是 web 模式（core/article_content.fetch_article_content(url, 'web')），
  能直接打开 mp.weixin.qq.com 原文页。因此只要拿到每篇的**原文链接**，
  就能用同一套 web 抓取路径补齐正文。

原文链接来源：鳄鱼派自营同步归档站 gator.ronchy2000.top（其文章页带
  "微信公众号原文 ↗" 链接，形如 mp.weixin.qq.com/s?__biz=...&mid=...&idx=1&sn=...）。

用法：
  # 列出档案站上可回补的文章（不落盘）
  python3 scripts/fetch_wechat_mp_backfill.py --list

  # 回补指定日期区间
  python3 scripts/fetch_wechat_mp_backfill.py --since 2026-10-16 --until 2026-10-22

  # 落盘到 sources/original/wechat/
  python3 scripts/fetch_wechat_mp_backfill.py --since 2026-10-16 --until 2026-10-22 --write

说明：
  * 落盘格式与 fetch_wechat_article.py 保持一致（front-matter + 正文）
  * up_id 统一 gator-ecyu-0001（公众号与 B站同一人，2026-10-15 合并）
  * 正文抓取复用容器内 web 模式（需容器运行中）
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(os.environ.get("HERMES_REPO_ROOT", "/home/ubuntu/learning-investment-strategies"))
OUT_DIR = REPO_ROOT / "sources" / "original" / "wechat"
ARCHIVE_BASE = "https://gator.ronchy2000.top"
# column -> (栏目 slug, 该栏目公众号名)
# 两个栏目是**同一人**的两个公众号（见 sources/third_party/gator-method/README.md），
# up_id 统一 gator-ecyu-0001（2026-10-15 合并），但 up_name 与 mp biz 不同。
ARCHIVE_COLUMNS = {
    "review": ("archive/like-a-gator/", "像鳄鱼一样思考"),   # 每日复盘
    "info": ("archive/huode-xinxicha/", "获得信息差"),      # 每日信息
}
UP_ID = "gator-ecyu-0001"
CONTAINER = "we-mp-rss"


def fetch_html(url: str) -> str:
    """抓网页 HTML（宿主 urllib；容器内无 curl）。"""
    import urllib.request
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
    for enc in ("utf-8", "gbk", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def list_archive(column: str = "review") -> list[dict]:
    """从档案站栏目页列出文章（日期 + 标题 + 详情页链接）。"""
    slug = ARCHIVE_COLUMNS[column][0]
    html_text = fetch_html(f"{ARCHIVE_BASE}/{slug}")
    out: list[dict] = []
    # 详情页链接形如 /articles/2026-10-22-wx-dc354e7c-2247492124-1/
    # 标题在锚点内的 <h3>（Astro 静态站，属性带 data-astro-cid）
    for m in re.finditer(
        r'<a href="(/articles/(\d{4}-\d{2}-\d{2})-[^"]+/)"[^>]*>\s*<h3[^>]*>(.*?)</h3>',
        html_text,
        re.S,
    ):
        title = re.sub(r"<[^>]+>", "", m.group(3)).strip()
        if not title:
            continue
        out.append({"date": m.group(2), "href": ARCHIVE_BASE + m.group(1), "title": title})
    # 去重（按 date+title）
    seen, uniq = set(), []
    for a in out:
        k = (a["date"], a["title"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(a)
    return uniq


def extract_mp_url(detail_html: str) -> str:
    """从档案站详情页提取 mp.weixin.qq.com 原文链接。"""
    m = re.search(r'href="(https://mp\.weixin\.qq\.com/s\?__biz=[^"]+)"', detail_html)
    if m:
        return m.group(1).replace("&amp;", "&")
    m = re.search(r'href="(https://mp\.weixin\.qq\.com/s/[A-Za-z0-9_\-]+)"', detail_html)
    return m.group(1) if m else ""


def strip_html(raw: str) -> str:
    if not raw:
        return ""
    t = raw
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", t, flags=re.S | re.I)
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
    t = re.sub(r"</p\s*>|</div\s*>|</section\s*>|</h\d>", "\n\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t)
    # mp 原文 HTML 常带大量缩进/空 span，剥离标签后留下成片空白行 → 压缩
    t = re.sub(r"[ \t\u00a0]+\n", "\n", t)
    t = re.sub(r"\n[ \t\u00a0]*\n[ \t\u00a0]*\n+", "\n\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def fetch_body_via_container(mp_url: str, retries: int = 3) -> str:
    """用容器内 web 模式抓正文（与 we-mp-rss 内容补抓同一条路径）。

    注意：web 模式用 multiprocessing(spawn) 启浏览器，脚本必须带
    __main__ 守卫，否则 spawn 重新导入 __main__ 时会再次执行顶层代码，
    报 "attempt has been made to start a new process before bootstrapping"。

    浏览器抓取存在较高瞬时失败率（实测同一 URL 重试即成功）→ 必须重试。
    """
    script = f'''
import sys, os, json
sys.path.insert(0, "/app")
os.chdir("/app")

def _run():
    from core.article_content import fetch_article_content
    url = {mp_url!r}
    try:
        content, mode, at = fetch_article_content(url, "web")
        print("__BODY__" + (content or ""))
    except Exception as e:
        print("__ERR__" + repr(e))

if __name__ == "__main__":
    _run()
'''
    p = Path("/tmp/_backfill_fetch.py")
    p.write_text(script, encoding="utf-8")
    subprocess.run(["docker", "cp", str(p), f"{CONTAINER}:{p}"], capture_output=True)

    last_err = ""
    for attempt in range(1, retries + 1):
        r = subprocess.run(
            ["docker", "exec", CONTAINER, "bash", "-lc",
             "source /app/environment.sh && source /app/env_x86_64/bin/activate && "
             "cd /app && python3 /tmp/_backfill_fetch.py 2>/dev/null"],
            capture_output=True, text=True, timeout=240,
        )
        out = r.stdout
        if "__ERR__" in out:
            last_err = out.split("__ERR__", 1)[1][:300]
        elif "__BODY__" in out:
            body = out.split("__BODY__", 1)[1]
            if body.strip():
                return body
            last_err = "empty_body"
        else:
            last_err = "no_marker:" + out[-200:]
        if attempt < retries:
            time.sleep(5 * attempt)
    raise RuntimeError(last_err or "unknown")


def safe_filename(title: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "-", title).strip("-.")[:80]


def write_article(date: str, title: str, url: str, body: str, up_name: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fname = f"{date}-{safe_filename(title)}.md"
    path = OUT_DIR / fname
    fm = (
        "---\n"
        'source: "wechat_mp"\n'
        f'up_id: "{UP_ID}"\n'
        f'up_name: "{up_name}"\n'
        f'pub_time: "{date}"\n'
        f'fetch_time: "{datetime.now().isoformat()}"\n'
        f'url: "{url}"\n'
        f"fetch_mode: mp_direct_backfill\n"
        "unprocessed: true\n"
        "---\n\n"
        f"> 来源：公众号 [{up_name}]({url})（经 mp 原文直抓回补）\n\n"
    )
    path.write_text(fm + body + "\n", encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-10-16")
    ap.add_argument("--until", default="2026-10-22")
    ap.add_argument("--column", default="review", choices=["review", "info"])
    ap.add_argument("--list", action="store_true", help="只列出，不抓取")
    ap.add_argument("--write", action="store_true", help="落盘到 sources/original/wechat/")
    args = ap.parse_args()

    items = list_archive(args.column)
    if args.list:
        for it in items:
            if args.since <= it["date"] <= args.until:
                print(it["date"], "|", it["title"], "|", it["href"])
        return 0

    up_name = ARCHIVE_COLUMNS[args.column][1]
    written = []
    for it in items:
        if not (args.since <= it["date"] <= args.until):
            continue
        detail = fetch_html(it["href"])
        mp_url = extract_mp_url(detail)
        if not mp_url:
            print(f"SKIP {it['date']} {it['title']}: 未找到 mp 原文链接", file=sys.stderr)
            continue
        try:
            body = fetch_body_via_container(mp_url)
        except Exception as exc:
            print(f"FAIL {it['date']} {it['title']}: {exc}", file=sys.stderr)
            continue
        if not body.strip():
            print(f"EMPTY {it['date']} {it['title']}", file=sys.stderr)
            continue
        if args.write:
            p = write_article(it["date"], it["title"], mp_url, strip_html(body), up_name)
            written.append(p)
            print(f"NEW_ARTICLE: {p}")
        else:
            print(f"OK {it['date']} {it['title']} body_len={len(body)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
