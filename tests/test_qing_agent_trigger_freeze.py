from __future__ import annotations

import json
import logging

import pytest

from qing_investment.agent.models.schemas import TriggerRequest
from scripts import hermes_stock_monitor_agent as wrapper


def _graph_result() -> dict:
    return {
        "final_output": "最终合成判断：震荡，等待确认。",
        "claims_cited": [],
        "data_sources": ["market_snapshot"],
        "confidence": "medium",
        "review_passed": True,
        "review_notes": [],
        "citation_report": {"valid": True},
        "reasoning_steps": [],
        "cost_tracking": [],
        "market_summary_context": {
            "final_judgment": {
                "market_stage": "震荡",
                "evidence": ["指数缩量"],
                "direction": ["银行"],
                "targets": [{"stock_code": "600000", "name": "浦发银行"}],
                "horizon": "T+5",
                "trigger_conditions": ["放量确认"],
                "invalidation_conditions": ["跌破失效位"],
            },
            "directions": [
                {
                    "direction_id": "bank-600000",
                    "stock_code": "600000",
                    "horizon": "T+5",
                    "polarity": "long",
                    "invalidation": "跌破失效位",
                }
            ],
            "expert_views": [
                {
                    "school": "gator",
                    "view": "规则快照观点",
                    "evidence": {"available": True, "marker": "gator"},
                    "horizon": "",
                }
            ],
            "pattern_refs": [
                {"pattern_id": "gator-draft", "school": "gator", "validation": {}}
            ],
            "gator_rules_snapshot": {"available": True, "marker": "gator"},
            "prompt_version": "prompt-v1",
            "rules_version": "rules-v1",
        },
    }


def _request() -> TriggerRequest:
    return TriggerRequest(
        query="盘前验证",
        trigger={"id": "pre_market", "title": "盘前验证"},
        data_as_of="2026-11-02T08:55:00+08:00",
        market_snapshot={
            "timestamp": "2026-11-02T09:00:00+08:00",
            "quotes": [{"code": "000001", "price": 3000}],
        },
        external_sector_boards={"available": True},
        positions=[{"code": "600000", "cost": 123.45, "shares": 100}],
        watchlist=[],
    )


@pytest.mark.asyncio
async def test_analyze_trigger_freezes_complete_record(monkeypatch, tmp_path):
    from qing_investment.agent import main as agent_main

    root = tmp_path / "records"
    monkeypatch.setenv("QING_AGENT_VALIDATION_ROOT", str(root))

    async def fake_ainvoke(state):
        assert state["data_as_of"] == "2026-11-02T08:55:00+08:00"
        return _graph_result()

    monkeypatch.setattr(agent_main.graph, "ainvoke", fake_ainvoke)

    response = await agent_main.analyze_trigger(_request())

    paths = list(root.rglob("*.json"))
    assert len(paths) == 1
    record = json.loads(paths[0].read_text(encoding="utf-8"))
    assert paths[0].parent.name == "pre_market"
    assert record["record_id"]
    assert response.record_id == record["record_id"]
    assert response.record_status == "pending_maturity"
    assert record["track"] == "pre_market"
    assert record["data_as_of"] == "2026-11-02T08:55:00+08:00"
    assert record["status"] == "pending_maturity"
    assert record["raw_output"] == response.final_output
    assert record["final_judgment"]["market_stage"] == "震荡"
    assert record["final_judgment"]["view"] == response.final_output
    assert record["final_judgment"]["score_eligible"] is True
    assert record["directions"][0]["score_eligible"] is True
    assert record["expert_views"][0]["school"] == "gator"
    assert record["review"]["passed"] is True
    assert record["citations"] == {"valid": True}
    assert record["data_version"] == "2026-11-02T08:55:00+08:00"
    assert record["rules_version"].startswith("sha256:")
    assert record["prompt_version"].startswith("sha256:")
    assert len(record["input_hash"]) == 64
    assert record["input_availability"]["position_snapshot_stored"] is False
    assert "123.45" not in paths[0].read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_freeze_failure_is_logged_without_blocking_response(
    monkeypatch, tmp_path, caplog
):
    from investment_engine.qing_validation import records
    from qing_investment.agent import main as agent_main

    monkeypatch.setenv("QING_AGENT_VALIDATION_ROOT", str(tmp_path / "records"))

    async def fake_ainvoke(state):
        return _graph_result()

    def fail_save(record, *, root=None):
        raise OSError("disk full")

    monkeypatch.setattr(agent_main.graph, "ainvoke", fake_ainvoke)
    monkeypatch.setattr(records, "save_record", fail_save)

    with caplog.at_level(logging.ERROR):
        response = await agent_main.analyze_trigger(_request())

    assert "最终合成判断" in response.final_output
    assert "留痕失败" in caplog.text
    assert not list((tmp_path / "records").rglob("*.json"))


