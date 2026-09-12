"""stocks_kline 键格式统一 —— 归一化收口契约测试（2026-09-12）。

背景：kline_cache.db 曾双键并存（裸码 '000021' 与后缀键 '000021.SZ'），
复权口径不同（裸=TDX 不复权 / 后缀=qfq），断点续拉跨键 MAX(trade_date)
判定导致裸键停更被遮蔽（9/12 实测 113 只停在 06-24）。

统一约定：
- 规范键 = {6位数字}.{SH|SZ|BJ}，交易所由数字前缀权威推导
  （0/1/2/3→SZ，5/6→SH，900→SH，920/4/8→BJ），修正历史错标
  （如 000001.SH 实为平安银行数据 → 000001.SZ）
- save_klines 写入端归一化（所有写入方单点收口）
- 读取端双键兼容：code IN (规范后缀键, 裸码)，存量未迁移数据仍可读
- IDX 别名命名空间不归一（fetch_index_klines 写 'IDX000001'，
  指数已统一读 index_klines 表，别名键原样保留）
"""
import sqlite3

import pytest

from qing_investment.kline_cache import (
    get_klines,
    init_db,
    normalize_stock_key,
    save_klines,
)


def _kline(code: str, dates: list[str], base: float = 10.0) -> list[dict]:
    return [
        {
            "date": d,
            "open": base + i * 0.1,
            "high": base + i * 0.2,
            "low": base + i * 0.05,
            "close": base + i * 0.1,
            "volume": 1000.0 + i,
        }
        for i, d in enumerate(dates)
    ]


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "kline_cache.db"
    init_db(db_path=p)
    return p


class TestNormalizeStockKey:
    @pytest.mark.parametrize(
        "raw,expect",
        [
            # 裸码 → 按数字前缀推导交易所
            ("000021", "000021.SZ"),
            ("600363", "600363.SH"),
            ("300054", "300054.SZ"),
            ("159381", "159381.SZ"),   # 深 ETF
            ("512400", "512400.SH"),   # 沪 ETF
            ("920001", "920001.BJ"),   # 北交所新码段
            ("900901", "900901.SH"),   # 沪 B 股
            # 市场前缀 → 剥前缀再按数字推导
            ("sh512880", "512880.SH"),
            ("SZ002459", "002459.SZ"),
            # 错标后缀 → 数字前缀权威修正
            ("000001.SH", "000001.SZ"),
            ("600363.SZ", "600363.SH"),
            # 已规范 → 原样
            ("000636.SZ", "000636.SZ"),
            ("605376.SH", "605376.SH"),
            # IDX 别名命名空间 → 不动
            ("IDX000001", "IDX000001"),
            ("IDX000300", "IDX000300"),
            # 无法识别 → 原样返回（保守，不破坏未知键）
            ("", ""),
            ("ABC123", "ABC123"),
        ],
    )
    def test_mapping(self, raw, expect):
        assert normalize_stock_key(raw) == expect

    def test_whitespace_and_case(self):
        assert normalize_stock_key(" 600363 ") == "600363.SH"
        assert normalize_stock_key("000636.sz") == "000636.SZ"


class TestSaveCanonical:
    def test_bare_code_saved_under_suffix_key(self, db):
        save_klines("600378", _kline("600378", ["2026-09-10", "2026-09-11"]), db_path=db)
        conn = sqlite3.connect(db)
        keys = [r[0] for r in conn.execute("SELECT DISTINCT code FROM stocks_kline")]
        conn.close()
        assert keys == ["600378.SH"]

    def test_mislabeled_suffix_corrected_on_save(self, db):
        # 000001.SH 历史上写入的是平安银行（SZ）数据，保存时按数字前缀纠正
        save_klines("000001.SH", _kline("000001", ["2026-06-30"]), db_path=db)
        conn = sqlite3.connect(db)
        keys = [r[0] for r in conn.execute("SELECT DISTINCT code FROM stocks_kline")]
        conn.close()
        assert keys == ["000001.SZ"]

    def test_prefixed_code_saved_canonical(self, db):
        save_klines("sh512880", _kline("512880", ["2026-09-11"]), db_path=db)
        conn = sqlite3.connect(db)
        keys = [r[0] for r in conn.execute("SELECT DISTINCT code FROM stocks_kline")]
        conn.close()
        assert keys == ["512880.SH"]

    def test_overwrite_replaces_same_canonical_key(self, db):
        # 先以裸码写，再以后缀写 → 覆盖同一条规范键，不产生双键
        save_klines("002371", _kline("002371", ["2026-09-10"]), db_path=db)
        save_klines("002371.SZ", _kline("002371", ["2026-09-10", "2026-09-11"]), db_path=db)
        conn = sqlite3.connect(db)
        rows = conn.execute(
            "SELECT code, COUNT(*) FROM stocks_kline GROUP BY code"
        ).fetchall()
        conn.close()
        assert rows == [("002371.SZ", 2)]

    def test_idx_alias_not_normalized(self, db):
        # fetch_index_klines 写 IDX 别名键，不得被归一化改写
        save_klines("IDX000001", _kline("IDX000001", ["2026-08-12"]), db_path=db)
        conn = sqlite3.connect(db)
        keys = [r[0] for r in conn.execute("SELECT DISTINCT code FROM stocks_kline")]
        conn.close()
        assert keys == ["IDX000001"]


class TestDualReadCompat:
    def test_get_klines_reads_legacy_bare_rows(self, db):
        # 存量库（未迁移）裸码行：裸码查询与后缀查询都要能读到
        conn = sqlite3.connect(db)
        conn.execute(
            "INSERT INTO stocks_kline (code, trade_date, close) VALUES ('002371', '2026-09-10', 10.5)"
        )
        conn.commit()
        conn.close()

        by_bare = get_klines("002371", days=5, db_path=db)
        by_suffix = get_klines("002371.SZ", days=5, db_path=db)
        assert len(by_bare) == 1 and len(by_suffix) == 1
        assert by_bare[0]["close"] == 10.5
        assert by_suffix[0]["close"] == 10.5

    def test_get_klines_range_reads_legacy_bare_rows(self, db):
        from investment_engine.backtest.history import get_klines_range

        conn = sqlite3.connect(db)
        conn.executemany(
            "INSERT INTO stocks_kline (code, trade_date, close) VALUES ('002371', ?, ?)",
            [("2026-07-01", 10.0), ("2026-07-02", 10.1)],
        )
        conn.commit()
        conn.close()

        rows = get_klines_range("002371.SZ", "2026-07-01", "2026-07-31", db_path=db)
        assert [r["close"] for r in rows] == [10.0, 10.1]
