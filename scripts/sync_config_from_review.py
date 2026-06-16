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
STOCK_POOL = REPO_ROOT / "config" / "stock_monitor" / "stock_pool.yaml"
DIRECTION_CANDIDATES = REPO_ROOT / "config" / "stock_monitor" / "direction_candidates.yaml"

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
    if state.get("entry_zone_updates"):
        all_changes.extend(update_watchlist(state, dry_run))
    else:
        logger.info("daily_state.json 无 entry_zone_updates，跳过 watchlist")
    # stock_pool entry zone 反写
    all_changes.extend(update_stock_pool(state, dry_run))
    # direction candidates 生成
    all_changes.extend(update_direction_candidates(state, dry_run))

    return all_changes


# ═══════════════════════════════════════════
# Stock Pool entry zone 反写
# ═══════════════════════════════════════════

def parse_entry_zone(text: str) -> list[float] | None:
    """从文本中提取价格区间，如 '回踩42-43区间' → [42.0, 43.0]"""
    # 模式1: 数字-数字区间
    m = re.search(r'(\d+\.?\d*)\s*[-–—~到]\s*(\d+\.?\d*)', text)
    if m:
        return [float(m.group(1)), float(m.group(2))]
    return None


def update_stock_pool(state: dict, dry_run: bool) -> list[str]:
    """从 active_opportunities 反写 stock_pool.yaml entry.primary_zone。

    合并策略:
    - stock_pool 无 primary_zone → 直接写入
    - stock_pool 有 primary_zone 且 LLM 建议一致 → 跳过
    - stock_pool 有 primary_zone 但 LLM 建议不同 → 追加到 backup_zones，保留人工判断
    """
    changes = []
    data = load_yaml(STOCK_POOL)
    if not data:
        return changes

    opportunities = state.get("active_opportunities", [])
    if not opportunities:
        return changes

    stocks = data.get("stocks", [])
    if not stocks:
        return changes

    # 建立 code → opportunity 映射
    opp_map: dict[str, dict] = {}
    for opp in opportunities:
        code = str(opp.get("code", ""))
        if not code:
            continue
        # 标准化：去掉 .SZ/.SH 后缀
        pure = code.replace(".SZ", "").replace(".SH", "")
        opp_map[pure] = opp
        opp_map[code] = opp  # 同时保留原始格式

    for stock in stocks:
        code = str(stock.get("code", ""))
        pure = code.replace(".SZ", "").replace(".SH", "")
        opp = opp_map.get(pure) or opp_map.get(code)
        if not opp:
            # 尝试按 name 匹配
            name = stock.get("name", "")
            for o in opportunities:
                if o.get("stock") == name or o.get("name") == name:
                    opp = o
                    break
        if not opp:
            continue

        # 尝试获取 entry zone
        zone = None
        if "entry_zone" in opp and isinstance(opp["entry_zone"], list) and len(opp["entry_zone"]) == 2:
            zone = [float(opp["entry_zone"][0]), float(opp["entry_zone"][1])]
        elif opp.get("trigger"):
            zone = parse_entry_zone(str(opp["trigger"]))

        if not zone:
            continue

        entry = stock.setdefault("entry", {})
        current_zone = entry.get("primary_zone")

        # 合并策略
        if current_zone is None:
            # 无 zone → 直接写入
            entry["primary_zone"] = zone
            changes.append(
                f"stock_pool.{stock.get('name', code)}.entry.primary_zone: None → {zone}"
            )
        elif isinstance(current_zone, list) and len(current_zone) == 2:
            # 比较是否一致（容忍0.5的偏差）
            if abs(current_zone[0] - zone[0]) <= 0.5 and abs(current_zone[1] - zone[1]) <= 0.5:
                continue  # 一致，跳过
            else:
                # 不一致 → 追加到 backup_zones
                backup = entry.setdefault("backup_zones", [])
                # 检查是否已有相同或相近的 backup
                already_exists = False
                for bz in backup:
                    if (isinstance(bz, list) and len(bz) == 2
                        and abs(bz[0] - zone[0]) <= 0.5
                        and abs(bz[1] - zone[1]) <= 0.5):
                        already_exists = True
                        break
                if not already_exists:
                    backup.append(zone)
                    changes.append(
                        f"stock_pool.{stock.get('name', code)}.entry.backup_zones: +{zone} (保留 primary_zone={current_zone})"
                    )

    if not dry_run:
        save_yaml(STOCK_POOL, data)
        logger.info("✅ stock_pool.yaml 已更新")
    else:
        if changes:
            logger.info("[DRY RUN] stock_pool.yaml 将更新")

    return changes


