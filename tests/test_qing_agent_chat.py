from datetime import date

import pytest


@pytest.mark.asyncio
async def test_chat_preserves_school_attribution_and_injects_dual_contract(monkeypatch):
    from qing_investment.agent import main as agent_main
    from qing_investment.agent.tools import sector_data, stock_data
    from qing_investment import kline_cache

    today = date.today().isoformat()
    claim_rows = [
        {
            "claim_id": "qing-1",
            "statement": "QING_UNIQUE_VIEW",
            "subject": "市场",
            "source_date": today,
            "claim_type": "market-view",
            "school": "qing",
            "up_id": "qing-main",
            "intensity": "medium",
            "status": "active",
        },
        {
            "claim_id": "gator-1",
            "statement": "GATOR_UNIQUE_VIEW",
            "subject": "市场",
            "source_date": today,
            "claim_type": "market-view",
            "school": "gator",
            "up_id": "gator-ecyu-0001",
            "intensity": "medium",
            "status": "active",
        },
    ]

    class FakeMemory:
        def search(self, *args, **kwargs):
            return []

    class FakeQdrant:
        def search(self, vector, collection, limit):
            if collection == "qing_claims":
                return [{"payload": dict(row), "score": 0.8} for row in claim_rows]
            return []

    class FakeNeo4j:
        def get_stock_by_name(self, message):
            return []

        def get_claims_by_keyword(self, keyword, limit=5):
            return []

        def get_related_claims(self, claim_id, limit=5):
            return []

        def close(self):
            pass

    class FakeLLM:
        def __init__(self):
            self.prompts = []

        def invoke(self, prompt):
            self.prompts.append(prompt)
            return type("Response", (), {"content": "CHAT_RESPONSE"})()

    fake_llm = FakeLLM()
    monkeypatch.setattr(agent_main, "Mem0ClientWrapper", FakeMemory)
    monkeypatch.setattr(agent_main, "QdrantClientWrapper", FakeQdrant)
    monkeypatch.setattr(agent_main, "Neo4jClient", FakeNeo4j)
    monkeypatch.setattr(
        agent_main,
        "get_embedding_model",
        lambda: type("Embedding", (), {"encode": lambda self, text: [0.1]})(),
    )
    monkeypatch.setattr(agent_main, "get_llm_client", lambda: fake_llm)
    monkeypatch.setattr(stock_data, "fetch_index_quotes", lambda: [])
    monkeypatch.setattr(kline_cache, "get_index_macd_snapshot", lambda code: {})
    monkeypatch.setattr(kline_cache, "compute_td_report", lambda *args: "")
    monkeypatch.setattr(kline_cache, "compute_fibonacci_time_report", lambda code: "")

    def fail_sector_fetch(*args, **kwargs):
        raise RuntimeError("sector data intentionally unavailable in test")

    monkeypatch.setattr(
        sector_data, "get_sector_strength_snapshot", fail_sector_fetch
    )

    response = await agent_main.chat(
        agent_main.ChatRequest(message="两派都看，今天大盘怎么看", session_id="test")
    )

    assert response.reply == "CHAT_RESPONSE"
    assert len(fake_llm.prompts) == 1
    prompt = fake_llm.prompts[0]
    assert "双学派输出契约" in prompt
    assert "[qing]" in prompt
    assert "[gator]" in prompt
    qing_section = prompt.split("【Qing历史观点】", 1)[1].split(
        "【其他学派历史观点】", 1
    )[0]
    other_section = prompt.split("【其他学派历史观点】", 1)[1]
    assert "QING_UNIQUE_VIEW" in qing_section
    assert "GATOR_UNIQUE_VIEW" not in qing_section
    assert "GATOR_UNIQUE_VIEW" in other_section


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("quotes", "sector_snapshot", "expected_realtime", "forbidden_text"),
    [
        ([{}], None, False, None),
        ([{"price": 0, "latest": 0, "pct_change": 0, "amount": 0}], None, False, None),
        ([{"price": "nan", "latest": "inf", "pct_change": "-inf"}], None, False, None),
        ([{"name": "上证指数", "code": "000001", "price": 3000}], None, True, None),
        (
            [
                {"name": "上证指数", "code": "000001", "price": 3000},
                {"name": "BAD_QUOTE", "code": "bad", "price": "nan", "pct_change": "inf"},
            ],
            None,
            True,
            "BAD_QUOTE",
        ),
        (
            [{"name": "上证指数", "code": "000001", "price": 3000}],
            {
                "concept": {
                    "leaders": [
                        {"name": "ZERO_BOARD", "pct_change": 0, "latest": 0, "amount": 0}
                    ]
                },
                "industry": {"leaders": []},
            },
            True,
            "ZERO_BOARD",
        ),
    ],
)
async def test_chat_applies_quote_data_quality_gate(
    monkeypatch, quotes, sector_snapshot, expected_realtime, forbidden_text
):
    from qing_investment import kline_cache
    from qing_investment.agent import main as agent_main
    from qing_investment.agent.tools import sector_data, stock_data

    class FakeMemory:
        def search(self, *args, **kwargs):
            return []

    class FakeQdrant:
        def search(self, *args, **kwargs):
            return []

    class FakeNeo4j:
        def get_stock_by_name(self, message):
            return []

        def get_claims_by_keyword(self, keyword, limit=5):
            return []

        def get_related_claims(self, claim_id, limit=5):
            return []

        def close(self):
            pass

    class FakeLLM:
        def __init__(self):
            self.prompts = []

        def invoke(self, prompt):
            self.prompts.append(prompt)
            return type("Response", (), {"content": "CHAT_RESPONSE"})()

    fake_llm = FakeLLM()
    monkeypatch.setattr(agent_main, "Mem0ClientWrapper", FakeMemory)
    monkeypatch.setattr(agent_main, "QdrantClientWrapper", FakeQdrant)
    monkeypatch.setattr(agent_main, "Neo4jClient", FakeNeo4j)
    monkeypatch.setattr(
        agent_main,
        "get_embedding_model",
        lambda: type("Embedding", (), {"encode": lambda self, text: [0.1]})(),
    )
    monkeypatch.setattr(agent_main, "get_llm_client", lambda: fake_llm)
    monkeypatch.setattr(stock_data, "fetch_index_quotes", lambda: quotes)
    monkeypatch.setattr(kline_cache, "get_index_macd_snapshot", lambda code: {})
    monkeypatch.setattr(kline_cache, "compute_td_report", lambda *args: "")
    monkeypatch.setattr(kline_cache, "compute_fibonacci_time_report", lambda code: "")

    def get_sector_snapshot(*args, **kwargs):
        if sector_snapshot is None:
            raise RuntimeError("sector data intentionally unavailable in test")
        return sector_snapshot

    monkeypatch.setattr(sector_data, "get_sector_strength_snapshot", get_sector_snapshot)

    await agent_main.chat(
        agent_main.ChatRequest(message="今天大盘怎么看", session_id="test")
    )

    prompt = fake_llm.prompts[0]
    assert ("【实时行情数据】（✅ 主要分析依据）" in prompt) is expected_realtime
    assert ("- 个股/指数行情:" in prompt) is expected_realtime
    if expected_realtime:
        assert "3000" in prompt
    else:
        assert "【实时行情数据】（❌ 无法获取）" in prompt
    if forbidden_text is not None:
        assert forbidden_text not in prompt
