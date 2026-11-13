import pytest

from qing_investment.agent.tools import llm_client


def test_default_max_tokens_constant():
    assert llm_client.DEFAULT_MAX_TOKENS == 10000


@pytest.mark.parametrize("entrypoint", ["hermes_global", "standard", "fallback"])
@pytest.mark.parametrize("max_tokens", [None, 16384])
def test_llm_client_max_tokens_defaults_and_explicit_override(
    monkeypatch, entrypoint, max_tokens
):
    captured = []

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.append(kwargs)

    monkeypatch.setattr(llm_client, "ChatOpenAI", FakeChatOpenAI)
    monkeypatch.setattr(
        llm_client,
        "_resolve_hermes_global",
        lambda: {"model": "test-model", "api_key": "test-key", "base_url": "https://example.test/v1"},
    )
    monkeypatch.setattr(
        llm_client, "_get_provider_api_key", lambda *_args: "test-key"
    )

    if entrypoint == "hermes_global":
        llm_client.get_llm_client(provider="hermes_global", max_tokens=max_tokens)
    elif entrypoint == "standard":
        llm_client.get_llm_client(provider="deepseek", max_tokens=max_tokens)
    else:
        monkeypatch.setattr(llm_client, "get_llm_client", lambda **_kwargs: object())
        llm_client.get_llm_client_with_fallback(
            provider="sensenova",
            max_tokens=max_tokens,
            fallback_models=["zhipu:test-model"],
        )

    assert captured[-1]["max_tokens"] == (max_tokens or 10000)
    assert captured[-1]["max_retries"] == 0


def test_nemotron_reasoning_model_has_larger_output_budget(monkeypatch):
    captured = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(llm_client, "ChatOpenAI", FakeChatOpenAI)
    monkeypatch.setattr(
        llm_client,
        "_resolve_hermes_global",
        lambda: {
            "model": "nvidia/nemotron-3.5-super-vl:free",
            "api_key": "test-key",
            "base_url": "https://openrouter.ai/api/v1",
        },
    )

    llm_client.get_llm_client(provider="hermes_global")

    assert captured["max_tokens"] == 32768


@pytest.mark.parametrize(
    ("provider", "client_class"),
    [
        ("kimi-coding", "KimiCodingClient"),
        ("kimi-code-acp", "KimiCodeAcpClient"),
    ],
)
def test_specialized_clients_receive_request_timeout(
    monkeypatch, provider, client_class
):
    captured = {}

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(
        f"qing_investment.agent.tools.{ 'kimi_coding_client' if provider == 'kimi-coding' else 'kimi_code_acp_client' }.{client_class}",
        FakeClient,
    )
    monkeypatch.setattr(
        llm_client, "_get_provider_api_key", lambda *_args: "test-key"
    )

    llm_client.get_llm_client(provider=provider, request_timeout=37)

    assert captured["timeout"] == 37


def test_llm_base_url_only_applies_to_configured_primary_provider(monkeypatch):
    captured = []

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.append(kwargs)

    primary_base_url = "https://primary-only.example.test/v1"
    monkeypatch.setattr(llm_client, "ChatOpenAI", FakeChatOpenAI)
    monkeypatch.setattr(llm_client.settings, "llm_provider", "sensenova")
    monkeypatch.setattr(llm_client.settings, "llm_base_url", primary_base_url)
    monkeypatch.setattr(
        llm_client, "_get_provider_api_key", lambda *_args: "test-key"
    )

    llm_client.get_llm_client(provider="sensenova")
    llm_client.get_llm_client(provider="zhipu")

    assert captured[0]["base_url"] == primary_base_url
    assert captured[1]["base_url"] == llm_client.LLM_PROVIDERS["zhipu"]["base_url"]


@pytest.mark.parametrize("entrypoint", ["hermes_global", "standard", "fallback"])
def test_gpt_4o_default_max_tokens_cap_across_client_factories(
    monkeypatch, entrypoint
):
    captured = []

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.append(kwargs)

    monkeypatch.setattr(llm_client, "ChatOpenAI", FakeChatOpenAI)
    monkeypatch.setattr(llm_client.settings, "llm_provider", "openai")
    monkeypatch.setattr(llm_client.settings, "llm_model", "gpt-4o")
    monkeypatch.setattr(
        llm_client,
        "_resolve_hermes_global",
        lambda: {"model": "gpt-4o", "api_key": "test-key", "base_url": "https://example.test/v1"},
    )
    monkeypatch.setattr(
        llm_client, "_get_provider_api_key", lambda *_args: "test-key"
    )

    if entrypoint == "hermes_global":
        llm_client.get_llm_client(provider="hermes_global")
    elif entrypoint == "standard":
        llm_client.get_llm_client(provider="openai")
    else:
        monkeypatch.setattr(llm_client, "get_llm_client", lambda **_kwargs: object())
        llm_client.get_llm_client_with_fallback(
            provider="sensenova", fallback_models=["openai:gpt-4o"]
        )

    assert captured[-1]["max_tokens"] == 16384
