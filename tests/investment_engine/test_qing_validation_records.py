import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest

import investment_engine.qing_validation.records as records_module
from investment_engine.qing_validation import (
    build_record,
    record_path,
    resolve_track,
    save_record,
)


GENERATED_AT = "2026-11-02T08:30:00+08:00"


def _direction(**overrides):
    direction = {
        "direction_id": "dir-001",
        "stock_code": "600000.SH",
        "horizon": "T+5",
        "polarity": "long",
        "invalidation": "收盘价跌破 10 元",
    }
    direction.update(overrides)
    return direction


def _final_judgment(**overrides):
    judgment = {
        "data_as_of": "2026-11-01T15:00:00+08:00",
        "market_stage": "上升段",
        "direction": ["银行"],
        "horizon": "T+5",
        "trigger_conditions": ["放量确认"],
        "invalidation_conditions": ["跌破失效位"],
    }
    judgment.update(overrides)
    return judgment


def _assert_all_score_gates_false(record):
    items = [
        record["final_judgment"],
        *record["directions"],
        *record["expert_views"],
    ]
    assert items
    assert all(item["score_eligible"] is False for item in items)


def _record(**overrides):
    kwargs = {
        "trigger": {"id": "pre_market", "request_id": "request-001"},
        "data_as_of": "2026-11-01T15:00:00+08:00",
        "input_payload": {"market": {"phase": "震荡"}},
        "generated_at": GENERATED_AT,
    }
    kwargs.update(overrides)
    return build_record(**kwargs)


@pytest.mark.parametrize(
    ("trigger_id", "expected"),
    [
        ("pre_market", "pre_market"),
        ("closing_review", "closing"),
        ("intraday", "intraday"),
        ("afternoon_alert", "intraday"),
    ],
)
def test_resolve_track(trigger_id, expected):
    assert resolve_track({"id": trigger_id}) == expected


def test_three_tracks_do_not_overwrite_each_other(tmp_path):
    record_id = "shared-record-id"
    paths = []

    for trigger_id, track in [
        ("pre_market", "pre_market"),
        ("intraday", "intraday"),
        ("closing_review", "closing"),
    ]:
        record = _record(record_id=record_id, trigger={"id": trigger_id})
        path = save_record(record, root=tmp_path)
        paths.append(path)
        assert path == tmp_path / "2026-11-02" / track / f"{record_id}.json"
        assert json.loads(path.read_text(encoding="utf-8"))["track"] == track

    assert len(set(paths)) == 3
    assert all(path.exists() for path in paths)


def test_rerun_adds_linked_version_without_changing_old_bytes(tmp_path):
    first = _record(record_id="run-001", raw_output="第一次判断")
    first_path = save_record(first, root=tmp_path)
    first_bytes = first_path.read_bytes()

    second = _record(
        record_id="run-002",
        raw_output="重跑后的判断",
        supersedes_record_id=first["record_id"],
    )
    second_path = save_record(second, root=tmp_path)

    assert first_path.read_bytes() == first_bytes
    assert second_path != first_path
    assert json.loads(second_path.read_text(encoding="utf-8"))["supersedes_record_id"] == "run-001"
    assert json.loads(first_path.read_text(encoding="utf-8"))["raw_output"] == "第一次判断"


def test_save_uses_exclusive_creation_and_never_overwrites(tmp_path):
    record = _record(record_id="exclusive-001", raw_output="原始内容")
    path = save_record(record, root=tmp_path)
    original_bytes = path.read_bytes()

    replacement = dict(record, raw_output="试图覆盖")
    with pytest.raises(FileExistsError):
        save_record(replacement, root=tmp_path)

    assert path.read_bytes() == original_bytes


def test_complete_direction_is_score_eligible_without_mutating_input():
    direction = _direction(score_eligible=False)
    record = _record(directions=[direction])

    assert record["directions"][0]["score_eligible"] is True
    assert direction == _direction(score_eligible=False)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("direction_id", ""),
        ("stock_code", None),
        ("horizon", "T+1"),
        ("horizon", None),
        ("polarity", "  "),
        ("invalidation", ""),
    ],
)
def test_incomplete_direction_is_not_score_eligible(field, value):
    record = _record(directions=[_direction(**{field: value}, score_eligible=True)])
    assert record["directions"][0]["score_eligible"] is False


