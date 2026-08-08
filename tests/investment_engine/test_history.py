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
        """重建的 quote 必须符合生产 fetcher 契约（code=裸码 + secid 字段）。"""
        kline = _klines("603986", ["2026-07-03"], base=100.0)[0]
        q = quote_from_kline("603986.SH", "兆易创新", kline)
        assert q["code"] == "603986"        # 裸 6 位代码
        assert q["secid"] == "1.603986"     # 沪市 secid
        assert q["name"] == "兆易创新"
        assert q["latest"] == kline["close"]
        assert q["turnover_rate"] == 1.5

    def test_secid_market_prefix(self):
        kline = _klines("002371", ["2026-07-03"])[0]
        assert quote_from_kline("002371.SZ", "北方华创", kline)["secid"] == "0.002371"
        assert quote_from_kline("600519.SH", "贵州茅台", kline)["secid"] == "1.600519"

    def test_build_quote_snapshot(self):
        klines = _klines("002371", ["2026-07-03"])
        snapshot = build_quote_snapshot([quote_from_kline("002371.SZ", "北方华创", klines[0])])
        assert "quotes" in snapshot and len(snapshot["quotes"]) == 1
        assert snapshot["source"] == "kline_cache_backtest"


class TestSuffixedCodeCompat:
    """代码格式回归：pre_fetch 写入的是带后缀代码（'002371.SZ'），读取必须兼容。"""

    def setup_method(self):
        self.db_path = Path(tempfile.gettempdir()) / f"test_hist_suffix_{id(self)}.db"
        init_db(db_path=self.db_path)
        save_klines("002371.SZ", _klines("002371.SZ", ["2026-07-01", "2026-07-02"]), db_path=self.db_path)

    def teardown_method(self):
        self.db_path.unlink(missing_ok=True)

    def test_range_query_accepts_bare_and_suffixed(self):
        assert len(get_klines_range("002371", "2026-07-01", "2026-07-02", db_path=self.db_path)) == 2
        assert len(get_klines_range("002371.SZ", "2026-07-01", "2026-07-02", db_path=self.db_path)) == 2

    def test_coverage_keys_are_bare(self):
        cov = coverage(db_path=self.db_path)
        assert cov["002371"] == ("2026-07-01", "2026-07-02")
        assert "002371.SZ" not in cov


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

    def test_engine_alert_end_to_end(self, monkeypatch):
        """真实回归：价格进入 stock_pool 介入区间且条件凑齐时，引擎必须出信号。

        覆盖三个历史 bug：缓存带后缀代码的读取、quote code/secid 匹配。
        引擎内部 get_klines/get_ma 读默认 DB，这里 monkeypatch 掉以保证隔离。
        """
        from qing_investment import kline_cache
        from qing_investment.monitor.rules import BuySignalRuleEngine

        fake_klines = [
            {"date": "2026-07-01", "close": 10.0, "volume": 100},
            {"date": "2026-07-02", "close": 10.1, "volume": 200},
            {"date": "2026-07-03", "close": 10.2, "volume": 300},
        ]
        monkeypatch.setattr(
            kline_cache, "get_klines", lambda code, days=5, **kw: fake_klines
        )
        monkeypatch.setattr(
            kline_cache, "get_ma", lambda code, days=20, **kw: 9.0
        )

        kline = {"date": "2026-07-03", "open": 10.0, "high": 10.4, "low": 9.9,
                 "close": 10.2, "volume": 300, "turnover": 1.5,
                 "amplitude": 5.0, "pct_change": 1.0}
        snapshot = build_quote_snapshot([quote_from_kline("002371.SZ", "北方华创", kline)])
        config = {
            "watchlist": {"themes": []},
            "stock_pool": {"stocks": [
                {"code": "002371.SZ", "name": "北方华创",
                 "entry": {"primary_zone": [9.0, 11.0], "hard_stop": 8.5}},
            ]},
            "positions": {"accounts": []},
        }
        alerts = BuySignalRuleEngine().evaluate(config, snapshot)
        assert len(alerts) == 1
        assert alerts[0].stock_code == "002371.SZ"
        assert alerts[0].price == 10.2
