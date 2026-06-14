"""LLM 调用成本追踪器。

设计原则:
    - 轻量：不依赖外部服务，纯内存计算
    - 精确：按 provider + 实际调用次数累加
    - 可测试：支持 mock provider
"""

from __future__ import annotations

import logging
from decimal import Decimal

logger = logging.getLogger(__name__)

# Provider 单价（USD/次调用，按输出 token ≈500 估算）
# 价格基准时间：2026-06-14
# 数据来源：各厂商官网公布价
_PROVIDER_COST: dict[str, Decimal] = {
    "deepseek": Decimal("0.0003"),      # DeepSeek V4 Flash
    "kimi": Decimal("0.0005"),          # Moonshot v1 128k
    "claude": Decimal("0.0015"),        # Claude Sonnet 4
    "openai": Decimal("0.0010"),        # GPT-4o mini
    "qwen": Decimal("0.0008"),          # Qwen Max
    "zhipu": Decimal("0.0010"),         # GLM-4
    "siliconflow": Decimal("0.0002"),   # DeepSeek V3 via SiliconFlow
}

_DEFAULT_COST = Decimal("0.0003")


class CostTracker:
    """轻量 LLM 调用成本追踪器。

    用法:
        tracker = CostTracker()
        tracker.record_call("deepseek")
        tracker.record_call("kimi")
        print(tracker.snapshot())  # {"llm_calls": 2, "total_cost_usd": "0.0008"}
    """

    def __init__(self) -> None:
        self.calls: int = 0
        self._total_cost: Decimal = Decimal("0")

    def record_call(self, provider: str = "deepseek") -> None:
        """记录一次 LLM 调用。

        Args:
            provider: provider 名称，对应 _PROVIDER_COST 中的 key
        """
        cost = _PROVIDER_COST.get(provider, _DEFAULT_COST)
        self.calls += 1
        self._total_cost += cost
        logger.debug("[CostTracker] record_call: provider=%s cost=%s total_calls=%d total_cost=%s", provider, cost, self.calls, self._total_cost)

    def merge(self, other: CostTracker) -> None:
        """合并另一个追踪器的统计（用于跨节点叠加）。"""
        self.calls += other.calls
        self._total_cost += other._total_cost
        logger.debug("[CostTracker] merge: added_calls=%d added_cost=%s total_calls=%d", other.calls, other._total_cost, self.calls)

    def snapshot(self) -> dict:
        """返回当前快照。"""
        snap = {"llm_calls": self.calls, "total_cost_usd": str(self._total_cost)}
        logger.info("[CostTracker] snapshot: %s", snap)
        return snap

    @classmethod
    def provider_cost(cls, provider: str) -> Decimal:
        """查询指定 provider 的单次调用成本。"""
        return _PROVIDER_COST.get(provider, _DEFAULT_COST)
