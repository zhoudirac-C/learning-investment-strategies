import hashlib
import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest

from investment_engine.qing_validation.report import (
    collect_daily,
    collect_reliability,
    render_daily,
    render_reliability,
    write_reports,
)


DAY = "2026-07-15"


def _record(record_id, *, day=DAY, track="pre_market", status="pending_maturity", **overrides):
    record = {
        "record_id": record_id,
        "date": day,
        "track": track,
        "generated_at": f"{day}T08:30:00+08:00",
        "data_as_of": f"{day}T08:00:00+08:00",
        "status": status,
        "final_judgment": {
            "market_stage": "震荡",
            "direction": "up",
            "horizon": "T+5",
            "trigger_conditions": ["confirmed"],
            "invalidation_conditions": ["invalidated"],
        },
        "raw_output": f"RAW-SECRET-{record_id}",
        "expert_views": [{"school": "gator", "view": f"EXPERT-SECRET-{record_id}"}],
        "data_version": "data-v1",
        "rules_version": "rules-v1",
        "prompt_version": "prompt-v1",
        "review": {"passed": True, "notes": []},
        "input_availability": {"missing": []},
        "settlement": None,
        "attribution": None,
        "stage_hit": None,
        "input_snapshot": {"positions": [f"POSITION-SECRET-{record_id}"]},
    }
    record.update(overrides)
    return record


def _save(root, record):
    path = Path(root) / record["date"] / record["track"] / f"{record['record_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _item(record_id, *, day=DAY, target="final", school=None, target_id=None,
          metric="direction", status="scored", hit=True):
    return {
        "record_id": record_id,
        "date": day,
        "target": target,
        "school": school,
        "target_id": target_id or f"{record_id}-{target}-{metric}",
        "metric": metric,
        "status": status,
        "hit": hit,
        "dir_ret": 0.02,
        "ret": 0.03,
        "bench_ret": 0.01,
    }


def _with_items(record, items):
    record["settlement"] = {"day": DAY, "status": "scored", "items": items}
    return record


def _calendar(db_path, days):
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE stocks_kline (trade_date TEXT)")
        conn.executemany("INSERT INTO stocks_kline VALUES (?)", [(day,) for day in days])


def _weekdays(start, end):
    current = date.fromisoformat(start)
    last = date.fromisoformat(end)
    days = []
    while current <= last:
        if current.weekday() < 5:
            days.append(current.isoformat())
        current += timedelta(days=1)
    return days


def _id(value, *, prefix="id"):
    serialized = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _row(window, target, metric, stage):
    return next(
        row for row in window["rows"]
        if (row["target"], row["metric"], row["market_stage"]) == (target, metric, stage)
    )


def test_daily_separates_tracks_statuses_and_superseded_versions_without_leaking(tmp_path):
    root = tmp_path / "records"
    old = _record("old", status="error", raw_output="OLD-RAW-SECRET")
    _save(root, old)
    current = _record("current", supersedes_record_id="old")
    _save(root, current)
    _save(root, _record("scored", status="scored"))
    _save(root, _record("failed", track="closing", status="error"))
    _save(root, _record("absent", track="closing", status="missing"))

    daily = collect_daily(DAY, root=root)
    text = render_daily(daily)

    assert daily["status_counts"] == {"pending": 1, "scored": 1, "error": 1, "missing": 1}
    assert daily["missing_tracks"] == ["intraday"]
    assert [entry["record_id"] for entry in daily["tracks"]["pre_market"]] == [_id("current"), _id("scored")]
    assert {entry["record_id"] for entry in daily["tracks"]["closing"]} == {_id("failed"), _id("absent")}
    assert daily["tracks"]["intraday"] == []
    assert "old" not in text
    assert "RAW-SECRET" not in text
    assert "EXPERT-SECRET" not in text
    assert "POSITION-SECRET" not in text
    assert "pre_market" in text and "intraday" in text and "closing" in text


