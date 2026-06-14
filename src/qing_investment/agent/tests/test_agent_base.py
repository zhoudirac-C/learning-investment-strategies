"""Agent 基类 + 成本追踪 单元测试。"""
from __future__ import annotations

from decimal import Decimal

import pytest

from qing_investment.agent.base import AgentOutput, Agent
from qing_investment.agent.tools.cost_tracker import CostTracker


class TestAgentOutput:
    """AgentOutput 基类测试。"""

    def test_defaults(self):
        output = AgentOutput(agent_name="test")
        assert output.agent_name == "test"
        assert output.findings == []
        assert output.errors == []
        assert output.llm_calls == 0
        assert output.cost_usd == Decimal("0")
        assert output.latency_ms == 0.0

    def test_custom_values(self):
        output = AgentOutput(
            agent_name="analyst",
            findings=[{"key": "val"}],
            errors=["err1"],
            llm_calls=2,
            cost_usd=Decimal("0.0006"),
            latency_ms=150.0,
        )
        assert output.agent_name == "analyst"
        assert len(output.findings) == 1
        assert output.llm_calls == 2
        assert output.cost_usd == Decimal("0.0006")
        assert output.latency_ms == 150.0

    def test_json_serializable(self):
        output = AgentOutput(agent_name="test", llm_calls=1, cost_usd=Decimal("0.0003"))
        # model_dump(mode='json') 会序列化 Decimal 为 str
        data = output.model_dump(mode="json")
        assert data["agent_name"] == "test"
        assert data["llm_calls"] == 1
        assert data["cost_usd"] == "0.0003"  # Decimal serializes to str in json mode


class TestCostTracker:
    """CostTracker 单元测试。"""

    def test_empty(self):
        ct = CostTracker()
        snap = ct.snapshot()
        assert snap["llm_calls"] == 0
        assert snap["total_cost_usd"] == "0"

    def test_single_call(self):
        ct = CostTracker()
        ct.record_call("deepseek")
        snap = ct.snapshot()
        assert snap["llm_calls"] == 1
        assert snap["total_cost_usd"] == "0.0003"

    def test_multiple_calls(self):
        ct = CostTracker()
        ct.record_call("deepseek")  # 0.0003
        ct.record_call("kimi")      # 0.0005
        ct.record_call("deepseek")  # 0.0003
        snap = ct.snapshot()
        assert snap["llm_calls"] == 3
        assert snap["total_cost_usd"] == "0.0011"

    def test_unknown_provider_fallsback(self):
        ct = CostTracker()
        ct.record_call("unknown_provider")
        snap = ct.snapshot()
        assert snap["llm_calls"] == 1
        assert snap["total_cost_usd"] == "0.0003"  # _DEFAULT_COST

    def test_merge(self):
        a = CostTracker()
        a.record_call("deepseek")  # 0.0003
        b = CostTracker()
        b.record_call("kimi")      # 0.0005
        a.merge(b)
        snap = a.snapshot()
        assert snap["llm_calls"] == 2
        assert snap["total_cost_usd"] == "0.0008"

    def test_provider_cost_lookup(self):
        assert CostTracker.provider_cost("deepseek") == Decimal("0.0003")
        assert CostTracker.provider_cost("kimi") == Decimal("0.0005")
        assert CostTracker.provider_cost("nonexistent") == Decimal("0.0003")


class TestMarketAnalystAgent:
    """MarketAnalystAgent 测试（无 LLM 的错误路径）。"""

    def test_market_analyst_no_llm(self):
        """MarketAnalystAgent 无 LLM 时返回 error 而不是崩溃。"""
        from qing_investment.agent.agents.market_analyst import MarketAnalystAgent

        agent = MarketAnalystAgent(llm=None)  # ✅ 可以实例化（有 run 实现）

        async def _run():
            return await agent.run(prompt="")  # 空 prompt → error finding

        import asyncio
        output = asyncio.run(_run())
        assert len(output.errors) > 0
        assert output.agent_name == "market_analyst"
        assert output.llm_calls == 0
        assert output.cost_usd == Decimal("0")

    def test_agent_output_abc(self):
        """验证 Agent 类确实是 ABC，不能直接实例化。"""
        with pytest.raises(TypeError):
            Agent()  # ABC can't be instantiated directly
