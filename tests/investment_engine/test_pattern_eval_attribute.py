"""attribute：按 used_patterns 分组与 per-pattern 指标。"""

from investment_engine.pattern_eval.attribute import group_by_pattern, pattern_metrics


def _row(day, stage, patterns):
    return {"date": day, "ok": True,
            "result": {"market_stage": stage, "directions": [],
                       "used_patterns": patterns}}


def test_group_by_pattern_multi_attribution():
    results = [
        _row("2026-08-03", "震荡", ["sector_rotation", "mainline_identification"]),
        _row("2026-08-04", "震荡", ["sector_rotation"]),
        _row("2026-08-05", "震荡", []),               # 空列表不归因
        {"date": "2026-08-06", "ok": True, "result": {"market_stage": "震荡"}},  # 缺字段不归因
    ]
    grouped = group_by_pattern(results)
    assert set(grouped) == {"sector_rotation", "mainline_identification"}
    assert len(grouped["sector_rotation"]) == 2
    assert len(grouped["mainline_identification"]) == 1


def test_pattern_metrics_uses_scorers():
    results = [
        _row("2026-08-03", "震荡", ["sector_rotation"]),
        _row("2026-08-04", "调整", ["sector_rotation"]),
        _row("2026-08-05", "震荡", ["upstream_cycle"]),
    ]
    truth = {"2026-08-03": "震荡", "2026-08-04": "震荡", "2026-08-05": "调整"}

    def fake_direction(rs):
        return {"samples": len(rs) * 2, "hits": len(rs), "hit_rate": 0.5, "details": []}

    def fake_stock(rs):
        return {"samples": len(rs), "hits": 0, "hit_rate": 0.0, "details": []}

    metrics = pattern_metrics(results, truth=truth,
                              direction_scorer=fake_direction, stock_scorer=fake_stock)
    sr = metrics["sector_rotation"]
    assert sr["days_used"] == 2
    # 08-03 预测震荡=真值命中；08-04 预测调整≠震荡 → 1/2
    assert sr["stage"] == {"rate": 0.5, "n": 2}
    assert sr["direction"] == {"rate": 0.5, "n": 4}
    assert sr["stock"] == {"rate": 0.0, "n": 2}
    assert sr["regime"] == {"震荡": {"rate": 0.5, "n": 2}}
    uc = metrics["upstream_cycle"]
    assert uc["stage"] == {"rate": 0.0, "n": 1}   # 预测震荡≠调整
