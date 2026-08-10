"""render_report 必须带定性说明：执行层规则回测，非方法论有效证据。"""
from scripts.backtest_buy_signals import render_report


def _result() -> dict:
    return {
        "params": {"start": "2026-04-27", "end": "2026-08-07",
                   "horizons": (5,), "universe_size": 2, "trading_days": 3},
        "signals": [],
        "stats": {"5": {"samples": 1, "hits": 1, "hit_rate": 1.0,
                        "avg_return": 0.01}},
        "skipped_no_data": {},
    }


def test_report_contains_caveats():
    md = render_report(_result())
    assert "# 买入信号回测报告" in md
    assert "执行层规则" in md
    assert "MarketGate" in md and "SectorGate" in md
    assert "前视" in md
    assert "不能作为方法论有效的证据" in md