def test_missing_data_as_of_disables_scoring_even_for_complete_direction():
    record = _record(data_as_of="", directions=[_direction(score_eligible=True)])
    assert record["directions"][0]["score_eligible"] is False


def test_error_and_missing_are_independent_and_never_score_eligible():
    final_judgment = {"market_stage": "震荡", "score_eligible": True}
    error = _record(
        record_id="error-001",
        status="error",
        error={"kind": "timeout"},
        final_judgment=final_judgment,
        directions=[_direction(score_eligible=True)],
        expert_views=[{"school": "gator", "score_eligible": True}],
    )
    missing = _record(
        record_id="missing-001",
        status="missing",
        input_availability={"missing": ["original_input_snapshot"]},
        final_judgment=final_judgment,
        directions=[_direction(score_eligible=True)],
        expert_views=[{"school": "gator", "score_eligible": True}],
    )

    assert error["status"] == "error"
    assert error["error"] == {"kind": "timeout"}
    assert missing["status"] == "missing"
    assert missing["error"] is None
    assert missing["input_availability"]["missing"] == ["original_input_snapshot"]
    for record in (error, missing):
        assert record["final_judgment"]["score_eligible"] is False
        assert all(item["score_eligible"] is False for item in record["directions"])
        assert all(view["score_eligible"] is False for view in record["expert_views"])


def test_final_judgment_fields_are_preserved_without_inventing_missing_fields():
    final_judgment = {
        "data_as_of": "2026-11-01T15:00:00+08:00",
        "market_stage": "上升段",
        "rationale": ["量能扩大"],
        "direction": "bullish",
        "targets": [{"stock_code": "600000.SH"}],
        "horizon": "T+5",
        "trigger_conditions": ["放量突破"],
        "invalidation": "跌破突破位",
        "score_eligible": True,
        "custom_context": {"source": "test"},
    }
    record = _record(final_judgment=final_judgment)

    assert record["final_judgment"] == final_judgment
    assert "targets" not in _record(final_judgment={"market_stage": "震荡"})["final_judgment"]


def test_default_root_and_call_time_environment_override(monkeypatch, tmp_path):
    monkeypatch.delenv("QING_AGENT_VALIDATION_ROOT", raising=False)
    fake_repo = tmp_path / "repo"
    monkeypatch.setattr(records_module, "repo_root", lambda: fake_repo)
    record = _record(record_id="root-001")

    assert record_path(record) == (
        fake_repo / "infra" / "data" / "qing_agent" / "2026-11-02" / "pre_market" / "root-001.json"
    )

    redirected = tmp_path / "redirected"
    monkeypatch.setenv("QING_AGENT_VALIDATION_ROOT", str(redirected))
    path = save_record(record)
    assert path == redirected / "2026-11-02" / "pre_market" / "root-001.json"
    assert path.exists()
    assert not (fake_repo / "infra" / "data").exists()


def test_input_hash_is_canonical_and_raw_holdings_are_not_saved(tmp_path):
    payload = {
        "positions": [{"stock_code": "600000.SH", "shares": 12345}],
        "watchlist": ["机密标的"],
        "nested": {"b": 2, "a": 1},
    }
    reordered_payload = {
        "nested": {"a": 1, "b": 2},
        "watchlist": ["机密标的"],
        "positions": [{"stock_code": "600000.SH", "shares": 12345}],
    }
    first = _record(record_id="hash-001", input_payload=payload)
    second = _record(record_id="hash-002", input_payload=reordered_payload)
    expected = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()

    assert first["input_hash"] == expected
    assert second["input_hash"] == expected
    assert "input_payload" not in first
    assert {"positions", "watchlist"}.isdisjoint(first)

    path = save_record(first, root=tmp_path)
    serialized = path.read_text(encoding="utf-8")
    assert "12345" not in serialized
    assert "机密标的" not in serialized
    assert '"positions"' not in serialized
    assert '"watchlist"' not in serialized


