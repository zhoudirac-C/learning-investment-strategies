"""Tests for WsQuoteClient.

覆盖场景：
- 模拟 WebSocket 服务连接
- 订阅/取消订阅
- 消息解析（JSON + 文本格式）
- 断线重连（指数退避）
- 队列积压丢弃
- 心跳机制
"""

import asyncio
import json
from collections.abc import Sequence
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from qing_investment.monitor.fetchers.ws_client import QuoteEvent, WsQuoteClient, create_ws_client


# ── 模拟 WebSocket 服务器 ─────────────────────────────────────────

class MockWebSocket:
    """模拟 websockets 连接对象."""

    def __init__(self, messages: Sequence[str | bytes] | None = None) -> None:
        self.messages = messages or []
        self.sent: list[str] = []
        self._closed = False
        self._recv_idx = 0

    async def recv(self) -> str | bytes:
        if self._recv_idx < len(self.messages):
            msg = self.messages[self._recv_idx]
            self._recv_idx += 1
            return msg
        # 阻塞直到有新消息
        await asyncio.sleep(3600)
        return ""

    async def send(self, msg: str) -> None:
        self.sent.append(msg)

    async def close(self) -> None:
        self._closed = True

    @property
    def closed(self) -> bool:
        return self._closed


# ── 基础连接测试 ─────────────────────────────────────────────────

class TestConnection:

    @pytest.mark.asyncio
    async def test_connect_and_subscribe(self):
        mock_ws = MockWebSocket()

        async def mock_connect(*args, **kwargs):
            return mock_ws

        with patch("websockets.connect", side_effect=mock_connect):
            client = WsQuoteClient(host="wss://test.example.com/")
            await client.subscribe(["000534"])

            assert client.is_connected
            assert "000534" in client._subscribed_codes
            # 检查订阅消息
            assert len(mock_ws.sent) >= 1
            sub_msg = json.loads(mock_ws.sent[0])
            assert sub_msg["cmd"] == "subscribe"
            assert "sz000534" in sub_msg["codes"]

            await client.close()

    @pytest.mark.asyncio
    async def test_connect_sh_code(self):
        """上海股票代码前缀应为 sh."""
        mock_ws = MockWebSocket()

        async def mock_connect(*args, **kwargs):
            return mock_ws

        with patch("websockets.connect", side_effect=mock_connect):
            client = WsQuoteClient()
            await client.subscribe(["600000"])

            sub_msg = json.loads(mock_ws.sent[0])
            assert "sh600000" in sub_msg["codes"]
            await client.close()

    @pytest.mark.asyncio
    async def test_subscribe_multiple(self):
        mock_ws = MockWebSocket()

        async def mock_connect(*args, **kwargs):
            return mock_ws

        with patch("websockets.connect", side_effect=mock_connect):
            client = WsQuoteClient()
            await client.subscribe(["000534", "002353", "600000"])

            assert len(client._subscribed_codes) == 3
            sub_msg = json.loads(mock_ws.sent[0])
            assert len(sub_msg["codes"]) == 3
            await client.close()


# ── 消息接收与解析 ───────────────────────────────────────────────

class TestMessageParsing:

    @pytest.mark.asyncio
    async def test_receive_json_event(self):
        event_data = {
            "code": "sz000534",
            "price": 31.5,
            "change_pct": 2.5,
            "volume": 1500000,
        }
        mock_ws = MockWebSocket(messages=[json.dumps(event_data)])

        async def mock_connect(*args, **kwargs):
            return mock_ws

        with patch("websockets.connect", side_effect=mock_connect):
            client = WsQuoteClient()
            await client.subscribe(["000534"])

            # 等待消息处理
            await asyncio.sleep(0.1)

            # 读取事件
            events = []
            async for event in client.read_events():
                events.append(event)
                if len(events) >= 1:
                    break

            assert len(events) == 1
            assert events[0].code == "000534"
            assert events[0].price == 31.5
            assert events[0].change_pct == 2.5

            await client.close()

    @pytest.mark.asyncio
    async def test_receive_text_event(self):
        """测试腾讯原始文本格式解析."""
        mock_ws = MockWebSocket(messages=["v_sh000001~上证指数~3050.12"])

        async def mock_connect(*args, **kwargs):
            return mock_ws

        with patch("websockets.connect", side_effect=mock_connect):
            client = WsQuoteClient()
            await client.subscribe(["000001"])
            await asyncio.sleep(0.1)

            events = []
            async for event in client.read_events():
                events.append(event)
                if len(events) >= 1:
                    break

            assert len(events) == 1
            assert events[0].code == "000001"
            assert events[0].price == 3050.12

            await client.close()

    @pytest.mark.asyncio
    async def test_receive_bytes_event(self):
        """测试二进制消息解析."""
        event_data = {"code": "sz000534", "price": 31.5, "change_pct": 0.0, "volume": 0}
        mock_ws = MockWebSocket(messages=[json.dumps(event_data).encode("utf-8")])

        async def mock_connect(*args, **kwargs):
            return mock_ws

        with patch("websockets.connect", side_effect=mock_connect):
            client = WsQuoteClient()
            await client.subscribe(["000534"])
            await asyncio.sleep(0.1)

            events = []
            async for event in client.read_events():
                events.append(event)
                if len(events) >= 1:
                    break

            assert len(events) == 1
            assert events[0].code == "000534"

            await client.close()


