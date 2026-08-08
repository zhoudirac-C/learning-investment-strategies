"""命中率统计测试。"""
from investment_engine.backtest.hit_rate import forward_return, summarize


def _klines(closes: list[float]) -> list[dict]:
    return [
        {"date": f"2026-07-{i + 1:02d}", "close": c, "open": c, "high": c, "low": c,
         "volume": 100, "turnover": 1.0, "amplitude": 1.0, "pct_change": 0.0}
        for i, c in enumerate(closes)
    ]


class TestForwardReturn:
    def test_basic(self):
        klines = _klines([10.0, 10.5, 11.0, 11.5, 12.0, 12.5])
        assert forward_return(klines, "2026-07-01", 5) == 12.5 / 10.0 - 1.0

    def test_insufficient_data_returns_none(self):
        klines = _klines([10.0, 10.5])
        assert forward_return(klines, "2026-07-01", 5) is None

    def test_unknown_date_returns_none(self):
        klines = _klines([10.0])
        assert forward_return(klines, "2026-08-01", 5) is None


class TestSummarize:
    def test_hit_rate_and_avg(self):
        records = [
            {"code": "a", "date": "d1", "returns": {5: 0.10, 10: 0.20}},
            {"code": "b", "date": "d1", "returns": {5: -0.05, 10: 0.05}},
            {"code": "c", "date": "d2", "returns": {5: 0.02, 10: None}},  # 10日数据不足
        ]
        stats = summarize(records, horizons=(5, 10))
        assert stats[5]["samples"] == 3
        assert stats[5]["hits"] == 2
        assert abs(stats[5]["hit_rate"] - 2 / 3) < 1e-9
        assert abs(stats[5]["avg_return"] - (0.10 - 0.05 + 0.02) / 3) < 1e-9
        assert stats[10]["samples"] == 2  # None 不计入样本

    def test_empty_records(self):
        stats = summarize([], horizons=(5,))
        assert stats[5]["samples"] == 0
        assert stats[5]["hit_rate"] is None
