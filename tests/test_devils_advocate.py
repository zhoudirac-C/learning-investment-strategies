import pytest
from unittest.mock import MagicMock, patch

from qing_investment.agent.agents.devils_advocate import DevilsAdvocateAgent


class _FakeResponse:
    def __init__(self, content):
        self.content = content


@pytest.mark.asyncio
async def test_devils_advocate_uses_default_provider_then_fallback():
    agent = DevilsAdvocateAgent()
    assert agent._target_model is None

    default_llm = MagicMock()
    default_llm.invoke.return_value = _FakeResponse("default response long enough")

    with patch("qing_investment.agent.tools.llm_client.get_llm_client") as mock_get:
        mock_get.return_value = default_llm
        result = await agent.run(market_analysis="test", stock_analysis="test")

    assert agent.used_provider == "default"
