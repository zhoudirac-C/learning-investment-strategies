"""推理模式的生产准入与输出投影。"""

from __future__ import annotations

import math


def is_pattern_production_eligible(pattern: dict) -> bool:
    """qing 需有 [0,1] 内的有限数值历史命中率；其他学派保留既有召回资格。"""
    if pattern.get("school", "qing") != "qing":
        return True
    validation = pattern.get("validation")
    if not isinstance(validation, dict):
        return False
    hit_rate = validation.get("historical_hit_rate")
    return (
        isinstance(hit_rate, (int, float))
        and not isinstance(hit_rate, bool)
        and math.isfinite(hit_rate)
        and 0 <= hit_rate <= 1
    )


def filter_production_patterns(patterns: list[dict]) -> list[dict]:
    """过滤不得进入生产召回的 pattern，不改变原对象。"""
    return [pattern for pattern in patterns if is_pattern_production_eligible(pattern)]


def project_pattern(pattern: dict) -> dict:
    """生成召回结果公共字段，并保留学派归属与原始验证信息。"""
    return {
        "pattern_id": pattern.get("pattern_id", ""),
        "name": pattern.get("name", ""),
        "description": pattern.get("description", ""),
        "reasoning_chain": pattern.get("reasoning_chain", []),
        "risk_factors": pattern.get("risk_factors", []),
        "confidence_indicators": pattern.get("confidence_indicators", []),
        "school": pattern.get("school", "qing"),
        "validation": pattern.get("validation", {}),
    }
