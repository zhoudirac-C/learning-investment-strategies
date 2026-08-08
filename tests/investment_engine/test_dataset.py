"""每日数据包构建与防泄漏测试。"""
import tempfile
from pathlib import Path

import pytest

from qing_investment.kline_cache import init_db, save_klines
from investment_engine.blindtest.dataset import (
    LeakageError, assert_no_leakage, build_daily_pack, pack_to_prompt, trading_days,
)


def _klines(code: str, closes: list[float]) -> list[dict]:
    return [
        {"code": code, "date": f"2026-06-{i + 1:02d}", "open": c, "high": c * 1.02,
         "low": c * 0.98, "close": c, "volume": 1000 + i * 10,
         "turnover": 1.5, "amplitude": 4.0, "pct_change": 0.5}
        for i, c in enumerate(closes)
    ]


class TestTradingDays:
    def setup_method(self):
        self.db = Path(tempfile.gettempdir()) / f"test_ds_{id(self)}.db"
        init_db(db_path=self.db)
        save_klines("002371", _klines("002371", [10.0] * 30), db_path=self.db)

    def teardown_method(self):
        self.db.unlink(missing_ok=True)

    def test_days_from_cache(self):
        days = trading_days("2026-06-01", "2026-06-30", db_path=self.db)
        assert days[0] == "2026-06-01" and len(days) == 30


class TestAssertNoLeakage:
    def test_future_date_rejected(self):
        with pytest.raises(LeakageError, match="2026-08-01"):
            assert_no_leakage("截至 2026-07-01 数据。参考 2026-08-01 走势", "2026-07-01")

    def test_up_words_rejected(self):
        for w in ("UP", "青枫浦", "博主"):
            with pytest.raises(LeakageError):
                assert_no_leakage(f"某 {w} 观点", "2026-07-01")

    def test_clean_text_passes(self):
        assert_no_leakage("2026-07-01 收盘综述：量能 1.2 万亿", "2026-07-01")


class TestBuildDailyPack:
    def setup_method(self):
        self.db = Path(tempfile.gettempdir()) / f"test_ds2_{id(self)}.db"
        init_db(db_path=self.db)
        save_klines("002371.SZ", _klines("002371.SZ", [10.0 + i * 0.1 for i in range(30)]), db_path=self.db)
        save_klines("IDX000300", _klines("IDX000300", [4000.0 + i for i in range(30)]), db_path=self.db)

    def teardown_method(self):
        self.db.unlink(missing_ok=True)

    def test_pack_truncates_at_day(self):
        pack = build_daily_pack("2026-06-15", config_dir=Path("config/stock_monitor"), db_path=self.db)
        assert pack["date"] == "2026-06-15"
        idx = pack["index"]["IDX000300"]
        assert idx[-1]["d"] == "2026-06-15"  # 数据截至当日，无未来
        assert len(idx) == 15

    def test_pack_stock_entry_fields(self):
        pack = build_daily_pack("2026-06-15", config_dir=Path("config/stock_monitor"), db_path=self.db)
        s = next(x for x in pack["stocks"] if x["code"] == "002371")
        assert set(s) == {"code", "name", "direction", "close", "pct", "turnover", "pos20"}

    def test_direction_pool_has_no_time_varying_fields(self):
        pack = build_daily_pack("2026-06-15", config_dir=Path("config/stock_monitor"), db_path=self.db)
        for d in pack["directions"]:
            assert set(d) == {"id", "name"}  # current_stage 等时变字段不得进入

    def test_prompt_passes_leakage_assertion(self):
        pack = build_daily_pack("2026-06-15", config_dir=Path("config/stock_monitor"), db_path=self.db)
        text = pack_to_prompt(pack)
        assert_no_leakage(text, "2026-06-15")  # 自身产出必须过自家断言
