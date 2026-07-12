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
        # 清理过期失效机会
        if isinstance(data.get("active_opportunities"), list):
            data["active_opportunities"] = _cleanup_opportunities(data["active_opportunities"])

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


def normalize_code(code: str) -> str:
    """统一股票代码格式为 6位数字.SZ/.SH。"""
    if not code:
        return ""
    text = str(code).strip().upper()
    # 去掉已有的 .SZ/.SH 后缀
    if text.endswith(".SZ") or text.endswith(".SH"):
        text = text[:-3]
    # 去掉可能的前缀 sh/sz
    text = text.replace("SH", "").replace("SZ", "")
    # 保留最后 6 位数字
    digits = "".join(c for c in text if c.isdigit())
    if len(digits) >= 6:
        digits = digits[-6:]
    market = "SH" if digits.startswith("6") else "SZ"
    return f"{digits}.{market}"


def update_field(
    state: dict,
    source_tag: str,
    key: str,
    value: Any,
) -> dict:
    """字段级更新，并记录最后修改来源。

    Args:
        state: daily_state 字典
        source_tag: 修改来源标识，如 "market_summary:open_auction"
        key: 字段名
        value: 字段值
    """
    state.setdefault("_field_sources", {})
    state["_field_sources"][key] = source_tag
    state[key] = value
    return state


def _cleanup_opportunities(opportunities: list[dict]) -> list[dict]:
    """清理失效超过 3 天的机会。"""
    cutoff = datetime.now() - timedelta(days=3)
    kept: list[dict] = []
    for opp in opportunities:
        if opp.get("status") == "失效":
            last_checked = opp.get("last_checked_at") or opp.get("updated_at")
            if last_checked:
                try:
                    last_dt = datetime.fromisoformat(last_checked)
                    if last_dt < cutoff:
                        continue
                except ValueError:
                    pass
        kept.append(opp)
    return kept


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
    entry_zone: list | tuple | None = None,
    stop_loss: float | str | None = None,
    source_node: str = "unknown",
) -> dict:
    """添加或更新活跃机会。

    统一 schema：
    - code: 6位数字.SZ/.SH
    - first_seen_at / last_checked_at: 首次发现/最后检查时间
    - entry_zone: 介入区间 [low, high]
    - stop_loss: 止损位
    - source_node: 产生该机会的节点
    """
    opportunities = state.get("active_opportunities", [])
    code = normalize_code(code)
    now = datetime.now().isoformat()

    # 查找是否已存在（统一 code 后比较）
    existing = None
    for i, opp in enumerate(opportunities):
        if normalize_code(opp.get("code", "")) == code:
            existing = i
            break

    new_opp = {
        "stock": stock,
        "code": code,
        "pattern": pattern,
        "trigger": trigger,
        "status": status,
        "upside": str(upside) if upside is not None else "",
        "downside": str(downside) if downside is not None else "",
        "ratio": str(ratio) if ratio is not None else "",
        "entry_zone": list(entry_zone) if entry_zone else [],
        "stop_loss": stop_loss,
        "last_checked_at": now,
        "source_node": source_node,
    }

    if existing is not None:
        old_opp = opportunities[existing]
        new_opp["first_seen_at"] = old_opp.get("first_seen_at", now)
        # 若新值未提供，保留旧值
        if not new_opp["entry_zone"]:
            new_opp["entry_zone"] = old_opp.get("entry_zone", [])
        if new_opp["stop_loss"] is None:
            new_opp["stop_loss"] = old_opp.get("stop_loss")
        # 保留旧 opp 中的扩展字段
        for k, v in old_opp.items():
            if k not in new_opp:
                new_opp[k] = v
        opportunities[existing] = new_opp
    else:
        new_opp["first_seen_at"] = now
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


def _price_bucket(price: float, bucket_size_pct: float = 1.0) -> str:
    """计算价格分桶键（用于去重）。

    bucket_size_pct: 分桶大小百分比，默认 1.0%（如 30.0 元 → 桶大小 0.3 元）
    """
    if price <= 0:
        return "0"
    bucket = round(price * bucket_size_pct / 100, 2)
    bucket_idx = int(price / bucket) if bucket > 0 else 0
    return f"{bucket_idx * bucket:.2f}-{(bucket_idx + 1) * bucket:.2f}"


