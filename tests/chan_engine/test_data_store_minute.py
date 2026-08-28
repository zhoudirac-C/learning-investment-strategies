"""M7-1 分钟数据层：minute_bars 存储与 load_bars(tf) 适配测试。

全部使用 tmp_path 独立库，不触网、不碰真实 infra/data。
口径依据：docs/design/chanlun-m7-multitimeframe-skill.md §4.2/§4.3。
"""
from __future__ import annotations

import sqlite3

import pytest

from chan_engine.data import store
from chan_engine.spec.model import Bar

MIN_ROWS_60 = [
    {"dt": "2026-08-26 14:00", "open": 1.90, "high": 1.91, "low": 1.89,
     "close": 1.905, "volume": 100.0, "complete": 1},
    {"dt": "2026-08-26 15:00", "open": 1.905, "high": 1.92, "low": 1.90,
     "close": 1.918, "volume": 110.0, "complete": 1},
    {"dt": "2026-08-27 10:30", "open": 1.918, "high": 1.93, "low": 1.91,
     "close": 1.925, "volume": 120.0, "complete": 1},
]

MIN_ROWS_30 = [
    {"dt": "2026-08-27 10:00", "open": 1.918, "high": 1.925, "low": 1.915,
     "close": 1.922, "volume": 60.0, "complete": 1},
    {"dt": "2026-08-27 10:30", "open": 1.922, "high": 1.93, "low": 1.91,
     "close": 1.925, "volume": 60.0, "complete": 1},
]


def _db(tmp_path):
    db = tmp_path / "chan_bars.db"
    store.init_db(db)
    return db


class TestSaveAndLoadMinute:
    def test_roundtrip_dt_ascending(self, tmp_path):
        db = _db(tmp_path)
        store.save_minute("sh512400", 60, list(reversed(MIN_ROWS_60)),
                          source="sina", db_path=db)
        rows = store.load_minute("sh512400", 60, db_path=db)
        assert [r["dt"] for r in rows] == [r["dt"] for r in MIN_ROWS_60]
        assert rows[0]["close"] == 1.905
        assert rows[0]["source"] == "sina"
        assert rows[0]["complete"] == 1

    def test_idempotent_no_duplicates(self, tmp_path):
        """INSERT OR REPLACE 幂等：同窗口重拉行数不变（§4.2 滑动窗口快照）。"""
        db = _db(tmp_path)
        store.save_minute("sh512400", 60, MIN_ROWS_60, source="sina", db_path=db)
        store.save_minute("sh512400", 60, MIN_ROWS_60, source="sina", db_path=db)
        with sqlite3.connect(str(db)) as conn:
            n = conn.execute("SELECT COUNT(*) FROM minute_bars").fetchone()[0]
        assert n == len(MIN_ROWS_60)

    def test_upsert_updates_value_and_complete(self, tmp_path):
        """盘中 complete=0 bar 收盘后重拉 → 同主键更新为 complete=1 与最终价。"""
        db = _db(tmp_path)
        partial = [dict(MIN_ROWS_60[-1], close=1.921, complete=0)]
        store.save_minute("sh512400", 60, MIN_ROWS_60[:2] + partial,
                          source="sina", db_path=db)
        store.save_minute("sh512400", 60, MIN_ROWS_60, source="sina", db_path=db)
        rows = store.load_minute("sh512400", 60, db_path=db)
        assert len(rows) == 3
        assert rows[-1]["close"] == 1.925
        assert rows[-1]["complete"] == 1

    def test_tf_isolation(self, tmp_path):
        """同一 code 不同 tf 分行存储（PRIMARY KEY code+tf+dt）。"""
        db = _db(tmp_path)
        store.save_minute("sh512400", 60, MIN_ROWS_60, source="sina", db_path=db)
        store.save_minute("sh512400", 30, MIN_ROWS_30, source="sina", db_path=db)
        assert len(store.load_minute("sh512400", 60, db_path=db)) == 3
        assert len(store.load_minute("sh512400", 30, db_path=db)) == 2

    def test_save_tf_validation(self, tmp_path):
        db = _db(tmp_path)
        with pytest.raises(ValueError):
            store.save_minute("sh512400", 15, MIN_ROWS_60, source="sina", db_path=db)

    def test_range_filter_inclusive(self, tmp_path):
        """start/end 含首尾；date 前缀界（'2026-08-27'）按字符串比较自然生效。"""
        db = _db(tmp_path)
        store.save_minute("sh512400", 60, MIN_ROWS_60, source="sina", db_path=db)
        rows = store.load_minute("sh512400", 60, start="2026-08-27", db_path=db)
        assert [r["dt"] for r in rows] == ["2026-08-27 10:30"]
        rows = store.load_minute("sh512400", 60,
                                 start="2026-08-26 15:00", end="2026-08-27 10:30",
                                 db_path=db)
        assert [r["dt"] for r in rows] == ["2026-08-26 15:00", "2026-08-27 10:30"]

    def test_range_end_pure_date_inclusive(self, tmp_path):
        """end 传纯日期须含当天全部 bar（评审 Major-1：'2026-08-27' 不得丢掉当天）。"""
        db = _db(tmp_path)
        store.save_minute("sh512400", 60, MIN_ROWS_60, source="sina", db_path=db)
        rows = store.load_minute("sh512400", 60,
                                 start="2026-08-26", end="2026-08-26", db_path=db)
        assert [r["dt"] for r in rows] == ["2026-08-26 14:00", "2026-08-26 15:00"]
        rows = store.load_minute("sh512400", 60, end="2026-08-27", db_path=db)
        assert len(rows) == 3

    def test_load_minute_tf_validation(self, tmp_path):
        db = _db(tmp_path)
        with pytest.raises(ValueError):
            store.load_minute("sh512400", 15, db_path=db)

    def test_save_rejects_dirty_rows(self, tmp_path):
        """写入侧防线（评审 Major-2/3）：缺 dt 或 o/h/l/c 为 None 的行拒绝入库。"""
        db = _db(tmp_path)
        with pytest.raises(ValueError):
            store.save_minute("sh512400", 60, [dict(MIN_ROWS_60[0], close=None)],
                              source="sina", db_path=db)
        with pytest.raises(ValueError):
            store.save_minute("sh512400", 60, [dict(MIN_ROWS_60[0], dt="")],
                              source="sina", db_path=db)
        # 坏行不得残留
        assert store.load_minute("sh512400", 60, db_path=db) == []

    def test_save_complete_none_defaults_1(self, tmp_path):
        """complete 值为 None 时按默认 1 处理（缺键同）；显式 0 必须保持 0。"""
        db = _db(tmp_path)
        store.save_minute("sh512400", 60, [dict(MIN_ROWS_60[0], complete=None)],
                          source="sina", db_path=db)
        rows = store.load_minute("sh512400", 60, db_path=db)
        assert rows[0]["complete"] == 1

    def test_save_complete_missing_key_defaults_1(self, tmp_path):
        db = _db(tmp_path)
        row = {k: v for k, v in MIN_ROWS_60[0].items() if k != "complete"}
        store.save_minute("sh512400", 60, [row], source="sina", db_path=db)
        assert store.load_minute("sh512400", 60, db_path=db)[0]["complete"] == 1

    def test_include_partial(self, tmp_path):
        """默认剔除未收盘 bar；include_partial=True 才返回（§4.3）。"""
        db = _db(tmp_path)
        rows = MIN_ROWS_60[:2] + [dict(MIN_ROWS_60[2], complete=0)]
        store.save_minute("sh512400", 60, rows, source="sina", db_path=db)
        full = store.load_minute("sh512400", 60, db_path=db)
        assert [r["dt"] for r in full] == [r["dt"] for r in MIN_ROWS_60[:2]]
        with_partial = store.load_minute("sh512400", 60, include_partial=True, db_path=db)
        assert len(with_partial) == 3
        assert with_partial[-1]["complete"] == 0

    def test_empty_load(self, tmp_path):
        db = _db(tmp_path)
        assert store.load_minute("sh512400", 60, db_path=db) == []
        assert store.load_bars("sh512400", tf=60, db_path=db) == []