def test_daily_reports_missing_fields_prediction_gates_and_structured_review_errors(tmp_path):
    root = tmp_path / "records"
    incomplete = _record(
        "incomplete",
        generated_at="not-a-time",
        data_as_of=None,
        final_judgment={"market_stage": "震荡", "direction": "up"},
        raw_output="",
        expert_views=None,
        data_version=None,
        rules_version=None,
        prompt_version=None,
        review={"passed": False, "notes": ["人工备注，不等于事实错误"]},
        fact_errors=[{"code": "fact_error", "field": "citations"}],
        school_attribution_errors=[{"code": "school_attribution_error", "school": "gator"}],
    )
    _save(root, incomplete)
    _save(
        root,
        _record(
            "notes-only",
            track="intraday",
            review={"passed": False, "notes": ["仅流程备注"]},
        ),
    )
    closing = _record(
        "closing-explanation",
        track="closing",
        final_judgment={"market_stage": "震荡", "rationale": ["当日解释"]},
        stage_hit="not_applicable",
    )
    _save(root, closing)
    _save(root, _record("no-available-views", expert_views=[]))

    daily = collect_daily(DAY, root=root)
    entries = {entry["record_id"]: entry for entry in daily["records"]}
    incomplete = entries[_id("incomplete")]
    notes_only = entries[_id("notes-only")]
    closing_explanation = entries[_id("closing-explanation")]
    no_available_views = entries[_id("no-available-views")]
    missing = set(incomplete["missing_fields"])
    assert {"data_as_of", "raw_output", "expert_views", "data_version", "rules_version", "prompt_version"} <= missing
    assert "expert_views" not in no_available_views["missing_fields"]
    assert incomplete["invalid_fields"] == ["generated_at"]
    assert set(incomplete["prediction_missing_fields"]) == {
        "final_judgment.horizon",
        "final_judgment.trigger_conditions",
        "final_judgment.invalidation_conditions",
    }
    assert incomplete["review_passed"] is False
    assert incomplete["review_note_count"] == 1
    assert incomplete["review_codes"] == []
    assert incomplete["fact_errors"] == [{"code": "fact_error"}]
    assert incomplete["school_attribution_errors"] == [
        {"code": "school_attribution_error", "school": "gator"}
    ]
    assert notes_only["fact_errors"] == []
    assert notes_only["school_attribution_errors"] == []
    assert closing_explanation["prediction_missing_fields"] == []
    text = render_daily(daily)
    assert "note_count=1" in text
    assert "人工备注，不等于事实错误" not in text
    assert "fact_error" in text and "school_attribution_error" in text
    assert "RAW-SECRET" not in text and "POSITION-SECRET" not in text


def test_reliability_4_and_8_week_iso_boundaries_exclude_future_records(tmp_path):
    root = tmp_path / "records"
    db_path = tmp_path / "calendar.db"
    _calendar(db_path, _weekdays("2026-05-25", DAY))
    specs = [
        ("before-8", "2026-05-24"),
        ("at-8-start", "2026-05-25"),
        ("before-4", "2026-06-21"),
        ("at-4-start", "2026-06-22"),
        ("future", "2026-07-16"),
    ]
    for record_id, day in specs:
        _save(root, _record(record_id, day=day, status="scored"))
    _save(root, _record("on-report-day", status="scored"))

    reliability = collect_reliability(DAY, root=root, db_path=db_path, validation_start="2026-01-01")
    four = reliability["windows"][4]
    eight = reliability["windows"][8]

    assert four["start"] == "2026-06-22" and four["end"] == DAY
    assert eight["start"] == "2026-05-25" and eight["end"] == DAY
    assert four["record_ids"] == [_id("at-4-start"), _id("on-report-day")]
    assert eight["record_ids"] == [
        _id("at-8-start"), _id("before-4"), _id("at-4-start"), _id("on-report-day")
    ]
    assert all("future" != record_id for record_id in eight["record_ids"])
    assert all("before-8" != record_id for record_id in eight["record_ids"])


