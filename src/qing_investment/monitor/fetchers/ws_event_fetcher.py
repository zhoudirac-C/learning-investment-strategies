"""WebSocket 事件驱动行情获取器.

将 WsQuoteClient 的实时事件流转换为 scheduler 可用的 quote_snapshot 格式，
支持事件去重、断路器、HTTP 降级。

设计参考: docs/task/T20260614-004-architecture-remaining-v2.md §2.3.2
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable

from qing_investment.monitor.fetchers.ws_client import QuoteEvent, WsQuoteClient
from qing_investment.monitor.health_stats import get_health_registry

logger = logging.getLogger(__name__)


@dataclass
class CircuitBreakerState:
    """断路器状态."""

    failures: int = 0
    last_failure: datetime | None = None
    is_open: bool = False          # 断路器是否打开（拒绝请求）
    cooldown_until: datetime | None = None  # 冷却结束时间

    def record_failure(self) -> None:
        self.failures += 1
        self.last_failure = datetime.now()
        if self.failures >= 3:
            self.is_open = True
            self.cooldown_until = datetime.now() + timedelta(hours=1)
            logger.warning(f"Circuit breaker OPENED. Cooldown until {self.cooldown_until}")
        # 上报到健康指标
        try:
            registry = get_health_registry()
            remaining = 0.0
            if self.cooldown_until:
                remaining = max(0.0, (self.cooldown_until - datetime.now()).total_seconds() / 3600)
            registry.update_circuit_breaker(
                is_open=self.is_open,
                failures=self.failures,
                cooldown_remaining_hours=remaining,
                last_failure_time=self.last_failure.isoformat() if self.last_failure else "",
            )
        except Exception:
            pass

    def record_success(self) -> None:
        if self.failures > 0:
            self.failures = 0
            self.is_open = False
            self.cooldown_until = None
            logger.info("Circuit breaker CLOSED (success)")
        # 上报到健康指标
        try:
            get_health_registry().update_circuit_breaker(
                is_open=False, failures=0,
            )
        except Exception:
            pass

    def can_attempt(self) -> bool:
        if not self.is_open:
            return True
        if self.cooldown_until and datetime.now() >= self.cooldown_until:
            self.is_open = False
            self.failures = 0
            self.cooldown_until = None
            logger.info("Circuit breaker cooldown expired, CLOSED")
            return True
        return False


class WsEventDrivenFetcher:
    """WebSocket 事件驱动行情获取器.

    功能:
    - 连接 WsQuoteClient，订阅 watchlist 标的
    - 事件去重（同一标的 500ms 内连续报价合并为一个事件）
    - 断路器：WebSocket 断开超过 3 次 → 自动降级到 HTTP 轮询，1 小时后重试
    - 输出 quote_snapshot 格式（与现有 fetcher 兼容）

    使用方式:
        fetcher = WsEventDrivenFetcher(
            http_fetcher=fetch_quotes_with_fallback,  # HTTP 降级
            codes=["000534", "002353"],
        )
        await fetcher.start()
        snapshot = await fetcher.get_snapshot()  # 非阻塞，返回最新缓存
        await fetcher.stop()
    """

    # 事件去重窗口（毫秒）
    DEDUPE_MS: float = 500.0

    def __init__(
        self,
        http_fetcher: Callable,
        codes: list[str],
        host: str | None = None,
    ) -> None:
        self._http_fetcher = http_fetcher
        self._codes = codes
        self._host = host

        self._client: WsQuoteClient | None = None
        self._latest_quotes: dict[str, dict] = {}  # code -> quote_data
        self._last_event_time: dict[str, float] = {}  # code -> timestamp_ms
        self._circuit = CircuitBreakerState()
        self._running = False
        self._reader_task: asyncio.Task | None = None
        self._fallback_active = False

    # ── 公共 API ──────────────────────────────────────────────────

    async def start(self) -> bool:
        """启动 WebSocket 连接.

        Returns:
            bool: 是否成功启动（如果断路器打开则返回 False，由 HTTP 降级）
        """
        if not self._circuit.can_attempt():
            logger.info("Circuit breaker open, using HTTP fallback immediately")
            self._fallback_active = True
            return False

        try:
            self._client = WsQuoteClient(host=self._host)
            await self._client.subscribe(self._codes)
            self._running = True
            self._fallback_active = False
            self._circuit.record_success()

            # 启动事件读取循环
            self._reader_task = asyncio.create_task(self._reader_loop())
            logger.info(f"WsEventDrivenFetcher started with {len(self._codes)} codes")
            return True

        except Exception as e:
            logger.error(f"WebSocket start failed: {e}")
            self._circuit.record_failure()
            self._fallback_active = True
            return False

    async def stop(self) -> None:
        """停止连接."""
        self._running = False
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        if self._client:
            await self._client.close()
        logger.info("WsEventDrivenFetcher stopped")

    async def get_snapshot(self) -> dict[str, Any]:
        """获取最新行情快照（非阻塞）.

        如果 WebSocket 不可用，自动降级到 HTTP 轮询。
        输出格式与现有 fetcher 兼容:
            {"source": "ws" | "http_fallback", "quotes": [...], "errors": []}
        """
        if self._fallback_active or not self._running:
            return await self._http_fallback()

        # 从缓存构建 snapshot
        quotes = list(self._latest_quotes.values())
        return {
            "source": "ws",
            "quotes": quotes,
            "errors": [],
            "ws_connected": self._client.is_connected if self._client else False,
            "ws_reconnect_count": self._client.reconnect_count if self._client else 0,
        }

    def update_codes(self, codes: list[str]) -> None:
        """更新订阅标的列表（watchlist 变更时调用）."""
        new_codes = set(codes) - set(self._codes)
        if new_codes and self._client and self._running:
            # 异步重新订阅
            asyncio.create_task(self._client.subscribe(list(new_codes)))
        self._codes = codes

    @property
    def is_fallback(self) -> bool:
        """当前是否处于 HTTP 降级模式."""
        return self._fallback_active

    @property
    def circuit_state(self) -> dict:
        """断路器状态（用于监控）."""
        return {
            "failures": self._circuit.failures,
            "is_open": self._circuit.is_open,
            "cooldown_until": self._circuit.cooldown_until.isoformat() if self._circuit.cooldown_until else None,
        }

    # ── 内部方法 ──────────────────────────────────────────────────

    async def _reader_loop(self) -> None:
        """读取事件循环：接收 → 去重 → 缓存."""
        if not self._client:
            return

        try:
            async for event in self._client.read_events():
                if not self._running:
                    break

                # 事件去重：同一标的 500ms 内跳过
                now_ms = time.time() * 1000
                last_ms = self._last_event_time.get(event.code, 0)
                if now_ms - last_ms < self.DEDUPE_MS:
                    continue
                self._last_event_time[event.code] = now_ms

                # 转换为标准 quote_data 格式
                self._latest_quotes[event.code] = self._event_to_quote(event)

        except Exception as e:
            logger.error(f"WebSocket reader loop error: {e}")
            self._circuit.record_failure()
            self._fallback_active = True

    def _event_to_quote(self, event: QuoteEvent) -> dict:
        """将 QuoteEvent 转换为标准 quote_data 格式."""
        return {
            "code": event.code,
            "latest": event.price,
            "pct_change": event.change_pct,
            "volume": event.volume,
            "timestamp": event.timestamp.isoformat(),
            "source": "ws",
        }

    async def _http_fallback(self) -> dict[str, Any]:
        """HTTP 降级获取."""
        try:
            # 构建 targets 格式
            from qing_investment.monitor.fetchers import collect_quote_targets
            targets = {code: code for code in self._codes}
            result = self._http_fetcher(targets)
            reason = "circuit_breaker" if self._circuit.is_open else "ws_not_started"
            result["source"] = "http_fallback"
            result["ws_fallback_reason"] = reason
            # 上报降级
            try:
                get_health_registry().record_degradation(
                    source="http_fallback", reason=reason,
                )
            except Exception:
                pass
            return result
        except Exception as e:
            logger.error(f"HTTP fallback also failed: {e}")
            # 上报降级失败
            try:
                get_health_registry().record_degradation(
                    source="none", reason="http_fallback_failed",
                )
            except Exception:
                pass
            return {
                "source": "none",
                "quotes": [],
                "errors": [str(e)],
            }
