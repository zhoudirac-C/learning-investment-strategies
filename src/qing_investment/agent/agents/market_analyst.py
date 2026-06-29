"""MarketAnalystAgent — Agent 基类的示例子类。

不做 LangGraph 节点替换，只作为"增强版"包装器：
    - 封装 LLM 调用逻辑
    - 输出完整的 AgentOutput（含成本追踪）
    - 可被测试框架独立运行验证
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from qing_investment.agent.base import Agent, AgentOutput

logger = logging.getLogger(__name__)


class MarketAnalystAgent(Agent):
    """大盘分析 Agent — 基于基类实现的示例子类。"""

    name = "market_analyst"

    def __init__(self, llm: Any | None = None):
        super().__init__(llm=llm)
        self._prompt_template: str | None = None

    # ── 公开方法 ──

    async def run(self, **kwargs) -> AgentOutput:
        """执行大盘分析，返回标准化输出。

        接收 kwargs 中的参数（与 LangGraph market_analyst 节点兼容）:
            - prompt: str — 已填充的完整 prompt
            - prompt_template: str — 模板（可选）
            - context: dict — 分析上下文数据
        """
        self._reset_stats()
        logger.info("[MarketAnalystAgent.run] starting")

        prompt = kwargs.get("prompt", "")
        if not prompt:
            template = kwargs.get("prompt_template", "")
            context = kwargs.get("context", {})
            if template and context:
                prompt = f"{template}\n\n{json.dumps(context, ensure_ascii=False, indent=2)}"
                logger.info("[MarketAnalystAgent.run] built prompt from template+context: len=%d", len(prompt))
            else:
                logger.warning("[MarketAnalystAgent.run] no prompt provided")
                return self._build_output(
                    findings=[],
                    errors=["No prompt or prompt_template+context provided"],
                )

        try:
            content = await self._invoke_llm(prompt)
            self._track_llm_call()

            parsed = self._parse_response(content)
            return self._build_output(findings=parsed)
        except Exception as e:
            logger.warning("MarketAnalystAgent.run failed: %s", e)
            return self._build_output(findings=[], errors=[str(e)])

    # ── 内部方法 ──

    async def _invoke_llm(self, prompt: str) -> str:
        """调用 LLM（使用 self.llm 或 fallback 到全局 get_llm_client）。

        同步调用通过 asyncio.to_thread 放到线程池执行，并加 120s 硬超时，
        避免在 async 事件循环中阻塞导致整个服务 hang 死。
        """
        prompt_len = len(prompt)
        if self.llm is not None:
            logger.info("[MarketAnalystAgent] _invoke_llm: using injected llm, prompt_len=%d", prompt_len)
            response = await asyncio.wait_for(
                asyncio.to_thread(self.llm.chat, [{"role": "user", "content": prompt}]),
                timeout=120.0,
            )
            content = response.get("content", "")
            logger.info("[MarketAnalystAgent] _invoke_llm: response_len=%d", len(content))
            return content

        logger.info("[MarketAnalystAgent] _invoke_llm: fallback to global get_llm_client(), prompt_len=%d", prompt_len)
        from qing_investment.agent.tools.llm_client import get_llm_client

        llm = get_llm_client()
        result = await asyncio.wait_for(
            asyncio.to_thread(llm.invoke, prompt),
            timeout=120.0,
        )
        content = result.content if hasattr(result, "content") else str(result)
        logger.info("[MarketAnalystAgent] _invoke_llm: response_len=%d", len(content))
        return content

    def _parse_response(self, content: str) -> list[dict]:
        """解析 LLM 响应为 findings 列表。"""
        if not content:
            logger.warning("[MarketAnalystAgent] _parse_response: empty content")
            return []

        try:
            parsed = json.loads(content) if isinstance(content, str) else content
            if isinstance(parsed, dict):
                logger.info("[MarketAnalystAgent] _parse_response: parsed as dict (1 finding)")
                return [parsed]
            if isinstance(parsed, list):
                logger.info("[MarketAnalystAgent] _parse_response: parsed as list (%d findings)", len(parsed))
                return parsed
            logger.warning("[MarketAnalystAgent] _parse_response: unexpected type=%s", type(parsed).__name__)
            return [{"raw": content}]
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning("[MarketAnalystAgent] _parse_response: JSON decode failed: %s", e)
            return [{"raw": content}]