def test_reliability_separates_final_expert_metrics_stages_and_all_non_scored_statuses(tmp_path):
    root = tmp_path / "records"
    db_path = tmp_path / "calendar.db"
    days = _weekdays("2026-06-22", DAY)
    _calendar(db_path, days)
    scored = _record(
        "scored",
        day="2026-06-22",
        status="scored",
        final_judgment={**_record("x")["final_judgment"], "market_stage": "震荡"},
        stage_hit=True,
    )
    items = [
        _item("scored", day="2026-06-22", hit=False),
        _item("scored", day="2026-06-22", metric="stock", hit=True),
        _item("scored", day="2026-06-22", target="expert", school="qing", hit=True),
        _item("scored", day="2026-06-22", target="expert", school="gator", metric="stock", hit=False),
    ]
    _save(root, _with_items(scored, items))
    other_stage = _record(
        "other-stage",
        day="2026-06-23",
        status="scored",
        final_judgment={**_record("x")["final_judgment"], "market_stage": "主升"},
        stage_hit=False,
    )
    _save(root, _with_items(other_stage, [_item("other-stage", day="2026-06-23", hit=True)]))
    for record_id, day, item_status in [
        ("pending", "2026-06-24", "pending_maturity"),
        ("insufficient", "2026-06-25", "insufficient_data"),
        ("not-applicable", "2026-06-26", "not_applicable"),
        ("non-bool", "2026-06-29", "scored"),
    ]:
        record = _record(record_id, day=day)
        hit = 1 if record_id == "non-bool" else None
        _save(root, _with_items(record, [_item(record_id, day=day, status=item_status, hit=hit)]))
    _save(root, _record("error", day="2026-06-30", status="error"))
    _save(root, _record("missing", day="2026-07-01", status="missing"))
    closing = _record(
        "closing",
        day="2026-07-02",
        track="closing",
        status="scored",
        stage_hit=True,
    )
    _save(root, _with_items(closing, []))

    window = collect_reliability(DAY, root=root, db_path=db_path, validation_start="2026-01-01")["windows"][4]
    final_direction = _row(window, "final", "direction", "震荡")
    assert (final_direction["n"], final_direction["hits"], final_direction["hit_rate"]) == (1, 0, 0.0)
    assert final_direction["pending_maturity"] == 1
    assert final_direction["insufficient_data"] == 1
    assert final_direction["not_applicable"] == 1
    assert final_direction["invalid_scored"] == 1
    assert _row(window, "final", "stock", "震荡")["n"] == 1
    assert _row(window, "expert", "direction", "震荡")["n"] == 1
    assert _row(window, "expert", "stock", "震荡")["hits"] == 0
    assert _row(window, "final", "direction", "主升")["n"] == 1
    assert window["item_status_counts"] == {
        "scored": 6,
        "pending_maturity": 1,
        "insufficient_data": 1,
        "not_applicable": 1,
    }
    assert window["record_counts"]["error"] == 1
    assert window["record_counts"]["missing"] == 1
    assert window["stage"] == {"n": 2, "hits": 1, "hit_rate": pytest.approx(1 / 2), "status": "ok"}


def test_zero_valid_samples_and_calendar_are_explicitly_insufficient(tmp_path):
    root = tmp_path / "records"
    record = _record("zero", day="2026-07-14")
    _save(root, _with_items(record, [
        _item("zero", day="2026-07-14", target="expert", school="gator", metric="stock",
              status="insufficient_data", hit=None)
    ]))
    empty_db = tmp_path / "empty.db"
    _calendar(empty_db, [])

    reliability = collect_reliability(DAY, root=root, db_path=empty_db, validation_start="2026-01-01")
    window = reliability["windows"][4]
    row = _row(window, "expert", "stock", "震荡")
    assert row["n"] == 0 and row["hit_rate"] is None and row["status"] == "insufficient_data"
    assert window["calendar"] == "insufficient_data"
    assert window["expected_days"] == [] and window["missing_days"] is None
    assert window["missing_days_status"] == "unknown"
    text = render_reliability(reliability)
    assert "calendar=insufficient_data" in text
    assert "缺报日期: unknown" in text
    assert "缺报日期: 无" not in text
    assert "连续缺报未知" in text
    assert "insufficient_data" in text
    assert "graduated" not in text and "not_yet" not in text
    expert_lines = [line for line in text.splitlines() if "| expert | stock |" in line]
    assert expert_lines and all("0.0%" not in line and "0%" not in line for line in expert_lines)


