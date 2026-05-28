#!/usr/bin/env python3
"""
Fetch UP主 B站动态，保存到 sources/original/bilibili/。
支持：PaddleOCR 图片文字识别、置顶评论提取、index.md 生成。

用法:
    uv run python scripts/fetch_bilibili_up_v2.py --uid <UP_UID>
    uv run python scripts/fetch_bilibili_up_v2.py --uid <UP_UID> --check-only
    uv run python scripts/fetch_bilibili_up_v2.py --uid <UP_UID> --state-file ~/.hermes/bilibili_up_state.json

环境变量:
    BILIBILI_SESSDATA: B站登录Cookie（必须，用于看"仅粉丝可见"动态）
    HERMES_REPO_ROOT: 项目根目录

输出:
    - 无新动态: 静默（空输出）
    - 有新动态: stdout 打印 "NEW_DYNAMIC: <文件路径>"
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ── 配置 ──────────────────────────────────────────────────────────

DEFAULT_UP_UID = "1420210197"
DEFAULT_CONFIG_DIR = Path.home() / ".hermes"
STATE_FILE_NAME = "bilibili_up_state.json"
ORIGINAL_DIR = "sources/original/bilibili"
INDEX_FILE = "index.md"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

COOKIE_TEMPLATE = (
    "buvid3=7862F2E3-72CC-6C07-C823-12A4B73DF10533008infoc; "
    "b_nut=1779981633; "
    "bsource=search_baidu; "
    "_uuid=89631AD2-81E8-229B-10859-21F10E53CDD3234604infoc; "
    "bmg_af_switch=1; "
    "bmg_src_def_domain=i1.hdslb.com; "
    "bmg_af_sc=%7B%22none%22%3A%7B%22on%22%3A1%2C%22def%22%3A%22i1.hdslb.com%22%7D%2C%22sgp%22%3A%7B%22on%22%3A1%2C%22def%22%3A%22i1-sgp.hdslb.com%22%7D%7D; "
    "buvid_fp=ac2e4bc70bddb6f684ff4ae9750f8b5f; "
    "bili_ticket=eyJhbGciOiJIUzI1NiIsImtpZCI6InMwMyIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3ODAyNDE1NzQsImlhdCI6MTc3OTk4MjMxNCwicGx0IjotMX0.3rlSPgynyqjrbgkp24cJhiuBQlFRCS5XfIclD4Sd-k0; "
    "bili_ticket_expires=1780241514; "
    "buvid4=A6FAE8B5-D524-2FBF-A56E-00CC6CB960CD35540-126052823-qdiavzWE57mWDv4hXUk+GpCvhjquQQbux6eudP0KvwwYmZBhju4kCSxiCa/IMvig; "
    "bili_jct={bili_jct}; "
    "DedeUserID=39923426; "
    "DedeUserID__ckMd5=f11f6846570fc63e; "
    "sid=mx6ttueb; "
    "b_lsid=09218290_19E6F379638; "
    "SESSDATA={sessdata}; "
    "CURRENT_FNVAL=16; "
    "CURRENT_QUALITY=0; "
    "theme-tip-show=SHOWED"
)


# ── 路径工具 ──────────────────────────────────────────────────────

def repo_root() -> Path:
    configured = os.environ.get("HERMES_REPO_ROOT")
    if configured:
        return Path(configured)
    cwd = Path.cwd()
    if (cwd / "scripts" / "stock_monitor.py").exists():
        return cwd
    return Path(__file__).resolve().parents[1]


def original_dir() -> Path:
    return repo_root() / ORIGINAL_DIR


def index_path() -> Path:
    return original_dir() / INDEX_FILE


# ── 状态管理 ──────────────────────────────────────────────────────

def load_state(state_path: Path) -> dict:
    if not state_path.exists():
        return {}
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(state_path: Path, state: dict) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


# ── B站 API ───────────────────────────────────────────────────────

def build_cookie(sessdata: str, bili_jct: str = "a5d0a6acbcf87e09490777462e19a4ee") -> str:
    return COOKIE_TEMPLATE.format(sessdata=sessdata, bili_jct=bili_jct)


def fetch_dynamic_list(uid: str, sessdata: str, offset: str = "") -> dict:
    url = f"https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space?host_mid={uid}&timezone_offset=-480"
    if offset:
        url += f"&offset={offset}"

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Referer": f"https://space.bilibili.com/{uid}/dynamic",
            "Cookie": build_cookie(sessdata),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )

    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_dynamic_detail(dynamic_id: str, sessdata: str) -> dict:
    url = f"https://api.bilibili.com/x/polymer/web-dynamic/v1/detail?id={dynamic_id}"

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Referer": "https://t.bilibili.com/",
            "Cookie": build_cookie(sessdata),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )

    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_top_comment(dynamic_id: str, sessdata: str) -> dict | None:
    """获取动态置顶评论（UP主置顶）。
    
    使用 /x/v2/reply API，因为 /x/v2/reply/main 不返回 upper.top 字段。
    """
    # 需要先获取动态的 comment_id (rid_str)
    detail = fetch_dynamic_detail(dynamic_id, sessdata)
    if detail.get("code") != 0:
        return None
    
    basic = detail.get("data", {}).get("item", {}).get("basic", {})
    oid = basic.get("rid_str", "") or basic.get("comment_id_str", "")
    if not oid:
        return None
    
    url = f"https://api.bilibili.com/x/v2/reply?oid={oid}&type=11&pn=1&ps=20&sort=2"

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Referer": f"https://t.bilibili.com/{dynamic_id}",
            "Cookie": build_cookie(sessdata),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("code") != 0:
                return None

            # 优先取 UP 主置顶评论
            upper_top = data.get("data", {}).get("upper", {}).get("top")
            if upper_top:
                return {
                    "content": upper_top.get("content", {}).get("message", ""),
                    "uname": upper_top.get("member", {}).get("uname", ""),
                    "like": upper_top.get("like", 0),
                    "rpid": upper_top.get("rpid", ""),
                    "is_up_top": True,
                }

            # 没有置顶，返回第一条热评
            replies = data.get("data", {}).get("replies", [])
            if replies:
                top = replies[0]
                return {
                    "content": top.get("content", {}).get("message", ""),
                    "uname": top.get("member", {}).get("uname", ""),
                    "like": top.get("like", 0),
                    "rpid": top.get("rpid", ""),
                    "is_hot": True,
                }
            return None
    except Exception as exc:
        print(f"WARN: 获取评论失败 {dynamic_id}: {exc}", file=sys.stderr)
        return None


# ── OCR ───────────────────────────────────────────────────────────

def ocr_image(image_path: Path) -> str:
    """使用 RapidOCR 识别图片文字。"""
    try:
        from rapidocr_onnxruntime import RapidOCR
        from PIL import Image
    except ImportError:
        return ""

    try:
        ocr = RapidOCR()
        img = Image.open(image_path)
        width, height = img.size

        # 长图分块 OCR，每块最大 2000px 高度
        chunk_height = 2000
        all_texts = []

        for y in range(0, height, chunk_height):
            bottom = min(y + chunk_height, height)
            chunk = img.crop((0, y, width, bottom))
            result, _ = ocr(chunk)
            if result:
                for line in result:
                    text = line[1] if isinstance(line[1], str) else line[1][0] if len(line) > 1 else ""
                    if text.strip():
                        all_texts.append(text)

        return "\n".join(all_texts)
    except Exception as exc:
        print(f"WARN: OCR 失败 {image_path}: {exc}", file=sys.stderr)
        return ""


def ocr_image_from_url(image_url: str, temp_dir: Path) -> str:
    """下载图片并 OCR。"""
    try:
        from PIL import Image
        import urllib.request

        # 下载图片
        ext = ".png" if ".png" in image_url else ".jpg"
        temp_path = temp_dir / f"ocr_temp_{hash(image_url) % 1000000}{ext}"

        req = urllib.request.Request(
            image_url,
            headers={
                "User-Agent": USER_AGENT,
                "Referer": "https://t.bilibili.com/",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            temp_path.write_bytes(resp.read())

        text = ocr_image(temp_path)
        temp_path.unlink(missing_ok=True)
        return text
    except Exception as exc:
        print(f"WARN: 下载/OCR 图片失败 {image_url}: {exc}", file=sys.stderr)
        return ""


# ── Playwright 工具 ───────────────────────────────────────────────

def screenshot_dynamic(dynamic_id: str, sessdata: str, output_path: Path) -> bool:
    """使用Playwright对动态页面截图。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False

    chromium_path = os.environ.get("BILIBILI_UP_CHROMIUM_PATH", "/snap/bin/chromium")
    url = f"https://www.bilibili.com/opus/{dynamic_id}"

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=chromium_path,
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            context = browser.new_context(
                viewport={"width": 1280, "height": 2000},
                user_agent=USER_AGENT,
            )
            context.add_cookies([{
                "name": "SESSDATA",
                "value": sessdata,
                "domain": ".bilibili.com",
                "path": "/",
            }])
            page = context.new_page()
            page.goto(url, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(5000)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(output_path), full_page=True)
            browser.close()
            return True
    except Exception as exc:
        print(f"WARN: 截图失败 {dynamic_id}: {exc}", file=sys.stderr)
        return False


