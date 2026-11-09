from qing_investment.agent.tools import llm_client


def test_hermes_global_default_max_tokens_is_10000(monkeypatch):
    captured = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(
        llm_client,
        "_resolve_hermes_global",
        lambda: {"model": "test-model", "api_key": "test-key", "base_url": "https://example.test/v1"},
    )
    monkeypatch.setattr(llm_client, "ChatOpenAI", FakeChatOpenAI)

    llm_client.get_llm_client(provider="hermes_global")

    assert captured["max_tokens"] == 10000