def test_missing_days_and_consecutive_gap_alert_use_only_valid_records(tmp_path):
    root = tmp_path / "records"
    db_path = tmp_path / "calendar.db"
    expected = ["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-06"]
    _calendar(db_path, expected)
    _save(root, _record("valid-pending", day="2026-07-01"))
    _save(root, _record("valid-scored", day="2026-07-06", status="scored"))
    _save(root, _record("only-error", day="2026-07-02", status="error"))
    _save(root, _record("only-missing", day="2026-07-03", status="missing"))

    window = collect_reliability(
        "2026-07-06", root=root, db_path=db_path, validation_start="2026-01-01"
    )["windows"][4]
    assert window["expected_days"] == expected
    assert window["missing_days"] == ["2026-07-02", "2026-07-03"]
    assert window["missing_days_status"] == "non_exhaustive"
    assert window["consecutive_missing"] == [["2026-07-02", "2026-07-03"]]
    text = render_reliability({"date": "2026-07-06", "windows": {4: window, 8: window}})
    assert "连续缺报告警" in text
    assert "2026-07-02~2026-07-03" in text
    assert "非完整" in text
    assert text.index("连续缺报告警") < text.index("窗口统计")


def test_attribution_status_counts_keep_record_and_school_identity(tmp_path):
    root = tmp_path / "records"
    db_path = tmp_path / "calendar.db"
    _calendar(db_path, [DAY])
    record = _record("attributed", status="scored")
    record["attribution"] = {
        "candidates": [
            {"record_id": "attributed", "target": "expert", "school": "qing", "target_id": "q-1", "metric": "direction", "status": "pending_review", "review_items": []},
            {"record_id": "attributed", "target": "expert", "school": "gator", "target_id": "g-1", "metric": "direction", "status": "reviewed", "review_items": []},
            {"record_id": "attributed", "target": "expert", "school": "gator", "target_id": "g-2", "metric": "stock", "status": "rejected", "review_items": []},
            {"record_id": "attributed", "target": "expert", "school": "qing", "target_id": "q-2", "metric": "direction", "status": "in_progress", "review_items": []},
            {"record_id": "attributed", "target": "expert", "school": "qing", "target_id": "q-3", "metric": "direction", "status": None, "review_items": []},
            {"record_id": "attributed", "target": "expert", "school": "gator", "target_id": "g-3", "metric": "stock", "status": "unknown", "review_items": []},
        ]
    }
    _save(root, record)

    attribution = collect_reliability(DAY, root=root, db_path=db_path, validation_start="2026-01-01")["windows"][8]["attribution"]
    assert attribution["pending_review"] == 1
    assert attribution["human_reviewed"] == 2
    assert attribution["status_counts"] == {
        "in_progress": 1,
        "pending_review": 1,
        "reviewed": 1,
        "rejected": 1,
        "unknown": 2,
    }
    assert attribution["other_status_counts"] == {"in_progress": 1, "unknown": 2}
    assert {(item["school"], item["target_id"], item["status"]) for item in attribution["candidates"]} == {
        ("qing", _id("q-1"), "pending_review"),
        ("gator", _id("g-1"), "reviewed"),
        ("gator", _id("g-2"), "rejected"),
        ("qing", _id("q-2"), "in_progress"),
        ("qing", _id("q-3"), "unknown"),
        ("gator", _id("g-3"), "unknown"),
    }
    assert attribution["by_school"] == [
        {"school": "gator", "status": "rejected", "count": 1},
        {"school": "gator", "status": "reviewed", "count": 1},
        {"school": "gator", "status": "unknown", "count": 1},
        {"school": "qing", "status": "in_progress", "count": 1},
        {"school": "qing", "status": "pending_review", "count": 1},
        {"school": "qing", "status": "unknown", "count": 1},
    ]


