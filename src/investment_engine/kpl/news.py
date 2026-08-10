"""资讯流：IndexPlate.GetIndexList 列表（按日过滤）+ ForumsMsgJX.GetInfo 全文 + 落盘。

已知限制：列表只拉单页（观察到的 st=2 组合一页覆盖多日，日常够用）；
若某日资讯超过一页可能漏，后续对照 App 再补分页。
付费专栏条目（6 位 ID、带 AID/SpecType，多为券商研报转载）全文返回
errcode=1130 无权限，逐篇跳过并记入 index.json（fetched=false）。
"""

from __future__ import annotations

import json
import re
import time
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path

from investment_engine.kpl.client import KplAuthError, KplClient, KplError

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


def fetch_day_news(client: KplClient, day: date, pause: float = 0.5
                   ) -> tuple[list[dict], list[dict]]:
    """列表过滤当日 → 逐篇拉全文（篇间 pause 秒，降低风控暴露）。

    返回 (articles, skipped)。单篇业务错误（如 errcode=1130 付费专栏无权限）
    记入 skipped 继续；鉴权失败（KplAuthError）为致命错误照常抛出。
    skipped 元素：{"item": 列表条目, "error": 错误信息}。
    """
    articles: list[dict] = []
    skipped: list[dict] = []
    for item in fetch_list(client, day):
        try:
            articles.append(fetch_full(client, item["ID"]))
        except KplAuthError:
            raise
        except KplError as e:
            skipped.append({"item": item, "error": str(e)})
        time.sleep(pause)
    return articles, skipped


def save_news(articles: list[dict], out_root: Path, day: str,
              skipped: list[dict] | None = None) -> Path:
    """写 <out_root>/news/<day>/：index.json（meta 列表）+ 每篇 <ID>.md（frontmatter+正文）。

    skipped（fetch_day_news 的返回值）中的条目只进 index.json（fetched=false +
    error），不生成 md——付费/异常内容拿不到全文，但标题摘要仍是证据。
    """
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
            "fetched": True,
        }
        frontmatter = "---\n" + "\n".join(
            f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in meta.items()
        ) + "\n---\n\n"
        (out_dir / f"{meta['id']}.md").write_text(
            frontmatter + f"# {meta['title']}\n\n" + text + "\n", encoding="utf-8")
        index.append(meta)
    for entry in skipped or []:
        item, error = entry["item"], entry["error"]
        img_list = [u for u in ((item.get("imgList") or {}).get("List") or []) if u]
        index.append({
            "id": item.get("ID"),
            "title": item.get("Title") or "",
            "create_time": item.get("CreateTime"),
            "msg_type": item.get("MsgType"),
            "stocks": item.get("Stock") or [],
            "img_list": img_list,
            "fetched": False,
            "error": error,
        })
    (out_dir / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return out_dir
