from datetime import date

import pytest

from qing_investment.agent.graph import nodes
from qing_investment.agent.tools import (
    context_builder,
    llm_client,
    sector_extractor,
)
from qing_investment.agent.tools.neo4j_client import Neo4jClient


class _FakeNeo4j:
    def get_claim_evolution(self, claim_id):
        return [{
            "id": claim_id,
            "statement": "半导体周期方法论：先判断周期再选择方向",
            "subject": "半导体周期",
            "source_date": date.today().isoformat(),
            "status": "active",
            "claim_type": "methodology",
            "intensity": "high",
            "school": "qing",
            "up_id": "qing-main",
            "supersedes": [],
            "superseded_by": [],
            "contradicts": [],
        }]

    def get_related_claims(self, claim_id, limit=5):
        return []

    def close(self):
        pass


class _FakeQdrant:
    def search(self, vector, collection, limit):
        if collection == "qing_claims":
            return [{"payload": {"claim_id": "claim-real-1"}}]
        return []

    def ensure_collection(self, *args, **kwargs):
        pass


class _FakeEmbedding:
    def encode(self, query):
        return type("Vector", (), {"tolist": lambda self: [[0.1]]})()


@pytest.mark.asyncio
async def test_semantic_claim_retrieval_preserves_flat_neo4j_record(monkeypatch):
    monkeypatch.setattr(nodes, "Neo4jClient", _FakeNeo4j)
    monkeypatch.setattr(nodes, "QdrantClientWrapper", _FakeQdrant)
    monkeypatch.setattr(
        nodes,
        "Mem0ClientWrapper",
        lambda: type("Memory", (), {"search": lambda self, *args, **kwargs: []})(),
    )
    monkeypatch.setattr(nodes, "_load_reasoning_patterns", lambda state: [])
    monkeypatch.setattr(nodes, "_load_few_shot_examples", lambda query: [])
    monkeypatch.setattr(llm_client, "get_embedding_model", lambda: _FakeEmbedding())
    monkeypatch.setattr(
        context_builder,
        "build_market_context",
        lambda **kwargs: {"stock_contexts": [], "direction_signals": {}},
    )
    monkeypatch.setattr(sector_extractor, "build_sector_context", lambda **kwargs: [])

    result = await nodes.retrieve_knowledge(
        {
            "query": "半导体周期怎么看",
            "parsed_intent": {"analysis_type": "market"},
            "positions": [],
            "watchlist": [],
        }
    )

    assert len(result["claims"]) == 1
    claim = result["claims"][0]
    assert claim["statement"] == "半导体周期方法论：先判断周期再选择方向"
    assert claim["claim_type"] == "methodology"
    assert claim["intensity"] == "high"
    assert claim["school"] == "qing"
    assert claim["up_id"] == "qing-main"
    assert claim["freshness_label"] == "最新"


class _FakeResult:
    def data(self):
        return []


class _FakeSession:
    def __init__(self, owner):
        self.owner = owner

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def run(self, query, **params):
        self.owner.query = query
        return _FakeResult()


class _FakeDriver:
    def __init__(self):
        self.query = ""

    def session(self):
        return _FakeSession(self)


@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("get_claim_evolution", ("claim-1",)),
        ("get_claims_with_evolution", ("600000",)),
        ("get_claims_by_keyword", ("半导体",)),
    ],
)
def test_neo4j_claim_queries_include_prompt_contract_fields(method, args):
    client = object.__new__(Neo4jClient)
    client.driver = _FakeDriver()

    getattr(client, method)(*args)

    for field in ("c.up_id", "c.school", "c.intensity"):
        assert field in client.driver.query
