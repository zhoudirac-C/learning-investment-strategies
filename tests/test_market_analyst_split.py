import json
import sys
from pathlib import Path

import pytest

ROOT = Path("/home/ubuntu/learning-investment-strategies/.worktrees/feat-split-market-analyst")


def _load_sample():
    with open(ROOT / "tmp" / "agent_context_sample.json", encoding="utf-8") as f:
        return json.load(f)


def _build_state(data: dict) -> dict:
    return {
        "query": f"{data.get('trigger', {}).get('title', '')}：{data.get('trigger', {}).get('reason', '')}",
        "session_id": f"hermes-{data.get('timestamp', 'now')}",
        "parsed_intent": {"analysis_type": data.get("analysis_type", "market")},
        "trigger": data.get("trigger", {}),
        "alerts": data.get("alerts", []),
        "buy_signal_candidates": data.get("buy_signal_candidates", []),
        "market_snapshot": data.get("quote_snapshot", {}),
        "positions": data.get("positions", []),
        "watchlist": data.get("watchlist", []),
        "sector_strengths": data.get("sector_strengths", []),
        "external_sector_boards": data.get("external_sector_boards", {}),
        "claims": data.get("claims", []),
        "wiki_snippets": data.get("wiki_snippets", []),
        "sector_context": data.get("sector_context", []),
        "memories": data.get("memories", []),
        "stock_contexts": data.get("stock_contexts", []),
        "direction_signals": data.get("direction_signals", {}),
        "reasoning_steps": [],
    }


def test_graph_has_new_nodes():
    sys.path.insert(0, str(ROOT / "src"))
    from qing_investment.agent.graph.builder import build_graph
    g = build_graph()
    assert "market_summary" in g.nodes
    assert "stock_scanner" in g.nodes
    assert "market_analyst" not in g.nodes


def test_market_summary_prompt_length():
    sys.path.insert(0, str(ROOT / "src"))
    from qing_investment.agent.graph.nodes import market_summary
    data = _load_sample()
    state = _build_state(data)
    # smoke: ensure function runs without LLM call by patching if needed
    # For now just assert the prompt construction does not explode
    import qing_investment.agent.graph.nodes as nodes
    original_invoke = nodes._safe_llm_invoke
    captured = {}
    def fake_invoke(prompt, min_length=0):
        captured["prompt_len"] = len(prompt)
        return json.dumps({"market_phase": "回暖期", "main_themes": []})
    nodes._safe_llm_invoke = fake_invoke
    try:
        result = market_summary(state)
        assert "market_summary_context" in result
        assert captured["prompt_len"] < 64000, f"prompt too long: {captured['prompt_len']}"
    finally:
        nodes._safe_llm_invoke = original_invoke


def test_stock_scanner_prompt_length():
    sys.path.insert(0, str(ROOT / "src"))
    from qing_investment.agent.graph.nodes import stock_scanner
    data = _load_sample()
    state = _build_state(data)
    state["market_summary_context"] = {
        "market_phase": "回暖期",
        "main_themes": ["半导体"],
        "sector_map": {},
        "risk_notes": "",
    }
    import qing_investment.agent.graph.nodes as nodes
    original_invoke = nodes._safe_llm_invoke
    captured = {}
    def fake_invoke(prompt, min_length=0):
        captured["prompt_len"] = len(prompt)
        return json.dumps({"opportunity_scan": [], "position_plans": []})
    nodes._safe_llm_invoke = fake_invoke
    try:
        result = stock_scanner(state)
        assert "market_context" in result
        assert captured["prompt_len"] < 64000, f"prompt too long: {captured['prompt_len']}"
    finally:
        nodes._safe_llm_invoke = original_invoke
