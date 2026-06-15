"""WebSocket 实时行情客户端.

提供腾讯行情 WebSocket 连接，支持:
- 订阅 watchlist 标的实时报价
- 消息队列缓冲（asyncio.Queue）
- 断线重连（指数退避，最多5次）
- 统一 QuoteEvent 输出格式

设计参考: docs/task/T20260614-004-architecture-remaining-v2.md §2.3.1
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncIterator

import websockets
from websockets.exceptions import ConnectionClosed
from websockets.legacy.client import WebSocketClientProtocol

logger = logging.getLogger(__name__)


# ── 数据模型 ──────────────────────────────────────────────────────

@dataclass
class QuoteEvent:
    """统一行情事件格式."""

    code: str          # 股票代码（如 000534）
    price: float
    change_pct: float
    volume: float
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "price": self.price,
            "change_pct": self.change_pct,
            "volume": self.volume,
            "timestamp": self.timestamp.isoformat(),
        }


# ── WebSocket 客户端 ──────────────────────────────────────────────

class WsQuoteClient:
    """腾讯行情 WebSocket 客户端.

    使用方式:
        client = WsQuoteClient()
        await client.subscribe(["000534", "002353"])
        async for event in client.read_events():
            print(event)
        await client.close()
    """

    # 腾讯行情 WebSocket 地址（多域名轮询）
    # 注意：腾讯 WS 并非标准 WebSocket，实际为 HTTP 长轮询/推送混合协议
    # 这里使用兼容层：优先 HTTP 长轮询，WS 作为备选
    WS_HOSTS: list[str] = [
        "wss://qt.gtimg.cn/",
        "wss://web.ifzq.gtimg.cn/",
    ]

    # 腾讯 HTTP 行情 API（长轮询降级用）
    # 格式: https://qt.gtimg.cn/q=sh600000,sz000001
    HTTP_QUOTE_URL: str = "https://qt.gtimg.cn/q"

    # 重连配置
    MAX_RECONNECT: int = 5
    BASE_BACKOFF: float = 1.0      # 基础退避秒数
    MAX_BACKOFF: float = 60.0      # 最大退避秒数
    CONNECT_TIMEOUT: float = 10.0  # 连接超时

    # 消息队列配置
    QUEUE_MAXSIZE: int = 1000      # 有界队列，防积压

    # 心跳配置（60秒 = 1分钟，避免请求过频被拉黑）
    HEARTBEAT_INTERVAL: float = 60.0  # 秒

    # 请求频率限制（防拉黑）
    MIN_SUBSCRIBE_INTERVAL: float = 60.0  # 两次订阅间隔最少60秒
    MAX_CODES_PER_BATCH: int = 50         # 单次订阅最多50个标的
    MIN_HTTP_POLL_INTERVAL: float = 60.0   # HTTP 轮询最少间隔60秒

    def __init__(self, host: str | None = None) -> None:
        self._host = host or random.choice(self.WS_HOSTS)
        self._ws: Any | None = None
        self._queue: asyncio.Queue[QuoteEvent] = asyncio.Queue(maxsize=self.QUEUE_MAXSIZE)
        self._subscribed_codes: set[str] = set()
        self._reconnect_count: int = 0
        self._running: bool = False
        self._reader_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._closed: bool = False

        # 频率限制状态
        self._last_subscribe_time: float = 0.0  # 上次订阅时间戳
        self._pending_codes: list[str] = []     # 待批量订阅的代码
        self._batch_timer: asyncio.Task | None = None  # 批量订阅定时器

    # ── 公共 API ──────────────────────────────────────────────────

    async def subscribe(self, codes: list[str]) -> None:
        """订阅指定标的的实时报价（带频率限制）.

        防拉黑机制:
        - 两次订阅间隔最少 60 秒
        - 单次最多 50 个标的，超出的分批处理
        - 高频调用时自动合并为批量订阅

        Args:
            codes: 股票代码列表（如 ["000534", "002353"]）
        """
        if self._closed:
            raise RuntimeError("Client is closed")

        # 去重并记录新代码
        new_codes = [c for c in codes if c not in self._subscribed_codes]
        if not new_codes:
            return

        self._subscribed_codes.update(new_codes)
        self._pending_codes.extend(new_codes)

        # 检查距离上次订阅的时间
        now = time.time()
        elapsed = now - self._last_subscribe_time

        if elapsed >= self.MIN_SUBSCRIBE_INTERVAL:
            # 可以直接订阅
            await self._flush_subscribe()
        else:
            # 需要等待，启动批量定时器
            if not self._batch_timer or self._batch_timer.done():
                wait = self.MIN_SUBSCRIBE_INTERVAL - elapsed
                logger.info(f"Subscribe rate limit: waiting {wait:.1f}s to batch {len(self._pending_codes)} codes")
                self._batch_timer = asyncio.create_task(self._delayed_subscribe(wait))

        if not self._running:
            self._running = True
            self._reader_task = asyncio.create_task(self._reader_loop())
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def read_events(self) -> AsyncIterator[QuoteEvent]:
        """读取行情事件流（异步迭代器）.

        使用方式:
            async for event in client.read_events():
                process(event)
        """
        while not self._closed:
            try:
                event = await asyncio.wait_for(
                    self._queue.get(),
                    timeout=1.0,
                )
                yield event
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.warning(f"read_events error: {e}")
                break

    async def close(self) -> None:
        """关闭连接并清理资源."""
        self._closed = True
        self._running = False

        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass

        if self._ws and not self._ws.closed:
            await self._ws.close()
            logger.info("WebSocket connection closed")

    @property
    def is_connected(self) -> bool:
        """当前是否已连接."""
        return self._ws is not None and not self._ws.closed

    @property
    def reconnect_count(self) -> int:
        """当前重连次数."""
        return self._reconnect_count

    async def _flush_subscribe(self) -> None:
        """立即执行待订阅的代码（分批处理，每批最多50个）."""
        if not self._pending_codes:
            return

        # 确保连接
        if self._ws is None or self._ws.closed:
            await self._connect()

        # 分批订阅
        batch = self._pending_codes[:self.MAX_CODES_PER_BATCH]
        self._pending_codes = self._pending_codes[self.MAX_CODES_PER_BATCH:]

        await self._send_subscribe(batch)
        self._last_subscribe_time = time.time()

        # 如果还有剩余的，继续分批
        if self._pending_codes:
            logger.info(f"Batch subscribe: {len(self._pending_codes)} codes remaining for next batch")
            # 等待间隔后订阅下一批
            self._batch_timer = asyncio.create_task(
                self._delayed_subscribe(self.MIN_SUBSCRIBE_INTERVAL)
            )

    async def _delayed_subscribe(self, delay: float) -> None:
        """延迟后执行批量订阅."""
        await asyncio.sleep(delay)
        await self._flush_subscribe()

    # ── 内部方法 ──────────────────────────────────────────────────

    async def _connect(self) -> None:
        """建立 WebSocket 连接."""
        try:
            logger.info(f"Connecting to {self._host}...")
            self._ws = await websockets.connect(
                self._host,
                ping_interval=None,  # 我们自己管理心跳
                close_timeout=5.0,
            )
            self._reconnect_count = 0
            logger.info("WebSocket connected")

            # 发送订阅
            if self._subscribed_codes:
                await self._send_subscribe(list(self._subscribed_codes))

        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}")
            raise

    async def _send_subscribe(self, codes: list[str]) -> None:
        """发送订阅消息."""
        if not self._ws or self._ws.closed:
            return

        # 腾讯行情订阅格式: 代码前缀 + 代码
        # 上海: sh+code, 深圳: sz+code
        formatted = []
        for code in codes:
            if code.startswith("6"):
                formatted.append(f"sh{code}")
            else:
                formatted.append(f"sz{code}")

        # 腾讯 WebSocket 订阅消息格式（模拟）
        msg = json.dumps({
            "cmd": "subscribe",
            "codes": formatted,
        })
        await self._ws.send(msg)
        logger.debug(f"Subscribed to {len(codes)} codes")

    async def _reader_loop(self) -> None:
        """主读取循环：接收消息 → 解析 → 入队.

        支持两种模式:
        1. WebSocket 模式: 实时推送（如果连接成功）
        2. HTTP 长轮询降级: 定时拉取（60秒间隔，防拉黑）
        """
        # 尝试 WebSocket 连接
        ws_mode = False
        if self._ws and not self._ws.closed:
            ws_mode = True
        else:
            # WS 不可用，切换到 HTTP 长轮询
            logger.info("WebSocket not available, switching to HTTP long-polling mode")
            await self._http_poll_loop()
            return

        while self._running and not self._closed:
            try:
                if ws_mode and (not self._ws or self._ws.closed):
                    # WS 断开，尝试重连
                    if not await self._try_reconnect():
                        logger.info("WebSocket reconnect failed, switching to HTTP long-polling")
                        await self._http_poll_loop()
                        return
                    continue

                if ws_mode:
                    msg = await asyncio.wait_for(
                        self._ws.recv(),
                        timeout=self.HEARTBEAT_INTERVAL * 2,
                    )
                    await self._handle_message(msg)
                else:
                    # HTTP 模式
                    await self._http_poll_once()
                    await asyncio.sleep(self.MIN_HTTP_POLL_INTERVAL)

            except asyncio.TimeoutError:
                # 超时检查连接状态
                if ws_mode and self._ws and not self._ws.closed:
                    await self._send_ping()
                continue

            except ConnectionClosed as e:
                logger.warning(f"WebSocket closed: {e}")
                if ws_mode:
                    # 先尝试重连，不立即降级
                    if not await self._try_reconnect():
                        logger.info("WebSocket reconnect failed, switching to HTTP long-polling")
                        await self._http_poll_loop()
                        return
                continue

            except Exception as e:
                logger.error(f"Reader loop error: {e}")
                await asyncio.sleep(1.0)
                continue

    async def _handle_message(self, raw: str | bytes) -> None:
        """解析单条 WebSocket 消息."""
        try:
            text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            if text.startswith("{"):
                data = json.loads(text)
                event = self._parse_json_event(data)
            else:
                event = self._parse_text_event(text)

            if event:
                # 队列满时丢弃最旧消息（防积压）
                if self._queue.full():
                    try:
                        self._queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                await self._queue.put(event)

        except json.JSONDecodeError:
            logger.debug(f"Non-JSON message: {raw[:100]}")
        except Exception as e:
            logger.warning(f"Message parse error: {e}")

    def _parse_json_event(self, data: dict) -> QuoteEvent | None:
        """解析 JSON 格式行情数据."""
        code = data.get("code", "")
        if not code:
            return None

        # 去除前缀
        code = code.replace("sh", "").replace("sz", "")

        return QuoteEvent(
            code=code,
            price=float(data.get("price", 0)),
            change_pct=float(data.get("change_pct", 0)),
            volume=float(data.get("volume", 0)),
        )

    def _parse_text_event(self, raw: str) -> QuoteEvent | None:
        """解析文本格式行情数据（腾讯原始格式）."""
        # 腾讯原始格式示例: v_sh000001="1~上证指数~..."
        # 这里做简化处理，实际需根据真实格式调整
        try:
            if "~" in raw:
                parts = raw.split("~")
                if len(parts) >= 3:
                    code = parts[0].replace("v_sh", "").replace("v_sz", "")
                    price = float(parts[2]) if parts[2] else 0.0
                    return QuoteEvent(
                        code=code,
                        price=price,
                        change_pct=0.0,
                        volume=0.0,
                    )
        except (ValueError, IndexError):
            pass
        return None

    async def _try_reconnect(self) -> bool:
        """尝试重连，指数退避.

        Returns:
            bool: 是否成功重连
        """
        if self._reconnect_count >= self.MAX_RECONNECT:
            logger.error(f"Max reconnect ({self.MAX_RECONNECT}) reached, giving up")
            return False

        self._reconnect_count += 1
        backoff = min(
            self.BASE_BACKOFF * (2 ** (self._reconnect_count - 1)),
            self.MAX_BACKOFF,
        )
        # 添加 jitter 避免重连风暴
        backoff = backoff * (0.5 + random.random())

        logger.info(f"Reconnecting in {backoff:.1f}s (attempt {self._reconnect_count}/{self.MAX_RECONNECT})...")
        await asyncio.sleep(backoff)

        try:
            await self._connect()
            return True
        except Exception as e:
            logger.error(f"Reconnect failed: {e}")
            return False

    async def _heartbeat_loop(self) -> None:
        """心跳循环：定期发送 ping 保持连接."""
        while self._running and not self._closed:
            try:
                await asyncio.sleep(self.HEARTBEAT_INTERVAL)
                if self._ws and not self._ws.closed:
                    await self._send_ping()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Heartbeat error: {e}")

    async def _send_ping(self) -> None:
        """发送心跳消息."""
        if self._ws and not self._ws.closed:
            try:
                # 发送空消息或特定 ping 格式
                await self._ws.send(json.dumps({"cmd": "ping"}))
            except Exception as e:
                logger.debug(f"Ping failed: {e}")

    # ── HTTP 长轮询降级 ────────────────────────────────────────────

    async def _http_poll_loop(self) -> None:
        """HTTP 长轮询循环（WebSocket 不可用时降级）.

        每 60 秒拉取一次行情，防拉黑。
        """
        logger.info(f"HTTP long-polling started for {len(self._subscribed_codes)} codes")
        while self._running and not self._closed:
            try:
                await self._http_poll_once()
            except Exception as e:
                logger.error(f"HTTP poll error: {e}")
            await asyncio.sleep(self.MIN_HTTP_POLL_INTERVAL)
        logger.info("HTTP long-polling stopped")

    async def _http_poll_once(self) -> None:
        """单次 HTTP 行情拉取.

        使用腾讯 HTTP API: https://qt.gtimg.cn/q=sh600000,sz000001
        返回格式: v_sh600000="1~股票名~..."
        """
        if not self._subscribed_codes:
            return

        # 格式化代码
        codes = list(self._subscribed_codes)[:self.MAX_CODES_PER_BATCH]
        formatted = []
        for code in codes:
            if code.startswith("6"):
                formatted.append(f"sh{code}")
            else:
                formatted.append(f"sz{code}")

        url = f"{self.HTTP_QUOTE_URL}={','.join(formatted)}"

        try:
            import urllib.request
            with urllib.request.urlopen(url, timeout=10.0) as resp:
                text = resp.read().decode("gbk")  # 腾讯返回 GBK 编码

            # 解析返回数据
            for line in text.strip().split(";"):
                line = line.strip()
                if not line:
                    continue
                event = self._parse_text_event(line)
                if event:
                    if self._queue.full():
                        try:
                            self._queue.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                    await self._queue.put(event)

            logger.debug(f"HTTP poll: {len(codes)} codes, {len(text)} bytes")

        except Exception as e:
            logger.warning(f"HTTP poll failed: {e}")


# ── 便捷函数 ──────────────────────────────────────────────────────

async def create_ws_client(codes: list[str]) -> WsQuoteClient:
    """一键创建并订阅的便捷函数."""
    client = WsQuoteClient()
    await client.subscribe(codes)
    return client
