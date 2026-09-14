#!/usr/bin/env python3
"""
B站多UP动态拉取 + 通知脚本。

用法:
    BILIBILI_SESSDATA=xxx python3 scripts/bilibili_notify.py
    python3 scripts/bilibili_notify.py --uid 52512172      # 只跑单个 UP
    python3 scripts/bilibili_notify.py --check-only        # 只查不存

配置:
    config/bilibili_ups.yaml   UP 列表（uid/name/enabled）
    ~/.hermes/bilibili_sessdata.txt  SESSDATA Cookie

环境变量:
    BILIBILI_SESSDATA: B站登录Cookie（优先读文件）
    HERMES_REPO_ROOT:  项目根目录
    BILIBILI_UPS_CONFIG: 覆盖 UP 列表路径

输出:
    - 无新动态: 静默（空 stdout）
    - 有新动态: stdout 打印完整内容（供 Hermes cron 投递）

state（v2，按 uid 分键）:
    ~/.hermes/bilibili_up_state.json
    {"version": 2, "ups": {"<uid>": {"processed_ids": [...],
      "last_dynamic_id": ..., "last_check_time": ..., "initialized": true}}}

    新 UP 首次运行 = 静默初始化：只记录 processed_ids，不发通知。
    之后只推增量。
"""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime
from pathlib import Path

# 确保能导入 v2 脚本
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetch_bilibili_up_v2 import (
    fetch_dynamic_list,
    fetch_dynamic_detail,
    fetch_up_comment,
    extract_text_from_dynamic,
    extract_pics_from_dynamic,
    classify_dynamic_type,
    ocr_image_from_url,
    save_dynamic_to_file,
    load_state,
    save_state,
    original_dir,
    repo_root,
    build_index,
)

# B站 claims 去重器
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
try:
    from qing_investment.monitor.deduplicator import BilibiliClaimsDeduplicator
except Exception:  # 去重器不可用时不影响主流程
    BilibiliClaimsDeduplicator = None  # type: ignore

DEFAULT_UP_UID = "1420210197"
STATE_PATH = Path.home() / ".hermes" / "bilibili_up_state.json"


# ── UP 列表加载 ────────────────────────────────────────────────────

def _fallback_ups() -> list[dict]:
    """config 缺失时的兜底：至少保留青枫浦上Q。"""
    return [{"uid": DEFAULT_UP_UID, "name": "青枫浦上Q", "enabled": True}]


def load_ups(explicit_path: str | None = None) -> list[dict]:
    """从 config/bilibili_ups.yaml 读取 UP 列表。

    返回 [{uid, name, enabled}, ...]（只含 enabled=True）。
    """
    cfg_path = None
    if explicit_path:
        cfg_path = Path(explicit_path)
    else:
        env_path = os.environ.get("BILIBILI_UPS_CONFIG")
        if env_path:
            cfg_path = Path(env_path)
        else:
            cfg_path = repo_root() / "config" / "bilibili_ups.yaml"

    if not cfg_path.exists():
        print(f"WARN: UP 配置不存在 {cfg_path}，回退到默认单 UP", file=sys.stderr)
        return _fallback_ups()

    try:
        import yaml
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        ups = []
        for entry in data.get("ups", []) or []:
            if not isinstance(entry, dict):
                continue
            uid = entry.get("uid")
            if uid is None:
                continue
            if entry.get("enabled", True) is False:
                continue
            ups.append({
                "uid": str(uid).strip(),
                "name": (entry.get("name") or str(uid)).strip(),
                "enabled": True,
            })
        if not ups:
            print(f"WARN: {cfg_path} 未解析出任何 UP，回退到默认", file=sys.stderr)
            return _fallback_ups()
        return ups
    except Exception as exc:
        print(f"WARN: 解析 {cfg_path} 失败: {exc}，回退到默认", file=sys.stderr)
        return _fallback_ups()


# ── state v1 → v2 迁移 ─────────────────────────────────────────────

def _normalize_state(state: dict, legacy_uid: str = DEFAULT_UP_UID) -> dict:
    """把旧版扁平 state 升级为 v2（按 uid 分键）。

    v1: {"processed_ids": [...], "last_dynamic_id": ..., "last_check_time": ...}
        → 归到 legacy_uid 名下。
    """
    if state.get("version") == 2 and isinstance(state.get("ups"), dict):
        return state

    ups: dict = {}
    if state.get("processed_ids") or state.get("last_dynamic_id"):
        ups[legacy_uid] = {
            "processed_ids": list(state.get("processed_ids", [])),
            "last_dynamic_id": state.get("last_dynamic_id", ""),
            "last_check_time": state.get("last_check_time", ""),
            "initialized": True,  # 旧 UP 已初始化过，正常推送增量
        }
    return {"version": 2, "ups": ups}


def _get_up_state(state: dict, uid: str) -> dict:
    return state.setdefault("ups", {}).setdefault(uid, {
        "processed_ids": [],
        "last_dynamic_id": "",
        "last_check_time": "",
        "initialized": False,
    })


# ── 内容指纹（去重） ───────────────────────────────────────────────

