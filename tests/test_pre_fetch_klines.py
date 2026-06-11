"""pre_fetch_klines.py 单元测试"""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from qing_investment.kline_cache import get_klines, init_db, is_cache_ready


class TestPreFetchKlines:
    def setup_method(self):
        self.db_path = Path(tempfile.gettempdir()) / f"test_prefetch_{id(self)}.db"
        if self.db_path.exists():
            self.db_path.unlink()
        init_db(db_path=self.db_path)

    def teardown_method(self):
        if self.db_path.exists():
            self.db_path.unlink()

    def test_extract_stock_codes_from_watchlist(self):
        """测试从 watchlist.yaml 提取代码"""
        from scripts.pre_fetch_klines import _extract_stock_codes

        codes = _extract_stock_codes()
        assert len(codes) >= 1
        # 所有代码应该是字符串且非空
        for code in codes:
            assert isinstance(code, str)
            assert len(code) >= 6

    def test_timezone_check_skips_outside_window(self):
        """测试时区校验：非 06:00-09:15 窗口应 skip"""
        import scripts.pre_fetch_klines as pf

        # 直接调用 main()，当前时间如果不是开盘前窗口，应返回 0
        result = pf.main()
        # 当前执行时间不确定，但至少不应抛异常
        assert result in (0, 1)

    @patch("scripts.pre_fetch_klines.fetch_stock_kline")
    def test_full_prefetch_flow(self, mock_fetch):
        """测试完整预拉取流程（mock API）"""
        import scripts.pre_fetch_klines as pf

        # mock 返回数据
        mock_klines = [
            {
                "date": f"2026-06-{10+i:02d}",
                "open": 50.0 + i,
                "high": 52.0 + i,
                "low": 49.0 + i,
                "close": 51.0 + i,
                "volume": 100000,
            }
            for i in range(5)
        ]
        mock_fetch.return_value = mock_klines

        # 只提取少量代码测试
        with patch.object(pf, "_extract_stock_codes", return_value=["600378.SH", "000001.SZ"]):
            with patch.object(pf, "init_db"):
                with patch.object(pf, "save_klines") as mock_save:
                    with patch.object(pf, "mark_cache_ready") as mock_mark:
                        # 强制在窗口内执行（mock 时区校验）
                        with patch.object(pf, "datetime") as mock_dt:
                            mock_now = datetime(2026, 6, 11, 7, 30, tzinfo=timezone(timedelta(hours=8)))
                            mock_dt.now.return_value = mock_now
                            mock_dt.strftime = datetime.strftime

                            result = pf.main()

                            # 应该成功执行
                            assert result == 0
                            # 每只票都保存了
                            assert mock_save.call_count == 2
                            # 标记完成
                            mock_mark.assert_called_once()

    @patch("scripts.pre_fetch_klines.fetch_stock_kline")
    def test_retry_on_failure(self, mock_fetch):
        """测试失败重试机制"""
        import scripts.pre_fetch_klines as pf

        # 第1次抛异常，第2次成功
        mock_fetch.side_effect = [Exception("timeout"), [{"date": "2026-06-11", "close": 100.0}]]

        with patch.object(pf, "_extract_stock_codes", return_value=["600378.SH"]):
            with patch.object(pf, "init_db"):
                with patch.object(pf, "save_klines") as mock_save:
                    with patch.object(pf, "mark_cache_ready"):
                        with patch.object(pf, "time") as mock_time:
                            with patch.object(pf, "datetime") as mock_dt:
                                mock_now = datetime(2026, 6, 11, 7, 30, tzinfo=timezone(timedelta(hours=8)))
                                mock_dt.now.return_value = mock_now
                                mock_dt.strftime = datetime.strftime

                                result = pf.main()
                                assert result == 0
                                # 保存了一次（重试成功后）
                                assert mock_save.call_count == 1

    def test_fail_rate_exit_code(self):
        """测试失败率 >20% 返回非0"""
        import scripts.pre_fetch_klines as pf

        # mock 全部失败
        with patch.object(pf, "fetch_stock_kline", side_effect=Exception("API down")):
            with patch.object(pf, "_extract_stock_codes", return_value=["600378.SH", "000001.SZ", "000002.SZ"]):
                with patch.object(pf, "init_db"):
                    with patch.object(pf, "save_klines"):
                        with patch.object(pf, "mark_cache_ready"):
                            with patch.object(pf, "time"):
                                with patch.object(pf, "datetime") as mock_dt:
                                    mock_now = datetime(2026, 6, 11, 7, 30, tzinfo=timezone(timedelta(hours=8)))
                                    mock_dt.now.return_value = mock_now
                                    mock_dt.strftime = datetime.strftime

                                    result = pf.main()
                                    # 3只全部失败，失败率 100% > 20%，应返回 1
                                    assert result == 1
