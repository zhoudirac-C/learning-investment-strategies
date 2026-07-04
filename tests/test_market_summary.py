import json
from pathlib import Path

import pytest

from qing_investment.agent.graph.nodes import market_summary
from qing_investment.agent.graph.state import AgentState


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def sample_state(tmp_path) -> AgentState:
    fixture = ROOT / "tmp" / "agent_context_sample.json"
    if not fixture.exists():
        pytest.skip("tmp/agent_context_sample.json not found")
    data = json.loads(fixture.read_text(encoding="utf-8"))
    return {
        "query": data.get("trigger", {}).get("title", "")
        + "："
        + data.get("trigger", {}).get("reason", ""),
        "parsed_intent": {"analysis_type": "market"},
        "market_snapshot": data.get("quote_snapshot", {}),
        "sector_strengths": data.get("sector_strengths", []),
        "external_sector_boards": data.get("external_sector_boards", {}),
        "sector_context": data.get("sector_context", []),
        "claims": data.get("claims", []),
        "wiki_snippets": data.get("wiki_snippets", []),
        "memories": data.get("memories", []),
        "reasoning_steps": [],
    }


def test_market_summary_prompt_guard(sample_state, monkeypatch):
    """超大 state 下 prompt 必须被截断至 < 64KB，且返回结果含 _truncated 标记。"""
    # 膨胀低优先级字段，确保原始 prompt 超过 64KB
    big_block = "x" * 2000
    sample_state["memories"] = [
        {"role": "user", "content": f"memory {i} {big_block}"}
        for i in range(50)
    ]
    sample_state["wiki_snippets"] = [
        {"source": f"framework/{i}", "content": f"snippet {i} {big_block}"}
        for i in range(50)
    ]
    sample_state["claims"] = [
        {
            "statement": f"claim {i} {big_block}",
            "subject": "框架",
            "claim_type": "methodology",
        }
        for i in range(50)
    ]

    captured = {}

    def _fake_invoke(prompt: str, min_length: int = 0) -> str:
        captured["prompt"] = prompt
        captured["prompt_bytes"] = len(prompt.encode("utf-8"))
        return json.dumps({"market_phase": "震荡", "market_summary": "test"})

    monkeypatch.setattr(
        "qing_investment.agent.graph.nodes._safe_llm_invoke", _fake_invoke
    )

    result = market_summary(sample_state)

    assert captured["prompt_bytes"] < 64000, (
        f"prompt size {captured['prompt_bytes']} exceeds 64000 bytes"
    )
    ctx = result.get("market_summary_context", {})
    assert ctx.get("_truncated") is True
    assert "market_summary" in ctx
    assert "market_phase" in ctx
    assert "main_themes" in ctx


def test_market_summary_returns_fallback_on_unparseable_response(
    sample_state, monkeypatch
):
    """LLM 返回不可解析内容时，仍返回包含所有必需键的 fallback dict。"""
    monkeypatch.setattr(
        "qing_investment.agent.graph.nodes._safe_llm_invoke",
        lambda prompt, min_length=0: "this is not { valid json",
    )

    result = market_summary(sample_state)
    ctx = result.get("market_summary_context", {})

    required_keys = {
        "market_summary",
        "market_phase",
        "phase_reasoning",
        "main_themes",
        "sector_map",
        "themes_in_focus",
        "index_discipline",
        "volume_note",
        "emotion_signals",
        "risk_notes",
        "citations",
    }
    assert required_keys.issubset(set(ctx.keys()))


def test_market_summary_merges_partial_response(sample_state, monkeypatch):
    """LLM 返回部分 JSON 时，缺失的必需键应被 fallback 默认值补齐。"""
    monkeypatch.setattr(
        "qing_investment.agent.graph.nodes._safe_llm_invoke",
        lambda prompt, min_length=0: json.dumps({"market_phase": "上升期"}),
    )

    result = market_summary(sample_state)
    ctx = result.get("market_summary_context", {})

    assert ctx.get("market_phase") == "上升期"
    assert ctx.get("main_themes") == []
    assert ctx.get("sector_map") == {}
    assert ctx.get("citations") == []


def test_market_summary_no_truncation_for_small_state(monkeypatch):
    """小 state 不应触发截断。"""
    captured = {}

    def _fake_invoke(prompt: str, min_length: int = 0) -> str:
        captured["prompt_bytes"] = len(prompt.encode("utf-8"))
        return json.dumps({"market_phase": "震荡"})

    monkeypatch.setattr(
        "qing_investment.agent.graph.nodes._safe_llm_invoke", _fake_invoke
    )

    small_state: AgentState = {
        "query": "test",
        "parsed_intent": {"analysis_type": "market"},
        "market_snapshot": {},
        "sector_strengths": [],
        "external_sector_boards": {},
        "sector_context": [],
        "claims": [],
        "wiki_snippets": [],
        "memories": [],
        "reasoning_steps": [],
    }
    result = market_summary(small_state)
    ctx = result.get("market_summary_context", {})

    assert captured["prompt_bytes"] < 64000
    assert ctx.get("_truncated") is not True