def test_write_reports_uses_contract_paths_and_does_not_modify_frozen_records(tmp_path):
    root = tmp_path / "records"
    out_dir = tmp_path / "reports"
    db_path = tmp_path / "calendar.db"
    path = _save(root, _record("readonly"))
    before = path.read_bytes()
    _calendar(db_path, [DAY])

    paths = write_reports(
        DAY, root=root, db_path=db_path, out_dir=out_dir, validation_start="2026-01-01"
    )

    assert paths == {
        "daily": out_dir / f"qing-agent-daily-{DAY}.md",
        "reliability": out_dir / f"qing-agent-reliability-{DAY}.md",
    }
    assert all(report_path.is_file() for report_path in paths.values())
    assert path.read_bytes() == before
    assert "RAW-SECRET" not in paths["daily"].read_text(encoding="utf-8")


def test_rolling_metrics_keep_tracks_separate_for_same_target_metric_and_stage(tmp_path):
    root = tmp_path / "records"
    db_path = tmp_path / "calendar.db"
    day = "2026-11-02"
    _calendar(db_path, [day])
    pre_market = _record("pre-scored", day=day, status="scored", stage_hit=True)
    closing = _record(
        "closing-scored",
        day=day,
        track="closing",
        status="scored",
        stage_hit=True,
    )
    _save(root, _with_items(pre_market, [
        _item("pre-scored", day=day, hit=True),
    ]))
    _save(root, _with_items(closing, [
        _item("closing-scored", day=day, hit=False),
        _item("closing-pending", day=day, status="pending_maturity", hit=None),
    ]))

    reliability = collect_reliability(day, root=root, db_path=db_path)
    window = reliability["windows"][4]
    matching = [
        row for row in window["rows"]
        if (row["target"], row["metric"], row["market_stage"]) == ("final", "direction", "震荡")
    ]
    assert len(matching) == 2
    rows = {row["track"]: row for row in matching}
    assert (rows["pre_market"]["n"], rows["pre_market"]["hits"], rows["pre_market"]["hit_rate"]) == (1, 1, 1.0)
    assert rows["pre_market"]["pending_maturity"] == 0
    assert (rows["closing"]["n"], rows["closing"]["hits"], rows["closing"]["hit_rate"]) == (1, 0, 0.0)
    assert rows["closing"]["pending_maturity"] == 1
    assert window["item_status_counts"]["scored"] == 2
    assert window["item_status_counts"]["pending_maturity"] == 1
    assert window["stage"] == {"n": 1, "hits": 1, "hit_rate": 1.0, "status": "ok"}
    text = render_reliability(reliability)
    assert "| target | metric | market_stage | track |" in text
    assert "| final | direction | 震荡 | pre_market | 1 | 1 | 100.0% |" in text
    assert "| final | direction | 震荡 | closing | 1 | 0 | 0.0% |" in text


def test_missing_day_calendar_starts_at_m4_validation_start(tmp_path):
    root = tmp_path / "records"
    db_path = tmp_path / "calendar.db"
    report_day = "2026-11-04"
    _calendar(db_path, [
        "2026-10-29",
        "2026-10-30",
        "2026-11-02",
        "2026-11-03",
        "2026-11-04",
    ])
    _save(root, _record("valid-post-launch", day="2026-11-02"))
    _save(root, _record("error-post-launch", day="2026-11-03", status="error"))

    reliability = collect_reliability(report_day, root=root, db_path=db_path)
    for window in reliability["windows"].values():
        assert window["start"] < "2026-11-02"
        assert window["expected_days"] == ["2026-11-02", "2026-11-03", "2026-11-04"]
        assert window["missing_days"] == ["2026-11-03", "2026-11-04"]
        assert window["consecutive_missing"] == [["2026-11-03", "2026-11-04"]]
        assert all(
            day >= "2026-11-02"
            for group in window["consecutive_missing"]
            for day in group
        )
    alerts = render_reliability(reliability).split("## 窗口统计")[0]
    assert "2026-11-03~2026-11-04" in alerts
    assert "2026-10-29" not in alerts and "2026-10-30" not in alerts

    historical = collect_reliability("2026-10-31", root=root, db_path=db_path)
    for window in historical["windows"].values():
        assert window["calendar"] == "ok"
        assert window["expected_days"] == []
        assert window["missing_days"] == []
        assert window["consecutive_missing"] == []