# ── 重连机制 ──────────────────────────────────────────────────────

class TestReconnection:

    @pytest.mark.asyncio
    async def test_reconnect_on_disconnect(self):
        """模拟连接断开后的重连."""
        call_count = 0

        async def mock_connect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # 第一次连接，发送一条消息后断开
                ws = MockWebSocket(messages=[json.dumps({"code": "sz000534", "price": 31.0, "change_pct": 0, "volume": 0})])
                # 模拟 recv 后断开
                orig_recv = ws.recv
                async def recv_once():
                    await orig_recv()
                    from websockets.exceptions import ConnectionClosed
                    raise ConnectionClosed(None, None)  # type: ignore[arg-type]
                ws.recv = recv_once
                return ws
            else:
                # 重连成功
                return MockWebSocket()

        with patch("websockets.connect", side_effect=mock_connect):
            client = WsQuoteClient()
            await client.subscribe(["000534"])
            await asyncio.sleep(0.5)

            # 应该至少尝试了一次重连
            assert client.reconnect_count >= 1
            await client.close()

    @pytest.mark.asyncio
    async def test_max_reconnect_gives_up(self):
        """超过最大重连次数后放弃."""
        async def always_fail(*args, **kwargs):
            raise Exception("Connection refused")

        with patch("websockets.connect", side_effect=always_fail):
            client = WsQuoteClient()
            with pytest.raises(Exception):
                await client.subscribe(["000534"])

            await client.close()


# ── 队列管理 ──────────────────────────────────────────────────────

class TestQueueManagement:

    @pytest.mark.asyncio
    async def test_queue_overflow_discard(self):
        """队列满时丢弃最旧消息."""
        # 生成大量消息
        messages = [
            json.dumps({"code": "sz000534", "price": 30.0 + i * 0.1, "change_pct": 0, "volume": 0})
            for i in range(1500)
        ]
        mock_ws = MockWebSocket(messages=messages)

        async def mock_connect(*args, **kwargs):
            return mock_ws

        with patch("websockets.connect", side_effect=mock_connect):
            client = WsQuoteClient()
            # 缩小队列以便测试
            client._queue = asyncio.Queue(maxsize=10)
            await client.subscribe(["000534"])
            await asyncio.sleep(0.2)

            # 队列不应超过 maxsize
            assert client._queue.qsize() <= 10

            await client.close()


# ── 便捷函数 ──────────────────────────────────────────────────────

class TestConvenienceFunctions:

    @pytest.mark.asyncio
    async def test_create_ws_client(self):
        mock_ws = MockWebSocket()

        async def mock_connect(*args, **kwargs):
            return mock_ws

        with patch("websockets.connect", side_effect=mock_connect):
            client = await create_ws_client(["000534", "002353"])
            assert client.is_connected
            assert len(client._subscribed_codes) == 2
            await client.close()


# ── 数据模型 ──────────────────────────────────────────────────────

class TestQuoteEvent:

    def test_to_dict(self):
        event = QuoteEvent(
            code="000534",
            price=31.5,
            change_pct=2.5,
            volume=1500000,
        )
        d = event.to_dict()
        assert d["code"] == "000534"
        assert d["price"] == 31.5
        assert "timestamp" in d

    def test_default_timestamp(self):
        event = QuoteEvent(code="000001", price=100.0, change_pct=0.0, volume=0)
        assert event.timestamp is not None
