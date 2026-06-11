"""kline_cache.py 单元测试"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from qing_investment.kline_cache import (
    clear_cache_ready,
    get_cache_stats,
    get_klines,
    get_ma,
    init_db,
    is_cache_ready,
    mark_cache_ready,
    save_klines,
)


def _make_klines(count: int = 5) -> list[dict]:
    """生成测试用 K线数据"""
    klines = []
    for i in range(count):
        klines.append(
            {
                "date": f"2026-06-{10 + i:02d}",
                "open": 50.0 + i,
                "high": 52.0 + i,
                "low": 49.0 + i,
                "close": 51.0 + i,
                "volume": 100000 + i * 1000,
                "turnover": 5000000 + i * 50000,
                "amplitude": 3.0 + i * 0.1,
                "pct_change": 1.0 + i * 0.1,
            }
        )
    return klines


class TestKlineCache:
    def setup_method(self):
        """每个测试用例前创建临时数据库"""
        self.db_path = Path(tempfile.gettempdir()) / f"test_kline_{id(self)}.db"
        if self.db_path.exists():
            self.db_path.unlink()
        init_db(db_path=self.db_path)

    def teardown_method(self):
        """每个测试用例后清理临时数据库"""
        if self.db_path.exists():
            self.db_path.unlink()

    def test_init_db_creates_tables(self):
        """测试 init_db 创建正确的表结构"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()

        assert "stocks_kline" in tables
        assert "kline_meta" in tables

    def test_save_and_get_klines(self):
        """测试写入和读取 K线数据"""
        klines = _make_klines(5)
        save_klines("600378", klines, db_path=self.db_path)

        # 读取全部 5 根
        result = get_klines("600378", days=5, db_path=self.db_path)
        assert len(result) == 5
        assert result[0]["date"] == "2026-06-10"  # 正序
        assert result[-1]["date"] == "2026-06-14"
        assert result[-1]["close"] == 55.0

        # 读取最近 3 根
        result3 = get_klines("600378", days=3, db_path=self.db_path)
        assert len(result3) == 3
        assert result3[0]["date"] == "2026-06-12"

    def test_save_overwrites_existing(self):
        """测试覆盖写入：同一股票新数据覆盖旧数据"""
        old_klines = _make_klines(3)
        save_klines("600378", old_klines, db_path=self.db_path)

        new_klines = [
            {"date": "2026-06-20", "open": 60, "high": 62, "low": 59, "close": 61},
        ]
        save_klines("600378", new_klines, db_path=self.db_path)

        result = get_klines("600378", days=10, db_path=self.db_path)
        assert len(result) == 1
        assert result[0]["date"] == "2026-06-20"

    def test_get_klines_returns_empty_for_missing_stock(self):
        """测试读取不存在的股票返回空列表"""
        result = get_klines("999999", days=30, db_path=self.db_path)
        assert result == []

    def test_get_ma_calculation(self):
        """测试均线计算"""
        klines = [
            {"date": "2026-06-01", "close": 10.0},
            {"date": "2026-06-02", "close": 20.0},
            {"date": "2026-06-03", "close": 30.0},
        ]
        save_klines("600378", klines, db_path=self.db_path)

        ma3 = get_ma("600378", days=3, db_path=self.db_path)
        assert ma3 == 20.0  # (10+20+30)/3

        ma5 = get_ma("600378", days=5, db_path=self.db_path)
        assert ma5 is None  # K线不足

    def test_cache_ready_marking(self):
        """测试预拉取完成标记"""
        assert is_cache_ready("2026-06-11", db_path=self.db_path) is False

        mark_cache_ready("2026-06-11", db_path=self.db_path)
        assert is_cache_ready("2026-06-11", db_path=self.db_path) is True
        assert is_cache_ready("2026-06-10", db_path=self.db_path) is False

        clear_cache_ready("2026-06-11", db_path=self.db_path)
        assert is_cache_ready("2026-06-11", db_path=self.db_path) is False

    def test_save_empty_klines(self):
        """测试写入空列表（用于标记停牌/无数据股票）"""
        save_klines("600378", [], db_path=self.db_path)
        result = get_klines("600378", days=30, db_path=self.db_path)
        assert result == []

    def test_cache_stats(self):
        """测试缓存统计信息"""
        klines1 = _make_klines(5)
        klines2 = _make_klines(3)
        save_klines("600378", klines1, db_path=self.db_path)
        save_klines("000001", klines2, db_path=self.db_path)
        mark_cache_ready("2026-06-11", db_path=self.db_path)

        stats = get_cache_stats(db_path=self.db_path)
        assert stats["stock_count"] == 2
        assert stats["kline_count"] == 8
        assert "ready_2026-06-11" in stats["meta"]

    def test_multiple_stocks_isolation(self):
        """测试多股票数据隔离"""
        save_klines("600378", [{"date": "2026-06-11", "close": 100.0}], db_path=self.db_path)
        save_klines("000001", [{"date": "2026-06-11", "close": 50.0}], db_path=self.db_path)

        k1 = get_klines("600378", days=1, db_path=self.db_path)
        k2 = get_klines("000001", days=1, db_path=self.db_path)

        assert k1[0]["close"] == 100.0
        assert k2[0]["close"] == 50.0
