from qing_investment.agent.graph import nodes


def _snapshot():
    return {
        "sentiment": {
            "up_count": 2142,
            "down_count": 2374,
            "limit_up_count": 11,
            "limit_down_count": 0,
        }
    }


def test_cron_fields_are_normalized_to_market_schema_and_json_daily_state():
    raw = {
        "scenario_validation": {"closest_match": "weak_consolidation"},
        "core_assumption": "竞价低开，等科技方向与大盘共振",
        "narrative": "竞价弱分歧，等待右侧确认",
        "direction_priority": [
            {"direction": "存储/半导体上游"},
            "国产算力链",
        ],
        "daily_state": {
            "market_stage": {"phase": "缩量弱分歧/等右侧确认", "detail": "竞价弱分歧"},
            "direction_priority": [{"direction": "存储/半导体上游"}],
        },
        "final_judgment": {
            "market_stage": "缩量弱分歧/等右侧确认",
            "direction": ["存储/半导体上游"],
        },
        "directions": [],
        "expert_views": [],
    }

    result, daily_state = nodes._normalize_market_summary_result(raw, _snapshot())

    assert result["market_summary"] == "竞价弱分歧，等待右侧确认"
    assert result["market_phase"] == "缩量弱分歧/等右侧确认"
    assert result["phase_reasoning"] == "竞价低开，等科技方向与大盘共振"
    assert result["main_themes"] == ["存储/半导体上游", "国产算力链"]
    assert result["emotion_signals"] == _snapshot()["sentiment"]
    assert "daily_state" not in result
    assert daily_state == raw["daily_state"]


def test_final_judgment_supplies_missing_phase_and_directions():
    raw = {
        "narrative": "指数缩量，等待确认",
        "final_judgment": {
            "market_stage": "震荡",
            "direction": ["银行"],
        },
    }

    result, daily_state = nodes._normalize_market_summary_result(raw, {})

    assert result["market_phase"] == "震荡"
    assert result["main_themes"] == ["银行"]
    assert result["market_summary"] == "指数缩量，等待确认"
    assert daily_state is None


def test_general_daily_state_shape_is_mapped_to_persistence_shape():
    raw = {
        "market_phase": "",
        "daily_state": {
            "market_phase": "回暖期",
            "main_themes": ["半导体"],
            "position_stance": "轻仓",
        }
    }

    result, daily_state = nodes._normalize_market_summary_result(raw, {})

    assert result["market_phase"] == "回暖期"
    assert result["main_themes"] == ["半导体"]
    assert daily_state["market_stage"]["phase"] == "回暖期"
    assert daily_state["direction_priority"] == [
        {"direction": "半导体", "intensity": ""}
    ]


def test_open_confirm_uses_dedicated_prompt():
    prompt = nodes._load_prompt_for_trigger("open_confirm", "market_summary")

    assert "assumption_validation" in prompt
    assert "scenario_validation" not in prompt


def test_markdown_daily_state_remains_supported():
    content = (
        '{"market_phase":"震荡"}\n'
        '```daily_state\n'
        '{"market_stage":{"phase":"震荡","detail":"旧格式"}}\n'
        '```'
    )

    assert nodes._extract_daily_state_block(content) == {
        "market_stage": {"phase": "震荡", "detail": "旧格式"}
    }


def test_llm_gator_view_is_still_rejected():
    result = nodes._attach_market_validation_contract(
        {
            "market_phase": "震荡",
            "expert_views": [{"school": "gator", "view": "LLM伪造的鳄鱼观点"}],
        },
        reasoning_patterns=[],
        gator_rules_snapshot={
            "available": True,
            "stop_falling": {"stance": "继续观望"},
        },
        school_conflicts="",
        prompt_material="test",
    )

    assert "LLM gator view rejected; deterministic snapshot is authoritative" in result[
        "_validation_contract_errors"
    ]
    assert len(result["expert_views"]) == 1
    assert result["expert_views"][0]["source"] == "deterministic_rules"


def test_market_summary_normalizes_cron_output_end_to_end(monkeypatch):
    import json

    raw = {
        "core_assumption": "竞价低开，等科技方向与大盘共振",
        "narrative": "竞价弱分歧，等待右侧确认",
        "direction_priority": ["存储/半导体上游", "国产算力链"],
        "daily_state": {
            "market_stage": {"phase": "缩量弱分歧/等右侧确认", "detail": "竞价弱分歧"}
        },
        "final_judgment": {"market_stage": "缩量弱分歧/等右侧确认"},
        "directions": [],
        "expert_views": [],
    }
    monkeypatch.setattr(nodes, "_load_reasoning_patterns", lambda state: [])
    monkeypatch.setattr(nodes, "_load_framework_files", lambda analysis_type: [])
    monkeypatch.setattr(nodes, "_load_gator_rules_snapshot", lambda: {"available": False})
    monkeypatch.setattr(nodes, "_load_school_conflicts_block", lambda: "")
    monkeypatch.setattr(nodes, "_load_dual_school_contract", lambda context: "")
    monkeypatch.setattr(nodes, "_load_industry_chain_states", lambda: {"available": False})
    monkeypatch.setattr(nodes, "load_daily_state", lambda: {"pre_market_brief": {"available": False}})
    monkeypatch.setattr(nodes, "_persist_daily_state_from_market_context", lambda *args, **kwargs: None)
    monkeypatch.setattr(nodes, "_safe_llm_invoke", lambda *args, **kwargs: json.dumps(raw, ensure_ascii=False))

    result = nodes.market_summary(
        {
            "trigger": {"id": "open_auction"},
            "parsed_intent": {"analysis_type": "market"},
            "market_snapshot": {"quotes": [], "sentiment": {"limit_up_count": 11}},
            "external_sector_boards": {"available": False},
        }
    )["market_summary_context"]

    assert result["market_phase"] == "缩量弱分歧/等右侧确认"
    assert result["main_themes"] == ["存储/半导体上游", "国产算力链"]
    assert result["emotion_signals"] == {"limit_up_count": 11}
    assert result["_daily_state_override"] == {
        **raw["daily_state"],
        "direction_priority": [
            {"direction": "存储/半导体上游", "intensity": ""},
            {"direction": "国产算力链", "intensity": ""},
        ],
    }
    assert "_validation_contract_errors" not in result
