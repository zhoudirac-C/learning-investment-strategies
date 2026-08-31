"""chain.yaml 状态更新（T13）。

仅在 LLM 判定阶段推进/回退时回写；护栏：一次最多走一格（防幻觉跳变）。
人工域字段（last_verified、timing.next_trigger）不动。
"""
from __future__ import annotations

from investment_engine.industry_chain.schema import CONFIDENCE_LEVELS, STAGE_LEVELS


def apply_chain_update(chain: dict, result: dict, *, today: str) -> dict | None:
    """按 LLM 分析结果就地更新 chain dict，返回变更记录；无变化返回 None。

    调用方负责用 store.save_chain 落盘（schema 强校验）。
    """
    step5 = result.get("step5_recommendation") or {}
    stage_change = step5.get("stage_change")
    if stage_change not in ("forward", "backward"):
        return None

    old_stage = chain.get("current_stage") or "阶段0-观察"
    if old_stage not in STAGE_LEVELS:
        old_stage = "阶段0-观察"
    old_idx = STAGE_LEVELS.index(old_stage)
    delta = 1 if stage_change == "forward" else -1
    new_idx = min(max(old_idx + delta, 0), len(STAGE_LEVELS) - 1)
    if new_idx == old_idx:
        return None

    llm_new_stage = step5.get("new_stage")
    clamped = llm_new_stage in STAGE_LEVELS and llm_new_stage != STAGE_LEVELS[new_idx]
    new_stage = STAGE_LEVELS[new_idx]

    chain["current_stage"] = new_stage
    step1 = result.get("step1_verification") or {}
    if step1.get("confidence") in CONFIDENCE_LEVELS:
        chain["stage_confidence"] = step1["confidence"]
    summary = str(result.get("summary") or "").strip()
    if summary:
        chain["stage_evidence"] = f"{today} 跟踪更新：{summary}"

    timing = chain.get("timing")
    if not isinstance(timing, dict):
        timing = {}
        chain["timing"] = timing
    if step5.get("timing"):
        timing["current_recommendation"] = step5["timing"]

    history = chain.setdefault("history", [])
    history.append({
        "date": today,
        "stage": new_stage,
        "action": step5.get("action") or "",
        "result": "待验证",
    })

    return {
        "chain_id": chain.get("chain_id"),
        "chain_name": chain.get("name"),
        "old_stage": old_stage,
        "new_stage": new_stage,
        "stage_change": stage_change,
        "clamped": clamped,
        "llm_new_stage": llm_new_stage,
        "verdict": result.get("verdict"),
        "confidence": chain.get("stage_confidence"),
        "action": step5.get("action") or "",
        "timing": step5.get("timing") or "",
        "summary": summary,
    }
