import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]

# The agent config module triggers a Pydantic V2 deprecation warning that is
# unrelated to the regression tests below; suppress it so the pytest run is clean.
pytestmark = pytest.mark.filterwarnings(
    "ignore::pydantic.warnings.PydanticDeprecatedSince20"
)


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


@pytest.fixture(scope="session", autouse=True)
def _add_src_to_path():
    """Ensure the local `src` package is importable regardless of checkout path."""
    src = str(ROOT / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    yield
    sys.path.remove(src)


def test_graph_has_new_nodes():
    from qing_investment.agent.graph.builder import build_graph

    g = build_graph()
    assert "market_summary" in g.nodes
    assert "stock_scanner" in g.nodes
    assert "market_analyst" not in g.nodes


def test_market_summary_prompt_length():
    from qing_investment.agent.graph.nodes import market_summary

    data = _load_sample()
    state = _build_state(data)
    captured = {}

    def fake_invoke(prompt, min_length=0):
        captured["prompt_len"] = len(prompt)
        return json.dumps({"market_phase": "回暖期", "main_themes": []})

    with patch("qing_investment.agent.graph.nodes._safe_llm_invoke", fake_invoke):
        result = market_summary(state)

    assert "market_summary_context" in result
    assert captured["prompt_len"] < 64000, f"prompt too long: {captured['prompt_len']}"


def test_stock_scanner_prompt_length():
    from qing_investment.agent.graph.nodes import stock_scanner

    data = _load_sample()
    state = _build_state(data)
    state["market_summary_context"] = {
        "market_summary": "test summary",
        "market_phase": "回暖期",
        "phase_reasoning": "test reasoning",
        "main_themes": ["半导体"],
        "sector_map": {},
        "themes_in_focus": ["半导体"],
        "index_discipline": {},
        "volume_note": "",
        "emotion_signals": {},
        "risk_notes": "",
        "citations": [],
    }
    captured = {}

    def fake_invoke(prompt, min_length=0):
        captured["prompt_len"] = len(prompt)
        return json.dumps({"opportunity_scan": [], "position_plans": []})

    with patch("qing_investment.agent.graph.nodes._safe_llm_invoke", fake_invoke):
        result = stock_scanner(state)

    assert "market_context" in result
    assert captured["prompt_len"] < 64000, f"prompt too long: {captured['prompt_len']}"

    # Backward compatibility: market_context must expose the original
    # market_analyst output schema keys.
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
        "opportunity_scan",
        "position_plans",
    }
    assert required_keys.issubset(set(result["market_context"].keys()))



def test_stock_scanner_returns_degraded_context_on_bad_llm_output():
    """LLM 输出不可解析或为空时，仍返回结构化 fallback 并标记 _scan_failed。"""
    from qing_investment.agent.graph.nodes import stock_scanner

    data = _load_sample()
    state = _build_state(data)
    state["market_summary_context"] = {
        "market_summary": "test summary",
        "market_phase": "回暖期",
        "phase_reasoning": "test reasoning",
        "main_themes": ["半导体"],
        "sector_map": {"半导体": ["000001"]},
        "themes_in_focus": ["半导体"],
        "index_discipline": {},
        "volume_note": "",
        "emotion_signals": {},
        "risk_notes": "",
        "citations": [],
    }

    with patch(
        "qing_investment.agent.graph.nodes._safe_llm_invoke",
        lambda prompt, min_length=0: "this is not { valid json",
    ):
        result = stock_scanner(state)

    ctx = result["market_context"]
    assert ctx.get("_scan_failed") is True
    assert ctx.get("opportunity_scan") == []
    assert ctx.get("position_plans") == []
    # 保留 market_summary_context 中的所有键
    for key in state["market_summary_context"]:
        assert key in ctx