def test_reports_redact_freeform_and_unsafe_metadata_without_markdown_injection(tmp_path):
    root = tmp_path / "records"
    db_path = tmp_path / "calendar.db"
    unsafe_id = "unsafe-RAW-SECRET\n## INJECTED"
    record = _record(
        unsafe_id,
        status="scored",
        review={
            "passed": False,
            "notes": [
                "RAW-SECRET\n## INJECTED",
                {"code": "fact_error", "details": "POSITION-SECRET"},
            ],
        },
        fact_errors=[
            {"code": "fact_error", "value": "RAW-SECRET"},
            {"code": "RAW-SECRET", "field": "POSITION-SECRET\n## INJECTED"},
        ],
        school_attribution_errors=[
            {"code": "school_attribution_error", "school": "gator-RAW-SECRET\n| injected"}
        ],
    )
    record["attribution"] = {
        "candidates": [{
            "record_id": unsafe_id,
            "target": "expert",
            "school": "RAW-SECRET\n| injected",
            "target_id": "POSITION-SECRET\n## INJECTED",
            "metric": "direction",
            "status": "reviewed",
            "review_items": [],
        }]
    }
    _save(root, record)
    _calendar(db_path, [DAY])

    daily = collect_daily(DAY, root=root)
    entry = daily["records"][0]
    assert entry["record_id"].startswith("id-")
    assert entry["review_note_count"] == 2
    assert entry["review_codes"] == ["fact_error"]
    assert entry["fact_errors"] == [{"code": "fact_error"}]
    reliability = collect_reliability(
        DAY, root=root, db_path=db_path, validation_start="2026-01-01"
    )
    candidate = reliability["windows"][4]["attribution"]["candidates"][0]
    assert candidate["record_id"] == entry["record_id"]
    assert candidate["target_id"].startswith("id-")
    assert candidate["school"].startswith("school-")
    text = render_daily(daily) + render_reliability(reliability)
    assert "RAW-SECRET" not in text
    assert "POSITION-SECRET" not in text
    assert "## INJECTED" not in text
    assert "| injected" not in text
    assert "note_count=2" in text


@pytest.mark.parametrize(
    "cached_days",
    [
        ["2026-11-02", "2026-11-04"],
        ["2026-11-02", "2026-11-03"],
    ],
    ids=["sparse-interior", "missing-endpoint"],
)
def test_calendar_coverage_is_partial_for_sparse_weekday_cache(tmp_path, cached_days):
    root = tmp_path / "records"
    db_path = tmp_path / "calendar.db"
    _calendar(db_path, cached_days)
    for index, day in enumerate(cached_days):
        _save(root, _record(f"valid-{index}", day=day))

    reliability = collect_reliability("2026-11-04", root=root, db_path=db_path)
    window = reliability["windows"][4]
    assert window["calendar"] == "partial"
    assert window["expected_days"] == cached_days
    assert window["missing_days"] == []
    assert window["missing_days_status"] == "non_exhaustive"
    text = render_reliability(reliability)
    assert "calendar=partial" in text
    assert "缺报=unknown（非完整）" in text
    assert "缺报=0" not in text
    assert "非完整" in text
    assert "缺报日期: 无" not in text
    alerts = text.split("## 窗口统计")[0]
    assert "连续缺报未知" in alerts
    assert "\n- 无\n" not in alerts


