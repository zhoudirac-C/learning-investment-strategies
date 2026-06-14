"""Tests for WsEventDrivenFetcher.

覆盖场景：
- 启动/停止
- 事件去重（500ms 窗口）
- 断路器（3次失败 → 打开 → 1小时后恢复）
- HTTP 降级
- 缓存快照构建
"""

import asyncio
from collections.abc import Sequence
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from qing_investment.monitor.fetchers.ws_event_fetcher import (
    CircuitBreakerState,
    WsEventDrivenFetcher,
)
from qing_investment.monitor.fetchers.ws_client import QuoteEvent


# ── CircuitBreaker 测试 ──────────────────────────────────────────

class TestCircuitBreaker:

    def test_initial_state_closed(self):
        cb = CircuitBreakerState()
        assert cb.can_attempt() is True
        assert cb.is_open is False

    def test_record_failure_increments(self):
        cb = CircuitBreakerState()
        cb.record_failure()
        assert cb.failures == 1
        assert cb.is_open is False
        assert cb.can_attempt() is True

    def test_opens_after_three_failures(self):
        cb = CircuitBreakerState()
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open is True
        assert cb.can_attempt() is False

    def test_success_resets(self):
        cb = CircuitBreakerState()
        cb.record_failure()
        cb.record_success()
        assert cb.failures == 0
        assert cb.is_open is False

    def test_cooldown_expires(self):
        cb = CircuitBreakerState()
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open is True

        # 模拟冷却时间已过
        cb.cooldown_until = datetime.now() - timedelta(minutes=1)
        assert cb.can_attempt() is True
        assert cb.is_open is False


# ── Mock WebSocket 客户端 ─────────────────────────────────────────

class MockWsClient:
    """模拟 WsQuoteClient."""

    def __init__(self, events: Sequence[QuoteEvent] | None = None) -> None:
        self.events = list(events or [])
        self._closed = False
        self._subscribed: list[str] = []
        self.reconnect_count = 0

    async def subscribe(self, codes: list[str]) -> None:
        self._subscribed.extend(codes)

    async def read_events(self):
        for event in self.events:
            yield event
        # 阻塞直到停止
        while not self._closed:
            await asyncio.sleep(0.1)

    async def close(self) -> None:
        self._closed = True

    @property
    def is_connected(self) -> bool:
        return not self._closed


# ── WsEventDrivenFetcher 测试 ────────────────────────────────────

class TestWsEventDrivenFetcher:

    @pytest.mark.asyncio
    async def test_start_stop(self):
        http_fetcher = MagicMock(return_value={"quotes": []})
        fetcher = WsEventDrivenFetcher(http_fetcher, codes=["000534"])

        with patch("qing_investment.monitor.fetchers.ws_event_fetcher.WsQuoteClient", return_value=MockWsClient()):
            result = await fetcher.start()
            assert result is True
            assert fetcher.is_fallback is False

            await fetcher.stop()
            assert fetcher._running is False

    @pytest.mark.asyncio
    async def test_event_dedupe(self):
        """同一标的 500ms 内只保留一个事件."""
        events = [
            QuoteEvent(code="000534", price=30.0, change_pct=0.0, volume=1000),
            QuoteEvent(code="000534", price=30.1, change_pct=0.1, volume=1100),  # 应被去重
            QuoteEvent(code="002353", price=50.0, change_pct=0.0, volume=2000),
        ]
        http_fetcher = MagicMock(return_value={"quotes": []})
        fetcher = WsEventDrivenFetcher(http_fetcher, codes=["000534", "002353"])

        mock_client = MockWsClient(events=events)
        with patch("qing_investment.monitor.fetchers.ws_event_fetcher.WsQuoteClient", return_value=mock_client):
            await fetcher.start()
            await asyncio.sleep(0.1)  # 让 reader_loop 处理事件
            await fetcher.stop()

        # 000534 应该只有一条（第一条，第二条被去重）
        assert len(fetcher._latest_quotes) == 2
        assert fetcher._latest_quotes["000534"]["latest"] == 30.0
        assert fetcher._latest_quotes["002353"]["latest"] == 50.0

    @pytest.mark.asyncio
    async def test_circuit_breaker_opens(self):
        """3 次失败后断路器打开."""
        http_fetcher = MagicMock(return_value={"quotes": []})
        fetcher = WsEventDrivenFetcher(http_fetcher, codes=["000534"])

        # 模拟连续 3 次启动失败
        with patch("qing_investment.monitor.fetchers.ws_event_fetcher.WsQuoteClient") as MockWs:
            MockWs.side_effect = Exception("Connection refused")

            for _ in range(3):
                result = await fetcher.start()
                assert result is False

        # 断路器应打开
        assert fetcher._circuit.is_open is True
        assert fetcher.is_fallback is True

    @pytest.mark.asyncio
    async def test_http_fallback(self):
        """断路器打开后自动降级到 HTTP."""
        http_fetcher = MagicMock(return_value={
            "quotes": [{"code": "000534", "latest": 31.5}],
            "errors": [],
        })
        fetcher = WsEventDrivenFetcher(http_fetcher, codes=["000534"])

        # 强制断路器打开
        fetcher._circuit.is_open = True
        fetcher._circuit.cooldown_until = datetime.now() + timedelta(hours=2)
        fetcher._fallback_active = True

        snapshot = await fetcher.get_snapshot()
        assert snapshot["source"] == "http_fallback"
        assert len(snapshot["quotes"]) == 1

    @pytest.mark.asyncio
    async def test_snapshot_from_cache(self):
        """从缓存构建快照."""
        events = [
            QuoteEvent(code="000534", price=31.5, change_pct=2.5, volume=1500000),
        ]
        http_fetcher = MagicMock(return_value={"quotes": []})
        fetcher = WsEventDrivenFetcher(http_fetcher, codes=["000534"])

        mock_client = MockWsClient(events=events)
        with patch("qing_investment.monitor.fetchers.ws_event_fetcher.WsQuoteClient", return_value=mock_client):
            await fetcher.start()
            await asyncio.sleep(0.1)

            snapshot = await fetcher.get_snapshot()
            assert snapshot["source"] == "ws"
            assert len(snapshot["quotes"]) == 1
            assert snapshot["quotes"][0]["code"] == "000534"
            assert snapshot["quotes"][0]["latest"] == 31.5

            await fetcher.stop()

    @pytest.mark.asyncio
    async def test_update_codes(self):
        """动态更新订阅标的."""
        http_fetcher = MagicMock(return_value={"quotes": []})
        fetcher = WsEventDrivenFetcher(http_fetcher, codes=["000534"])

        mock_client = MockWsClient()
        with patch("qing_investment.monitor.fetchers.ws_event_fetcher.WsQuoteClient", return_value=mock_client):
            await fetcher.start()
            fetcher.update_codes(["000534", "002353"])
            await asyncio.sleep(0.05)
            assert "002353" in mock_client._subscribed
            await fetcher.stop()