class TestLoadBarsMinute:
    def test_bar_fields_and_ts_sequence(self, tmp_path):
        """ts = 窗口内递增序号 0..n-1（与日线 load_bars 同约定）。"""
        db = _db(tmp_path)
        store.save_minute("sh512400", 60, MIN_ROWS_60, source="sina", db_path=db)
        bars = store.load_bars("sh512400", tf=60, db_path=db)
        assert all(isinstance(b, Bar) for b in bars)
        assert [b.ts for b in bars] == [0, 1, 2]
        assert (bars[0].o, bars[0].h, bars[0].l, bars[0].c, bars[0].vol) == (
            1.90, 1.91, 1.89, 1.905, 100.0,
        )

    def test_load_bars_excludes_partial_by_default(self, tmp_path):
        db = _db(tmp_path)
        rows = MIN_ROWS_60[:2] + [dict(MIN_ROWS_60[2], complete=0)]
        store.save_minute("sh512400", 60, rows, source="sina", db_path=db)
        bars = store.load_bars("sh512400", tf=60, db_path=db)
        assert len(bars) == 2
        bars = store.load_bars("sh512400", tf=60, include_partial=True, db_path=db)
        assert len(bars) == 3

    def test_load_bars_tf_validation(self, tmp_path):
        db = _db(tmp_path)
        with pytest.raises(ValueError):
            store.load_bars("sh512400", tf=15, db_path=db)

    def test_daily_path_unaffected(self, tmp_path):
        """tf 缺省走既有日线路径（签名兼容）。"""
        db = _db(tmp_path)
        store.save_daily("600519", [
            {"date": "2026-08-26", "open": 10.0, "high": 10.4, "low": 9.9,
             "close": 10.1, "volume": 100.0, "amount": 1010.0},
        ], source="baostock", db_path=db)
        bars = store.load_bars("600519", db_path=db)
        assert len(bars) == 1 and bars[0].c == 10.1


class TestCoverageMinute:
    def test_per_code_tf(self, tmp_path):
        db = _db(tmp_path)
        store.save_minute("sh512400", 60, MIN_ROWS_60, source="sina", db_path=db)
        store.save_minute("sh512400", 30, MIN_ROWS_30, source="sina", db_path=db)
        cov = store.coverage_minute(db_path=db)
        assert cov[("sh512400", 60)] == ("2026-08-26 14:00", "2026-08-27 10:30", 3)
        assert cov[("sh512400", 30)] == ("2026-08-27 10:00", "2026-08-27 10:30", 2)

    def test_empty(self, tmp_path):
        db = _db(tmp_path)
        assert store.coverage_minute(db_path=db) == {}