def test_wrapper_passes_explicit_data_as_of(monkeypatch):
    captured = {}
    data = {
        "timestamp": "2026-11-02T10:00:00+08:00",
        "trigger": {"id": "morning_confirm", "title": "十点确认", "reason": "测试"},
        "positions": {"accounts": []},
        "watchlist": {"themes": []},
    }

    monkeypatch.setattr(wrapper, "_wait_for_agent_health", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        wrapper,
        "_build_market_snapshot",
        lambda value: ({"timestamp": value["timestamp"], "quotes": []}, {}),
    )
    monkeypatch.setattr(wrapper, "_normalize_positions", lambda value, lookup: [])
    monkeypatch.setattr(wrapper, "_normalize_watchlist", lambda value, lookup: [])
    monkeypatch.setattr(wrapper, "_log_request_payload", lambda *args, **kwargs: None)

    def fake_post(payload, timeout=None, failure=None):
        captured.update(payload)
        return {"final_output": "ok"}

    monkeypatch.setattr(wrapper, "_post_analyze_trigger", fake_post)

    response = wrapper.call_qing_agent(data)

    assert response == {"final_output": "ok"}
    assert captured["data_as_of"] == "2026-11-02T10:00:00+08:00"


def test_wrapper_fallback_records_error_not_pending_prediction(
    monkeypatch, tmp_path, capsys
):
    root = tmp_path / "records"
    monkeypatch.setenv("QING_AGENT_VALIDATION_ROOT", str(root))
    data = {
        "timestamp": "2026-11-02T10:00:00+08:00",
        "trigger": {"id": "morning_confirm", "title": "十点确认", "reason": "测试"},
        "quote_snapshot": {
            "timestamp": "2026-11-02T10:00:00+08:00",
            "quotes": [{"code": "000001"}],
        },
        "positions": {"accounts": []},
        "watchlist": {"themes": []},
    }
    monkeypatch.setattr(wrapper, "fetch_json_context", lambda root: data)
    monkeypatch.setattr(wrapper, "call_qing_agent", lambda value: None)
    monkeypatch.setattr(wrapper, "QING_AGENT_FALLBACK_ENABLED", True)
    monkeypatch.setattr(
        wrapper, "fetch_fallback_text_context", lambda root, value: "LOCAL FALLBACK"
    )

    assert wrapper.main() == 0

    assert "LOCAL FALLBACK" in capsys.readouterr().out
    paths = list(root.rglob("*.json"))
    assert len(paths) == 1
    record = json.loads(paths[0].read_text(encoding="utf-8"))
    assert record["status"] == "error"
    assert record["error"]
    assert record["raw_output"] == ""
    assert record["directions"] == []
    assert record["final_judgment"]["score_eligible"] is False
    assert "LOCAL FALLBACK" not in paths[0].read_text(encoding="utf-8")
    assert not [p for p in paths if json.loads(p.read_text())["status"] == "pending_maturity"]


async def _call_with_result(monkeypatch, result: dict, request: TriggerRequest | None = None):
    from qing_investment.agent import main as agent_main

    async def fake_ainvoke(state):
        return result

    monkeypatch.setattr(agent_main.graph, "ainvoke", fake_ainvoke)
    return await agent_main.analyze_trigger(request or _request())


