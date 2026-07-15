import json
import re
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
    assert "shard_router" in g.nodes
    assert "stock_scanner_shard" in g.nodes
    assert "merge_scanner_results" in g.nodes
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


def _run_stock_scanner_shard(state):
    """调用分片版 scanner 并返回第一个分片结果（兼容旧测试的返回形状）。"""
    from qing_investment.agent.graph.nodes import stock_scanner_shard

    shard_result = stock_scanner_shard(state)
    results = shard_result.get("stock_scanner_results", [])
    assert results, "stock_scanner_shard returned no results"
    return results[0]


def test_stock_scanner_prompt_length():
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
        result = _run_stock_scanner_shard(state)

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
        "sector_strength",
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
        result = _run_stock_scanner_shard(state)

    ctx = result["market_context"]
    assert ctx.get("_scan_failed") is True
    assert ctx.get("opportunity_scan") == []
    assert ctx.get("position_plans") == []
    # 保留 market_summary_context 中的所有键
    for key in state["market_summary_context"]:
        assert key in ctx
    # sector_map / sector_strength 向后兼容
    assert ctx.get("sector_strength") == ctx.get("sector_map")


def test_stock_scanner_truncation_regression(monkeypatch):
    """超大 market_summary_context + watchlist 下，prompt 必须 < 64KB 且始终返回 market_context。"""
    data = _load_sample()
    state = _build_state(data)
    big_block = "x" * 2000
    state["market_summary_context"] = {
        "market_summary": "test summary",
        "market_phase": "回暖期",
        "phase_reasoning": "test reasoning",
        "main_themes": [f"主题 {i}" for i in range(100)],
        "sector_map": {},
        "themes_in_focus": [f"重点 {i}" for i in range(100)],
        "index_discipline": {},
        "volume_note": "",
        "emotion_signals": {},
        "risk_notes": "",
        "citations": [],
    }
    state["watchlist"] = [
        {
            "code": f"{600000 + i:06d}",
            "name": f"stock {i}",
            "priority": "P1",
            "watch_reason": big_block,
        }
        for i in range(100)
    ]
    state["stock_contexts"] = [
        {"code": f"{600000 + i:06d}", "summary": big_block}
        for i in range(100)
    ]

    captured = {}

    def fake_invoke(prompt, min_length=0):
        captured["prompt"] = prompt
        captured["prompt_bytes"] = len(prompt.encode("utf-8"))
        return json.dumps({"opportunity_scan": [], "position_plans": []})

    monkeypatch.setattr(
        "qing_investment.agent.graph.nodes._safe_llm_invoke", fake_invoke
    )

    result = _run_stock_scanner_shard(state)

    assert "market_context" in result
    assert captured["prompt_bytes"] < 64000, (
        f"prompt size {captured['prompt_bytes']} exceeds 64000 bytes"
    )
    ctx = result["market_context"]
    assert ctx.get("market_phase") == "回暖期"
    assert ctx.get("_truncated") is True


def test_stock_scanner_keeps_secid_only_quote(monkeypatch):
    """持仓个股行情若只有 East Money secid，也应被保留，不能误过滤。"""
    data = _load_sample()
    state = _build_state(data)
    state["market_summary_context"] = {
        "market_summary": "test summary",
        "market_phase": "回暖期",
        "phase_reasoning": "test reasoning",
        "main_themes": ["新能源"],
        "sector_map": {"新能源": ["002594"]},
        "themes_in_focus": ["新能源"],
        "index_discipline": {},
        "volume_note": "",
        "emotion_signals": {},
        "risk_notes": "",
        "citations": [],
    }
    state["positions"] = [{"code": "002594", "name": "比亚迪", "quantity": 100}]
    state["market_snapshot"] = {
        "quotes": [
            {"code": "000001", "name": "上证指数", "label": "指数", "pct_change": 0.1},
            {"secid": "0.002594", "name": "比亚迪", "pct_change": 1.2},
        ]
    }

    captured = {}

    def fake_invoke(prompt: str, min_length: int = 0) -> str:
        captured["prompt"] = prompt
        return json.dumps({"opportunity_scan": [], "position_plans": []})

    monkeypatch.setattr(
        "qing_investment.agent.graph.nodes._safe_llm_invoke", fake_invoke
    )

    result = _run_stock_scanner_shard(state)

    assert "market_context" in result
    assert captured.get("prompt")
    match = re.search(
        r"上下文：\s*\n(.*?)\n\s*请输出JSON：",
        captured["prompt"],
        re.DOTALL,
    )
    assert match, "could not find context JSON in prompt"
    context = json.loads(match.group(1))
    quotes = context["market_snapshot"]["quotes"]
    assert any(q.get("secid") == "0.002594" for q in quotes)
