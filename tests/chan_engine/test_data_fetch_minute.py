"""M7-1 分钟数据层：fetch_minute 降级链（新浪→TDX）与归一化口径测试。

单测不触网：网络函数一律 monkeypatch；归一化函数为纯函数直接测。
口径依据：docs/design/chanlun-m7-multitimeframe-skill.md §4。
"""
from __future__ import annotations

import json
from datetime import datetime

import pytest

from chan_engine.data import fetch

SINA_ROWS = [
    {"day": "2026-08-27 14:00:00", "open": "1.900", "high": "1.910",
     "low": "1.890", "close": "1.905", "volume": 123456},
    {"day": "2026-08-27 15:00:00", "open": "1.905", "high": "1.920",
     "low": "1.900", "close": "1.918", "volume": 234567},
]

TDX_ROWS = [
    {"date": "2026-08-27", "datetime": "2026-08-27 14:00", "open": 1.9,
     "high": 1.91, "low": 1.89, "close": 1.905, "volume": 123456.0,
     "amount": 235000.0, "pct_change": None, "source": "tdx"},
    {"date": "2026-08-27", "datetime": "2026-08-27 15:00", "open": 1.905,
     "high": 1.92, "low": 1.9, "close": 1.918, "volume": 234567.0,
     "amount": 449000.0, "pct_change": None, "source": "tdx"},
]


class TestToSinaSymbol:
    """新浪 symbol 必须带市场前缀：已带原样；裸码 5/6/9→sh，其余→sz（对齐 to_baostock_code 口径）。"""

    def test_prefixed_passthrough(self):
        assert fetch.to_sina_symbol("sh512400") == "sh512400"
        assert fetch.to_sina_symbol("sz399006") == "sz399006"

    def test_bare_code(self):
        assert fetch.to_sina_symbol("512400") == "sh512400"
        assert fetch.to_sina_symbol("600519") == "sh600519"
        assert fetch.to_sina_symbol("000001") == "sz000001"
        assert fetch.to_sina_symbol("300750") == "sz300750"


class TestNormalizeSinaMinute:
    def test_records(self):
        rows = fetch.normalize_sina_minute_records(SINA_ROWS)
        assert rows == [
            {"dt": "2026-08-27 14:00", "open": 1.9, "high": 1.91,
             "low": 1.89, "close": 1.905, "volume": 123456.0},
            {"dt": "2026-08-27 15:00", "open": 1.905, "high": 1.92,
             "low": 1.9, "close": 1.918, "volume": 234567.0},
        ]

    def test_dt_truncated_to_minute(self):
        """新浪 day 字段带秒尾，dt 统一截到 'YYYY-MM-DD HH:MM'（§4.2）。"""
        rows = fetch.normalize_sina_minute_records(SINA_ROWS)
        assert all(len(r["dt"]) == 16 for r in rows)


class TestNormalizeTdxMinute:
    def test_records(self):
        rows = fetch.normalize_tdx_minute_records(TDX_ROWS)
        assert rows[0]["dt"] == "2026-08-27 14:00"
        assert rows[0]["close"] == 1.905
        assert rows[1]["volume"] == 234567.0

    def test_fallback_to_date_when_no_datetime(self):
        rows = fetch.normalize_tdx_minute_records(
            [dict(TDX_ROWS[0], datetime=None)])
        assert rows[0]["dt"] == "2026-08-27"


class TestMarkComplete:
    """未收盘 bar 纪律（§4.3）：dt > now（截断到分钟）→ complete=0。"""

    NOW = datetime(2026, 8, 28, 10, 15, 30)  # 盘中 10:15

    def _rows(self):
        return [
            {"dt": "2026-08-28 10:30"},  # 60m 进行中 bar（10:30 收盘）
            {"dt": "2026-08-28 10:00"},  # 30m 已完成 bar
            {"dt": "2026-08-27 15:00"},  # 昨日 bar
        ]

    def test_partial_marking(self):
        rows = fetch.mark_complete(self._rows(), now=self.NOW)
        assert [r["complete"] for r in rows] == [0, 1, 1]

    def test_boundary_dt_equals_now_minute_is_complete(self):
        """dt == now（截断到分钟）视为完成：10:30:45 时 10:30 bar 刚收完。"""
        now = datetime(2026, 8, 28, 10, 30, 45)
        rows = fetch.mark_complete([{"dt": "2026-08-28 10:30"}], now=now)
        assert rows[0]["complete"] == 1

    def test_after_close_all_complete(self):
        now = datetime(2026, 8, 28, 15, 30)
        rows = fetch.mark_complete(self._rows(), now=now)
        assert all(r["complete"] == 1 for r in rows)


