"""资讯流：IndexPlate.GetIndexList 列表（按日过滤）+ ForumsMsgJX.GetInfo 全文 + 落盘。

已知限制：列表只拉单页（观察到的 st=2 组合一页覆盖多日，日常够用）；
若某日资讯超过一页可能漏，后续对照 App 再补分页。
"""

from __future__ import annotations

import json
import re
import time
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path

from investment_engine.kpl.client import KplClient

LIST_PARAMS = {"view": "1,2,3,4,6", "st": "2", "Type": "0"}


class _TextExtractor(HTMLParser):
    """极简 HTML→纯文本：丢标签留文本，段落标签换行，img 收集 src。"""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.images: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "img":
            src = dict(attrs).get("src")
            if src:
                self.images.append(src)
        if tag in ("p", "br", "div", "li", "tr"):
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)

    def text(self) -> str:
        raw = "".join(self.parts)
        raw = re.sub(r"[ \t\r\f\v]+", " ", raw)
        return re.sub(r"\n\s*\n+", "\n\n", raw).strip()


def html_to_text(html: str) -> tuple[str, list[str]]:
    """返回 (纯文本, 正文 img src 列表)。"""
    parser = _TextExtractor()
    parser.feed(html or "")
    return parser.text(), parser.images


def fetch_list(client: KplClient, day: date) -> list[dict]:
    """拉列表并按 CreateTime（本地时区 unix）过滤出 day 当日条目。"""
    resp = client.post("apparticle", "IndexPlate", "GetIndexList", LIST_PARAMS)
    items = (resp.get("MsgTop") or {}).get("List") or []
    out = []
    for it in items:
        ts = it.get("CreateTime")
        if not ts:
            continue
        if datetime.fromtimestamp(int(ts)).date() == day:
            out.append(it)
    return out


def fetch_full(client: KplClient, msg_id) -> dict:
    resp = client.post("apparticle", "ForumsMsgJX", "GetInfo",
                       {"MsgID": str(msg_id), "Tag": "1"})
    return resp.get("Msg") or {}


def fetch_day_news(client: KplClient, day: date, pause: float = 0.5) -> list[dict]:
    """列表过滤当日 → 逐篇拉全文（篇间 pause 秒，降低风控暴露）。"""
    articles = []
    for item in fetch_list(client, day):
        articles.append(fetch_full(client, item["ID"]))
        time.sleep(pause)
    return articles


def save_news(articles: list[dict], out_root: Path, day: str) -> Path:
    """写 <out_root>/news/<day>/：index.json（meta 列表）+ 每篇 <ID>.md（frontmatter+正文）。"""
    out_dir = Path(out_root) / "news" / day
    out_dir.mkdir(parents=True, exist_ok=True)
    index = []
    for art in articles:
        text, content_images = html_to_text(art.get("Content") or "")
        img_list = [u for u in (art.get("imgList") or []) if u] or content_images
        meta = {
            "id": art.get("ID"),
            "title": art.get("Title") or "",
            "create_time": art.get("CreateTime"),
            "msg_type": art.get("MsgType"),
            "stocks": art.get("Stock") or [],
            "img_list": img_list,
        }
        frontmatter = "---\n" + "\n".join(
            f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in meta.items()
        ) + "\n---\n\n"
        (out_dir / f"{meta['id']}.md").write_text(
            frontmatter + f"# {meta['title']}\n\n" + text + "\n", encoding="utf-8")
        index.append(meta)
    (out_dir / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return out_dir
