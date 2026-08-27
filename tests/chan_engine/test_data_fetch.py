"""M6-1 数据接入：fetch 降级链（akshare→baostock）与归一化口径测试。

单测不触网：网络函数一律 monkeypatch；归一化函数为纯函数直接测。
口径依据：docs/design/chanlun-m6-strategy-backtest.md §4。
"""
from __future__ import annotations

import pytest

from chan_engine.data import fetch


class TestCodeConvention:
    """代码形式约定：个股裸 6 位数字；指数带 sh/sz 字母前缀。"""

    def test_is_index(self):
        assert fetch.is_index("sh000001") is True
        assert fetch.is_index("sz399006") is True
        assert fetch.is_index("600519") is False
        assert fetch.is_index("000001") is False  # 平安银行（个股），非上证指数

    def test_to_baostock_code_stock(self):
        assert fetch.to_baostock_code("600519") == "sh.600519"
        assert fetch.to_baostock_code("000001") == "sz.000001"
        assert fetch.to_baostock_code("300750") == "sz.300750"

    def test_to_baostock_code_index(self):
        assert fetch.to_baostock_code("sh000001") == "sh.000001"
        assert fetch.to_baostock_code("sz399001") == "sz.399001"


class TestNormalizeAkshare:
    def test_stock_records(self):
        records = [
            {"日期": "2026-08-26", "开盘": 10.0, "最高": 10.5, "最低": 9.9,
             "收盘": 10.2, "成交量": 12345.0, "成交额": 12500000.0},
            {"日期": "2026-08-25", "开盘": 9.8, "最高": 10.1, "最低": 9.7,
             "收盘": 9.9, "成交量": 10000.0, "成交额": 9900000.0},
        ]
        rows = fetch.normalize_akshare_stock_records(records)
        assert rows == [
            {"date": "2026-08-26", "open": 10.0, "high": 10.5, "low": 9.9,
             "close": 10.2, "volume": 1234500.0, "amount": 12500000.0},
            {"date": "2026-08-25", "open": 9.8, "high": 10.1, "low": 9.7,
             "close": 9.9, "volume": 1000000.0, "amount": 9900000.0},
        ]
        # 成交量单位：akshare 为"手"，×100 归一到"股"（设计文档 §4.3）
        assert rows[0]["volume"] == 12345.0 * 100

    def test_index_records(self):
        records = [
            {"date": "2026-08-26", "open": 3800.0, "high": 3810.0,
             "low": 3790.0, "close": 3805.0, "volume": 500.0},
        ]
        rows = fetch.normalize_akshare_index_records(records)
        assert rows[0]["date"] == "2026-08-26"
        assert rows[0]["close"] == 3805.0
        assert rows[0]["volume"] == 500.0 * 100
        assert rows[0]["amount"] is None  # 新浪指数源无成交额字段 → None，不编造


class TestNormalizeBaostock:
    def test_rows(self):
        fields = ["date", "open", "high", "low", "close", "volume", "amount"]
        raw = [
            ["2026-08-25", "9.80", "10.10", "9.70", "9.90", "1000000", "9900000.00"],
            ["2026-08-26", "10.00", "10.50", "9.90", "10.20", "1234500", ""],
        ]
        rows = fetch.normalize_baostock_rows(raw, fields)
        assert rows[0] == {"date": "2026-08-25", "open": 9.8, "high": 10.1,
                           "low": 9.7, "close": 9.9, "volume": 1000000.0,
                           "amount": 9900000.0}
        # 空字符串字段 → None（baostock 指数 amount 常为空）
        assert rows[1]["amount"] is None
        # baostock volume 原生单位为"股"，不做 ×100
        assert rows[1]["volume"] == 1234500.0


class TestFetchDailyFallback:
    def test_akshare_ok_no_fallback(self, monkeypatch):
        monkeypatch.setattr(fetch, "_fetch_akshare",
                            lambda code, start, end: [{"date": "2026-08-26"}])

        def _boom(*a, **k):
            raise AssertionError("不应触达 baostock")

        monkeypatch.setattr(fetch, "_fetch_baostock", _boom)
        rows, source = fetch.fetch_daily("600519")
        assert source == "akshare"
        assert rows == [{"date": "2026-08-26"}]

    def test_akshare_raises_fallback_baostock(self, monkeypatch):
        def _fail(code, start, end):
            raise ConnectionError("Remote end closed connection")

        monkeypatch.setattr(fetch, "_fetch_akshare", _fail)
        monkeypatch.setattr(fetch, "_fetch_baostock",
                            lambda code, start, end: [{"date": "2026-08-26"}])
        rows, source = fetch.fetch_daily("600519")
        assert source == "baostock"
        assert len(rows) == 1

    def test_both_fail_raises_data_fetch_error(self, monkeypatch):
        def _fail_a(code, start, end):
            raise ConnectionError("ak down")

        def _fail_b(code, start, end):
            raise TimeoutError("bs down")

        monkeypatch.setattr(fetch, "_fetch_akshare", _fail_a)
        monkeypatch.setattr(fetch, "_fetch_baostock", _fail_b)
        with pytest.raises(fetch.DataFetchError) as exc:
            fetch.fetch_daily("600519")
        msg = str(exc.value)
        assert "600519" in msg and "ak down" in msg and "bs down" in msg

    def test_empty_is_success_no_fallback(self, monkeypatch):
        """空结果视为成功响应（该区间无交易），不触发降级——§4.1 口径。"""
        monkeypatch.setattr(fetch, "_fetch_akshare", lambda code, start, end: [])

        def _boom(*a, **k):
            raise AssertionError("空结果不应触发降级")

        monkeypatch.setattr(fetch, "_fetch_baostock", _boom)
        rows, source = fetch.fetch_daily("600519", "2026-01-01", "2026-01-02")
        assert rows == [] and source == "akshare"

    def test_results_sorted_by_date(self, monkeypatch):
        monkeypatch.setattr(fetch, "_fetch_akshare", lambda code, start, end: [
            {"date": "2026-08-26"}, {"date": "2026-08-25"},
        ])
        rows, _ = fetch.fetch_daily("600519")
        assert [r["date"] for r in rows] == ["2026-08-25", "2026-08-26"]
