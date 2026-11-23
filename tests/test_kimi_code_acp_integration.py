from unittest.mock import MagicMock

import pytest

from qing_investment.agent.graph import nodes


def _fake_response(content: str):
    class _R:
        def __init__(self, c):
            self.content = c
    return _R(content)


def test_safe_llm_invoke_ignores_acp_first(monkeypatch):
    """KIMI_CODE_ACP_FIRST=1 也不再调用 ACP，直接使用配置 provider。"""
    monkeypatch.setenv("KIMI_CODE_ACP_FIRST", "1")

    acp = MagicMock()
    acp.invoke.return_value = _fake_response("short")
    remote = MagicMock()
    remote.invoke.return_value = _fake_response("configured remote content")

    def fake_get_llm_client(provider=None):
        if provider == "kimi-code-acp":
            return acp
        return remote

    monkeypatch.setattr(nodes, "get_llm_client", fake_get_llm_client)

    result = nodes._safe_llm_invoke("prompt", min_length=20)
    assert result == "configured remote content"
    acp.invoke.assert_not_called()
    remote.invoke.assert_called_once()


def test_disabled_acp_first_preserves_remote_fallback_and_stops_clients(
    monkeypatch, tmp_path
):
    local = MagicMock()
    configured = MagicMock()
    configured.invoke.side_effect = RuntimeError("configured failed")
    fallback = MagicMock()
    fallback.invoke.return_value = _fake_response("fallback remote content")
    client_calls = []

    def fake_get_llm_client(provider=None):
        client_calls.append(provider)
        if provider == "kimi-code-acp":
            raise ValueError("ACP disabled")
        return {
            None: configured,
            "zhipu": fallback,
        }[provider]

    monkeypatch.setattr(nodes.settings, "llm_provider", "sensenova")
    monkeypatch.setenv("QING_AGENT_FALLBACK_PROVIDERS", "kimi-code-acp,zhipu")
    monkeypatch.setattr(nodes, "_LLM_FAILURE_LOG_PATH", tmp_path / "failures.jsonl")
    monkeypatch.setattr(nodes, "get_llm_client", fake_get_llm_client)

    result = nodes._safe_llm_invoke("prompt", use_acp_first=True)

    assert result == "fallback remote content"
    assert client_calls == [None, "kimi-code-acp", "zhipu"]
    local.invoke.assert_not_called()
    local.stop.assert_not_called()
    assert configured.stop.call_count == 1
    assert fallback.stop.call_count == 1


def test_acp_constructor_is_not_called_when_acp_first_enabled(
    monkeypatch, tmp_path
):
    remote = MagicMock()
    remote.invoke.return_value = _fake_response("configured remote content")
    client_calls = []

    def fake_get_llm_client(provider=None):
        client_calls.append(provider)
        if provider == "kimi-code-acp":
            raise ValueError("ACP disabled")
        return remote

    monkeypatch.setenv("KIMI_CODE_ACP_FIRST", "1")
    monkeypatch.setenv("QING_AGENT_FALLBACK_PROVIDERS", "")
    monkeypatch.setattr(nodes, "_LLM_FAILURE_LOG_PATH", tmp_path / "failures.jsonl")
    monkeypatch.setattr(nodes, "get_llm_client", fake_get_llm_client)

    result = nodes._safe_llm_invoke("prompt")

    assert result == "configured remote content"
    assert client_calls == [None]
    remote.invoke.assert_called_once_with("prompt")
