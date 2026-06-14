"""轻量 Kimi Coding Plan 客户端。

Kimi Coding Plan（api.kimi.com/coding）走的是 Anthropic Messages 协议，
不是 OpenAI Chat Completions。ChatOpenAI 不能直接用。

这里提供一个最小客户端，只做一件事：
    发一条 prompt → 收一段 text
不需要 tools、不需要 streaming、不需要多轮对话。

协议参考：https://docs.anthropic.com/en/api/messages
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ── 默认配置 ──

_DEFAULT_MODEL = "kimi-k2-turbo-preview"
_DEFAULT_BASE_URL = "https://api.kimi.com"
_API_PATH = "/coding/v1/messages"
_ENV_KEY = "KIMI_API_KEY"
_TIMEOUT = 120


class KimiCodingResponse:
    """模拟 ChatOpenAI.invoke() 的返回值结构，方便上层统一处理。"""

    def __init__(self, content: str):
        self.content = content

    def __repr__(self) -> str:
        return f"KimiCodingResponse(content_len={len(self.content)})"


class KimiCodingClient:
    """对 Kimi Coding Plan 的极简封装。

    用法与 ChatOpenAI 大致兼容：
        client = KimiCodingClient(api_key="sk-kimi-...")
        resp = client.invoke("prompt text")
        print(resp.content)
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = _DEFAULT_MODEL,
        base_url: str = _DEFAULT_BASE_URL,
        timeout: int = _TIMEOUT,
        max_tokens: int = 4096,
    ):
        self.api_key = api_key or os.environ.get(_ENV_KEY, "")
        if not self.api_key:
            raise ValueError(
                f"Kimi Coding Plan 需要 {_ENV_KEY}。"
                "请在 .env 中设置或传入 api_key。"
            )
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_tokens = max_tokens

        self._client = httpx.Client(timeout=timeout)

    # ── 公开方法 ──

    def invoke(self, prompt: str, **kwargs: Any) -> KimiCodingResponse:
        """发一条 prompt，返回 text 响应。与 ChatOpenAI.invoke() 签名兼容。

        Args:
            prompt: 用户消息文本。
            **kwargs: 额外参数（目前未使用，保留兼容性）。

        Returns:
            KimiCodingResponse，具 .content 属性。

        Raises:
            KimiCodingError: API 返回错误或网络异常。
        """
        logger.info(
            "[KimiCodingClient] invoke: model=%s prompt_len=%d",
            self.model, len(prompt),
        )

        url = f"{self.base_url}{_API_PATH}"
        payload = self._build_payload(prompt)
        logger.debug("[KimiCodingClient] invoke: url=%s payload_len=%d", url, len(payload))

        try:
            response = self._client.post(
                url,
                headers=self._build_headers(),
                json=payload,
            )
        except httpx.TimeoutException:
            raise KimiCodingError(
                f"Request timed out after {self.timeout}s"
            )
        except httpx.RequestError as e:
            raise KimiCodingError(f"Network error: {e}")

        if response.status_code == 200:
            content = self._parse_response(response.json())
            logger.info(
                "[KimiCodingClient] invoke: success response_len=%d",
                len(content),
            )
            return KimiCodingResponse(content=content)

        # ── 错误处理 ──
        status = response.status_code
        try:
            err_body = response.json()
            err_msg = err_body.get("error", {}).get("message", str(err_body))
        except Exception:
            err_msg = response.text[:500]

        logger.warning(
            "[KimiCodingClient] invoke: HTTP %d: %s", status, err_msg,
        )
        raise KimiCodingError(
            f"Kimi Coding Plan API error (HTTP {status}): {err_msg}",
            status_code=status,
        )

    def close(self):
        """释放 httpx 连接池。"""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # ── 内部方法 ──

    def _build_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "User-Agent": "claude-code/0.1.0",
        }

    def _build_payload(self, prompt: str) -> dict[str, Any]:
        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": [
                {"role": "user", "content": prompt},
            ],
        }

    @staticmethod
    def _parse_response(body: dict[str, Any]) -> str:
        """从 Anthropic Messages 响应中提取 text。"""
        content_blocks = body.get("content", [])
        if not content_blocks:
            return ""
        # 取所有 text 块拼接（通常只有一个）
        texts = []
        for block in content_blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                texts.append(block.get("text", ""))
        return "\n".join(texts)


class KimiCodingError(Exception):
    """Kimi Coding Plan API 调用异常。"""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code
