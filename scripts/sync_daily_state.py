#!/usr/bin/env python3
"""Daily State 同步扫描器。

扫描 ~/.hermes/cron/output/ 下 9 个看盘 cron job 的最新输出，
提取 ```daily_state 代码块中的 JSON，合并写入 daily_state.json。

用法:
    python scripts/sync_daily_state.py          # 扫描一次
    python scripts/sync_daily_state.py --dry-run  # 仅打印，不写入
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 项目路径（硬编码，cron 环境下 __file__ 在 ~/.hermes/scripts/ 下）
REPO_ROOT = Path("/home/ubuntu/learning-investment-strategies")
sys.path.insert(0, str(REPO_ROOT / "src"))

CN_TZ = timezone(timedelta(hours=8))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("sync_daily_state")

# ── 配置 ──
CRON_OUTPUT_DIR = Path.home() / ".hermes" / "cron" / "output"
TRACKER_FILE = REPO_ROOT / "config" / "stock_monitor" / ".sync_daily_state_last.json"
DAILY_STATE_FILE = REPO_ROOT / "config" / "stock_monitor" / "daily_state.json"

# 9 个看盘 cron job 的 ID
MONITOR_JOB_IDS = [
    "3a1c39a7e543",  # 09:26 集合竞价后
    "2761c40519b8",  # 09:45 开盘15分钟确认
    "20063caf1c46",  # 10:00 10点确认
    "40859a5c0546",  # 10:30 30分钟确认
    "f103249d0301",  # 11:20 上午收盘前
    "6e2c0c4f929b",  # 13:10 午后风险窗口
    "41c8e6da0e65",  # 14:00 午盘监控
    "0763d55a8472",  # 14:55 尾盘条件单
    "fc7d8a270d84",  # 15:20 收盘复盘
]

# ── 工具函数 ──


def load_tracker() -> dict:
    """加载上次扫描时间记录。"""
    if TRACKER_FILE.exists():
        try:
            return json.loads(TRACKER_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            pass
    return {}


def save_tracker(data: dict) -> None:
    """保存扫描时间记录。"""
    TRACKER_FILE.parent.mkdir(parents=True, exist_ok=True)
    TRACKER_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_daily_state() -> dict:
    """加载当前 daily_state.json。"""
    if DAILY_STATE_FILE.exists():
        try:
            return json.loads(DAILY_STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            pass
    return _init_daily_state()


def save_daily_state(data: dict) -> None:
    """保存 daily_state.json。"""
    DAILY_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    DAILY_STATE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _init_daily_state() -> dict:
    """初始化空的 daily_state。"""
    return {
        "date": datetime.now(CN_TZ).strftime("%Y-%m-%d"),
        "market_stage": {"phase": "", "detail": "", "updated_by": "", "updated_at": ""},
        "direction_priority": [],
        "position_stance": "",
        "active_opportunities": [],
        "intraday_narrative": [],
        "version": 1,
    }


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


def merge_daily_state(current: dict, update: dict, source: str) -> dict:
    """将更新合并到当前 daily_state。"""
    now = datetime.now(CN_TZ).strftime("%Y-%m-%dT%H:%M:%S+08:00")

    # market_stage
    if "market_stage" in update and update["market_stage"].get("phase"):
        current["market_stage"] = {
            **current["market_stage"],
            **update["market_stage"],
            "updated_by": source,
            "updated_at": now,
        }

    # direction_priority
    if "direction_priority" in update and update["direction_priority"]:
        if isinstance(update["direction_priority"][0], str):
            # Simple list → convert to dict format
            current["direction_priority"] = [
                {"direction": d, "intensity": "", "source": source} for d in update["direction_priority"]
            ]
        else:
            current["direction_priority"] = [
                {**d, "source": d.get("source", source)} for d in update["direction_priority"]
            ]

    # position_stance
    if "position_stance" in update and update["position_stance"]:
        current["position_stance"] = update["position_stance"]

    # active_opportunities — 按 code 去重合并
    if "active_opportunities" in update and update["active_opportunities"]:
        existing_codes = {o.get("code") for o in current.get("active_opportunities", [])}
        for opp in update["active_opportunities"]:
            if opp.get("code") not in existing_codes:
                current.setdefault("active_opportunities", []).append(opp)
                existing_codes.add(opp.get("code"))
            else:
                # 更新已有
                for existing in current["active_opportunities"]:
                    if existing.get("code") == opp.get("code"):
                        existing.update(opp)
                        break

    # intraday_narrative — 追加
    narrative_map = {
        "core_assumption": "09:26 核心假设",
        "assumption_validation": "09:45 假设验证",
        "morning_character": "10:00 早盘定性",
        "morning_summary": "11:20 上午总结",
        "morning_validation": "14:00 午盘验证",
        "afternoon_assessment": "14:00 午后评估",
        "tail_buy": "14:55 尾盘决策",
        "overnight_stance": "14:55 过夜策略",
        "tomorrow_assumption": "15:20 明日假设",
    }

    for key, label in narrative_map.items():
        if key in update and update[key]:
            entry = {
                "time": source,
                "label": label,
                "summary": str(update[key])[:200],
                "timestamp": now,
            }
            current.setdefault("intraday_narrative", []).append(entry)

    return current


def find_latest_output(job_id: str) -> Path | None:
    """找到指定 job 的最新输出文件。"""
    job_dir = CRON_OUTPUT_DIR / job_id
    if not job_dir.is_dir():
        return None
    files = sorted(job_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def scan_and_sync(dry_run: bool = False) -> int:
    """主扫描逻辑。返回更新的 job 数量。"""
    tracker = load_tracker()
    daily_state = load_daily_state()
    updated_count = 0

    for job_id in MONITOR_JOB_IDS:
        output_file = find_latest_output(job_id)
        if not output_file:
            continue

        mtime = output_file.stat().st_mtime
        last_seen = tracker.get(job_id, 0)

        if mtime <= last_seen:
            continue  # 无新输出

        logger.info("新输出: %s (%s)", job_id[:8], output_file.name)

        try:
            text = output_file.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning("读取失败: %s", e)
            continue

        blocks = extract_daily_state_blocks(text)
        if not blocks:
            logger.info("  未找到 daily_state 代码块")
            tracker[job_id] = mtime
            continue

        for block in blocks:
            daily_state = merge_daily_state(daily_state, block, job_id[:8])
            logger.info("  已合并 daily_state: %s", json.dumps(block, ensure_ascii=False)[:120])

        tracker[job_id] = mtime
        updated_count += 1

    if updated_count > 0:
        if dry_run:
            logger.info("[DRY RUN] 将写入 daily_state.json: %s", json.dumps(daily_state, ensure_ascii=False, indent=2))
        else:
            save_daily_state(daily_state)
            save_tracker(tracker)
            logger.info("✅ 已更新 daily_state.json (%d 个 job, %d 条narrative)",
                        updated_count,
                        len(daily_state.get("intraday_narrative", [])))
    else:
        logger.info("无新输出，跳过")

    return updated_count


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Daily State 同步扫描器")
    parser.add_argument("--dry-run", action="store_true", help="仅打印，不写入文件")
    args = parser.parse_args()
    scan_and_sync(dry_run=args.dry_run)
