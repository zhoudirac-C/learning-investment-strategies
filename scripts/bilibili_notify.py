#!/usr/bin/env python3
"""
B站动态拉取 + 微信通知脚本。

用法:
    BILIBILI_SESSDATA=xxx uv run python scripts/bilibili_notify.py

环境变量:
    BILIBILI_SESSDATA: B站登录Cookie
    HERMES_REPO_ROOT: 项目根目录

输出:
    - 无新动态: 静默
    - 有新动态: stdout 打印完整内容（供 Hermes cron 发送到微信）
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# 确保能导入 v2 脚本
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetch_bilibili_up_v2 import (
    build_cookie,
    fetch_dynamic_list,
    fetch_dynamic_detail,
    fetch_top_comment,
    extract_text_from_dynamic,
    extract_pics_from_dynamic,
    extract_author_info,
    extract_stat,
    classify_dynamic_type,
    ocr_image_from_url,
    save_dynamic_to_file,
    load_state,
    save_state,
    original_dir,
    repo_root,
    build_index,
)


def main() -> int:
    uid = os.environ.get("BILIBILI_UP_UID", "1420210197")
    sessdata = os.environ.get("BILIBILI_SESSDATA", "")
    if not sessdata:
        print("ERROR: 需要 BILIBILI_SESSDATA 环境变量", file=sys.stderr)
        return 1

    # 检查 Cookie 是否有效
    try:
        import urllib.request, json
        url = "https://api.bilibili.com/x/web-interface/nav"
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Cookie": f"SESSDATA={sessdata}",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if data.get("code") == -101 or not data.get("data", {}).get("isLogin"):
                print("⚠️ **B站 Cookie 已过期**")
                print("请更新 BILIBILI_SESSDATA 后重新运行")
                return 1
    except Exception as exc:
        print(f"WARN: Cookie 检查失败: {exc}", file=sys.stderr)

    state_path = Path.home() / ".hermes" / "bilibili_up_state.json"
    state = load_state(state_path)
    processed_ids: set = set(state.get("processed_ids", []))

    # 拉取动态列表
    resp = fetch_dynamic_list(uid, sessdata)
    if resp.get("code") != 0:
        print(f"ERROR: B站API错误: {resp.get('message')}", file=sys.stderr)
        return 1

    items = resp.get("data", {}).get("items", [])
    if not items:
        return 0

    # 筛选新动态
    new_items = []
    for item in items:
        dynamic_id = str(item.get("id_str", ""))
        if not dynamic_id or dynamic_id in processed_ids:
            continue
        new_items.append((dynamic_id, item))

    if not new_items:
        return 0

    temp_dir = original_dir() / ".temp"
    temp_dir.mkdir(exist_ok=True)

    saved_files = []
    for dynamic_id, item in reversed(new_items[:5]):  # 最多处理5条
        try:
            basic = item.get("basic", {})
            is_only_fans = basic.get("is_only_fans", False)

            detail_data = None
            top_comment = None
            ocr_text = ""

            if is_only_fans:
                try:
                    detail_data = fetch_dynamic_detail(dynamic_id, sessdata)
                except Exception:
                    pass

            # 获取置顶评论
            try:
                top_comment = fetch_top_comment(dynamic_id, sessdata)
            except Exception:
                pass

            # OCR
            pics = extract_pics_from_dynamic(item)
            if not pics and detail_data:
                pics = extract_pics_from_dynamic(detail_data.get("data", {}).get("item", {}))

            ocr_results = []
            for pic_url in pics[:5]:
                text = ocr_image_from_url(pic_url, temp_dir)
                if text.strip():
                    ocr_results.append(text)
            if ocr_results:
                ocr_text = "\n\n".join(ocr_results)

            filepath = save_dynamic_to_file(
                item, uid, dynamic_id,
                detail_data=detail_data,
                top_comment=top_comment,
                ocr_text=ocr_text,
                is_only_fans=is_only_fans,
            )
            saved_files.append(filepath)
            processed_ids.add(dynamic_id)
            state["last_dynamic_id"] = dynamic_id
        except Exception as exc:
            print(f"ERROR: 保存动态 {dynamic_id} 失败: {exc}", file=sys.stderr)

    # 清理
    if temp_dir.exists():
        for f in temp_dir.iterdir():
            f.unlink(missing_ok=True)
        temp_dir.rmdir()

    # 更新状态
    from datetime import datetime
    state["last_check_time"] = datetime.now().isoformat()
    state["processed_ids"] = sorted(list(processed_ids))[-1000:]
    save_state(state_path, state)

    # 生成索引
    if saved_files:
        build_index()

    # 输出微信通知内容（stdout 会被 Hermes cron 发送到微信）
    for filepath in saved_files:
        content = filepath.read_text(encoding="utf-8")
        # 提取关键信息
        lines = content.split("\n")
        title = ""
        url = ""
        pub_time = ""
        ocr_section = ""
        comment_section = ""
        in_ocr = False
        in_comment = False

        for line in lines:
            if line.startswith("## 图片 OCR"):
                in_ocr = True
                continue
            elif line.startswith("## 置顶评论"):
                in_ocr = False
                in_comment = True
                continue
            elif line.startswith("## 图片") or line.startswith("## 互动数据"):
                in_ocr = False
                in_comment = False
                continue

            if in_ocr and line.strip() and not line.startswith("```"):
                ocr_section += line + "\n"
            elif in_comment and line.strip() and not line.startswith("> 👤") and not line.startswith("> 👍"):
                comment_section += line.lstrip("> ").strip() + "\n"
            elif line.startswith("pub_time:"):
                pub_time = line.split(":", 1)[1].strip().strip('"')
            elif line.startswith("url:"):
                url = line.split(":", 1)[1].strip().strip('"')

        # 获取原文前200字
        text_start = content.find("## 原文\n\n")
        text_end = content.find("\n\n## 图片 OCR") if "## 图片 OCR" in content else content.find("\n\n## 图片")
        raw_text = ""
        if text_start > 0 and text_end > text_start:
            raw_text = content[text_start + 9:text_end].strip()[:200]

        # 构建微信消息
        msg = f"📢 **青枫浦上Q 新动态**\n\n"
        msg += f"⏰ {pub_time}\n"
        msg += f"🔗 {url}\n\n"
        if raw_text:
            msg += f"**原文摘要：**\n{raw_text}\n"
            if len(raw_text) >= 200:
                msg += "...\n"
            msg += "\n"
        if ocr_section.strip():
            msg += f"**图片内容：**\n{ocr_section.strip()[:300]}\n"
            if len(ocr_section.strip()) > 300:
                msg += "...\n"
            msg += "\n"
        if comment_section.strip():
            msg += f"**置顶评论：**\n{comment_section.strip()[:200]}\n"
            if len(comment_section.strip()) > 200:
                msg += "...\n"

        print(msg)
        print("---")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