def _content_fingerprint(content: str) -> str:
    import hashlib
    lines = content.split("\n")
    body_lines = []
    for line in lines:
        if line.startswith("pub_time:") or line.startswith("url:") or line.startswith("dynamic_id:"):
            continue
        body_lines.append(line.strip())
    text = " ".join(body_lines)
    normalized = re.sub(r"\s+|[，。！？、；：\"'（）【】\n]", "", text)[:200]
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()[:16]


# ── 单 UP 拉取 ────────────────────────────────────────────────────

def process_up(
    up: dict,
    sessdata: str,
    state: dict,
    dedup,
    *,
    check_only: bool = False,
    max_fetch: int = 5,
) -> tuple[list[Path], dict[str, bool]]:
    """拉取单个 UP 的动态，返回 (saved_files, {filepath: is_new})。"""
    uid = up["uid"]
    up_name = up.get("name") or uid
    up_state = _get_up_state(state, uid)
    processed_ids: set = set(up_state.get("processed_ids", []))

    resp = fetch_dynamic_list(uid, sessdata)
    if resp.get("code") != 0:
        print(f"ERROR: [{up_name}] B站API错误: {resp.get('message')}", file=sys.stderr)
        return [], {}

    items = resp.get("data", {}).get("items", []) or []
    if not items:
        up_state["last_check_time"] = datetime.now().isoformat()
        return [], {}

    new_items = []
    for item in items:
        dynamic_id = str(item.get("id_str", ""))
        if not dynamic_id or dynamic_id in processed_ids:
            continue
        new_items.append((dynamic_id, item))

    if not new_items:
        up_state["last_check_time"] = datetime.now().isoformat()
        return [], {}

    # ── 新 UP 首次运行 = 静默初始化 ──
    if not up_state.get("initialized"):
        for dynamic_id, _ in new_items:
            processed_ids.add(dynamic_id)
        up_state["processed_ids"] = sorted(processed_ids)
        up_state["last_dynamic_id"] = new_items[0][0]
        up_state["initialized"] = True
        up_state["last_check_time"] = datetime.now().isoformat()
        print(
            f"INFO: [{up_name}] 首次运行，静默初始化 {len(new_items)} 条历史动态"
            f"（不发通知，之后只推增量）",
            file=sys.stderr,
        )
        return [], {}

    if check_only:
        print(f"CHECK: [{up_name}] 发现 {len(new_items)} 条新动态")
        return [], {}

    temp_dir = original_dir() / ".temp"
    temp_dir.mkdir(exist_ok=True)

    saved_files: list[Path] = []
    dedup_results: dict[str, bool] = {}
    for dynamic_id, item in reversed(new_items[:max_fetch]):
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

            dyn_type = classify_dynamic_type(item)
            if dyn_type in ("图片", "文字") and not detail_data:
                has_text = bool(extract_text_from_dynamic(item).strip())
                has_pics = bool(extract_pics_from_dynamic(item))
                if not has_text or not has_pics:
                    try:
                        detail_data = fetch_dynamic_detail(dynamic_id, sessdata)
                    except Exception:
                        pass

            try:
                top_comment = fetch_up_comment(dynamic_id, sessdata)
            except Exception:
                pass

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
                sessdata=sessdata,
            )
            saved_files.append(filepath)
            processed_ids.add(dynamic_id)
            up_state["last_dynamic_id"] = dynamic_id

            content = filepath.read_text(encoding="utf-8")
            fp = _content_fingerprint(content)
            is_new = True
            if dedup is not None:
                pseudo_claim = {"claim_type": "bilibili_dynamic", "statement": content[:500]}
                try:
                    is_new = dedup.diff([pseudo_claim]).has_new
                except Exception:
                    is_new = True
            dedup_results[str(filepath)] = is_new
            mark = "✅ 新内容" if is_new else "⏭️ 已处理过"
            print(f"INFO: [{up_name}] {mark} {filepath.name}（指纹: {fp[:8]}）", file=sys.stderr)
        except Exception as exc:
            print(f"ERROR: [{up_name}] 保存动态 {dynamic_id} 失败: {exc}", file=sys.stderr)

    if temp_dir.exists():
        try:
            for f in temp_dir.iterdir():
                f.unlink(missing_ok=True)
            temp_dir.rmdir()
        except OSError:
            pass

    up_state["processed_ids"] = sorted(processed_ids)[-1000:]
    up_state["last_check_time"] = datetime.now().isoformat()
    up_state["initialized"] = True
    return saved_files, dedup_results


# ── 通知渲染 ──────────────────────────────────────────────────────

