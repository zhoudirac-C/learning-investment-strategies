"""历史区间数据访问测试（db_path 注入隔离，同 test_kline_cache 惯例）。"""
import tempfile
from pathlib import Path

from qing_investment.kline_cache import init_db, save_klines
from investment_engine.backtest.history import (
    build_quote_snapshot, coverage, get_klines_range, list_trading_days, quote_from_kline,
)


def _klines(code: str, dates: list[str], base: float = 10.0) -> list[dict]:
    return [
        {"code": code, "date": d, "open": base, "high": base + 0.5, "low": base - 0.5,
         "close": base + i * 0.1, "volume": 1000, "turnover": 1.5,
         "amplitude": 5.0, "pct_change": 1.0}
        for i, d in enumerate(dates)
    ]


class TestHistory:
    def setup_method(self):
        self.db_path = Path(tempfile.gettempdir()) / f"test_hist_{id(self)}.db"
        init_db(db_path=self.db_path)
        save_klines("002371", _klines("002371", ["2026-07-01", "2026-07-02", "2026-07-03"]), db_path=self.db_path)
        save_klines("603986", _klines("603986", ["2026-07-02", "2026-07-03"], base=100.0), db_path=self.db_path)

    def teardown_method(self):
        self.db_path.unlink(missing_ok=True)

    def test_get_klines_range(self):
        rows = get_klines_range("002371", "2026-07-01", "2026-07-02", db_path=self.db_path)
        assert [r["date"] for r in rows] == ["2026-07-01", "2026-07-02"]
        assert rows[0]["close"] == 10.0

    def test_get_klines_range_empty(self):
        assert get_klines_range("999999", "2026-07-01", "2026-07-02", db_path=self.db_path) == []

    def test_list_trading_days_uses_cache_presence(self):
        """交易日由缓存里实际存在的日期决定，不需要交易日历。"""
        days = list_trading_days("2026-07-01", "2026-07-31", db_path=self.db_path)
        assert days == ["2026-07-01", "2026-07-02", "2026-07-03"]

    def test_coverage(self):
        cov = coverage(db_path=self.db_path)
        assert cov["002371"] == ("2026-07-01", "2026-07-03")
        assert cov["603986"] == ("2026-07-02", "2026-07-03")

    def test_quote_from_kline_matches_rule_engine_contract(self):
        """重建的 quote 必须符合 test_e2e mock_quote_snapshot 的字段契约。"""
        kline = _klines("603986", ["2026-07-03"], base=100.0)[0]
        q = quote_from_kline("603986.SH", "兆易创新", kline)
        assert q["code"] == "1.603986"      # 沪市 secid
        assert q["name"] == "兆易创新"
        assert q["latest"] == kline["close"]
        assert q["turnover_rate"] == 1.5

    def test_secid_market_prefix(self):
        kline = _klines("002371", ["2026-07-03"])[0]
        assert quote_from_kline("002371.SZ", "北方华创", kline)["code"] == "0.002371"
        assert quote_from_kline("600519.SH", "贵州茅台", kline)["code"] == "1.600519"

    def test_build_quote_snapshot(self):
        klines = _klines("002371", ["2026-07-03"])
        snapshot = build_quote_snapshot([quote_from_kline("002371.SZ", "北方华创", klines[0])])
        assert "quotes" in snapshot and len(snapshot["quotes"]) == 1
        assert snapshot["source"] == "kline_cache_backtest"


class TestSnapshotFeedsRuleEngine:
    """重建快照必须能被真实 BuySignalRuleEngine 消费（行为测试，驱动字段补全）。"""

    def setup_method(self):
        self.db_path = Path(tempfile.gettempdir()) / f"test_hist_eng_{id(self)}.db"
        init_db(db_path=self.db_path)

    def teardown_method(self):
        self.db_path.unlink(missing_ok=True)

    def test_snapshot_accepted_by_engine(self):
        from qing_investment.monitor.rules import BuySignalRuleEngine

        save_klines("002371", _klines("002371", ["2026-07-03"]), db_path=self.db_path)
        kline = get_klines_range("002371", "2026-07-03", "2026-07-03", db_path=self.db_path)[0]
        snapshot = build_quote_snapshot([quote_from_kline("002371.SZ", "北方华创", kline)])
        alerts = BuySignalRuleEngine().evaluate(
            {"watchlist": {"stocks": []}, "stock_pool": {"stocks": []}, "positions": {"accounts": []}},
            snapshot,
        )
        assert isinstance(alerts, list)  # 不报错、类型正确即通过
