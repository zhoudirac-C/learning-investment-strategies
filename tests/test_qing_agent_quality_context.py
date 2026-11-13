import pytest

from qing_investment.agent.graph import nodes


@pytest.mark.parametrize(
    "shard",
    [None, {"name": "空分片", "items": []}],
)
def test_scanner_preserves_index_quotes_with_empty_candidate_pool(monkeypatch, shard):
    prompts = []
    monkeypatch.setattr(
        nodes,
        "_safe_llm_invoke",
        lambda prompt, **kwargs: prompts.append(prompt)
        or '{"opportunity_scan":[],"position_plans":[]}',
    )
    quotes = [
        {"code": "000001", "secid": "1.000001", "label": "上证指数", "latest": 3673.06},
        {"code": "399006", "secid": "0.399006", "label": "创业板指", "latest": 2559.16},
        {"code": "000688", "secid": "1.000688", "label": "科创50", "latest": 1302.5},
        {"code": "000985", "secid": "1.000985", "label": "全A指数", "latest": 5198.56},
    ]

    nodes.stock_scanner_shard(
        {
            "trigger": {"id": "open_auction"},
            "parsed_intent": {"analysis_type": "market"},
            "market_summary_context": {"market_phase": "震荡", "market_summary": "弱分歧"},
            "market_snapshot": {"quotes": quotes, "sentiment": {"limit_up_count": 11}},
            "positions": [],
            "watchlist": [],
            "watchlist_shard": shard,
        }
    )

    assert len(prompts) == 1
    for quote in quotes:
        assert quote["label"] in prompts[0]
        assert str(quote["latest"]) in prompts[0]


def _zero_boards():
    row = {"name": "农业", "pct_change": 0.0, "latest": 0.0, "amount": 0.0}
    return {
        "available": True,
        "concept": {"leaders": [dict(row)]},
        "industry": {"leaders": [dict(row)]},
    }


def _quality_state():
    return {
        "data_as_of": "2026-11-12T09:26:17+08:00",
        "market_snapshot": {
            "timestamp": "2026-11-12T09:26:17+08:00",
            "quotes": [{"code": "000001", "latest": 3673.06}],
            "sentiment": {"limit_up_count": 11},
        },
        "external_sector_boards": _zero_boards(),
        "claims": [{"id": "claim-1"}],
        "wiki_snippets": [{"source": "framework/test.md"}],
        "positions": [],
        "watchlist": [],
    }


def test_shared_data_quality_view_distinguishes_real_data_and_zero_boards():
    view = nodes._build_data_quality_view(_quality_state())

    assert view["available_sources"] == ["market_snapshot", "claims", "wiki"]
    assert view["degraded_sources"] == ["external_sector_boards"]
    assert "positions=0" in view["text"]
    assert "watchlist=0" in view["text"]
    assert "全零" in view["text"]


def test_empty_quote_objects_are_not_reported_as_realtime_data():
    state = _quality_state()
    state["market_snapshot"] = {"quotes": [{}], "sentiment": {}}

    view = nodes._build_data_quality_view(state)

    assert "market_snapshot" in view["degraded_sources"]
    assert "market_snapshot: 不可用" in view["text"]


@pytest.mark.parametrize(
    "sentiment",
    [
        {"errors": ["all providers failed"]},
        {"up_count": None, "limit_up_count": 0},
        {"up_count": "nan"},
        {"up_count": "inf"},
    ],
)
def test_invalid_sentiment_is_not_reported_as_realtime_data(sentiment):
    state = _quality_state()
    state["market_snapshot"] = {"quotes": [], "sentiment": sentiment}

    view = nodes._build_data_quality_view(state)

    assert "market_snapshot" in view["degraded_sources"]
    assert "market_snapshot: 不可用" in view["text"]
    assert "sentiment=无效/缺失" in view["text"]


def test_empty_candidate_pool_has_explicit_scan_and_position_sections():
    state = _quality_state()
    state["market_context"] = {
        "market_phase": "震荡",
        "market_summary": "指数弱分歧",
        "main_themes": [],
        "opportunity_scan": [],
        "position_plans": [],
    }

    draft = nodes.synthesize(state)["draft_analysis"]

    assert "【机会扫描】当前持仓与观察池均为空，未执行全市场扫描" in draft
    assert "不生成个股买卖建议" in draft
    assert "【持仓操作计划】当前无持仓，不生成持仓操作建议" in draft


