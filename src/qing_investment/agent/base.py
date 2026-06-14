"""Agent 基类 — 对标 AlphaAnalyst 的 Agent(ABC) + AgentOutput(BaseModel)。

设计原则:
    - 每个 Agent 独立 LLM 实例（便于成本追踪和模型切换）
    - 通过 LLMProtocol 解耦，不直接依赖 ChatOpenAI/DeepSeek
    - AgentOutput 统一输出格式
    - 向后兼容：不破坏现有的 LangGraph 节点函数
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any, Protocol

import logging
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class AgentOutput(BaseModel):
    """标准化 Agent 输出。"""

    agent_name: str
    findings: list[dict] = Field(default_factory=list, description="分析发现")
    errors: list[str] = Field(default_factory=list, description="错误列表")
    llm_calls: int = Field(default=0, description="本轮调用的 LLM 次数")
    cost_usd: Decimal = Field(default=Decimal("0"), description="本轮估算成本（USD）")
    latency_ms: float = Field(default=0.0, description="执行耗时（ms）")


class LLMProtocol(Protocol):
    """LLM 客户端协议 — 允许不同 provider 注入。

    鸭子类型匹配：任何有 chat() + model_name + cost_per_call 的对象均可。
    """

    def chat(self, messages: list[dict], **kwargs) -> dict: ...
    @property
    def model_name(self) -> str: ...
    @property
    def cost_per_call(self) -> Decimal: ...


class Agent(ABC):
    """所有 Agent 的基类。

    子类必须实现:
        - run(**kwargs) -> AgentOutput

    子类应继承:
        - _track_llm_call() — 每次调 LLM 后调用
        - _reset_stats() — run 开始时调用
        - _build_output() — run 结束时调用
    """

    name: str = "agent"

    def __init__(self, llm: Any | None = None):
        self.llm = llm
        self._llm_calls = 0
        self._total_cost = Decimal("0")
        self._start_time = 0.0

    @abstractmethod
    async def run(self, **kwargs) -> AgentOutput:
        """执行分析逻辑。"""
        ...

    # ── 内部方法 ──

    def _track_llm_call(self, provider: str = "unknown") -> None:
        """记录一次 LLM 调用（子类在调 LLM 后必须调用此方法）。

        Args:
            provider: provider 名称（仅用于日志）
        """
        self._llm_calls += 1
        if self.llm and hasattr(self.llm, "cost_per_call"):
            cost = self.llm.cost_per_call
            if isinstance(cost, Decimal):
                self._total_cost += cost
            elif isinstance(cost, (int, float)):
                self._total_cost += Decimal(str(cost))
        logger.debug("[%s] _track_llm_call: calls=%d cost=%s", self.name, self._llm_calls, self._total_cost)

    def _reset_stats(self) -> None:
        """重置统计（每次 run 前调用）。"""
        self._llm_calls = 0
        self._total_cost = Decimal("0")
        self._start_time = __import__("time").time()
        logger.debug("[%s] _reset_stats", self.name)

    def _build_output(
        self, findings: list[dict], errors: list[str] | None = None
    ) -> AgentOutput:
        """构造标准化输出。"""
        output = AgentOutput(
            agent_name=self.name,
            findings=findings,
            errors=errors or [],
            llm_calls=self._llm_calls,
            cost_usd=self._total_cost,
            latency_ms=(__import__("time").time() - self._start_time) * 1000,
        )
        logger.info(
            "[%s] _build_output: findings=%d errors=%d llm_calls=%d cost_usd=%s latency_ms=%.0f",
            self.name, len(findings), len(errors or []),
            output.llm_calls, output.cost_usd, output.latency_ms,
        )
        return output