def test_daily_surfaces_bad_files_unknown_track_and_empty_judgment(tmp_path):
    root = tmp_path / "records"
    pre_market = root / DAY / "pre_market"
    pre_market.mkdir(parents=True)
    (pre_market / "bad.json").write_text("{not json", encoding="utf-8")
    (pre_market / "nonobject.json").write_text("[]", encoding="utf-8")
    _save(root, _record("unknown-track", track="after_hours", status="scored"))
    _save(root, _record("empty-judgment", final_judgment={}))

    daily = collect_daily(DAY, root=root)
    entries = {entry["record_id"]: entry for entry in daily["records"]}
    assert daily["status_counts"] == {"pending": 1, "scored": 0, "error": 0, "missing": 0}
    assert [entry["record_id"] for entry in daily["tracks"]["invalid"]] == [_id("unknown-track")]
    assert "final_judgment" in entries[_id("empty-judgment")]["missing_fields"]
    assert {issue["code"] for issue in daily["integrity_issues"]} >= {
        "invalid_json",
        "nonobject_record",
        "unknown_track",
    }
    unknown_track_issue = next(
        issue for issue in daily["integrity_issues"] if issue["code"] == "unknown_track"
    )
    assert unknown_track_issue["track"] == "unknown"
    text = render_daily(daily)
    assert "invalid_json" in text
    assert "nonobject_record" in text
    assert "unknown_track" in text


def test_malformed_items_are_counted_and_unknown_tracks_do_not_enter_metrics(tmp_path):
    root = tmp_path / "records"
    db_path = tmp_path / "calendar.db"
    _calendar(db_path, [DAY])
    record = _record(
        "malformed-items",
        status="scored",
        stage_hit=True,
        expert_views=[{"school": ["RAW-SECRET"]}, "bad", {"school": "gator"}],
    )
    items = [
        _item("bad-target", target=["final"]),
        _item("bad-metric", metric={"bad": "metric"}),
        _item("bad-status", status=[]),
        "not-an-item",
        _item("valid-item", hit=True),
    ]
    _save(root, _with_items(record, items))
    unknown = _record("unknown-track", track="after_hours", status="scored", stage_hit=True)
    _save(root, _with_items(unknown, [_item("unknown-track", hit=True)]))

    daily = collect_daily(DAY, root=root)
    entry = next(item for item in daily["records"] if item["record_id"] == _id("malformed-items"))
    assert entry["schools"] == ["gator"]
    reliability = collect_reliability(
        DAY, root=root, db_path=db_path, validation_start="2026-01-01"
    )
    window = reliability["windows"][4]
    assert window["record_ids"] == [_id("malformed-items")]
    assert window["integrity_issue_counts"]["malformed_settlement_item"] == 4
    assert window["integrity_issue_counts"]["unknown_track"] == 1
    assert window["item_status_counts"]["scored"] == 1
    assert window["stage"] == {"n": 1, "hits": 1, "hit_rate": 1.0, "status": "ok"}
    assert "RAW-SECRET" not in render_daily(daily)


def test_supersession_branch_is_excluded_and_surfaced(tmp_path):
    root = tmp_path / "records"
    db_path = tmp_path / "calendar.db"
    _calendar(db_path, [DAY])
    for record_id, supersedes in [("a", None), ("b", "a"), ("c", "a")]:
        record = _record(record_id, status="scored", supersedes_record_id=supersedes)
        _save(root, _with_items(record, [_item(record_id)]))

    daily = collect_daily(DAY, root=root)
    assert daily["status_counts"]["scored"] == 0
    assert {issue["code"] for issue in daily["integrity_issues"]} >= {"supersession_branch"}
    window = collect_reliability(
        DAY, root=root, db_path=db_path, validation_start="2026-01-01"
    )["windows"][4]
    assert window["record_ids"] == []
    assert window["item_status_counts"]["scored"] == 0
    assert window["integrity_issue_counts"]["supersession_branch"] >= 1


def test_supersession_cycle_is_excluded_and_surfaced(tmp_path):
    root = tmp_path / "records"
    db_path = tmp_path / "calendar.db"
    _calendar(db_path, [DAY])
    for record_id, supersedes in [("a", "b"), ("b", "a")]:
        record = _record(record_id, status="scored", supersedes_record_id=supersedes)
        _save(root, _with_items(record, [_item(record_id)]))

    daily = collect_daily(DAY, root=root)
    assert daily["status_counts"]["scored"] == 0
    assert {issue["code"] for issue in daily["integrity_issues"]} >= {"supersession_cycle"}
    window = collect_reliability(
        DAY, root=root, db_path=db_path, validation_start="2026-01-01"
    )["windows"][4]
    assert window["record_ids"] == []
    assert window["item_status_counts"]["scored"] == 0
    assert window["integrity_issue_counts"]["supersession_cycle"] >= 1