# ═══════════════════════════════════════════
# Direction Candidates 生成
# ═══════════════════════════════════════════

def update_direction_candidates(state: dict, dry_run: bool) -> list[str]:
    """从 daily_state 的 direction_signals 更新 direction_candidates.yaml。

    direction_signals 格式:
    [{"direction": "方向名", "signal": "信号描述",
      "source": "来源(UP/复盘)", "status": "new/confirmed/expired"}]
    """
    changes = []
    signals = state.get("direction_signals", [])
    if not signals:
        return changes

    # 加载或初始化
    existing = load_yaml(DIRECTION_CANDIDATES) if DIRECTION_CANDIDATES.exists() else {}
    candidates = existing.get("directions", []) if existing else []

    existing_names = {d.get("direction", "") for d in candidates}

    for sig in signals:
        name = sig.get("direction", "")
        if not name:
            continue
        status = sig.get("status", "new")

        if status == "expired":
            # 标记过期
            for c in candidates:
                if c.get("direction") == name:
                    c["status"] = "expired"
                    changes.append(f"direction_candidates.{name}: → expired")
                    break
        elif name in existing_names:
            # 已存在 → 更新 signal
            for c in candidates:
                if c.get("direction") == name and c.get("status") != "expired":
                    old_signal = c.get("signal", "")
                    if old_signal != sig.get("signal", ""):
                        c["signal"] = sig.get("signal", "")
                        c["updated_at"] = datetime.now(CN_TZ).strftime("%Y-%m-%dT%H:%M")
                        changes.append(f"direction_candidates.{name}.signal: 已更新")
                    break
        else:
            # 新方向
            candidates.append({
                "direction": name,
                "signal": sig.get("signal", ""),
                "source": sig.get("source", "未标注"),
                "status": "new",
                "first_seen": datetime.now(CN_TZ).strftime("%Y-%m-%dT%H:%M"),
                "updated_at": datetime.now(CN_TZ).strftime("%Y-%m-%dT%H:%M"),
            })
            changes.append(f"direction_candidates.{name}: +new")
            existing_names.add(name)

    output = {"updated_at": datetime.now(CN_TZ).strftime("%Y-%m-%dT%H:%M"), "directions": candidates}

    if not dry_run and changes:
        DIRECTION_CANDIDATES.parent.mkdir(parents=True, exist_ok=True)
        save_yaml(DIRECTION_CANDIDATES, output)
        logger.info("✅ direction_candidates.yaml 已更新 (%d 条目)", len(candidates))
    elif dry_run and changes:
        logger.info("[DRY RUN] direction_candidates.yaml 将更新")

    return changes


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

    # 4.5 补 active_opportunities（LLM 输出不包含此字段，需从 daily_state.json 读取）
    if not state.get("active_opportunities") and DAILY_STATE_FILE.exists():
        try:
            ds = json.loads(DAILY_STATE_FILE.read_text(encoding="utf-8"))
            if ds.get("active_opportunities"):
                state["active_opportunities"] = ds["active_opportunities"]
                logger.info("从 daily_state.json 补充 active_opportunities (%d 条)",
                           len(state["active_opportunities"]))
        except Exception:
            pass

    # 5. 更新各文件
    all_changes = []
    all_changes.extend(update_strategy_pack(state, dry_run))
    all_changes.extend(update_positions(state, dry_run))
    all_changes.extend(update_watchlist(state, dry_run))
    all_changes.extend(update_stock_pool(state, dry_run))
    all_changes.extend(update_direction_candidates(state, dry_run))

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