class TestFetchSinaMinute:
    """_fetch_sina_minute：curl 子进程 mock；异常响应处理沿用 skill 实证纪律。"""

    def _mock_curl(self, monkeypatch, payload):
        class _R:
            stdout = json.dumps(payload).encode()

        monkeypatch.setattr(fetch.subprocess, "run", lambda *a, **k: _R())

    def test_ok(self, monkeypatch):
        self._mock_curl(monkeypatch, SINA_ROWS)
        rows = fetch._fetch_sina_minute("sh512400", 60)
        assert [r["dt"] for r in rows] == ["2026-08-27 14:00", "2026-08-27 15:00"]

    def test_url_params(self, monkeypatch):
        captured = {}

        class _R:
            stdout = json.dumps(SINA_ROWS).encode()

        def _run(cmd, **k):
            captured["url"] = cmd[-1]
            return _R()

        monkeypatch.setattr(fetch.subprocess, "run", _run)
        fetch._fetch_sina_minute("512400", 30, datalen=100)
        url = captured["url"]
        assert "symbol=sh512400" in url and "scale=30" in url and "datalen=100" in url

    def test_empty_list_raises(self, monkeypatch):
        """空列表视为限流/异常（skill 实证），抛错触发 TDX 降级。"""
        self._mock_curl(monkeypatch, [])
        with pytest.raises(fetch.DataFetchError):
            fetch._fetch_sina_minute("sh512400", 60)

    def test_abnormal_payload_raises(self, monkeypatch):
        self._mock_curl(monkeypatch, {"error": "null"})
        with pytest.raises(fetch.DataFetchError):
            fetch._fetch_sina_minute("sh512400", 60)

    def test_curl_failure_raises(self, monkeypatch):
        def _boom(*a, **k):
            raise OSError("curl not found")

        monkeypatch.setattr(fetch.subprocess, "run", _boom)
        with pytest.raises(fetch.DataFetchError):
            fetch._fetch_sina_minute("sh512400", 60)

    def test_curl_nonzero_exit_raises(self, monkeypatch):
        """check=True 下 curl 非零退出 → CalledProcessError → DataFetchError。"""
        def _boom(*a, **k):
            raise fetch.subprocess.CalledProcessError(7, "curl")

        monkeypatch.setattr(fetch.subprocess, "run", _boom)
        with pytest.raises(fetch.DataFetchError):
            fetch._fetch_sina_minute("sh512400", 60)

    def test_dirty_row_rejected(self, monkeypatch):
        """新浪后续行缺字段（close 缺失）→ 校验拒绝 → 触发降级（评审 Major-2）。"""
        dirty = SINA_ROWS[:1] + [{"day": "2026-08-27 15:00:00", "open": "1.905",
                                  "high": "1.920", "low": "1.900"}]
        self._mock_curl(monkeypatch, dirty)
        with pytest.raises(fetch.DataFetchError):
            fetch._fetch_sina_minute("sh512400", 60)

    def test_missing_day_key_rejected(self, monkeypatch):
        """缺 day 键不得产出 dt='None' 入库（评审 Major-3）。"""
        dirty = [{"open": "1.9", "high": "1.91", "low": "1.89", "close": "1.905"}]
        self._mock_curl(monkeypatch, dirty)
        with pytest.raises(fetch.DataFetchError):
            fetch._fetch_sina_minute("sh512400", 60)


class TestFetchTdxMinute:
    def _mock_market(self, monkeypatch, rows):
        class _M:
            def get_kline(self, code, category, count):
                assert category in ("60min", "30min")
                return rows

        monkeypatch.setattr(fetch, "_get_tdx_market", lambda: _M())

    def test_ok_60min(self, monkeypatch):
        self._mock_market(monkeypatch, TDX_ROWS)
        rows = fetch._fetch_tdx_minute("sh512400", 60)
        assert [r["dt"] for r in rows] == ["2026-08-27 14:00", "2026-08-27 15:00"]

    def test_empty_is_success(self, monkeypatch):
        """TDX 空结果视为成功响应（该窗口无交易），不抛错（与日线口径一致）。"""
        self._mock_market(monkeypatch, [])
        assert fetch._fetch_tdx_minute("sh512400", 30) == []

    def test_tdx_unavailable_raises(self, monkeypatch):
        """TDX 加载失败须带原始根因（评审 Minor：不得吞异常报笼统'不可用'）。"""
        def _boom():
            raise ImportError("pytdx api changed")

        monkeypatch.setattr(fetch, "_get_tdx_market", _boom)
        with pytest.raises(fetch.DataFetchError) as exc:
            fetch._fetch_tdx_minute("sh512400", 60)
        assert "pytdx api changed" in str(exc.value)

    def test_missing_datetime_rejected(self, monkeypatch):
        """TDX 行 datetime/date 双缺或退化为纯日期 → 拒绝（评审 Major-3：
        纯日期 dt 盘中会误判 complete=1，属反未来函数）。"""
        self._mock_market(monkeypatch, [dict(TDX_ROWS[0], datetime=None)])
        with pytest.raises(fetch.DataFetchError):
            fetch._fetch_tdx_minute("sh512400", 60)