def test_generated_at_defaults_to_timezone_aware_timestamp():
    record = _record(generated_at=None)
    generated_at = datetime.fromisoformat(record["generated_at"])

    assert generated_at.utcoffset() is not None
    assert record["date"] == generated_at.date().isoformat()
    assert record["record_id"]


@pytest.mark.parametrize(
    "unsafe_id", ["", "../escape", "..", "nested/id", "nested\\id", "/absolute"]
)
def test_record_id_cannot_escape_storage_directory(unsafe_id, tmp_path):
    with pytest.raises(ValueError):
        save_record(_record(record_id=unsafe_id), root=tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_record_contains_version_availability_and_append_only_reference_fields():
    record = _record(
        input_availability={"available": ["market"], "missing": ["expert_daily"]},
        data_version="data-v1",
        rules_version="rules-v1",
        prompt_version="prompt-v1",
        review={"passed": True},
        citations={"patterns": ["pattern-1"]},
    )

    assert record["input_availability"] == {
        "available": ["market"],
        "missing": ["expert_daily"],
    }
    assert record["data_version"] == "data-v1"
    assert record["rules_version"] == "rules-v1"
    assert record["prompt_version"] == "prompt-v1"
    assert record["review"] == {"passed": True}
    assert record["citations"] == {"patterns": ["pattern-1"]}
    assert record["settlement"] is None
    assert record["attribution"] is None
    assert record["supersedes_record_id"] is None


@pytest.mark.parametrize(
    "invalid_data_as_of",
    ["", None, "not-a-time", "2026-11-02T25:00:00"],
)
def test_invalid_data_as_of_is_frozen_but_disables_every_score_gate(invalid_data_as_of):
    record = _record(
        data_as_of=invalid_data_as_of,
        final_judgment=_final_judgment(score_eligible=True),
        directions=[_direction(score_eligible=True)],
        expert_views=[_direction(school="gator", score_eligible=True)],
    )

    assert record["data_as_of"] == invalid_data_as_of
    _assert_all_score_gates_false(record)


@pytest.mark.parametrize(
    ("data_as_of", "generated_at"),
    [
        ("2026-11-02T08:30:01+08:00", GENERATED_AT),
        ("2026-11-02T08:30:01", "2026-11-02T08:30:00"),
        ("9999-01-01", GENERATED_AT),
    ],
)
def test_future_data_as_of_disables_every_score_gate(data_as_of, generated_at):
    record = _record(
        data_as_of=data_as_of,
        generated_at=generated_at,
        final_judgment=_final_judgment(score_eligible=True),
        directions=[_direction(score_eligible=True)],
        expert_views=[_direction(school="gator", score_eligible=True)],
    )

    _assert_all_score_gates_false(record)


@pytest.mark.parametrize(
    ("data_as_of", "generated_at"),
    [
        ("2026-11-01T15:00:00", "2026-11-02T08:30:00"),
        ("2026-11-01T15:00:00", GENERATED_AT),
        ("2026-11-01", GENERATED_AT),
    ],
)
def test_parseable_naive_and_mixed_timezone_data_can_score(data_as_of, generated_at):
    record = _record(
        data_as_of=data_as_of,
        generated_at=generated_at,
        final_judgment=_final_judgment(data_as_of=data_as_of, score_eligible=False),
        directions=[_direction(score_eligible=False)],
        expert_views=[_direction(school="gator", score_eligible=False)],
    )

    assert record["final_judgment"]["score_eligible"] is True
    assert record["directions"][0]["score_eligible"] is True
    assert record["expert_views"][0]["score_eligible"] is True


@pytest.mark.parametrize(
    "judgment_data_as_of",
    ["", None, "not-a-time", "2026-11-02T08:30:01+08:00"],
)
def test_final_judgment_uses_its_own_valid_data_as_of(judgment_data_as_of):
    record = _record(
        final_judgment=_final_judgment(
            data_as_of=judgment_data_as_of,
            score_eligible=True,
        ),
        directions=[_direction()],
    )

    assert record["final_judgment"]["data_as_of"] == judgment_data_as_of
    assert record["final_judgment"]["score_eligible"] is False
    assert record["directions"][0]["score_eligible"] is True


def test_final_judgment_scoring_is_independent_of_directions():
    record = _record(
        final_judgment=_final_judgment(score_eligible=False),
        directions=[_direction(stock_code="not-a-code", score_eligible=True)],
    )

    assert record["final_judgment"]["score_eligible"] is True
    assert record["directions"][0]["score_eligible"] is False


def test_final_judgment_accepts_singular_trigger_and_invalidation_fields():
    judgment = _final_judgment(score_eligible=False)
    judgment.pop("trigger_conditions")
    judgment.pop("invalidation_conditions")
    judgment["trigger"] = "放量确认"
    judgment["invalidation"] = "跌破失效位"

    record = _record(final_judgment=judgment)

    assert record["final_judgment"]["score_eligible"] is True


@pytest.mark.parametrize(
    "stock_code",
    ["600000", "600000.SH", "sh600000", "1.600000", 600000],
)
def test_direction_accepts_stock_codes_with_one_extractable_six_digit_code(stock_code):
    record = _record(directions=[_direction(stock_code=stock_code)])

    assert record["directions"][0]["stock_code"] == stock_code
    assert record["directions"][0]["score_eligible"] is True


@pytest.mark.parametrize(
    "stock_code",
    [
        "",
        None,
        "60000",
        "6000000",
        "600000.SH/000001.SZ",
        "600000/600000",
        "600000600001",
        "not-a-code",
    ],
)
def test_direction_rejects_ambiguous_or_missing_stock_code_without_rewriting_it(stock_code):
    record = _record(directions=[_direction(stock_code=stock_code)])

    assert record["directions"][0]["stock_code"] == stock_code
    assert record["directions"][0]["score_eligible"] is False


@pytest.mark.parametrize(
    ("polarity", "normalized"),
    [("long", "long"), ("LONG", "long"), ("Short", "short"), (" neutral ", "neutral")],
)
def test_direction_normalizes_supported_polarity(polarity, normalized):
    record = _record(directions=[_direction(polarity=polarity)])

    assert record["directions"][0]["polarity"] == normalized
    assert record["directions"][0]["score_eligible"] is True


@pytest.mark.parametrize("polarity", ["", None, "bullish", "bearish", "up", 1])
def test_direction_rejects_unknown_polarity_without_rewriting_it(polarity):
    record = _record(directions=[_direction(polarity=polarity)])

    assert record["directions"][0]["polarity"] == polarity
    assert record["directions"][0]["score_eligible"] is False


def test_duplicate_direction_ids_make_all_duplicates_ineligible():
    record = _record(
        directions=[
            _direction(direction_id="duplicate", stock_code="600000"),
            _direction(direction_id="duplicate", stock_code="000001"),
            _direction(direction_id="unique", stock_code="000002"),
        ]
    )

    assert [item["score_eligible"] for item in record["directions"]] == [
        False,
        False,
        True,
    ]


def test_expert_view_score_eligibility_is_always_recomputed():
    complete = _direction(
        direction_id="expert-complete",
        school="gator",
        score_eligible=False,
    )
    incomplete = {
        "school": "qing",
        "view": "只有观点，没有独立结算字段",
        "horizon": "T+5",
        "score_eligible": True,
    }

    record = _record(expert_views=[complete, incomplete])

    assert record["expert_views"][0]["score_eligible"] is True
    assert record["expert_views"][1]["score_eligible"] is False
    assert complete["score_eligible"] is False
    assert incomplete["score_eligible"] is True


def test_failed_atomic_publish_leaves_no_final_json_or_temp_file(monkeypatch, tmp_path):
    record = _record(record_id="fsync-failure")

    def fail_fsync(_fd):
        raise OSError("injected fsync failure")

    monkeypatch.setattr(records_module.os, "fsync", fail_fsync)
    with pytest.raises(OSError, match="injected fsync failure"):
        save_record(record, root=tmp_path)

    assert not record_path(record, root=tmp_path).exists()
    assert list(tmp_path.rglob("*.json")) == []
    assert list(tmp_path.rglob("*.tmp")) == []


def test_concurrent_same_id_publish_has_one_complete_winner(tmp_path):
    records = [
        _record(record_id="concurrent-id", raw_output="版本 A"),
        _record(record_id="concurrent-id", raw_output="版本 B"),
    ]

    def attempt(record):
        try:
            return "saved", save_record(record, root=tmp_path)
        except FileExistsError:
            return "conflict", None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, records))

    assert [status for status, _path in results].count("saved") == 1
    assert [status for status, _path in results].count("conflict") == 1
    winner = next(record for record, (status, _path) in zip(records, results) if status == "saved")
    path = next(path for status, path in results if status == "saved")
    assert json.loads(path.read_text(encoding="utf-8"))["raw_output"] == winner["raw_output"]
    assert list(tmp_path.rglob("*.tmp")) == []


