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

    result = nodes._safe_llm_invoke("prompt", min_length=20)
    assert result == "fallback remote content"
    acp.invoke.assert_called_once_with("prompt")
    remote.invoke.assert_called_once()


def test_acp_fallback_is_deduplicated_and_every_client_is_stopped(
    monkeypatch, tmp_path
):
    local = MagicMock()
    local.invoke.return_value = _fake_response("")
    configured = MagicMock()
    configured.invoke.side_effect = RuntimeError("configured failed")
    fallback = MagicMock()
    fallback.invoke.return_value = _fake_response("fallback remote content")
    client_calls = []

    def fake_get_llm_client(provider=None):
        client_calls.append(provider)
        return {
            "kimi-code-acp": local,
            None: configured,
            "zhipu": fallback,
        }[provider]

    monkeypatch.setattr(nodes.settings, "llm_provider", "sensenova")
    monkeypatch.setenv("QING_AGENT_FALLBACK_PROVIDERS", "kimi-code-acp,zhipu")
    monkeypatch.setattr(nodes, "_LLM_FAILURE_LOG_PATH", tmp_path / "failures.jsonl")
    monkeypatch.setattr(nodes, "get_llm_client", fake_get_llm_client)

    result = nodes._safe_llm_invoke("prompt", use_acp_first=True)

    assert result == "fallback remote content"
    assert client_calls == ["kimi-code-acp", None, "zhipu"]
    assert local.stop.call_count == 1
    assert configured.stop.call_count == 1
    assert fallback.stop.call_count == 1


def test_acp_constructor_failure_falls_back_to_configured_provider(
    monkeypatch, tmp_path
):
    remote = MagicMock()
    remote.invoke.return_value = _fake_response("configured remote content")
    client_calls = []

    def fake_get_llm_client(provider=None):
        client_calls.append(provider)
        if provider == "kimi-code-acp":
            raise ValueError("invalid ACP timeout")
        return remote

    monkeypatch.setenv("KIMI_CODE_ACP_FIRST", "1")
    monkeypatch.setenv("QING_AGENT_FALLBACK_PROVIDERS", "")
    monkeypatch.setattr(nodes, "_LLM_FAILURE_LOG_PATH", tmp_path / "failures.jsonl")
    monkeypatch.setattr(nodes, "get_llm_client", fake_get_llm_client)

    result = nodes._safe_llm_invoke("prompt")

    assert result == "configured remote content"
    assert client_calls == ["kimi-code-acp", None]
    remote.invoke.assert_called_once_with("prompt")