def test_collect_apis_reject_noncanonical_dates(tmp_path):
    root = tmp_path / "records"
    with pytest.raises(ValueError):
        collect_daily("20261104", root=root)
    with pytest.raises(ValueError):
        collect_reliability("20261104", root=root, db_path=tmp_path / "calendar.db")


def test_write_reports_rejects_noncanonical_date_before_creating_output(tmp_path):
    root = tmp_path / "records"
    out_dir = tmp_path / "reports"
    _save(root, _record("readonly"))

    with pytest.raises(ValueError):
        write_reports(
            "20261104",
            root=root,
            db_path=tmp_path / "calendar.db",
            out_dir=out_dir,
            validation_start="2026-01-01",
        )

    assert not out_dir.exists()


def test_strict_projection_blocks_safe_looking_secrets_and_keeps_authoritative_ids(tmp_path):
    root = tmp_path / "records"
    db_path = tmp_path / "calendar.db"
    secret = _record(
        "RAW-SECRET",
        status="scored",
        final_judgment={"market_stage": "RAW-SECRET", "direction": "up"},
        expert_views=[{"school": "POSITION-SECRET"}],
    )
    secret["attribution"] = {
        "candidates": [{
            "record_id": "RAW-SECRET",
            "target": "expert",
            "school": "POSITION-SECRET",
            "target_id": "POSITION-SECRET",
            "metric": "direction",
            "status": "reviewed",
            "review_items": [],
        }]
    }
    _save(root, _with_items(secret, [_item("RAW-SECRET", target_id="POSITION-SECRET")]))
    (root / DAY / "pre_market" / "POSITION-SECRET.json").write_text("{bad", encoding="utf-8")

    stages = ["主升", "震荡", "调整", "恐慌"]
    schools = ["qing", "gator", "watchlist", "gator"]
    uuids = []
    for index, (stage, school) in enumerate(zip(stages, schools), start=1):
        record_id = f"{index:032x}"
        uuids.append(record_id)
        _save(root, _record(
            record_id,
            final_judgment={"market_stage": stage, "direction": "up"},
            expert_views=[{"school": school}],
        ))
    custom_status_id = "00000000000000000000000000000005"
    _save(root, _record(custom_status_id, status="in_progress"))
    _calendar(db_path, [DAY])

    daily = collect_daily(DAY, root=root)
    secret_entry = next(entry for entry in daily["records"] if entry["market_stage"].startswith("stage-"))
    assert secret_entry["record_id"].startswith("id-")
    assert secret_entry["schools"][0].startswith("school-")
    for record_id, stage, school in zip(uuids, stages, schools):
        entry = next(item for item in daily["records"] if item["record_id"] == record_id)
        assert entry["market_stage"] == stage
        assert entry["schools"] == [school]
    custom_status = next(entry for entry in daily["records"] if entry["record_id"] == custom_status_id)
    assert custom_status["status"] == "unknown"
    integrity_id = next(
        issue["record_id"] for issue in daily["integrity_issues"] if issue["code"] == "invalid_json"
    )
    assert integrity_id.startswith("id-")

    reliability = collect_reliability(
        DAY, root=root, db_path=db_path, validation_start="2026-01-01"
    )
    window = reliability["windows"][4]
    candidate = window["attribution"]["candidates"][0]
    assert candidate["record_id"] == secret_entry["record_id"]
    assert candidate["school"].startswith("school-")
    assert candidate["target_id"].startswith("id-")
    assert set(uuids) <= set(window["record_ids"])
    text = render_daily(daily) + render_reliability(reliability)
    assert "RAW-SECRET" not in text
    assert "POSITION-SECRET" not in text
    assert all(stage in text for stage in stages)
    assert all(school in text for school in ("qing", "gator", "watchlist"))
    assert all(record_id in text for record_id in uuids)