def test_same_hash_rerun_auto_links_latest_and_preserves_old_bytes(tmp_path):
    first = _record(record_id="auto-001", generated_at="2026-11-02T08:30:00+08:00")
    second = _record(
        record_id="auto-002",
        generated_at="2026-11-02T08:31:00+08:00",
        supersedes_record_id="",
    )
    third = _record(record_id="auto-003", generated_at="2026-11-02T08:32:00+08:00")

    first_path = save_record(first, root=tmp_path)
    first_bytes = first_path.read_bytes()
    second_path = save_record(second, root=tmp_path)
    third_path = save_record(third, root=tmp_path)

    second_saved = json.loads(second_path.read_text(encoding="utf-8"))
    third_saved = json.loads(third_path.read_text(encoding="utf-8"))
    assert second_saved["supersedes_record_id"] == "auto-001"
    assert third_saved["supersedes_record_id"] == "auto-002"
    assert first_path.read_bytes() == first_bytes
    assert json.loads(first_path.read_text(encoding="utf-8"))["supersedes_record_id"] is None


def test_auto_link_requires_same_hash_date_and_track(tmp_path):
    first = _record(record_id="scope-original")
    save_record(first, root=tmp_path)
    candidates = [
        _record(record_id="scope-other-date", generated_at="2026-11-03T08:30:00+08:00"),
        _record(record_id="scope-other-track", trigger={"id": "closing_review"}),
        _record(record_id="scope-other-hash", input_payload={"market": {"phase": "不同"}}),
    ]

    for candidate in candidates:
        path = save_record(candidate, root=tmp_path)
        assert json.loads(path.read_text(encoding="utf-8"))["supersedes_record_id"] is None


