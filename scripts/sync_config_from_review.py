#!/usr/bin/env python3
"""收盘复盘数据 → Config 同步器。

读取 17:00 收盘复盘 cron 输出的 daily_state JSON，写回 config 文件。

用法:
    python scripts/sync_config_from_review.py          # 执行同步
    python scripts/sync_config_from_review.py --dry-run  # 仅打印，不写入
    python scripts/sync_config_from_review.py --force    # 从 daily_state.json 读，不依赖 cron 输出
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

REPO_ROOT = Path("/home/ubuntu/learning-investment-strategies")
CN_TZ = timezone(timedelta(hours=8))

CRON_OUTPUT_DIR = Path.home() / ".hermes" / "cron" / "output"
TRACKER_FILE = REPO_ROOT / "config" / "stock_monitor" / ".sync_config_last.json"
DAILY_STATE_FILE = REPO_ROOT / "config" / "stock_monitor" / "daily_state.json"

STRATEGY_PACK = REPO_ROOT / "config" / "stock_monitor" / "strategy_pack.yaml"
POSITIONS = REPO_ROOT / "config" / "stock_monitor" / "positions.yaml"
WATCHLIST = REPO_ROOT / "config" / "stock_monitor" / "watchlist.yaml"

DAILY_REVIEW_JOB_ID = "fc7d8a270d84"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("sync_config_from_review")


def extract_daily_state_blocks(text: str) -> list[dict]:
    """从文本中提取 ```daily_state 代码块。"""
    pattern = re.compile(r"```daily_state\s*\n(.*?)```", re.DOTALL)
    results = []
    for match in pattern.finditer(text):
        json_str = match.group(1).strip()
        try:
            data = json.loads(json_str)
            results.append(data)
        except json.JSONDecodeError as e:
            logger.warning("daily_state JSON 解析失败: %s", e)
    return results


def find_latest_output(job_id: str) -> Path | None:
    """找到指定 job 的最新输出文件。"""
    job_dir = CRON_OUTPUT_DIR / job_id
    if not job_dir.is_dir():
        return None
    files = sorted(job_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def load_yaml(path: Path) -> dict:
    """安全加载 YAML 文件。"""
    if not path.exists():
        logger.warning("文件不存在: %s", path)
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning("YAML加载失败 %s: %s", path, e)
        return {}


def save_yaml(path: Path, data: dict) -> None:
    """保存 YAML 文件，保留原有格式。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def update_strategy_pack(state: dict, dry_run: bool) -> list[str]:
    """更新 strategy_pack.yaml 的市场框架。"""
    changes = []
    data = load_yaml(STRATEGY_PACK)
    if not data:
        return changes

    mf = data.setdefault("market_framework", {})

    # market_stage.phase → current_stage
    if "market_stage" in state:
        ms = state["market_stage"]
        phase = ms.get("phase", "")
        detail = ms.get("detail", "")
        if phase:
            new_stage = f"{phase} — {detail}" if detail else phase
            old = mf.get("current_stage", "")
            if old != new_stage:
                mf["current_stage"] = new_stage
                changes.append(f"strategy_pack.market_framework.current_stage: {old[:40]} → {new_stage[:40]}")

    # direction_priority
    if "direction_priority" in state and state["direction_priority"]:
        mf["direction_priority"] = state["direction_priority"]
        changes.append(f"strategy_pack.market_framework.direction_priority: {len(state['direction_priority'])} 条")

    # 更新 updated_at
    now_str = datetime.now(CN_TZ).strftime("%Y-%m-%dT%H:%M")
    data["updated_at"] = now_str

    if not dry_run:
        save_yaml(STRATEGY_PACK, data)
        logger.info("✅ strategy_pack.yaml 已更新")
    else:
        logger.info("[DRY RUN] strategy_pack.yaml 将更新")

    return changes


def update_positions(state: dict, dry_run: bool) -> list[str]:
    """更新 positions.yaml 的策略摘要和风险提醒。"""
    changes = []
    data = load_yaml(POSITIONS)
    if not data:
        return changes

    ss = data.setdefault("strategy_summary", {})

    # position_stance → current_stage
    stance = state.get("position_stance", "")
    if stance:
        old = ss.get("current_stage", "")
        # 如果已有内容则追加（保留原有持仓数据）
        new_stage = f"{stance}" if not old else f"{old} | {stance}"
        if old != new_stage:
            ss["current_stage"] = new_stage
            changes.append(f"positions.strategy_summary.current_stage: {old[:40]} → {new_stage[:40]}")

    # risk_reminder
    risk = state.get("risk_reminder", "")
    if risk:
        old = data.get("risk_reminder", "")
        if old != risk:
            data["risk_reminder"] = risk
            changes.append(f"positions.risk_reminder: {old[:40]} → {risk[:40]}")

    # today_key_signals
    signals = state.get("today_key_signals", [])
    if signals:
        old = data.get("today_key_signals", [])
        if old != signals:
            data["today_key_signals"] = signals
            changes.append(f"positions.today_key_signals: {len(signals)} 条")

    # tomorrow_scenarios
    scenarios = state.get("tomorrow_scenarios", {})
    if scenarios:
        old = data.get("tomorrow_scenarios", {})
        if old != scenarios:
            data["tomorrow_scenarios"] = scenarios
            changes.append(f"positions.tomorrow_scenarios: {json.dumps(scenarios, ensure_ascii=False)[:60]}")

    if not dry_run:
        save_yaml(POSITIONS, data)
        logger.info("✅ positions.yaml 已更新")
    else:
        logger.info("[DRY RUN] positions.yaml 将更新")

    return changes


def update_watchlist(state: dict, dry_run: bool) -> list[str]:
    """更新 watchlist.yaml 中标的的 current_ref。"""
    changes = []
    data = load_yaml(WATCHLIST)
    if not data:
        return changes

    entry_updates = state.get("entry_zone_updates", [])
    if not entry_updates:
        return changes

    # 建立 code → update 映射
    update_map = {u["code"]: u for u in entry_updates if u.get("code") and u.get("current_ref")}

    themes = data.get("themes", [])
    for theme in themes:
        for stock in theme.get("stocks", []):
            code = str(stock.get("code", ""))
            # 提取纯数字代码
            pure = code.replace(".SZ", "").replace(".SH", "").replace("sz", "").replace("sh", "")
            update = update_map.get(pure) or update_map.get(code)
            if not update:
                # 尝试匹配 name
                name = stock.get("name", "")
                for u in update_map.values():
                    if u.get("name") == name:
                        update = u
                        break
            if update:
                ez = stock.setdefault("entry_zone", {})
                old_ref = ez.get("current_ref", "")
                new_ref = update["current_ref"]
                if old_ref != new_ref:
                    ez["current_ref"] = new_ref
                    changes.append(f"watchlist.{stock.get('name', code)}.entry_zone.current_ref: {old_ref[:40]} → {new_ref[:40]}")

    if not dry_run:
        save_yaml(WATCHLIST, data)
        logger.info("✅ watchlist.yaml 已更新")
    else:
        logger.info("[DRY RUN] watchlist.yaml 将更新")

    return changes


def sync_from_daily_state_file(dry_run: bool) -> list[str]:
    """从 daily_state.json 读取数据同步（--force 模式）。"""
    if not DAILY_STATE_FILE.exists():
        logger.warning("daily_state.json 不存在")
        return []

    try:
        with open(DAILY_STATE_FILE, encoding="utf-8") as f:
            state = json.load(f)
    except Exception as e:
        logger.warning("读取 daily_state.json 失败: %s", e)
        return []

    logger.info("强制模式: 从 daily_state.json 读取")
    all_changes = []
    all_changes.extend(update_strategy_pack(state, dry_run))
    all_changes.extend(update_positions(state, dry_run))
    # watchlist 需要 entry_zone_updates 这个字段在 daily_state.json 里
    # 如果不存在则跳过
    if state.get("entry_zone_updates"):
        all_changes.extend(update_watchlist(state, dry_run))
    else:
        logger.info("daily_state.json 无 entry_zone_updates，跳过 watchlist")

    return all_changes


def sync(dry_run: bool = False, force: bool = False) -> int:
    """主同步逻辑。返回更新项数量。"""
    if force:
        changes = sync_from_daily_state_file(dry_run)
        for c in changes:
            logger.info("  %s", c)
        return len(changes)

    # 1. 找最新复盘输出
    output_file = find_latest_output(DAILY_REVIEW_JOB_ID)
    if not output_file:
        logger.warning("未找到收盘复盘输出文件 (job_id=%s)", DAILY_REVIEW_JOB_ID)
        logger.info("提示: 使用 --force 可从 daily_state.json 同步")
        return 0

    mtime = output_file.stat().st_mtime
    tracker = {}
    if TRACKER_FILE.exists():
        try:
            tracker = json.loads(TRACKER_FILE.read_text(encoding="utf-8"))
        except Exception:
            tracker = {}

    last_seen = tracker.get(DAILY_REVIEW_JOB_ID, 0)
    if mtime <= last_seen and not dry_run:
        logger.info("无新输出 (上次: %s)", datetime.fromtimestamp(last_seen, CN_TZ).isoformat())
        return 0

    logger.info("新输出文件: %s", output_file)

    # 2. 读取输出
    try:
        text = output_file.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("读取失败: %s", e)
        return 0

    # 3. 提取 daily_state JSON
    blocks = extract_daily_state_blocks(text)
    if not blocks:
        logger.warning("未找到 daily_state 代码块")
        return 0

    # 4. 合并所有块
    state = {}
    for block in blocks:
        state.update(block)

    # 5. 更新各文件
    all_changes = []
    all_changes.extend(update_strategy_pack(state, dry_run))
    all_changes.extend(update_positions(state, dry_run))
    all_changes.extend(update_watchlist(state, dry_run))

    # 6. 记录追踪
    if not dry_run and all_changes:
        TRACKER_FILE.parent.mkdir(parents=True, exist_ok=True)
        tracker[DAILY_REVIEW_JOB_ID] = mtime
        TRACKER_FILE.write_text(json.dumps(tracker, ensure_ascii=False, indent=2), encoding="utf-8")

    # 7. 打印变更摘要
    if all_changes:
        logger.info("=" * 40)
        logger.info("变更摘要:")
        for c in all_changes:
            logger.info("  ✅ %s", c)
        logger.info("=" * 40)
    else:
        logger.info("无变更")

    return len(all_changes)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Config 同步器：从收盘复盘输出更新配置文件")
    parser.add_argument("--dry-run", action="store_true", help="仅打印变更，不写入文件")
    parser.add_argument("--force", action="store_true", help="强制从 daily_state.json 同步（不依赖 cron 输出）")
    args = parser.parse_args()

    count = sync(dry_run=args.dry_run, force=args.force)
    raise SystemExit(0 if count >= 0 else 1)