def test_style_writer_uses_same_quality_view_for_header_and_prompt(monkeypatch):
    prompts = []
    monkeypatch.setattr(
        nodes,
        "_safe_llm_invoke",
        lambda prompt, **kwargs: prompts.append(prompt) or "保留真实行情与空池说明",
    )
    state = _quality_state()
    state.update(draft_analysis="【盘面】指数弱分歧", market_context={"market_phase": "震荡"})

    result = nodes.style_writer(state)

    assert result["styled_output"].splitlines()[:3] == [
        "【数据时点】2026-11-12T09:26:17+08:00",
        "【实际可用数据来源】market_snapshot、claims、wiki",
        "【缺失/降级数据来源】external_sector_boards",
    ]
    assert "positions=0" in prompts[0]
    assert "watchlist=0" in prompts[0]
    assert "全零" in prompts[0]


def test_validation_errors_skip_style_and_review_llm_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(
        nodes,
        "_safe_llm_invoke",
        lambda *args, **kwargs: calls.append((args, kwargs)) or "不应调用",
    )
    state = _quality_state()
    state.update(
        draft_analysis="【盘面】原始行情摘要",
        market_context={"_validation_contract_errors": ["bad schema"]},
    )

    styled = nodes.style_writer(state)
    reviewed = nodes.reviewer({**state, **styled})

    assert calls == []
    assert styled["_style_writer_failed"] is False
    assert "bad schema" in styled["styled_output"]
    assert reviewed["review_passed"] is False
    assert reviewed["_reviewer_error"] is False
    assert "bad schema" in reviewed["review_notes"]
    assert reviewed["final_output"] == styled["styled_output"]


def test_terminal_validation_failure_finishes_full_graph_without_style_retry(monkeypatch):
    import asyncio

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
                "market_phase": "未配置",
                "market_summary": "原始行情摘要",
                "_fallback_reason": "llm_empty",
            }
        },
    )
    monkeypatch.setattr(
        builder,
        "stock_scanner_shard",
        lambda state: {"stock_scanner_results": [{"market_context": {}}]},
    )
    monkeypatch.setattr(builder, "stock_analyst", lambda state: {})
    monkeypatch.setattr(builder, "devils_advocate", lambda state: {})

    style_calls = 0
    actual_style_writer = builder.style_writer

    def recording_style_writer(state):
        nonlocal style_calls
        style_calls += 1
        return actual_style_writer(state)

    monkeypatch.setattr(builder, "style_writer", recording_style_writer)

    result = asyncio.run(
        builder.build_graph().ainvoke(
            {
                "query": "终止型降级回归",
                "trigger": {"id": "morning_confirm"},
                "parsed_intent": {"analysis_type": "market"},
                "market_snapshot": {"quotes": []},
                "external_sector_boards": {},
                "positions": [],
                "watchlist": [],
            }
        )
    )

    assert style_calls == 1
    assert result["review_passed"] is False
    assert "market_summary:llm_empty" in result["final_output"]


def test_reviewer_receives_empty_pool_and_zero_board_context(monkeypatch):
    prompts = []
    monkeypatch.setattr(
        nodes,
        "_safe_llm_invoke",
        lambda prompt, **kwargs: prompts.append(prompt)
        or '{"passed":true,"issues":[],"verified_claims":[]}',
    )
    state = _quality_state()
    state.update(
        styled_output="指数弱分歧，空池不生成交易建议。" * 8,
        market_context={"market_phase": "震荡", "opportunity_scan": []},
    )

    result = nodes.reviewer(state)

    assert result["review_passed"] is True
    assert "positions=0" in prompts[0]
    assert "watchlist=0" in prompts[0]
    assert "全零" in prompts[0]


def test_style_prompt_has_no_leakable_numeric_examples():
    prompt = nodes._load_prompt("style_writer")

    assert "{data_quality}" in prompt
    assert "19元" not in prompt
    assert "18.5元" not in prompt
    assert "[未找到来源]" not in prompt


def test_scanner_discards_llm_opportunities_when_candidate_pool_is_empty(monkeypatch):
    monkeypatch.setattr(
        nodes,
        "_safe_llm_invoke",
        lambda *args, **kwargs: (
            '{"opportunity_scan":[{"stock":"中际旭创","code":"300308",'
            '"trigger":"待企稳","odds":"2:1"}],"position_plans":[]}'
        ),
    )
    state = _quality_state()
    state.update(
        parsed_intent={"analysis_type": "market"},
        trigger={"id": "afternoon_risk"},
        market_summary_context={"market_phase": "震荡", "main_themes": ["光互连"]},
    )

    result = nodes.stock_scanner_shard(state)

    scan = result["stock_scanner_results"][0]["market_context"]
    assert scan["opportunity_scan"] == []
    assert scan["position_plans"] == []
