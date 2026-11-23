import sys
from unittest.mock import MagicMock

import pytest


def _fake_response(content: str):
    class _R:
        def __init__(self, c):
            self.content = c

    return _R(content)


def test_safe_llm_invoke_ignores_local_output_when_acp_disabled(monkeypatch):
    """ACP 环境变量不再触发本地调用，直接使用配置 provider。"""
    monkeypatch.setenv("KIMI_CODE_ACP_FIRST", "1")
    from qing_investment.agent.graph import nodes

    local = MagicMock()
    local.invoke.return_value = _fake_response("{}")
    remote = MagicMock()
    remote.invoke.return_value = _fake_response("configured remote content")

    def fake_get_llm_client(provider=None):
        if provider == "kimi-code-acp":
            return local
        return remote

    monkeypatch.setattr(nodes, "get_llm_client", fake_get_llm_client)

    result = nodes._safe_llm_invoke("prompt", min_length=20)
    assert result == "configured remote content"
    local.invoke.assert_not_called()
    remote.invoke.assert_called_once()


def test_safe_llm_invoke_uses_remote_output_when_no_min_length(monkeypatch):
    """未设置 min_length 时也不启用本地 ACP。"""
    monkeypatch.setenv("KIMI_CODE_ACP_FIRST", "1")
    from qing_investment.agent.graph import nodes

    local = MagicMock()
    local.invoke.return_value = _fake_response("{}")
    remote = MagicMock()
    remote.invoke.return_value = _fake_response("configured remote content")

    def fake_get_llm_client(provider=None):
        if provider == "kimi-code-acp":
            return local
        return remote

    monkeypatch.setattr(nodes, "get_llm_client", fake_get_llm_client)

    result = nodes._safe_llm_invoke("prompt", min_length=0)
    assert result == "configured remote content"
    local.invoke.assert_not_called()
    remote.invoke.assert_called_once()


def test_invoke_logs_short_raw(caplog, monkeypatch):
    """KimiCodeCLIClient.invoke 清洗后过短，应记录 warning 级别原始输出。"""
    import logging

    from qing_investment.agent.tools.kimi_code_cli_client import KimiCodeCLIClient

    client = KimiCodeCLIClient()
    monkeypatch.setattr(client, "_run", lambda prompt: "• {}\n")
    with caplog.at_level(logging.WARNING):
        resp = client.invoke("prompt")
    assert resp.content == "{}"
    assert "suspiciously short output" in caplog.text


def test_citation_validator_rejects_short_output():
    """citation_validator 应对过短的 styled_output 返回不通过。"""
    from qing_investment.agent.graph.nodes import citation_validator

    result = citation_validator({"styled_output": "{}"})
    report = result["citation_report"]
    assert report["valid"] is False
    assert any(i["issue_type"] == "output_too_short" for i in report["issues"])
    assert "输出过短" in report["summary"]
