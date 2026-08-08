"""机械真值标签测试（合成 K 线构造已知走势）。"""
from investment_engine.blindtest.truth import (
    STAGES, compute_features, label_day, label_series,
)


def _klines(closes, vols=None) -> list[dict]:
    vols = vols or [1000.0] * len(closes)
    return [
        {"date": f"2026-05-{i + 1:02d}", "open": c, "high": c * 1.01, "low": c * 0.99,
         "close": c, "volume": v, "turnover": None, "amplitude": None, "pct_change": None}
        for i, (c, v) in enumerate(zip(closes, vols))
    ]


class TestComputeFeatures:
    def test_insufficient_lookback_returns_none(self):
        klines = _klines([10.0] * 24)
        assert compute_features(klines, 23) is None

    def test_flat_market(self):
        klines = _klines([10.0] * 30)
        f = compute_features(klines, 29)
        assert abs(f["r20"]) < 1e-9
        assert 0.0 <= f["pos20"] <= 1.0
        assert abs(f["vol_trend"] - 1.0) < 1e-9

    def test_rally(self):
        closes = [10.0] * 24 + [10.0 + 0.1 * i for i in range(6)]  # 末 5 日连涨
        klines = _klines(closes)
        f = compute_features(klines, 29)
        assert f["r5"] > 0
        assert f["pos20"] > 0.8  # (10.5-9.9)/(10.605-9.9)≈0.851，high/low 含 ±1% 边际


class TestLabelDay:
    def test_panic_by_r20(self):
        assert label_day({"r20": -0.09, "r5": -0.01, "pos20": 0.5, "vol_trend": 1.0}) == "恐慌"

    def test_panic_by_volume_crash(self):
        assert label_day({"r20": -0.02, "r5": -0.05, "pos20": 0.5, "vol_trend": 1.6}) == "恐慌"

    def test_pullback(self):
        assert label_day({"r20": -0.04, "r5": -0.01, "pos20": 0.5, "vol_trend": 1.0}) == "调整"
        assert label_day({"r20": 0.01, "r5": 0.0, "pos20": 0.3, "vol_trend": 1.0}) == "调整"

    def test_uptrend(self):
        assert label_day({"r20": 0.05, "r5": 0.01, "pos20": 0.7, "vol_trend": 1.0}) == "主升"

    def test_rangebound_default(self):
        assert label_day({"r20": 0.01, "r5": 0.0, "pos20": 0.5, "vol_trend": 1.0}) == "震荡"

    def test_vol_trend_none_neutral(self):
        """量能缺失时量能条件不触发（r20=-0.02 不到调整线，落回震荡）。"""
        assert label_day({"r20": -0.02, "r5": -0.05, "pos20": 0.5, "vol_trend": None}) == "震荡"


class TestLabelSeries:
    def test_series_skips_lookback_prefix(self):
        klines = _klines([10.0] * 30)
        rows = label_series(klines)
        assert len(rows) == 30 - 24  # 前 24 日 lookback 不足
        assert rows[0]["date"] == "2026-05-25"
        assert all(r["label"] in STAGES for r in rows)
