"""Daily State Manager — 盘中观点连续性状态机。

Phase 3 核心组件：
- 持久化 daily_state.json，记录全天观点演进
- 所有 cron 节点共享读写，实现观点连续性
- 收盘后自动归档，次日新建

Refs: docs/config-cron-architecture-review.md v2.0 Phase 3
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from qing_investment.paths import repo_root

logger = logging.getLogger(__name__)

DEFAULT_STATE_PATH = repo_root() / "config" / "stock_monitor" / "daily_state.json"


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def load_daily_state(path: Path | None = None) -> dict:
    """加载当前日期的 daily_state.json。如果文件不存在或日期过期，返回初始状态。"""
    state_path = path or DEFAULT_STATE_PATH
    
    if not state_path.exists():
        return _init_daily_state()
    
    try:
        with open(state_path, encoding="utf-8") as f:
            data = json.load(f)
        
        # 检查日期是否过期（非交易日或跨天）
        if data.get("date") != _today_str():
            logger.info("Daily state expired (%s -> %s), reinitializing", 
                       data.get("date"), _today_str())
            return _init_daily_state()
        
        return data
    except Exception as e:
        logger.warning("Failed to load daily_state: %s", e)
        return _init_daily_state()


def save_daily_state(data: dict, path: Path | None = None) -> None:
    """保存 daily_state.json。"""
    state_path = path or DEFAULT_STATE_PATH
    
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("Failed to save daily_state: %s", e)


def _init_daily_state() -> dict:
    """初始化新的 daily_state。"""
    return {
        "date": _today_str(),
        "market_stage": {
            "phase": "未判断",
            "detail": "",
            "updated_by": "",
            "updated_at": "",
        },
        "direction_priority": [],
        "position_stance": "未判断",
        "active_opportunities": [],
        "intraday_narrative": [],
        "version": 1,
    }


def update_market_stage(
    state: dict,
    phase: str,
    detail: str,
    updated_by: str,
) -> dict:
    """更新市场阶段判断。"""
    state["market_stage"] = {
        "phase": phase,
        "detail": detail,
        "updated_by": updated_by,
        "updated_at": datetime.now().isoformat(),
    }
    return state


def update_direction_priority(
    state: dict,
    directions: list[dict],
    updated_by: str,
) -> dict:
    """更新方向优先级排序。
    
    directions: [{"direction": "燃气轮机", "intensity": "🔥🔥🔥", 
                  "source_claims": [...], "up_quote": "..."}]
    """
    state["direction_priority"] = directions
    state.setdefault("_meta", {})
    state["_meta"]["direction_updated_by"] = updated_by
    state["_meta"]["direction_updated_at"] = datetime.now().isoformat()
    return state


def update_position_stance(
    state: dict,
    stance: str,
    updated_by: str,
) -> dict:
    """更新持仓态度（空仓等待/轻仓试探/重仓持有 等）。"""
    state["position_stance"] = stance
    state.setdefault("_meta", {})
    state["_meta"]["stance_updated_by"] = updated_by
    state["_meta"]["stance_updated_at"] = datetime.now().isoformat()
    return state


def add_opportunity(
    state: dict,
    stock: str,
    code: str,
    pattern: str,
    trigger: str,
    upside: str,
    downside: str,
    ratio: str,
    status: str = "未触发",
) -> dict:
    """添加或更新活跃机会。"""
    opportunities = state.get("active_opportunities", [])
    
    # 查找是否已存在
    existing = None
    for i, opp in enumerate(opportunities):
        if opp.get("code") == code:
            existing = i
            break
    
    new_opp = {
        "stock": stock,
        "code": code,
        "pattern": pattern,
        "trigger": trigger,
        "status": status,
        "upside": upside,
        "downside": downside,
        "ratio": ratio,
        "updated_at": datetime.now().isoformat(),
    }
    
    if existing is not None:
        opportunities[existing] = new_opp
    else:
        opportunities.append(new_opp)
    
    state["active_opportunities"] = opportunities
    return state


def add_intraday_narrative(
    state: dict,
    time_str: str,
    summary: str,
) -> dict:
    """添加盘中观点演进记录。"""
    narrative = state.get("intraday_narrative", [])
    narrative.append({
        "time": time_str,
        "summary": summary,
        "timestamp": datetime.now().isoformat(),
    })
    state["intraday_narrative"] = narrative
    return state


def get_state_summary(state: dict) -> str:
    """生成 human-readable 的状态摘要，用于注入 prompt。"""
    lines = []
    
    # 市场阶段
    stage = state.get("market_stage", {})
    if stage.get("phase") and stage["phase"] != "未判断":
        lines.append(f"【市场阶段】{stage['phase']} | {stage.get('detail', '')}")
    
    # 方向优先级
    directions = state.get("direction_priority", [])
    if directions:
        dir_str = " | ".join([
            f"{d['direction']}({d.get('intensity', '')})"
            for d in directions[:3]
        ])
        lines.append(f"【方向优先级】{dir_str}")
    
    # 持仓态度
    stance = state.get("position_stance", "未判断")
    if stance != "未判断":
        lines.append(f"【持仓态度】{stance}")
    
    # 活跃机会
    opportunities = state.get("active_opportunities", [])
    if opportunities:
        opp_str = " | ".join([
            f"{o['stock']}({o['code']}): {o['pattern']} {o['ratio']}"
            for o in opportunities[:3]
        ])
        lines.append(f"【活跃机会】{opp_str}")
    
    # 今日观点演进
    narrative = state.get("intraday_narrative", [])
    if narrative:
        lines.append("【今日观点演进】")
        for n in narrative[-3:]:  # 最近3条
            lines.append(f"  {n['time']}: {n['summary']}")
    
    return "\n".join(lines) if lines else "今日尚未建立市场判断。"


def archive_daily_state(path: Path | None = None) -> Path | None:
    """收盘后将 daily_state 归档到历史目录。"""
    state_path = path or DEFAULT_STATE_PATH
    
    if not state_path.exists():
        return None
    
    try:
        with open(state_path, encoding="utf-8") as f:
            data = json.load(f)
        
        date_str = data.get("date", _today_str())
        archive_dir = state_path.parent / "daily_state_archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_path = archive_dir / f"daily_state_{date_str}.json"
        
        with open(archive_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        logger.info("Archived daily_state to %s", archive_path)
        return archive_path
    except Exception as e:
        logger.warning("Failed to archive daily_state: %s", e)
        return None
