"""_safe_llm_invoke 的 json_mode 参数测试（方案 3：API 层 response_format 双保险）。

背景：k3 (Kimi coding) 端点实测支持 response_format={"type":"json_object"}（2026-10-12），
json_mode=True 时应把该参数传给底层 ChatOpenAI.invoke；客户端不支持 kwargs 时降级裸调用。
"""
from unittest.mock import MagicMock


class _FakeContent:
    def __init__(self, text):
        self.content = text


def _make_client(monkeypatch, capture):
    fake = MagicMock()

    def invoke(prompt, **kwargs):
        capture.update(kwargs)
        return _FakeContent('{"ok": true}')

    fake.invoke = invoke
    monkeypatch.setattr(
        "qing_investment.agent.graph.nodes.get_llm_client", lambda *a, **k: fake
    )
    return fake


def test_json_mode_passes_response_format(monkeypatch):
    from qing_investment.agent.graph import nodes
    capture = {}
    _make_client(monkeypatch, capture)
    out = nodes._safe_llm_invoke("给JSON", use_acp_first=False, json_mode=True)
    assert out == '{"ok": true}'
    assert capture.get("response_format") == {"type": "json_object"}


def test_default_no_response_format(monkeypatch):
    from qing_investment.agent.graph import nodes
    capture = {}
    _make_client(monkeypatch, capture)
    out = nodes._safe_llm_invoke("写文章", use_acp_first=False)
    assert out == '{"ok": true}'
    assert "response_format" not in capture


def test_json_mode_typeerror_falls_back_to_plain_invoke(monkeypatch):
    """客户端不接受 kwargs 时降级为裸 invoke，不报错。"""
    from qing_investment.agent.graph import nodes
    fake = MagicMock()

    def invoke(prompt):
        return _FakeContent('{"ok": true}')

    fake.invoke = invoke  # 不接收 **kwargs
    monkeypatch.setattr(
        "qing_investment.agent.graph.nodes.get_llm_client", lambda *a, **k: fake
    )
    out = nodes._safe_llm_invoke("给JSON", use_acp_first=False, json_mode=True)
    assert out == '{"ok": true}'
