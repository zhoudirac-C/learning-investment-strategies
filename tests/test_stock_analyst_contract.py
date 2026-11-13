import asyncio

from qing_investment.agent.graph import nodes


def test_stock_analyst_prompt_includes_snapshot_and_market_summary(monkeypatch):
    prompts = []
    monkeypatch.setattr(nodes, "_fetch_stock_external_info", lambda *args: [])
    monkeypatch.setattr(nodes, "_get_stock_sector_positioning", lambda *args: {})

    def fake_llm(prompt, **kwargs):
        prompts.append(prompt)
        return '{"stock_code":"600000","stock_role":"未知"}'

    monkeypatch.setattr(nodes, "_safe_llm_invoke", fake_llm)
    nodes.stock_analyst(
        {
            "parsed_intent": {"stock_code": "600000", "analysis_type": "stock"},
            "market_snapshot": {
                "quotes": [{"code": "600000", "name": "浦发银行", "price": 98765.43}]
            },
            "market_summary_context": {
                "market_phase": "震荡",
                "phase_reasoning": "底部共振确认后再评估",
            },
            "market_context": {},
            "positions": [],
            "watchlist": [],
            "claims": [],
            "stock_contexts": [],
            "trigger": {"kind": "buy_signal_candidate"},
        }
    )

    assert "98765.43" in prompts[0]
    assert "底部共振确认后再评估" in prompts[0]


def test_full_graph_stock_analyst_receives_completed_market_summary(monkeypatch):
    import qing_investment.agent.graph.builder as builder

    async def fake_retrieve_knowledge(state):
        return {}

    monkeypatch.setattr(builder, "parse_query", lambda state: {})
    monkeypatch.setattr(builder, "retrieve_knowledge", fake_retrieve_knowledge)
    monkeypatch.setattr(
        builder,
        "market_summary",
        lambda state: {
            "market_summary_context": {
                "market_phase": "震荡",
                "phase_reasoning": "市场摘要已完成",
                "market_summary": "指数缩量",
            }
        },
    )
    monkeypatch.setattr(
        builder,
        "stock_scanner_shard",
        lambda state: {"stock_scanner_results": [{"market_context": {}}]},
    )
    monkeypatch.setattr(builder, "devils_advocate", lambda state: {})
    monkeypatch.setattr(
        builder,
        "style_writer",
        lambda state: {
            "styled_output": state.get("draft_analysis", ""),
            "_style_writer_failed": False,
        },
    )
    monkeypatch.setattr(
        builder,
        "reviewer",
        lambda state: {
            "review_passed": True,
            "final_output": state.get("styled_output", ""),
            "confidence": "high",
        },
    )

    prompts = []
    monkeypatch.setattr(nodes, "_fetch_stock_external_info", lambda *args: [])
    monkeypatch.setattr(nodes, "_get_stock_sector_positioning", lambda *args: {})

    def fake_llm(prompt, **kwargs):
        prompts.append(prompt)
        return '{"stock_code":"600000","stock_role":"未知"}'

    monkeypatch.setattr(nodes, "_safe_llm_invoke", fake_llm)
    result = asyncio.run(
        builder.build_graph().ainvoke(
            {
                "query": "买入确认",
                "trigger": {"kind": "buy_signal_candidate"},
                "parsed_intent": {"analysis_type": "stock", "stock_code": "600000"},
                "market_snapshot": {
                    "quotes": [
                        {"code": "600000", "name": "浦发银行", "price": 98765.43}
                    ]
                },
                "external_sector_boards": {},
                "positions": [],
                "watchlist": [],
                "claims": [],
                "stock_contexts": [],
            }
        )
    )

    assert result["review_passed"] is True
    assert len(prompts) == 1
    assert "98765.43" in prompts[0]
    assert "市场摘要已完成" in prompts[0]
