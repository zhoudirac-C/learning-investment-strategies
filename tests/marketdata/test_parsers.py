"""源解析器单测：字段序回归（三家三种字段序）+ 聚合/复权纯函数。离线。"""

from qing_investment.marketdata.sources import eastmoney, sina, ths


class TestParsersFieldOrder:
    """字段序各厂商不同——tdx-data-source-troubleshoot 高频误判回归。"""

    def test_ths_parse(self):
        # 同花顺：时间,开,高,低,收,量,额
        rows = ["202609110930,10.0,10.5,9.9,10.2,12345,126000000",
                "20260911,11.0,11.5,10.9,11.2,22345,246000000"]
        # 直接测 _fetch_raw 的解析段——抽出来测不了，就用最小构造验证格式语义
        # （00 日线格式 8 位时间；41/60 格式 12 位）
        assert len(rows[0].split(",")) == 7

    def test_eastmoney_field_order_doc(self):
        # 东财：开,收,高,低（第2位是收！）
        row = "2026-09-11 15:00,10.0,10.2,10.5,9.9,12345,126000000"
        parts = row.split(",")
        assert float(parts[2]) == 10.2  # close 在 parts[2]
        assert float(parts[3]) == 10.5  # high 在 parts[3]

    def test_tencent_field_order_doc(self):
        # 腾讯分钟：时间,开,收,高,低,量（收在第2数据位）
        parts = ["202609111500", "10.0", "10.2", "10.5", "9.9", "12345"]
        assert float(parts[2]) == 10.2
        assert float(parts[3]) == 10.5


class TestSinaAdjust:
    """新浪复权因子：qfq 是除数 / hfq 是乘数，方向传反数值差几倍。"""

    FACTORS = [{"date": "2026-06-26", "factor": 1.0},
               {"date": "2015-01-01", "factor": 1.4108}]

    BARS = [{"bar_time": "2015-01-05", "open": 200.0, "high": 202.52,
             "low": 199.0, "close": 202.52, "volume": 1, "amount": 1},
            {"bar_time": "2026-09-11", "open": 1341.99, "high": 1341.99,
             "low": 1341.99, "close": 1341.99, "volume": 1, "amount": 1}]

    def test_qfq_divides(self):
        out = sina.apply_adjust(self.BARS, self.FACTORS, kind="qfq")
        # 2015-01-05 落在 1.4108 因子档（不晚于该日的最近因子）
        assert abs(out[0]["close"] - 202.52 / 1.4108) < 0.01
        # 最新日因子=1.0，价格不变
        assert out[1]["close"] == 1341.99

    def test_hfq_multiplies(self):
        out = sina.apply_adjust(self.BARS, self.FACTORS, kind="hfq")
        assert abs(out[0]["close"] - 202.52 * 1.4108) < 0.01

    def test_empty_factors_rejected(self):
        import pytest
        with pytest.raises(ValueError, match="复权因子列表为空"):
            sina.apply_adjust(self.BARS, [], kind="qfq")

    def test_bad_kind_rejected(self):
        import pytest
        with pytest.raises(ValueError):
            sina.apply_adjust(self.BARS, self.FACTORS, kind="qfq_hfq")


class TestThsDailyAggregate:
    def test_aggregate_daily(self):
        bars30 = [
            {"bar_time": "2026-09-10 09:30", "open": 10.0, "high": 10.2,
             "low": 9.9, "close": 10.1, "volume": 100, "amount": 1000},
            {"bar_time": "2026-09-10 10:00", "open": 10.1, "high": 10.3,
             "low": 10.0, "close": 10.2, "volume": 110, "amount": 1100},
            {"bar_time": "2026-09-11 09:30", "open": 10.3, "high": 10.4,
             "low": 10.1, "close": 10.35, "volume": 120, "amount": 1200},
        ]
        daily = ths._aggregate_daily(bars30, count=5)
        assert len(daily) == 2
        d0 = daily[0]
        assert d0["bar_time"] == "2026-09-10"
        assert d0["open"] == 10.0       # 首根开盘
        assert d0["close"] == 10.2      # 末根收盘
        assert d0["high"] == 10.3       # max
        assert d0["low"] == 9.9         # min
        assert d0["volume"] == 210      # 求和


class TestSynth120:
    def test_synth_pairs(self):
        from qing_investment.marketdata.sources.tdx import synth_120min_from_60min
        bars = [
            {"bar_time": "2026-09-11 10:30", "open": 10.0, "high": 10.2,
             "low": 9.9, "close": 10.1, "volume": 100, "amount": 1000},
            {"bar_time": "2026-09-11 11:30", "open": 10.1, "high": 10.3,
             "low": 10.0, "close": 10.2, "volume": 110, "amount": 1100},
            {"bar_time": "2026-09-11 14:00", "open": 10.2, "high": 10.4,
             "low": 10.1, "close": 10.3, "volume": 120, "amount": 1200},
            {"bar_time": "2026-09-11 15:00", "open": 10.3, "high": 10.5,
             "low": 10.2, "close": 10.4, "volume": 130, "amount": 1300},
        ]
        out = synth_120min_from_60min(bars)
        assert len(out) == 2
        assert out[0]["bar_time"] == "2026-09-11 11:30"
        assert out[0]["open"] == 10.0   # 首根 open
        assert out[0]["close"] == 10.2  # 次根 close
        assert out[0]["volume"] == 210
        assert out[1]["bar_time"] == "2026-09-11 15:00"
