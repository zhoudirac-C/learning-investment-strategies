"""按 used_patterns 归因的 per-pattern 盲测指标（使用归因，不隔离单模式贡献）。"""
from __future__ import annotations

from investment_engine.blindtest.score import (
    direction_scores,
    stage_accuracy,
    stock_scores,
)


def group_by_pattern(results: list[dict]) -> dict[str, list[dict]]:
    """同日多模式共用时，当日归入每个模式；无 used_patterns 的日子不归因。"""
    grouped: dict[str, list[dict]] = {}
    for r in results:
        for pid in (r.get("result") or {}).get("used_patterns") or []:
            grouped.setdefault(pid, []).append(r)
    return grouped


def pattern_metrics(results: list[dict], *, truth: dict[str, str],
                    config_dir=None, db_path=None,
                    direction_scorer=None, stock_scorer=None) -> dict:
    """每个被使用模式的三指标 + 分环境段一致率，口径同 M1 基线。

    direction/stock scorer 可注入（测试用假 scorer，真实跑用 score.py）。
    """
    dir_score = direction_scorer or (
        lambda rs: direction_scores(rs, config_dir=config_dir, db_path=db_path))
    stk_score = stock_scorer or (
        lambda rs: stock_scores(rs, db_path=db_path))
    metrics = {}
    for pid, rs in sorted(group_by_pattern(results).items()):
        stage = stage_accuracy(rs, truth)
        direction = dir_score(rs)
        stock = stk_score(rs)
        metrics[pid] = {
            "days_used": len(rs),
            "stage": {"rate": stage["accuracy"], "n": stage["samples"]},
            "direction": {"rate": direction["hit_rate"], "n": direction["samples"]},
            "stock": {"rate": stock["hit_rate"], "n": stock["samples"]},
            "regime": {label: {"rate": b["accuracy"], "n": b["samples"]}
                       for label, b in stage["by_label"].items()},
        }
    return metrics