def _only_record(root):
    paths = list(root.rglob("*.json"))
    assert len(paths) == 1
    return json.loads(paths[0].read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_freeze_uses_merged_final_context_not_only_upstream_summary(
    monkeypatch, tmp_path
):
    root = tmp_path / "records"
    monkeypatch.setenv("QING_AGENT_VALIDATION_ROOT", str(root))
    result = _graph_result()
    merged = dict(result["market_summary_context"])
    merged["final_judgment"] = dict(merged["final_judgment"], market_stage="最终修复")
    merged["position_plans"] = [{"code": "600000", "action": "等待触发"}]
    merged["opportunity_scan"] = [{"code": "600000", "horizon": "T+5"}]
    result["market_context"] = merged
    result["stock_analysis"] = {"stock_code": "600000", "stock_role": "前排"}

    response = await _call_with_result(monkeypatch, result)

    record = _only_record(root)
    assert record["final_judgment"]["market_stage"] == "最终修复"
    assert record["final_judgment"]["view"] == response.final_output
    assert record["final_judgment"]["position_plans"] == merged["position_plans"]
    assert record["final_judgment"]["opportunity_scan"] == merged["opportunity_scan"]
    assert record["final_judgment"]["stock_analysis"] == result["stock_analysis"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [{"_fallback_reason": "llm_empty"}, {"_validation_contract_errors": ["bad schema"]}],
)
async def test_internal_generation_failures_are_error_not_pending(
    monkeypatch, tmp_path, failure
):
    root = tmp_path / "records"
    monkeypatch.setenv("QING_AGENT_VALIDATION_ROOT", str(root))
    result = _graph_result()
    result["market_summary_context"].update(failure)

    response = await _call_with_result(monkeypatch, result)

    record = _only_record(root)
    assert response.record_status == "error"
    assert record["status"] == "error"
    assert record["directions"][0]["score_eligible"] is False
    assert record["final_judgment"]["score_eligible"] is False


@pytest.mark.asyncio
async def test_missing_input_snapshot_is_missing_not_pending(monkeypatch, tmp_path):
    root = tmp_path / "records"
    monkeypatch.setenv("QING_AGENT_VALIDATION_ROOT", str(root))
    request = _request()
    request.data_as_of = None
    request.market_snapshot = {"quotes": []}
    request.external_sector_boards = {"available": False}

    response = await _call_with_result(monkeypatch, _graph_result(), request)

    record = _only_record(root)
    assert response.record_status == "missing"
    assert record["status"] == "missing"
    assert record["directions"][0]["score_eligible"] is False


@pytest.mark.asyncio
async def test_same_request_retry_creates_linked_version(monkeypatch, tmp_path):
    root = tmp_path / "records"
    monkeypatch.setenv("QING_AGENT_VALIDATION_ROOT", str(root))
    request = _request()

    await _call_with_result(monkeypatch, _graph_result(), request)
    await _call_with_result(monkeypatch, _graph_result(), request)

    records = [json.loads(p.read_text(encoding="utf-8")) for p in root.rglob("*.json")]
    assert len(records) == 2
    records.sort(key=lambda item: item["generated_at"])
    assert records[0]["record_id"] != records[1]["record_id"]
    assert records[1]["supersedes_record_id"] == records[0]["record_id"]


@pytest.mark.asyncio
async def test_hallucinated_output_is_frozen_as_rejected_error(monkeypatch, tmp_path):
    root = tmp_path / "records"
    monkeypatch.setenv("QING_AGENT_VALIDATION_ROOT", str(root))
    result = _graph_result()
    result["final_output"] = "这是2027年复盘，虚构未来结果。"

    response = await _call_with_result(monkeypatch, result)

    record = _only_record(root)
    assert response.record_status == "error"
    assert record["status"] == "error"
    assert record["error"]["type"] == "output_rejected"
    assert record["directions"][0]["score_eligible"] is False


def test_wrapper_failure_preserves_error_details_and_sent_payload_hash(
    monkeypatch, tmp_path, capsys
):
    import hashlib

    root = tmp_path / "records"
    monkeypatch.setenv("QING_AGENT_VALIDATION_ROOT", str(root))
    captured = {}
    data = {
        "timestamp": "2026-11-02T10:00:00+08:00",
        "trigger": {"id": "morning_confirm", "title": "十点确认", "reason": "测试"},
        "quote_snapshot": {"timestamp": "2026-11-02T10:00:00+08:00", "quotes": [{"code": "000001"}]},
        "positions": {"accounts": []},
        "watchlist": {"themes": []},
    }
    monkeypatch.setattr(wrapper, "fetch_json_context", lambda root: data)
    monkeypatch.setattr(wrapper, "_wait_for_agent_health", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        wrapper,
        "_build_market_snapshot",
        lambda value: ({"timestamp": value["timestamp"], "quotes": [{"code": "000001"}]}, {}),
    )
    monkeypatch.setattr(wrapper, "_normalize_positions", lambda value, lookup: [])
    monkeypatch.setattr(wrapper, "_normalize_watchlist", lambda value, lookup: [])
    monkeypatch.setattr(wrapper, "_log_request_payload", lambda *args, **kwargs: None)
    monkeypatch.setattr(wrapper, "QING_AGENT_FALLBACK_ENABLED", True)
    monkeypatch.setattr(wrapper, "fetch_fallback_text_context", lambda root, value: "fallback")

    def fake_post(payload, timeout=None, failure=None):
        captured["payload"] = payload
        if failure is not None:
            failure.update({"type": "timeout", "message": "timed out", "attempts": 2})
        return None

    monkeypatch.setattr(wrapper, "_post_analyze_trigger", fake_post)

    assert wrapper.main() == 0
    capsys.readouterr()

    record = _only_record(root)
    assert record["status"] == "error"
    assert record["error"]["type"] == "timeout"
    assert record["error"]["attempts"] == 2
    canonical = json.dumps(
        captured["payload"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    assert record["input_hash"] == hashlib.sha256(canonical).hexdigest()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_key", ["_scan_failed", "_style_writer_failed"])
async def test_downstream_generation_failures_are_error_not_pending(
    monkeypatch, tmp_path, failure_key
):
    root = tmp_path / "records"
    monkeypatch.setenv("QING_AGENT_VALIDATION_ROOT", str(root))
    result = _graph_result()
    if failure_key == "_scan_failed":
        result["market_context"] = dict(result["market_summary_context"])
        result["market_context"][failure_key] = True
    else:
        result[failure_key] = True

    response = await _call_with_result(monkeypatch, result)

    record = _only_record(root)
    assert response.record_status == "error"
    assert record["status"] == "error"
    assert record["directions"][0]["score_eligible"] is False


def test_wrapper_does_not_present_error_response_as_success(
    monkeypatch, tmp_path, capsys
):
    root = tmp_path / "records"
    monkeypatch.setenv("QING_AGENT_VALIDATION_ROOT", str(root))
    data = {
        "timestamp": "2026-11-02T10:00:00+08:00",
        "trigger": {"id": "morning_confirm", "title": "十点确认", "reason": "测试"},
        "quote_snapshot": {"timestamp": "2026-11-02T10:00:00+08:00", "quotes": [{"code": "000001"}]},
    }
    response = {
        "final_output": "非空降级文本",
        "record_status": "error",
        "record_id": "server-error-record",
    }
    monkeypatch.setattr(wrapper, "fetch_json_context", lambda root: data)
    monkeypatch.setattr(wrapper, "call_qing_agent", lambda value: response)
    monkeypatch.setattr(wrapper, "QING_AGENT_FALLBACK_ENABLED", True)
    monkeypatch.setattr(
        wrapper, "fetch_fallback_text_context", lambda root, value: "ERROR FALLBACK"
    )

    assert wrapper.main() == 0

    output = capsys.readouterr().out
    assert "[Qing-Agent ✓]" not in output
    assert "ERROR FALLBACK" in output
    assert not list(root.rglob("*.json"))