class TestValidateMinuteRows:
    """入库前校验（评审 Major-2/3）：dt 完整 16 字符可解析；o/h/l/c 非 None。"""

    GOOD = {"dt": "2026-08-28 15:00", "open": 1.9, "high": 1.92,
            "low": 1.89, "close": 1.91, "volume": None}

    def test_valid_passes(self):
        # volume=None 容忍（load_bars 有 0.0 兜底）
        rows = fetch.validate_minute_rows([self.GOOD])
        assert rows[0]["dt"] == "2026-08-28 15:00"

    def test_bad_dt_rejected(self):
        for bad in ("", "None", "2026-08-28", "2026-08-28 25:00", "not-a-date"):
            with pytest.raises(fetch.DataFetchError):
                fetch.validate_minute_rows([dict(self.GOOD, dt=bad)])

    def test_none_price_rejected(self):
        for k in ("open", "high", "low", "close"):
            with pytest.raises(fetch.DataFetchError) as exc:
                fetch.validate_minute_rows([dict(self.GOOD, **{k: None})])
            assert k in str(exc.value)

    def test_error_message_locates_row(self):
        with pytest.raises(fetch.DataFetchError) as exc:
            fetch.validate_minute_rows([self.GOOD, dict(self.GOOD, dt="")])
        assert "[1]" in str(exc.value)


class TestFetchMinuteFallback:
    def test_sina_dirty_falls_back_tdx(self, monkeypatch):
        """链级：新浪产出脏行 → 校验拒绝 → TDX 接管（评审 Major-2/3 修复路径）。"""
        def _dirty(code, tf, datalen=260):
            raise fetch.DataFetchError("分钟行[3] 缺字段 close")

        monkeypatch.setattr(fetch, "_fetch_sina_minute", _dirty)
        monkeypatch.setattr(fetch, "_fetch_tdx_minute",
                            lambda code, tf, datalen=260: [
                                {"dt": "2020-01-02 10:30", "open": 1.0, "high": 1.1,
                                 "low": 0.9, "close": 1.05, "volume": 10.0}])
        rows, source = fetch.fetch_minute("sh512400", 60)
        assert source == "tdx" and len(rows) == 1

    def test_tf_validation(self):
        with pytest.raises(ValueError):
            fetch.fetch_minute("sh512400", 15)
        with pytest.raises(ValueError):
            fetch.fetch_minute("sh512400", 5)

    def test_sina_ok_no_fallback(self, monkeypatch):
        monkeypatch.setattr(fetch, "_fetch_sina_minute",
                            lambda code, tf, datalen=260: [
                                {"dt": "2020-01-02 10:30", "open": 1.0, "high": 1.1,
                                 "low": 0.9, "close": 1.05, "volume": 10.0}])

        def _boom(*a, **k):
            raise AssertionError("不应触达 TDX")

        monkeypatch.setattr(fetch, "_fetch_tdx_minute", _boom)
        rows, source = fetch.fetch_minute("sh512400", 60)
        assert source == "sina"
        assert rows[0]["complete"] == 1  # 历史 dt 必然已完成

    def test_sina_raises_fallback_tdx(self, monkeypatch):
        def _fail(code, tf, datalen=260):
            raise ConnectionError("sina down")

        monkeypatch.setattr(fetch, "_fetch_sina_minute", _fail)
        monkeypatch.setattr(fetch, "_fetch_tdx_minute",
                            lambda code, tf, datalen=260: [{"dt": "2020-01-02 10:30"}])
        rows, source = fetch.fetch_minute("sh512400", 60)
        assert source == "tdx" and len(rows) == 1

    def test_both_fail_raises_data_fetch_error(self, monkeypatch):
        def _fail_a(code, tf, datalen=260):
            raise ConnectionError("sina down")

        def _fail_b(code, tf, datalen=260):
            raise TimeoutError("tdx down")

        monkeypatch.setattr(fetch, "_fetch_sina_minute", _fail_a)
        monkeypatch.setattr(fetch, "_fetch_tdx_minute", _fail_b)
        with pytest.raises(fetch.DataFetchError) as exc:
            fetch.fetch_minute("sh512400", 30)
        msg = str(exc.value)
        assert "sh512400" in msg and "sina down" in msg and "tdx down" in msg

    def test_results_sorted_and_marked(self, monkeypatch):
        monkeypatch.setattr(fetch, "_fetch_sina_minute",
                            lambda code, tf, datalen=260: [
                                {"dt": "2020-01-02 11:30"}, {"dt": "2020-01-02 10:30"}])
        rows, _ = fetch.fetch_minute("sh512400", 60)
        assert [r["dt"] for r in rows] == ["2020-01-02 10:30", "2020-01-02 11:30"]
        assert all(r["complete"] == 1 for r in rows)

    def test_future_bar_marked_partial(self, monkeypatch):
        monkeypatch.setattr(fetch, "_fetch_sina_minute",
                            lambda code, tf, datalen=260: [{"dt": "2099-01-04 10:30"}])
        rows, _ = fetch.fetch_minute("sh512400", 60)
        assert rows[0]["complete"] == 0
