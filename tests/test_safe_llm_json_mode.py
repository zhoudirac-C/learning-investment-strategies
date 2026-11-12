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


def test_provider_fallback_reuses_request_and_skips_configured_provider(monkeypatch):
    from qing_investment.agent.graph import nodes
    from qing_investment.agent.tools import llm_client

    monkeypatch.setattr(nodes.settings, "llm_provider", "primary")
    monkeypatch.setenv(
        "QING_AGENT_FALLBACK_PROVIDERS", "sensenova, primary, zhipu"
    )
    client_calls = []
    invocations = []

    def fake_get_llm_client(provider=None):
        client_calls.append(provider)
        fake = MagicMock()

        def invoke(prompt, **kwargs):
            invocations.append((provider, prompt, kwargs))
            if provider is None:
                raise RuntimeError("primary token limit")
            return _FakeContent("" if provider == "sensenova" else '{"ok": true}')

        fake.invoke = invoke
        return fake

    monkeypatch.setattr(nodes, "get_llm_client", fake_get_llm_client)
    llm_client.reset_provider_usage()

    out = nodes._safe_llm_invoke(
        "给JSON", min_length=2, use_acp_first=False, json_mode=True
    )

    assert out == '{"ok": true}'
    assert client_calls == [None, "sensenova", "zhipu"]
    assert invocations == [
        (provider, "给JSON", {"response_format": {"type": "json_object"}})
        for provider in (None, "sensenova", "zhipu")
    ]
    assert [
        (record["provider"], record["status"])
        for record in llm_client.get_provider_usage_records()
    ] == [
        ("primary", "attempt"),
        ("primary", "failed"),
        ("sensenova", "attempt"),
        ("sensenova", "failed"),
        ("zhipu", "attempt"),
        ("zhipu", "success"),
    ]


def test_provider_fallback_applies_min_length_to_every_remote_attempt(monkeypatch):
    from qing_investment.agent.graph import nodes

    monkeypatch.setenv("QING_AGENT_FALLBACK_PROVIDERS", "zhipu,deepseek")
    client_calls = []

    def fake_get_llm_client(provider=None):
        client_calls.append(provider)
        fake = MagicMock()
        content = {
            None: "short",
            "zhipu": "also short",
            "deepseek": "long enough content",
        }[provider]
        fake.invoke.return_value = _FakeContent(content)
        return fake

    monkeypatch.setattr(nodes, "get_llm_client", fake_get_llm_client)

    out = nodes._safe_llm_invoke(
        "写文章", min_length=15, use_acp_first=False
    )

    assert out == "long enough content"
    assert client_calls == [None, "zhipu", "deepseek"]


def test_json_mode_internal_typeerror_does_not_retry_same_client(
    monkeypatch, tmp_path
):
    from qing_investment.agent.graph import nodes

    class PrimaryClient:
        def __init__(self):
            self.calls = 0

        def invoke(self, prompt, **kwargs):
            self.calls += 1
            raise TypeError("client internal TypeError")

    class FallbackClient:
        def __init__(self):
            self.calls = 0

        def invoke(self, prompt, **kwargs):
            self.calls += 1
            return _FakeContent('{"ok": true}')

    primary = PrimaryClient()
    fallback = FallbackClient()
    monkeypatch.setattr(nodes.settings, "llm_provider", "primary")
    monkeypatch.setenv("QING_AGENT_FALLBACK_PROVIDERS", "zhipu")
    monkeypatch.setattr(nodes, "_LLM_FAILURE_LOG_PATH", tmp_path / "failures.jsonl")
    monkeypatch.setattr(
        nodes,
        "get_llm_client",
        lambda provider=None: primary if provider is None else fallback,
    )

    out = nodes._safe_llm_invoke("给JSON", use_acp_first=False, json_mode=True)

    assert out == '{"ok": true}'
    assert primary.calls == 1
    assert fallback.calls == 1


def test_provider_chain_shares_deadline_and_stops_after_budget(
    monkeypatch, tmp_path
):
    from qing_investment.agent.graph import nodes

    monkeypatch.setenv("QING_AGENT_LLM_CHAIN_TIMEOUT", "150")
    monkeypatch.setenv("QING_AGENT_FALLBACK_PROVIDERS", "sensenova,zhipu")
    monkeypatch.setattr(nodes, "_LLM_FAILURE_LOG_PATH", tmp_path / "failures.jsonl")
    clock = [0.0]
    client_calls = []
    monkeypatch.setattr(nodes.time, "monotonic", lambda: clock[0])

    def fake_get_llm_client(provider=None, request_timeout=120):
        client_calls.append((provider, request_timeout))
        fake = MagicMock()

        def invoke(prompt, **kwargs):
            clock[0] += 100
            raise RuntimeError(f"{provider} failed")

        fake.invoke = invoke
        return fake

    monkeypatch.setattr(nodes, "get_llm_client", fake_get_llm_client)

    out = nodes._safe_llm_invoke("测试", use_acp_first=False)

    assert out == ""
    assert client_calls == [(None, 120), ("sensenova", 50)]