def render_notification(filepath: Path, up_name: str, is_new: bool) -> str:
    content = filepath.read_text(encoding="utf-8")
    lines = content.split("\n")
    url = ""
    pub_time = ""
    ocr_section = ""
    comment_section = ""
    in_ocr = False
    in_comment = False

    for line in lines:
        if line.startswith("## 图片 OCR"):
            in_ocr, in_comment = True, False
            continue
        elif line.startswith("## 置顶评论"):
            in_ocr, in_comment = False, True
            continue
        elif line.startswith("## 图片") or line.startswith("## 互动数据"):
            in_ocr, in_comment = False, False
            continue

        if in_ocr and line.strip() and not line.startswith("```"):
            ocr_section += line + "\n"
        elif in_comment and line.strip() and not line.startswith("> 👤") and not line.startswith("> 👍"):
            comment_section += line.lstrip("> ").strip() + "\n"
        elif line.startswith("pub_time:"):
            pub_time = line.split(":", 1)[1].strip().strip('"')
        elif line.startswith("url:"):
            url = line.split(":", 1)[1].strip().strip('"')

    text_start = content.find("## 原文\n\n")
    text_end = content.find("\n\n## 图片 OCR") if "## 图片 OCR" in content else content.find("\n\n## 图片")
    raw_text = ""
    if text_start > 0 and text_end > text_start:
        raw_text = content[text_start + 9:text_end].strip()

    msg = f"📢 **{up_name} 新动态**\n\n"
    if not is_new:
        msg += "🔄 *此内容已处理过，本次跳过*\n\n"
    msg += f"⏰ {pub_time}\n"
    msg += f"🔗 {url}\n\n"
    if raw_text:
        msg += f"**原文：**\n{raw_text}\n\n"
    if ocr_section.strip():
        msg += f"**图片内容：**\n{ocr_section.strip()}\n\n"
    if comment_section.strip():
        msg += f"**置顶评论：**\n{comment_section.strip()}\n\n"
    if is_new:
        msg += f"<!-- BILIBILI_NEW_CONTENT:{filepath.name} -->\n"
    else:
        msg += f"<!-- BILIBILI_DUPLICATE:{filepath.name} -->\n"
    return msg


# ── main ──────────────────────────────────────────────────────────

def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="B站多UP动态拉取 + 通知")
    parser.add_argument("--uid", help="只跑指定 uid（默认跑 config 全部）")
    parser.add_argument("--config", help="UP 列表 yaml 路径")
    parser.add_argument("--check-only", action="store_true", help="只查不存")
    parser.add_argument("--max-fetch", type=int, default=5, help="每个UP最多处理几条新动态")
    parser.add_argument("--state-file", type=Path, help="state 文件路径")
    args = parser.parse_args()

    sessdata = os.environ.get("BILIBILI_SESSDATA", "")
    sessdata_file = Path.home() / ".hermes" / "bilibili_sessdata.txt"
    if not sessdata and sessdata_file.exists():
        sessdata = sessdata_file.read_text(encoding="utf-8").strip()
        if sessdata:
            print("INFO: 从文件读取 SESSDATA", file=sys.stderr)

    if not sessdata:
        print("ERROR: 需要 BILIBILI_SESSDATA 环境变量或 ~/.hermes/bilibili_sessdata.txt",
              file=sys.stderr)
        return 1

    # Cookie 有效性检查
    try:
        import urllib.request, json
        req = urllib.request.Request(
            "https://api.bilibili.com/x/web-interface/nav",
            headers={"User-Agent": "Mozilla/5.0", "Cookie": f"SESSDATA={sessdata}"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if data.get("code") == -101 or not data.get("data", {}).get("isLogin"):
                print("⚠️ **B站 Cookie 已过期**")
                print("请更新 BILIBILI_SESSDATA 后重新运行")
                return 1
    except Exception as exc:
        print(f"WARN: Cookie 检查失败: {exc}", file=sys.stderr)

    ups = load_ups(args.config)
    if args.uid:
        target = str(args.uid).strip()
        ups = [u for u in ups if u["uid"] == target] or [
            {"uid": target, "name": target, "enabled": True}
        ]

    state_path = args.state_file or STATE_PATH
    state = _normalize_state(load_state(state_path))

    dedup = None
    if BilibiliClaimsDeduplicator is not None:
        dedup_cache_dir = Path.home() / ".hermes" / "bilibili_dedup_cache"
        dedup_cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            dedup = BilibiliClaimsDeduplicator(cache_dir=dedup_cache_dir)
        except Exception as exc:
            print(f"WARN: 去重器初始化失败: {exc}", file=sys.stderr)

    all_saved: list[tuple[Path, str, bool]] = []
    for up in ups:
        try:
            saved, dedup_results = process_up(
                up, sessdata, state, dedup,
                check_only=args.check_only, max_fetch=args.max_fetch,
            )
        except SystemExit:
            continue
        except Exception as exc:
            print(f"ERROR: [{up.get('name')}] 拉取失败: {exc}", file=sys.stderr)
            continue
        for fp in saved:
            all_saved.append((fp, up.get("name") or up["uid"], dedup_results.get(str(fp), True)))

    state["version"] = 2
    state["last_check_time"] = datetime.now().isoformat()
    save_state(state_path, state)

    if all_saved:
        try:
            build_index()
        except Exception as exc:
            print(f"WARN: build_index 失败: {exc}", file=sys.stderr)

    for filepath, up_name, is_new in all_saved:
        print(render_notification(filepath, up_name, is_new))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
