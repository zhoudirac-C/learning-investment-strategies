#!/usr/bin/env python3
"""
Fetch UP主 B站动态，保存到 sources/original/bilibili/。

用法:
    uv run python scripts/fetch_bilibili_up.py --uid <UP_UID>
    uv run python scripts/fetch_bilibili_up.py --uid <UP_UID> --check-only
    uv run python scripts/fetch_bilibili_up.py --uid <UP_UID> --state-file ~/.hermes/bilibili_up_state.json

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
import textwrap
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


# ── 配置 ──────────────────────────────────────────────────────────

DEFAULT_UP_UID = "3546639031295331"  # 默认UP主UID，可覆盖
DEFAULT_CONFIG_DIR = Path.home() / ".hermes"
STATE_FILE_NAME = "bilibili_up_state.json"
ORIGINAL_DIR = "sources/original/bilibili"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# 完整Cookie模板（B站API需要完整cookie才能通过412校验）
# 使用时将 {SESSDATA} 替换为实际的SESSDATA值
COOKIE_TEMPLATE = (
    "buvid3=EA64D8DF-1755-F5AA-CC68-2F435670F1DA33186infoc; "
    "b_nut=1768824333; "
    "_uuid=93CCF2410-410F7-89910-D8E4-3D43F1E8382733611infoc; "
    "buvid_fp=a7af4eeecb04cc7ab100f226d73326eb; "
    "home_feed_column=5; "
    "buvid4=563DB691-59B4-B6DB-4169-B25E4E4BF10A34272-026011920-iD1f/Vrkvy27OQ8ubPgzDA%3D%3D; "
    "theme-tip-show=SHOWED; "
    "rpdid=%7C(u%7CJk)mm%7CR)0J'u~Y))kRYlk; "
    "CURRENT_QUALITY=80; "
    "theme-avatar-tip-show=SHOWED; "
    "DedeUserID=39923426; "
    "DedeUserID__ckMd5=f11f6846570fc63e; "
    "hit-dyn-v2=1; "
    "theme-switch-show=SHOWED; "
    "PVID=1; "
    "browser_resolution=1512-706; "
    "bili_ticket=eyJhbGciOiJIUzI1NiIsImtpZCI6InMwMyIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3Nzk5NzE0MjMsImlhdCI6MTc3OTcxMjE2MywicGx0IjotMX0.mbx5YGFyBSQpGgdV9aVGmz0kBGRhDudKmiESLvdfKLY; "
    "bili_ticket_expires=1779971363; "
    "SESSDATA={sessdata}; "
    "bili_jct=a5d0a6acbcf87e09490777462e19a4ee; "
    "sid=5rbhaomc; "
    "bp_t_offset_39923426=1207131920391995392; "
    "CURRENT_FNVAL=2000; "
    "b_lsid=8C830058_19E6C94BD32"
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

def build_cookie(sessdata: str) -> str:
    """构建完整的B站Cookie，避免412错误。"""
    return COOKIE_TEMPLATE.format(sessdata=sessdata)


def fetch_dynamic_list(uid: str, sessdata: str, offset: str = "") -> dict:
    """拉取UP主动态列表（粉丝可见需要SESSDATA）。"""
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
    """拉取单条动态详情（含完整内容）。"""
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


# ── 内容解析 ──────────────────────────────────────────────────────

def extract_text_from_dynamic(item: dict) -> str:
    """从动态结构中提取纯文本内容。"""
    modules = item.get("modules", {})
    dynamic_module = modules.get("module_dynamic", {})

    # 尝试 opus（图文动态）
    opus = dynamic_module.get("major", {}).get("opus")
    if opus and isinstance(opus, dict):
        summary = opus.get("summary", {}) or {}
        text = summary.get("text", "")
        if text:
            return text

    # 尝试 desc（普通动态/转发）
    desc = dynamic_module.get("desc") or {}
    if isinstance(desc, dict):
        text = desc.get("text", "")
        if text:
            return text

    # 尝试 archive（视频动态，取标题和简介）
    archive = dynamic_module.get("major", {}).get("archive")
    if archive and isinstance(archive, dict):
        parts = []
        title = archive.get("title", "")
        if title:
            parts.append(title)
        desc_text = archive.get("desc", "")
        if desc_text:
            parts.append(desc_text)
        return "\n".join(parts)

    # 尝试 additional（转发/引用内容）
    additional = dynamic_module.get("additional")
    if additional and isinstance(additional, dict):
        item_add = additional.get("item", {}) or {}
        if isinstance(item_add, dict):
            return item_add.get("content", "")
        return str(additional)

    return ""


def extract_pics_from_dynamic(item: dict) -> list[str]:
    """提取动态中的图片URL。"""
    modules = item.get("modules", {})
    dynamic_module = modules.get("module_dynamic", {})

    # opus 图片
    opus = dynamic_module.get("major", {}).get("opus")
    if opus and isinstance(opus, dict):
        pics = opus.get("pics", [])
        return [p.get("url", "") for p in pics if p.get("url")]

    # draw 图片
    draw = dynamic_module.get("major", {}).get("draw")
    if draw and isinstance(draw, dict):
        items = draw.get("items", [])
        return [p.get("src", "") for p in items if p.get("src")]

    # archive 视频封面
    archive = dynamic_module.get("major", {}).get("archive")
    if archive and isinstance(archive, dict):
        cover = archive.get("cover", "")
        if cover:
            return [cover]

    return []


def extract_video_info(item: dict) -> dict:
    """提取视频动态的信息。"""
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
    """判断动态类型。"""
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
    """提取作者信息。"""
    author = item.get("modules", {}).get("module_author", {})
    return {
        "name": author.get("name", "未知UP"),
        "mid": author.get("mid", ""),
        "pub_time": author.get("pub_time", ""),
        "pub_location": author.get("pub_location", ""),
    }


def extract_stat(item: dict) -> dict:
    """提取互动数据。"""
    stat = item.get("modules", {}).get("module_stat", {})
    return {
        "like": stat.get("like", {}).get("count", 0) if isinstance(stat.get("like"), dict) else stat.get("like", 0),
        "comment": stat.get("comment", {}).get("count", 0) if isinstance(stat.get("comment"), dict) else stat.get("comment", 0),
        "forward": stat.get("forward", {}).get("count", 0) if isinstance(stat.get("forward"), dict) else stat.get("forward", 0),
    }


# ── 文件保存 ──────────────────────────────────────────────────────

def sanitize_filename(text: str, max_len: int = 40) -> str:
    """清理文件名中的非法字符。"""
    text = text.strip().replace("\n", " ")
    # 移除非法字符
    text = re.sub(r'[<>:"/\\|?*]', "", text)
    # 移除B站表情 [xxx]
    text = re.sub(r'\[.*?\]', "", text)
    # 移除多余空格
    text = re.sub(r'\s+', " ", text).strip()
    return text[:max_len].strip()


def parse_pub_time(pub_time_str: str, pub_ts: str = "") -> datetime:
    """解析B站动态发布时间。
    
    B站返回的时间格式：
    - 绝对时间: "2024-05-28 14:30:00" 或 "05月22日"
    - 相对时间: "57分钟前", "2小时前", "昨天", "3天前"
    
    优先使用 pub_ts（Unix时间戳），如果没有则解析 pub_time_str。
    """
    # 优先使用Unix时间戳（最准确）
    if pub_ts:
        try:
            return datetime.fromtimestamp(int(pub_ts), tz=timezone.utc).astimezone()
        except (ValueError, OSError):
            pass
    
    if not pub_time_str:
        return datetime.now(timezone.utc).astimezone()
    
    # 尝试标准格式
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(pub_time_str, fmt)
            # 无时区信息，假设为本地时间
            return dt.replace(tzinfo=timezone.utc).astimezone()
        except ValueError:
            continue
    
    # 处理 "05月22日" 格式（当年）
    try:
        dt = datetime.strptime(pub_time_str, "%m月%d日")
        now = datetime.now(timezone.utc).astimezone()
        dt = dt.replace(year=now.year)
        return dt.replace(tzinfo=timezone.utc).astimezone()
    except ValueError:
        pass
    
    # 处理相对时间
    now = datetime.now(timezone.utc).astimezone()
    
    # "57分钟前", "2小时前"
    minute_match = re.match(r'(\d+)\s*分钟前', pub_time_str)
    if minute_match:
        minutes = int(minute_match.group(1))
        return now - __import__('datetime').timedelta(minutes=minutes)
    
    hour_match = re.match(r'(\d+)\s*小时前', pub_time_str)
    if hour_match:
        hours = int(hour_match.group(1))
        return now - __import__('datetime').timedelta(hours=hours)
    
    # "昨天"
    if pub_time_str == "昨天":
        return now - __import__('datetime').timedelta(days=1)
    
    # "3天前"
    day_match = re.match(r'(\d+)\s*天前', pub_time_str)
    if day_match:
        days = int(day_match.group(1))
        return now - __import__('datetime').timedelta(days=days)
    
    # 无法解析，使用当前时间
    return now


def _merge_detail(item: dict, detail_data: dict) -> dict:
    """将详情API的数据合并到列表API的数据中。"""
    # 深拷贝避免修改原始数据
    import copy
    merged = copy.deepcopy(item)
    
    detail_item = detail_data.get("data", {}).get("item", {})
    if not detail_item:
        return merged
    
    # 合并modules
    detail_modules = detail_item.get("modules", {})
    if detail_modules:
        merged_modules = merged.get("modules", {})
        
        # 合并module_dynamic（详情API有更完整的desc和major）
        detail_dynamic = detail_modules.get("module_dynamic", {})
        if detail_dynamic:
            merged_dynamic = merged_modules.get("module_dynamic", {})
            
            # 合并desc（详情API有完整文字）
            detail_desc = detail_dynamic.get("desc")
            if detail_desc is not None:
                merged_dynamic["desc"] = detail_desc
            
            # 合并major（详情API有完整图片）
            detail_major = detail_dynamic.get("major")
            if detail_major is not None:
                merged_dynamic["major"] = detail_major
            
            merged_modules["module_dynamic"] = merged_dynamic
        
        # 合并其他模块（stat等）
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
) -> Path:
    """保存动态到 sources/original/bilibili/。"""
    # 如果有详情数据，合并到item中
    if detail_data:
        item = _merge_detail(item, detail_data)
    
    author = extract_author_info(item)
    text = extract_text_from_dynamic(item)
    pics = extract_pics_from_dynamic(item)
    stat = extract_stat(item)
    dyn_type = classify_dynamic_type(item)

    # 解析时间（优先使用pub_ts时间戳）
    pub_time_str = author.get("pub_time", "")
    pub_ts = author.get("pub_ts", "")
    pub_dt = parse_pub_time(pub_time_str, pub_ts)

    date_str = pub_dt.strftime("%Y-%m-%d")
    time_str = pub_dt.strftime("%H%M")

    # 文件名
    title_part = sanitize_filename(text, max_len=30) or f"动态-{dynamic_id}"
    filename = f"{date_str}-{time_str}-{dyn_type}-{title_part}.md"
    filepath = original_dir() / filename

    # 避免覆盖：如果文件已存在，加序号
    counter = 1
    original_filepath = filepath
    while filepath.exists():
        stem = original_filepath.stem
        filepath = original_filepath.with_name(f"{stem}_{counter}.md")
        counter += 1

    # 构建内容
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
        "unprocessed: true",
        "---",
        "",
        f"> 来源：B站动态 [{author['name']}](https://space.bilibili.com/{uid})",
        f"> 发布时间：{pub_time_str}",
        f"> 动态链接：https://www.bilibili.com/opus/{dynamic_id}",
        "",
        "## 原文",
        "",
    ]

    # 原文内容（保留原始格式）
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

    # 图片链接
    if pics:
        lines.append("## 图片")
        lines.append("")
        for i, pic_url in enumerate(pics, 1):
            lines.append(f"![图片{i}]({pic_url})")
        lines.append("")

    # 视频封面
    if video_info.get('cover'):
        lines.append("## 视频封面")
        lines.append("")
        lines.append(f"![视频封面]({video_info['cover']})")
        lines.append("")

    # 互动数据
    lines.extend([
        "## 互动数据",
        "",
        f"- 点赞：{stat['like']}",
        f"- 评论：{stat['comment']}",
        f"- 转发：{stat['forward']}",
        "",
    ])

    # 原始API数据（可选，用于调试）
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


# ── 主流程 ────────────────────────────────────────────────────────

def run(
    uid: str,
    sessdata: str,
    state: dict,
    state_path: Path,
    *,
    check_only: bool = False,
    max_fetch: int = 5,
) -> list[Path]:
    """拉取动态，返回新保存的文件路径列表。"""
    saved_files: list[Path] = []
    last_dynamic_id = state.get("last_dynamic_id", "")

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

    # 找到比 last_dynamic_id 更新的动态
    new_items = []
    for item in items:
        dynamic_id = str(item.get("id_str", ""))
        if not dynamic_id:
            continue
        # 如果已经处理过这条，停止（列表是按时间倒序）
        if dynamic_id == last_dynamic_id:
            break
        new_items.append((dynamic_id, item))

    if not new_items:
        return saved_files

    if check_only:
        print(f"CHECK: 发现 {len(new_items)} 条新动态")
        return saved_files

    # 保存新动态（按时间正序，最早的先保存）
    for dynamic_id, item in reversed(new_items[:max_fetch]):
        try:
            # 检查是否是仅粉丝可见动态，如果是则调用详情API
            detail_data = None
            basic = item.get("basic", {})
            if basic.get("is_only_fans"):
                try:
                    detail_data = fetch_dynamic_detail(dynamic_id, sessdata)
                except Exception as exc:
                    print(f"WARN: 获取动态详情失败 {dynamic_id}: {exc}", file=sys.stderr)
            
            filepath = save_dynamic_to_file(item, uid, dynamic_id, detail_data=detail_data)
            saved_files.append(filepath)
            # 更新状态（用最新的dynamic_id）
            state["last_dynamic_id"] = dynamic_id
        except Exception as exc:
            print(f"ERROR: 保存动态 {dynamic_id} 失败: {exc}", file=sys.stderr)

    # 更新时间戳
    state["last_check_time"] = datetime.now().isoformat()
    save_state(state_path, state)

    return saved_files


def main() -> int:
    parser = argparse.ArgumentParser(description="拉取B站UP主动态")
    parser.add_argument("--uid", default=DEFAULT_UP_UID, help="UP主UID")
    parser.add_argument("--sessdata", default=os.environ.get("BILIBILI_SESSDATA", ""), help="B站SESSDATA Cookie")
    parser.add_argument("--state-file", type=Path, help="状态文件路径")
    parser.add_argument("--check-only", action="store_true", help="只检查是否有新动态，不保存")
    parser.add_argument("--max-fetch", type=int, default=5, help="最多拉取几条新动态")
    args = parser.parse_args()

    if not args.sessdata:
        print("ERROR: 需要提供 BILIBILI_SESSDATA 环境变量或 --sessdata 参数", file=sys.stderr)
        return 1

    # 状态文件路径
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
    )

    for filepath in saved:
        print(f"NEW_DYNAMIC: {filepath.relative_to(repo_root())}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