def test_explicit_supersedes_must_exist_in_same_track(tmp_path):
    target = _record(record_id="explicit-target")
    target_path = save_record(target, root=tmp_path)
    target_bytes = target_path.read_bytes()
    dangling = _record(record_id="dangling", supersedes_record_id="absent")
    cross_track = _record(
        record_id="cross-track",
        trigger={"id": "closing_review"},
        supersedes_record_id=target["record_id"],
    )

    with pytest.raises(ValueError, match="supersedes_record_id"):
        save_record(dangling, root=tmp_path)
    with pytest.raises(ValueError, match="supersedes_record_id"):
        save_record(cross_track, root=tmp_path)

    assert target_path.read_bytes() == target_bytes
    assert not record_path(dangling, root=tmp_path).exists()
    assert not record_path(cross_track, root=tmp_path).exists()


def test_explicit_supersedes_cannot_point_to_newer_record(tmp_path):
    target = _record(record_id="newer-target", generated_at="2026-11-02T08:31:00+08:00")
    target_path = save_record(target, root=tmp_path)
    target_bytes = target_path.read_bytes()
    older = _record(
        record_id="older-rerun",
        generated_at=GENERATED_AT,
        supersedes_record_id=target["record_id"],
    )

    with pytest.raises(ValueError, match="generated_at"):
        save_record(older, root=tmp_path)

    assert target_path.read_bytes() == target_bytes
    assert not record_path(older, root=tmp_path).exists()
    assert list(tmp_path.rglob("*.tmp")) == []
