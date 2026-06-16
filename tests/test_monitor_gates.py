from __future__ import annotations

from qing_investment.monitor.gates import MarketGate, SectorGate, GateResult


def test_market_gate_passes_with_good_data():
    gate = MarketGate()
    config = {
        "strategy_pack": {
            "market_gate_rules": {
                "index_checks": [{"index": "全A指数", "condition": "not_close_below", "level": 6000}],
                "volume_checks": [{"metric": "total_amount", "condition": "greater_than", "threshold": 2_500_000_000_000}],
            }
        }
    }
    snapshot = {
        "quotes": [
            {"label": "全A指数", "latest": 6500, "pct_change": 1.2},
            {"label": "上证指数", "latest": 4000, "pct_change": 0.8, "amount": 1_5000_0000_000},
            {"label": "深证成指", "latest": 11000, "pct_change": 1.0, "amount": 1_5000_0000_000},
        ]
    }
    result = gate.evaluate(config, snapshot)
    assert isinstance(result, GateResult)
    assert result.passed is True
    assert result.bias == "可操作"


def test_market_gate_fails_when_index_breaks():
    gate = MarketGate()
    config = {
        "strategy_pack": {
            "market_gate_rules": {
                "index_checks": [{"index": "全A指数", "condition": "not_close_below", "level": 7000}],
            }
        }
    }
    snapshot = {"quotes": [{"label": "全A指数", "latest": 6500, "pct_change": -4.0}]}
    result = gate.evaluate(config, snapshot)
    assert result.passed is False
    assert result.checks["全A非破位"] is False


def test_sector_gate_skips_first_pump():
    gate = SectorGate()
    direction = {"current_stage": "first_pump"}
    result = gate.evaluate(direction)
    assert result.passed is False
    assert "跳过" in result.reason


def test_sector_gate_passes_on_diverging():
    gate = SectorGate()
    direction = {"current_stage": "diverging"}
    result = gate.evaluate(direction)
    assert result.passed is True
