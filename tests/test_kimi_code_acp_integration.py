import json
from unittest.mock import MagicMock

import pytest

from qing_investment.agent.graph import nodes


def _fake_response(content: str):
    class _R:
        def __init__(self, c):
            self.content = c
    return _R(content)


def test_safe_llm_invoke_acp_first_with_fallback(monkeypatch):
    """When KIMI_CODE_ACP_FIRST=1 and ACP returns too-short output, fall back to provider."""
    monkeypatch.setenv("KIMI_CODE_ACP_FIRST", "1")

    acp = MagicMock()
    acp.invoke.return_value = _fake_response("short")
    remote = MagicMock()
    remote.invoke.return_value = _fake_response("fallback remote content")

    def fake_get_llm_client(provider=None):
        if provider == "kimi-code-acp":
            return acp
        return remote

    monkeypatch.setattr(nodes, "get_llm_client", fake_get_llm_client)

    result = nodes._safe_llm_invoke("prompt", min_length=50)
    assert result == "fallback remote content"
    acp.invoke.assert_called_once_with("prompt")
    remote.invoke.assert_called_once()