def extract_pics_from_screenshot(dynamic_id: str, sessdata: str) -> list[str]:
    """使用Playwright访问页面并提取图片URL。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return []

    chromium_path = os.environ.get("BILIBILI_UP_CHROMIUM_PATH", "/snap/bin/chromium")
    url = f"https://www.bilibili.com/opus/{dynamic_id}"
    pics = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=chromium_path,
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            context = browser.new_context(
                viewport={"width": 1280, "height": 2000},
                user_agent=USER_AGENT,
            )
            context.add_cookies([{
                "name": "SESSDATA",
                "value": sessdata,
                "domain": ".bilibili.com",
                "path": "/",
            }])
            page = context.new_page()
            page.goto(url, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(5000)

            selectors = [
                ".opus-module-content img",
                ".dynamic-content img",
                ".img-content img",
                ".bili-dyn-item__body img",
                ".dyn-card img",
                "[class*=opus] img",
                "[class*=dynamic] img",
            ]

            for selector in selectors:
                try:
                    elements = page.query_selector_all(selector)
                    for el in elements:
                        src = el.get_attribute("src") or ""
                        if src and src.startswith("http") and src not in pics:
                            src_clean = src.split("@")[0]
                            pics.append(src_clean)
                except Exception:
                    continue

            try:
                all_imgs = page.query_selector_all("img")
                for img in all_imgs:
                    src = img.get_attribute("src") or ""
                    if "new_dyn" in src:
                        src_clean = src.split("@")[0]
                        if src_clean.startswith("//"):
                            src_clean = "https:" + src_clean
                        if src_clean not in pics:
                            pics.append(src_clean)
            except Exception:
                pass

            browser.close()
    except Exception as exc:
        print(f"WARN: 提取图片失败 {dynamic_id}: {exc}", file=sys.stderr)

    return pics


# ── 内容解析 ──────────────────────────────────────────────────────

def extract_text_from_dynamic(item: dict) -> str:
    modules = item.get("modules", {})
    dynamic_module = modules.get("module_dynamic", {})
    if not dynamic_module:
        return ""

    major = dynamic_module.get("major", {}) or {}
    opus = major.get("opus") if major else None
    if opus and isinstance(opus, dict):
        summary = opus.get("summary", {}) or {}
        text = summary.get("text", "")
        if text:
            return text

    desc = dynamic_module.get("desc") or {}
    if isinstance(desc, dict):
        text = desc.get("text", "")
        if text:
            return text

    archive = major.get("archive") if major else None
    if archive and isinstance(archive, dict):
        parts = []
        title = archive.get("title", "")
        if title:
            parts.append(title)
        desc_text = archive.get("desc", "")
        if desc_text:
            parts.append(desc_text)
        return "\n".join(parts)

    additional = dynamic_module.get("additional")
    if additional and isinstance(additional, dict):
        item_add = additional.get("item", {}) or {}
        if isinstance(item_add, dict):
            return item_add.get("content", "")
        return str(additional)

    return ""


def extract_pics_from_dynamic(item: dict) -> list[str]:
    modules = item.get("modules", {})
    dynamic_module = modules.get("module_dynamic", {})
    if not dynamic_module:
        return []

    major = dynamic_module.get("major", {}) or {}
    if not major:
        return []

    opus = major.get("opus")
    if opus and isinstance(opus, dict):
        pics = opus.get("pics", [])
        return [p.get("url", "") for p in pics if p.get("url")]

    draw = major.get("draw")
    if draw and isinstance(draw, dict):
        items = draw.get("items", [])
        return [p.get("src", "") for p in items if p.get("src")]

    archive = major.get("archive")
    if archive and isinstance(archive, dict):
        cover = archive.get("cover", "")
        if cover:
            return [cover]

    return []


def extract_video_info(item: dict) -> dict:
    modules = item.get("modules", {})
    dynamic_module = modules.get("module_dynamic", {})
    archive = dynamic_module.get("major", {}).get("archive")
    if archive and isinstance(archive, dict):
        return {
            "title": archive.get("title", ""),
            "bvid": archive.get("bvid", ""),
            "cover": archive.get("cover", ""),
            "desc": archive.get("desc", ""),
            "duration": archive.get("duration_text", ""),
            "stat": archive.get("stat", {}),
        }
    return {}


def classify_dynamic_type(item: dict) -> str:
    type_map = {
        "DYNAMIC_TYPE_WORD": "文字",
        "DYNAMIC_TYPE_DRAW": "图片",
        "DYNAMIC_TYPE_AV": "视频",
        "DYNAMIC_TYPE_FORWARD": "转发",
        "DYNAMIC_TYPE_ARTICLE": "专栏",
        "DYNAMIC_TYPE_MUSIC": "音乐",
        "DYNAMIC_TYPE_COMMON_SQUARE": "通用",
        "DYNAMIC_TYPE_COMMON_VERTICAL": "通用",
        "DYNAMIC_TYPE_LIVE": "直播",
        "DYNAMIC_TYPE_LIVE_RCMD": "直播推荐",
        "DYNAMIC_TYPE_PGC": "PGC",
        "DYNAMIC_TYPE_COURSES": "课程",
        "DYNAMIC_TYPE_NONE": "无",
    }
    return type_map.get(item.get("type", ""), "其他")


def extract_author_info(item: dict) -> dict:
    author = item.get("modules", {}).get("module_author", {})
    return {
        "name": author.get("name", "未知UP"),
        "mid": author.get("mid", ""),
        "pub_time": author.get("pub_time", ""),
        "pub_ts": author.get("pub_ts", ""),
        "pub_location": author.get("pub_location", ""),
    }


def extract_stat(item: dict) -> dict:
    stat = item.get("modules", {}).get("module_stat", {})
    return {
        "like": stat.get("like", {}).get("count", 0) if isinstance(stat.get("like"), dict) else stat.get("like", 0),
        "comment": stat.get("comment", {}).get("count", 0) if isinstance(stat.get("comment"), dict) else stat.get("comment", 0),
        "forward": stat.get("forward", {}).get("count", 0) if isinstance(stat.get("forward"), dict) else stat.get("forward", 0),
    }


# ── 文件保存 ──────────────────────────────────────────────────────

def sanitize_filename(text: str, max_len: int = 40) -> str:
    text = text.strip().replace("\n", " ")
    text = re.sub(r'[<>:"/\\|?*]', "", text)
    text = re.sub(r'\[.*?\]', "", text)
    text = re.sub(r'\s+', " ", text).strip()
    return text[:max_len].strip()


def parse_pub_time(pub_time_str: str, pub_ts: str = "") -> datetime:
    if pub_ts:
        try:
            return datetime.fromtimestamp(int(pub_ts), tz=timezone.utc).astimezone()
        except (ValueError, OSError):
            pass

    if not pub_time_str:
        return datetime.now(timezone.utc).astimezone()

    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(pub_time_str, fmt)
            return dt.replace(tzinfo=timezone.utc).astimezone()
        except ValueError:
            continue

    try:
        dt = datetime.strptime(pub_time_str, "%m月%d日")
        now = datetime.now(timezone.utc).astimezone()
        dt = dt.replace(year=now.year)
        return dt.replace(tzinfo=timezone.utc).astimezone()
    except ValueError:
        pass

    now = datetime.now(timezone.utc).astimezone()
    minute_match = re.match(r'(\d+)\s*分钟前', pub_time_str)
    if minute_match:
        minutes = int(minute_match.group(1))
        return now - __import__('datetime').timedelta(minutes=minutes)

    hour_match = re.match(r'(\d+)\s*小时前', pub_time_str)
    if hour_match:
        hours = int(hour_match.group(1))
        return now - __import__('datetime').timedelta(hours=hours)

    if pub_time_str == "昨天":
        return now - __import__('datetime').timedelta(days=1)

    day_match = re.match(r'(\d+)\s*天前', pub_time_str)
    if day_match:
        days = int(day_match.group(1))
        return now - __import__('datetime').timedelta(days=days)

    return now


def _merge_detail(item: dict, detail_data: dict) -> dict:
    import copy
    merged = copy.deepcopy(item)
    detail_item = detail_data.get("data", {}).get("item", {})
    if not detail_item:
        return merged

    detail_modules = detail_item.get("modules", {})
    if detail_modules:
        merged_modules = merged.get("modules", {})
        detail_dynamic = detail_modules.get("module_dynamic", {})
        if detail_dynamic:
            merged_dynamic = merged_modules.get("module_dynamic", {})
            detail_desc = detail_dynamic.get("desc")
            if detail_desc is not None:
                merged_dynamic["desc"] = detail_desc
            detail_major = detail_dynamic.get("major")
            if detail_major is not None:
                merged_dynamic["major"] = detail_major
            merged_modules["module_dynamic"] = merged_dynamic

        for key in ["module_stat", "module_author"]:
            if key in detail_modules and detail_modules[key]:
                merged_modules[key] = detail_modules[key]
        merged["modules"] = merged_modules

    return merged


def save_dynamic_to_file(
    item: dict,
    uid: str,
    dynamic_id: str,
    detail_data: dict | None = None,
    top_comment: dict | None = None,
    ocr_text: str = "",
    *,
    is_only_fans: bool = False,
    screenshot_path: Path | None = None,
    playwright_pics: list[str] | None = None,
) -> Path:
    if detail_data:
        item = _merge_detail(item, detail_data)

    author = extract_author_info(item)
    text = extract_text_from_dynamic(item)
    pics = extract_pics_from_dynamic(item)
    stat = extract_stat(item)
    dyn_type = classify_dynamic_type(item)

    pub_time_str = author.get("pub_time", "")
    pub_ts = author.get("pub_ts", "")
    pub_dt = parse_pub_time(pub_time_str, pub_ts)

    date_str = pub_dt.strftime("%Y-%m-%d")
    time_str = pub_dt.strftime("%H%M")

    title_part = sanitize_filename(text, max_len=30) or f"动态-{dynamic_id}"
    filename = f"{date_str}-{time_str}-{dyn_type}-{title_part}.md"
    filepath = original_dir() / filename

    counter = 1
    original_filepath = filepath
    while filepath.exists():
        stem = original_filepath.stem
        filepath = original_filepath.with_name(f"{stem}_{counter}.md")
        counter += 1

    lines = [
        "---",
        f'source: "bilibili_dynamic"',
        f'up_uid: "{uid}"',
        f'up_name: "{author["name"]}"',
        f'dynamic_id: "{dynamic_id}"',
        f'dynamic_type: "{dyn_type}"',
        f'pub_time: "{pub_time_str}"',
        f'fetch_time: "{datetime.now().isoformat()}"',
        f'url: "https://www.bilibili.com/opus/{dynamic_id}"',
        f'pics_count: {len(pics)}',
        f'like: {stat["like"]}',
        f'comment: {stat["comment"]}',
        f'forward: {stat["forward"]}',
    ]

    if is_only_fans:
        lines.append("is_only_fans: true")

    lines.append("unprocessed: true")
    lines.extend([
        "---",
        "",
        f"> 来源：B站动态 [{author['name']}](https://space.bilibili.com/{uid})",
        f"> 发布时间：{pub_time_str}",
        f"> 动态链接：https://www.bilibili.com/opus/{dynamic_id}",
        "",
        "## 原文",
        "",
    ])

    video_info = extract_video_info(item)
    if text:
        lines.append(text)
    elif video_info:
        lines.append(f"**视频：{video_info.get('title', '')}**")
        lines.append(f"- BV号：{video_info.get('bvid', '')}")
        lines.append(f"- 时长：{video_info.get('duration', '')}")
        if video_info.get('desc'):
            lines.append(f"- 简介：{video_info['desc']}")
    else:
        lines.append("（无文字内容）")

    lines.append("")

    # OCR 结果
    if ocr_text:
        lines.append("## 图片 OCR 识别")
        lines.append("")
        lines.append("```")
        lines.append(ocr_text)
        lines.append("```")
        lines.append("")

    # 置顶评论
    if top_comment:
        lines.append("## 置顶评论")
        lines.append("")
        lines.append(f"> 👤 **{top_comment.get('uname', '')}**")
        lines.append(f"> 👍 {top_comment.get('like', 0)}")
        lines.append(">")
        lines.append("> " + top_comment.get('content', '').replace('\n', '\n> '))
        lines.append("")

    # 图片处理
    if dyn_type != "视频":
        if is_only_fans:
            if playwright_pics:
                lines.append("## 图片（Playwright提取）")
                lines.append("")
                for i, pic_url in enumerate(playwright_pics, 1):
                    lines.append(f"![图片{i}]({pic_url})")
                lines.append("")
            elif screenshot_path:
                rel_path = screenshot_path.relative_to(repo_root())
                lines.append("## 图片")
                lines.append("")
                lines.append(f"> 充电专属动态，API未返回图片。已保存页面截图：")
                lines.append(f"> ![页面截图]({rel_path})")
                lines.append("")
            else:
                lines.append("## 图片")
                lines.append("")
                lines.append("> 充电专属动态，图片需访问原页面查看。")
                lines.append(f"> 链接：https://www.bilibili.com/opus/{dynamic_id}")
                lines.append("")
        else:
            if pics:
                lines.append("## 图片")
                lines.append("")
                for i, pic_url in enumerate(pics, 1):
                    lines.append(f"![图片{i}]({pic_url})")
                lines.append("")

    if dyn_type == "视频" and video_info.get('cover'):
        lines.append("## 视频封面")
        lines.append("")
        lines.append(f"![视频封面]({video_info['cover']})")
        lines.append("")

    lines.extend([
        "## 互动数据",
        "",
        f"- 点赞：{stat['like']}",
        f"- 评论：{stat['comment']}",
        f"- 转发：{stat['forward']}",
        "",
    ])

    lines.extend([
        "<!--",
        "## 原始API数据",
        "",
        "```json",
        json.dumps(item, ensure_ascii=False, indent=2),
        "```",
        "-->",
    ])

    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text("\n".join(lines), encoding="utf-8")

    return filepath


# ── Index 生成 ────────────────────────────────────────────────────

def build_index() -> None:
    """生成 index.md，列出所有已拉取的动态。"""
    src_dir = original_dir()
    if not src_dir.exists():
        return

    # 收集所有 markdown 文件（排除 index.md）
    md_files = []
    for f in sorted(src_dir.iterdir()):
        if f.suffix == ".md" and f.name != INDEX_FILE:
            # 解析文件名: YYYY-MM-DD-HHMM-类型-标题.md
            parts = f.stem.split("-", 4)
            if len(parts) >= 4:
                date_str = f"{parts[0]}-{parts[1]}-{parts[2]}"
                time_str = parts[3]
                dyn_type = parts[4].split("-")[0] if len(parts) > 4 else "未知"
                title = "-".join(parts[4].split("-")[1:]) if len(parts) > 4 else ""
            else:
                date_str = ""
                time_str = ""
                dyn_type = "未知"
                title = f.stem

            # 读取 frontmatter 获取 dynamic_id
            dynamic_id = ""
            try:
                content = f.read_text(encoding="utf-8")
                for line in content.split("\n"):
                    if line.startswith("dynamic_id:"):
                        dynamic_id = line.split(":", 1)[1].strip().strip('"')
                        break
            except Exception:
                pass

            md_files.append({
                "path": f,
                "date": date_str,
                "time": time_str,
                "type": dyn_type,
                "title": title,
                "dynamic_id": dynamic_id,
            })

    # 按日期时间倒序
    md_files.sort(key=lambda x: (x["date"], x["time"]), reverse=True)

    lines = [
        "# B站动态索引",
        "",
        f"> 自动生成于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"> 共 {len(md_files)} 条动态",
        "",
        "| 日期 | 时间 | 类型 | 标题 | 动态ID |",
        "|------|------|------|------|--------|",
    ]

    for item in md_files:
        title_display = item["title"][:40] if item["title"] else "(无标题)"
        url = f"https://www.bilibili.com/opus/{item['dynamic_id']}" if item["dynamic_id"] else ""
        lines.append(
            f"| {item['date']} | {item['time']} | {item['type']} | [{title_display}]({item['path'].name}) | "
            f"[{item['dynamic_id'][:12]}...]({url}) |" if item["dynamic_id"] else f"| {item['date']} | {item['time']} | {item['type']} | [{title_display}]({item['path'].name}) | - |"
        )

    lines.extend([
        "",
        "## 说明",
        "",
        "- 本文件由脚本自动生成，请勿手动修改",
        "- `unprocessed: true` 标记的动态尚未进入 qing-learning 处理流程",
        "- 点击标题可查看原始 Markdown 文件",
        "",
    ])

    index_path().write_text("\n".join(lines), encoding="utf-8")


# ── 主流程 ────────────────────────────────────────────────────────

def run(
    uid: str,
    sessdata: str,
    state: dict,
    state_path: Path,
    *,
    check_only: bool = False,
    max_fetch: int = 5,
    screenshot: bool = False,
    extract_pics: bool = False,
    enable_ocr: bool = True,
    enable_comment: bool = True,
) -> list[Path]:
    """拉取动态，返回新保存的文件路径列表。"""
    saved_files: list[Path] = []
    processed_ids: set = set(state.get("processed_ids", []))

    # 拉取动态列表
    try:
        resp = fetch_dynamic_list(uid, sessdata)
    except Exception as exc:
        print(f"ERROR: 拉取动态列表失败: {exc}", file=sys.stderr)
        sys.exit(1)

    if resp.get("code") != 0:
        msg = resp.get("message", "未知错误")
        print(f"ERROR: B站API返回错误: {msg}", file=sys.stderr)
        sys.exit(1)

    items = resp.get("data", {}).get("items", [])
    if not items:
        return saved_files

    # 找到未处理的动态（按时间倒序，从最新开始）
    new_items = []
    for item in items:
        dynamic_id = str(item.get("id_str", ""))
        if not dynamic_id:
            continue
        # 如果已经处理过这条，跳过
        if dynamic_id in processed_ids:
            continue
        new_items.append((dynamic_id, item))

    if not new_items:
        return saved_files

    if check_only:
        print(f"CHECK: 发现 {len(new_items)} 条新动态")
        return saved_files

    temp_dir = original_dir() / ".temp"
    temp_dir.mkdir(exist_ok=True)

    # 保存新动态（按时间正序，最早的先保存）
    for dynamic_id, item in reversed(new_items[:max_fetch]):
        try:
            basic = item.get("basic", {})
            is_only_fans = basic.get("is_only_fans", False)

            detail_data = None
            screenshot_path = None
            playwright_pics = None
            top_comment = None
            ocr_text = ""

            # 获取详情
            if is_only_fans:
                try:
                    detail_data = fetch_dynamic_detail(dynamic_id, sessdata)
                except Exception as exc:
                    print(f"WARN: 获取动态详情失败 {dynamic_id}: {exc}", file=sys.stderr)

                api_pics = extract_pics_from_dynamic(item)
                detail_pics = extract_pics_from_dynamic(detail_data.get("data", {}).get("item", {}) if detail_data else {})

                if not api_pics and not detail_pics:
                    if extract_pics:
                        playwright_pics = extract_pics_from_screenshot(dynamic_id, sessdata)
                    if not playwright_pics and screenshot:
                        screenshot_path = original_dir() / "screenshots" / f"{dynamic_id}.png"
                        screenshot_dynamic(dynamic_id, sessdata, screenshot_path)

            # 获取置顶评论
            if enable_comment:
                try:
                    top_comment = fetch_top_comment(dynamic_id, sessdata)
                except Exception as exc:
                    print(f"WARN: 获取评论失败 {dynamic_id}: {exc}", file=sys.stderr)

            # OCR 识别图片文字
            if enable_ocr:
                dyn_type = classify_dynamic_type(item)
                if dyn_type in ("图片", "文字"):
                    pics = extract_pics_from_dynamic(item)
                    if not pics and detail_data:
                        pics = extract_pics_from_dynamic(detail_data.get("data", {}).get("item", {}))

                    ocr_results = []
                    for pic_url in pics[:5]:  # 最多 OCR 5 张图
                        text = ocr_image_from_url(pic_url, temp_dir)
                        if text.strip():
                            ocr_results.append(text)

                    if ocr_results:
                        ocr_text = "\n\n".join(ocr_results)

                    # 对充电专属动态，如果有截图也 OCR
                    if not ocr_text and screenshot_path and screenshot_path.exists():
                        ocr_text = ocr_image(screenshot_path)

            filepath = save_dynamic_to_file(
                item, uid, dynamic_id,
                detail_data=detail_data,
                top_comment=top_comment,
                ocr_text=ocr_text,
                is_only_fans=is_only_fans,
                screenshot_path=screenshot_path,
                playwright_pics=playwright_pics,
            )
            saved_files.append(filepath)
            processed_ids.add(dynamic_id)
            state["last_dynamic_id"] = dynamic_id
        except Exception as exc:
            print(f"ERROR: 保存动态 {dynamic_id} 失败: {exc}", file=sys.stderr)

    # 清理临时目录
    if temp_dir.exists():
        for f in temp_dir.iterdir():
            f.unlink(missing_ok=True)
        temp_dir.rmdir()

    # 更新状态
    state["last_check_time"] = datetime.now().isoformat()
    state["processed_ids"] = sorted(list(processed_ids))[-1000:]  # 保留最近1000条
    save_state(state_path, state)

    # 生成索引
    if saved_files:
        build_index()

    return saved_files


def main() -> int:
    parser = argparse.ArgumentParser(description="拉取B站UP主动态（增强版）")
    parser.add_argument("--uid", default=DEFAULT_UP_UID, help="UP主UID")
    parser.add_argument("--sessdata", default=os.environ.get("BILIBILI_SESSDATA", ""), help="B站SESSDATA Cookie")
    parser.add_argument("--state-file", type=Path, help="状态文件路径")
    parser.add_argument("--check-only", action="store_true", help="只检查是否有新动态，不保存")
    parser.add_argument("--max-fetch", type=int, default=5, help="最多拉取几条新动态")
    parser.add_argument("--screenshot", action="store_true", help="对充电专属动态进行截图")
    parser.add_argument("--extract-pics", action="store_true", help="用Playwright提取充电专属动态的图片URL")
    parser.add_argument("--no-ocr", action="store_true", help="禁用 OCR")
    parser.add_argument("--no-comment", action="store_true", help="禁用评论获取")
    args = parser.parse_args()

    if not args.sessdata:
        print("ERROR: 需要提供 BILIBILI_SESSDATA 环境变量或 --sessdata 参数", file=sys.stderr)
        return 1

    if args.state_file:
        state_path = args.state_file
    else:
        state_path = DEFAULT_CONFIG_DIR / STATE_FILE_NAME

    state = load_state(state_path)

    saved = run(
        uid=args.uid,
        sessdata=args.sessdata,
        state=state,
        state_path=state_path,
        check_only=args.check_only,
        max_fetch=args.max_fetch,
        screenshot=args.screenshot,
        extract_pics=args.extract_pics,
        enable_ocr=not args.no_ocr,
        enable_comment=not args.no_comment,
    )

    for filepath in saved:
        print(f"NEW_DYNAMIC: {filepath.relative_to(repo_root())}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
