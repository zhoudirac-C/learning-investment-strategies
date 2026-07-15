from unittest.mock import patch

from qing_investment.agent.graph.nodes import merge_scanner_results


def test_merge_combines_opportunities_and_plans():
    state = {
        "stock_scanner_results": [
            {
                "market_context": {
                    "opportunity_scan": [{"code": "000001", "name": "A"}],
                    "position_plans": [{"code": "000001", "action": "hold"}],
                },
                "reasoning_steps": ["shard-A"],
                "cost_tracking": [{"llm_calls": 1, "total_cost_usd": "0.01"}],
            },
            {
                "market_context": {
                    "opportunity_scan": [{"code": "000002", "name": "B"}],
                    "position_plans": [],
                },
                "reasoning_steps": ["shard-B"],
                "cost_tracking": [{"llm_calls": 1, "total_cost_usd": "0.01"}],
            },
        ],
        "market_summary_context": {"market_phase": "磨底期"},
        "trigger": {"id": "morning_confirm"},
        "parsed_intent": {"analysis_type": "market"},
    }
    with patch("qing_investment.agent.graph.nodes._persist_daily_state_from_market_context") as mock_persist:
        result = merge_scanner_results(state)

    mc = result["market_context"]
    assert len(mc["opportunity_scan"]) == 2
    assert len(mc["position_plans"]) == 1
    assert result["stock_scanner_results"] == []
    assert mock_persist.call_count == 1


def test_merge_daily_state_overrides_are_merged():
    state = {
        "stock_scanner_results": [
            {
                "market_context": {},
                "daily_state_override": {
                    "market_stage": {"phase": "回暖期"},
                    "active_opportunities": [{"code": "000001"}],
                },
            },
            {
                "market_context": {},
                "daily_state_override": {
                    "position_stance": "积极",
                    "active_opportunities": [{"code": "000002"}],
                },
            },
        ],
        "market_summary_context": {},
        "trigger": {"id": "morning_confirm"},
        "parsed_intent": {"analysis_type": "market"},
    }
    with patch("qing_investment.agent.graph.nodes._persist_daily_state_from_market_context") as mock_persist:
        merge_scanner_results(state)

    _, override, source_tag, trigger_id = mock_persist.call_args[0]
    assert source_tag == "stock_scanner:market"
    assert trigger_id == "morning_confirm"
    assert override["market_stage"]["phase"] == "回暖期"
    assert override["position_stance"] == "积极"
    assert len(override["active_opportunities"]) == 2
