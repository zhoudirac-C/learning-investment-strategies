from investment_engine.sentiment.thermometer import (
    compute_temperature, percentile_rank, volume_component)


def _bars(amounts, closes=None):
    closes = closes or [100.0] * len(amounts)
    return [{"date": f"2026-{i:04d}", "open": c, "high": c, "low": c,
             "close": c, "volume": 1.0, "amount": a}
            for i, (a, c) in enumerate(zip(amounts, closes))]


def test_percentile_rank_basic():
    assert percentile_rank([1, 2, 3, 4, 5], 5) == 100.0
    assert percentile_rank([1, 2, 3, 4, 5], 1) == 0.0
    assert 40 <= percentile_rank([1, 2, 3, 4, 5], 3) <= 60


def test_volume_component_cold():
    # 历史高量、当前地量 → 低分
    bars = _bars([100.0] * 245 + [5.0] * 5)
    assert volume_component(bars) <= 10


def test_volume_component_hot():
    bars = _bars([10.0] * 245 + [200.0] * 5)
    assert volume_component(bars) >= 90


def test_compute_temperature_zones():
    cold = compute_temperature(_bars([100.0] * 245 + [5.0] * 5))
    assert cold["zone"] == "cold"
    hot = compute_temperature(_bars([10.0] * 245 + [200.0] * 5),
                              board_stats={"retail_buy_ratio": 0.9, "board_hits_20d": 15})
    assert hot["zone"] == "hot"
    assert set(hot["components"]) >= {"volume", "pattern", "billboard"}


def test_compute_temperature_missing_optional_data():
    # 无龙虎榜/融资数据时权重自动归一化到可用分量，不报错
    r = compute_temperature(_bars([10.0] * 250))
    assert 0 <= r["score"] <= 100
    assert r["components"]["billboard"] is None
