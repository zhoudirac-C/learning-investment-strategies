"""M6-1 数据接入：chan_bars SQLite 存储与 Bar 适配测试。

全部使用 tmp_path 独立库，不触网、不碰真实 infra/data。
口径依据：docs/design/chanlun-m6-strategy-backtest.md §4.3/§4.4。
"""
from __future__ import annotations

import sqlite3

from chan_engine.data import store
from chan_engine.spec.model import Bar

ROWS = [
    {"date": "2026-08-24", "open": 10.0, "high": 10.4, "low": 9.9,
     "close": 10.1, "volume": 100.0, "amount": 1010.0},
    {"date": "2026-08-25", "open": 10.1, "high": 10.3, "low": 10.0,
     "close": 10.2, "volume": 110.0, "amount": 1122.0},
    {"date": "2026-08-26", "open": 10.2, "high": 10.6, "low": 10.1,
     "close": 10.5, "volume": 120.0, "amount": 1260.0},
]


def _db(tmp_path):
    db = tmp_path / "chan_bars.db"
    store.init_db(db)
    return db


class TestSaveAndLoad:
    def test_roundtrip_date_ascending(self, tmp_path):
        db = _db(tmp_path)
        store.save_daily("600519", list(reversed(ROWS)), source="baostock", db_path=db)
        rows = store.load_daily("600519", db_path=db)
        assert [r["trade_date"] for r in rows] == [r["date"] for r in ROWS]
        assert rows[0]["close"] == 10.1
        assert rows[0]["source"] == "baostock"
        assert rows[0]["adjust"] == "qfq"

    def test_idempotent_no_duplicates(self, tmp_path):
        """INSERT OR REPLACE 幂等：同区间重拉行数不变（§4.3）。"""
        db = _db(tmp_path)
        store.save_daily("600519", ROWS, source="baostock", db_path=db)
        store.save_daily("600519", ROWS, source="baostock", db_path=db)
        with sqlite3.connect(str(db)) as conn:
            n = conn.execute("SELECT COUNT(*) FROM daily_bars").fetchone()[0]
        assert n == len(ROWS)

    def test_upsert_updates_value(self, tmp_path):
        db = _db(tmp_path)
        store.save_daily("600519", ROWS, source="baostock", db_path=db)
        fixed = [dict(ROWS[0], close=99.9)]
        store.save_daily("600519", fixed, source="baostock", db_path=db)
        rows = store.load_daily("600519", db_path=db)
        assert len(rows) == len(ROWS)
        assert rows[0]["close"] == 99.9

    def test_adjust_isolation(self, tmp_path):
        """同一 code 不同 adjust 口径分行存储（§4.3 预留 raw）。"""
        db = _db(tmp_path)
        store.save_daily("600519", ROWS, source="baostock", db_path=db)
        store.save_daily("600519", ROWS[:1], source="baostock", adjust="raw", db_path=db)
        assert len(store.load_daily("600519", adjust="qfq", db_path=db)) == 3
        assert len(store.load_daily("600519", adjust="raw", db_path=db)) == 1

    def test_range_filter_inclusive(self, tmp_path):
        db = _db(tmp_path)
        store.save_daily("600519", ROWS, source="baostock", db_path=db)
        rows = store.load_daily("600519", start="2026-08-25", end="2026-08-26", db_path=db)
        assert [r["trade_date"] for r in rows] == ["2026-08-25", "2026-08-26"]

    def test_empty_load(self, tmp_path):
        db = _db(tmp_path)
        assert store.load_daily("999999", db_path=db) == []
        assert store.load_bars("999999", db_path=db) == []


class TestLoadBars:
    def test_bar_fields_and_ts_sequence(self, tmp_path):
        """ts = 窗口内递增序号 0..n-1（§4.4，对齐 spec/model.py Bar 约定）。"""
        db = _db(tmp_path)
        store.save_daily("600519", ROWS, source="baostock", db_path=db)
        bars = store.load_bars("600519", db_path=db)
        assert all(isinstance(b, Bar) for b in bars)
        assert [b.ts for b in bars] == [0, 1, 2]
        assert (bars[0].o, bars[0].h, bars[0].l, bars[0].c, bars[0].vol) == (
            10.0, 10.4, 9.9, 10.1, 100.0,
        )

    def test_ts_rebased_on_range(self, tmp_path):
        """区间截取的子窗口 ts 仍从 0 起（窗口语义由调用方持有）。"""
        db = _db(tmp_path)
        store.save_daily("600519", ROWS, source="baostock", db_path=db)
        bars = store.load_bars("600519", start="2026-08-25", db_path=db)
        assert [b.ts for b in bars] == [0, 1]
        assert bars[0].c == 10.2


class TestCoverage:
    def test_coverage_min_max_count(self, tmp_path):
        db = _db(tmp_path)
        store.save_daily("600519", ROWS, source="baostock", db_path=db)
        store.save_daily("sh000001", ROWS[:1], source="akshare", db_path=db)
        cov = store.coverage(db_path=db)
        assert cov["600519"] == ("2026-08-24", "2026-08-26", 3)
        assert cov["sh000001"] == ("2026-08-24", "2026-08-24", 1)

    def test_coverage_empty(self, tmp_path):
        db = _db(tmp_path)
        assert store.coverage(db_path=db) == {}