def sync_buy_candidates(
    state: dict,
    candidates: list[dict],
    now: datetime | None = None,
) -> dict:
    """同步买入信号候选到 daily_state 的 active_opportunities。

    - 新候选：若不存在或已失效，添加为"候选"
    - 已有候选：若仍在列表中，更新价格和时间戳
    - 失效候选：若之前是候选但现在不在列表中，标记为"失效"

    candidates: list[dict] 格式见 stock_monitor.py 中的 buy_signal_candidates
    """
    if now is None:
        now = datetime.now()
    now_iso = now.isoformat()

    opportunities = state.get("active_opportunities", [])
    candidate_codes = {normalize_code(c["stock_code"]) for c in candidates}

    # 1. 更新已有机会的状态
    for opp in opportunities:
        code = normalize_code(opp.get("code", ""))
        if code in candidate_codes:
            # 仍在候选列表中 → 更新信息
            for c in candidates:
                if normalize_code(c["stock_code"]) == code:
                    opp["status"] = "候选"
                    opp["price"] = c.get("price")
                    opp["price_bucket"] = _price_bucket(c.get("price", 0))
                    opp["entry_zone"] = c.get("entry_zone")
                    opp["stop_loss"] = c.get("stop_loss")
                    opp["matched_conditions"] = c.get("matched_conditions", [])
                    opp["updated_at"] = now_iso
                    opp["last_checked_at"] = now_iso
                    break
        else:
            # 不在候选列表中 → 如果之前是候选，标记为失效
            if opp.get("status") == "候选":
                opp["status"] = "失效"
                opp["updated_at"] = now_iso
                opp["last_checked_at"] = now_iso

    # 2. 添加新候选
    existing_codes = {normalize_code(o.get("code", "")) for o in opportunities}
    for c in candidates:
        code = normalize_code(c["stock_code"])
        if code not in existing_codes:
            opportunities.append({
                "stock": c.get("stock_name", ""),
                "code": code,
                "pattern": "买入信号候选",
                "trigger": f"价格{c.get('price')} 进入区间 {c.get('entry_zone')}",
                "status": "候选",
                "upside": str(c.get("odds_analysis", {}).get("upside_pct", "")),
                "downside": str(c.get("odds_analysis", {}).get("downside_pct", "")),
                "ratio": str(c.get("odds_analysis", {}).get("odds_ratio", "")),
                "price": c.get("price"),
                "price_bucket": _price_bucket(c.get("price", 0)),
                "entry_zone": c.get("entry_zone"),
                "stop_loss": c.get("stop_loss"),
                "matched_conditions": c.get("matched_conditions", []),
                "updated_at": now_iso,
                "first_seen_at": now_iso,
                "last_checked_at": now_iso,
                "last_agent_check": None,
                "source_node": "buy_signal_candidate",
            })

    state["active_opportunities"] = opportunities
    return state


def should_trigger_agent_for_candidate(
    state: dict,
    code: str,
    price: float,
    now: datetime | None = None,
    cooldown_hours: float = 4.0,
) -> bool:
    """判断是否应该为该候选触发 Agent 分析（价格分桶 + 冷却窗口去重）。

    规则：
    1. 同一股票同一价格桶内，4 小时内不重复触发
    2. 价格桶变化 或 冷却期已过 → 允许触发
    """
    if now is None:
        now = datetime.now()

    opportunities = state.get("active_opportunities", [])
    bucket = _price_bucket(price)
    cutoff = now - timedelta(hours=cooldown_hours)

    for opp in opportunities:
        if opp.get("code") != code:
            continue
        # 检查是否是同一价格桶且冷却期内
        if opp.get("price_bucket") == bucket:
            last_check = opp.get("last_agent_check")
            if last_check:
                try:
                    last_dt = datetime.fromisoformat(last_check)
                    if last_dt > cutoff:
                        return False  # 冷却期内，同一价格桶，不触发
                except ValueError:
                    pass
        # 价格桶不同 → 允许触发（价格发生了显著变化）
        return True

    # 未找到该股票的机会 → 允许触发（新候选）
    return True


def mark_candidate_checked(state: dict, code: str, now: datetime | None = None) -> dict:
    """标记候选已被 Agent 检查过（更新 last_agent_check 时间戳）。"""
    if now is None:
        now = datetime.now()

    for opp in state.get("active_opportunities", []):
        if opp.get("code") == code:
            opp["last_agent_check"] = now.isoformat()
            opp["updated_at"] = now.isoformat()
            break

    return state


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
