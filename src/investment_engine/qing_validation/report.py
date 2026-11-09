from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

from investment_engine.backtest.history import list_trading_days
from investment_engine.qing_validation.records import normalize_day
from investment_engine.qing_validation.settle import load_active_records


TRACKS = ("pre_market", "intraday", "closing")
ITEM_STATUSES = ("scored", "pending_maturity", "insufficient_data", "not_applicable")
REVIEWED_ATTRIBUTION_STATUSES = frozenset({
    "accepted", "confirmed", "dismissed", "rejected", "resolved", "reviewed",
})
SAFE_CODES = frozenset({
    "citation_error",
    "concept_misuse",
    "data_gap",
    "fact_error",
    "factual_error",
    "information_gap",
    "invalid_field",
    "invalid_timestamp",
    "missing_step",
    "school_attribution_error",
})
_REQUIRED_FIELDS = (
    "generated_at",
    "data_as_of",
    "final_judgment",
    "raw_output",
    "expert_views",
    "data_version",
    "rules_version",
    "prompt_version",
)
_RECORD_UUID_PATTERN = re.compile(r"[0-9a-f]{32}\Z")
_KNOWN_SCHOOLS = frozenset({"qing", "gator", "watchlist"})
_KNOWN_STAGES = frozenset({"主升", "震荡", "调整", "恐慌"})
_PROJECTED_STATUS_VALUES = frozenset({
    "accepted", "confirmed", "dismissed", "rejected", "resolved", "reviewed",
    "pending_review", "in_progress", "unknown", "pending", "pending_maturity",
    "scored", "error", "missing", "pre_market", "intraday", "closing", "invalid",
    "invalid_json", "nonobject_record", "unreadable_record", "unknown_track",
    "supersession_branch", "supersession_cycle", "supersession_ambiguous",
    "malformed_settlement_item", "malformed_record_status",
})


def _is_present(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def _stable_hash(value) -> str:
    try:
        serialized = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
        )
    except (TypeError, ValueError):
        serialized = str(value)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:12]


def _safe_identity(value, *, prefix: str = "id") -> str:
    if value is None or value == "":
        return "-"
    return f"{prefix}-{_stable_hash(value)}"


def _safe_record_id(value) -> str:
    if isinstance(value, str) and _RECORD_UUID_PATTERN.fullmatch(value):
        return value
    return _safe_identity(value)


def _safe_school(value) -> str:
    if value is None or value == "":
        return "-"
    if isinstance(value, str) and value in _KNOWN_SCHOOLS:
        return value
    if isinstance(value, str):
        return _safe_identity(value, prefix="school")
    return "unknown"


def _safe_stage(value) -> str:
    if value is None or value == "":
        return "unknown"
    if isinstance(value, str) and value in _KNOWN_STAGES:
        return value
    if isinstance(value, str):
        return _safe_identity(value, prefix="stage")
    return "unknown"


def _safe_date(value) -> str:
    try:
        return normalize_day(value)
    except (TypeError, ValueError):
        return "unknown"


def _safe_status(value) -> str:
    if isinstance(value, str) and value in _PROJECTED_STATUS_VALUES:
        return value
    return "unknown"


def _safe_record_status(value) -> str:
    allowed = {"pending_maturity", "pending", "scored", "error", "missing"}
    return value if isinstance(value, str) and value in allowed else "unknown"


def _safe_track(value) -> str:
    allowed = {*TRACKS, "invalid", "unknown"}
    return value if isinstance(value, str) and value in allowed else "unknown"


def _safe_code(value) -> str | None:
    return value if isinstance(value, str) and value in SAFE_CODES else None


def _review_summary(review: dict) -> tuple[int, list[str]]:
    notes = review.get("notes")
    if notes is None:
        notes = []
    elif not isinstance(notes, list):
        notes = [notes]
    codes = []
    for note in notes:
        value = note.get("code") if isinstance(note, dict) else note
        code = _safe_code(value)
        if code is not None and code not in codes:
            codes.append(code)
    return len(notes), codes


def _structured_errors(record: dict, kind: str) -> list[dict]:
    names = {
        "fact": ("fact_errors", "factual_errors"),
        "school": ("school_attribution_errors", "attribution_errors"),
    }[kind]
    values = []
    review = record.get("review")
    containers = [record, review] if isinstance(review, dict) else [record]
    for container in containers:
        for name in names:
            entries = container.get(name)
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if isinstance(entry, dict):
                    code = _safe_code(entry.get("code"))
                    if code is None:
                        code = _safe_code(entry.get("category"))
                else:
                    code = _safe_code(entry)
                if code is None:
                    continue
                value = {"code": code}
                if kind == "school" and isinstance(entry, dict) and "school" in entry:
                    value["school"] = _safe_school(entry.get("school"))
                values.append(value)
    return values


def _valid_timestamp(value) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _prediction_missing_fields(record: dict) -> list[str]:
    final = record.get("final_judgment")
    final = final if isinstance(final, dict) else {}
    predictive = record.get("track") != "closing"
    if record.get("track") == "closing":
        predictive = final.get("score_eligible") is True or final.get("horizon") == "T+5"
    if not predictive:
        return []
    missing = []
    if final.get("horizon") != "T+5":
        missing.append("final_judgment.horizon")
    if not any(_is_present(final.get(field)) for field in (
        "trigger", "trigger_condition", "trigger_conditions"
    )):
        missing.append("final_judgment.trigger_conditions")
    if not any(_is_present(final.get(field)) for field in (
        "invalidation", "invalidation_condition", "invalidation_conditions"
    )):
        missing.append("final_judgment.invalidation_conditions")
    return missing


def _daily_entry(record: dict) -> dict:
    missing = []
    invalid = []
    for field in _REQUIRED_FIELDS:
        value = record.get(field)
        if field in {"generated_at", "data_as_of"}:
            if not _is_present(value):
                missing.append(field)
            elif not _valid_timestamp(value):
                invalid.append(field)
        elif field == "final_judgment" and not isinstance(value, dict):
            missing.append(field)
        elif field == "expert_views":
            if not isinstance(value, list):
                missing.append(field)
        elif not _is_present(value):
            missing.append(field)
    final = record.get("final_judgment")
    final = final if isinstance(final, dict) else {}
    experts = record.get("expert_views")
    experts = experts if isinstance(experts, list) else []
    schools = sorted({
        _safe_school(view.get("school"))
        for view in experts
        if isinstance(view, dict) and isinstance(view.get("school"), str) and view["school"]
    })
    review = record.get("review")
    review = review if isinstance(review, dict) else {}
    note_count, review_codes = _review_summary(review)
    track = record.get("track")
    return {
        "record_id": _safe_record_id(record.get("record_id")),
        "date": _safe_date(record.get("date")),
        "track": _safe_track(track),
        "status": _safe_record_status(record.get("status")),
        "market_stage": _safe_stage(final.get("market_stage")),
        "schools": schools,
        "missing_fields": missing,
        "invalid_fields": invalid,
        "prediction_missing_fields": _prediction_missing_fields(record),
        "review_passed": review.get("passed") if isinstance(review.get("passed"), bool) else None,
        "review_note_count": note_count,
        "review_codes": review_codes,
        "fact_errors": _structured_errors(record, "fact"),
        "school_attribution_errors": _structured_errors(record, "school"),
    }


def _record_sort_key(record: dict) -> tuple:
    return (
        str(record.get("date") or ""),
        str(record.get("track") or ""),
        str(record.get("record_id") or ""),
    )


def _safe_integrity_issue(issue: dict) -> dict:
    return {
        "code": _safe_status(issue.get("code")),
        "record_id": _safe_record_id(issue.get("record_id")),
        "date": _safe_date(issue.get("date")),
        "track": _safe_track(issue.get("track")),
    }


def collect_daily(day: str, *, root) -> dict:
    report_day = normalize_day(day)
    entries, loader_issues = load_active_records(Path(root), include_issues=True)
    records = [record for _path, record in entries if record.get("date") == report_day]
    integrity_issues = [issue for issue in loader_issues if issue.get("date") == report_day]
    tracks = {track: [] for track in (*TRACKS, "invalid")}
    status_counts = Counter()
    for record in sorted(records, key=_record_sort_key):
        entry = _daily_entry(record)
        track = record.get("track")
        if not isinstance(track, str) or track not in TRACKS:
            entry["track"] = "invalid"
            tracks["invalid"].append(entry)
            integrity_issues.append({
                "code": "unknown_track",
                "record_id": record.get("record_id"),
                "date": report_day,
                "track": track,
            })
            continue
        tracks[track].append(entry)
        status = record.get("status")
        if status == "pending_maturity":
            status = "pending"
        if status in {"pending", "scored", "error", "missing"}:
            status_counts[status] += 1
    return {
        "date": report_day,
        "tracks": tracks,
        "records": [entry for track in (*TRACKS, "invalid") for entry in tracks[track]],
        "missing_tracks": [track for track in TRACKS if not tracks[track]],
        "status_counts": {
            status: status_counts[status]
            for status in ("pending", "scored", "error", "missing")
        },
        "integrity_issues": [
            _safe_integrity_issue(issue) for issue in integrity_issues
        ],
    }


def _window_start(report_day: date, weeks: int) -> date:
    monday = report_day - timedelta(days=report_day.weekday())
    return monday - timedelta(weeks=weeks - 1)


def _consecutive_missing(expected_days: list[str], missing_days: list[str]) -> list[list[str]]:
    missing = set(missing_days)
    groups = []
    current = []
    for day in expected_days:
        if day in missing:
            current.append(day)
        else:
            if len(current) >= 2:
                groups.append(current)
            current = []
    if len(current) >= 2:
        groups.append(current)
    return groups


def _weekdays(start: date, end: date) -> list[str]:
    days = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            days.append(current.isoformat())
        current += timedelta(days=1)
    return days


def _calendar(start: date, end: date, db_path) -> tuple[str, list[str]]:
    try:
        days = list_trading_days(start.isoformat(), end.isoformat(), db_path=db_path)
    except (OSError, sqlite3.Error):
        return "insufficient_data", []
    weekdays = _weekdays(start, end)
    if not weekdays:
        return "ok", days
    cached = set(days)
    if not cached.intersection(weekdays):
        return "insufficient_data", days
    if any(day not in cached for day in weekdays):
        return "partial", days
    return "ok", days


def _new_row(track: str, target: str, metric: str, stage: str) -> dict:
    return {
        "track": track,
        "target": target,
        "metric": metric,
        "market_stage": stage,
        "n": 0,
        "hits": 0,
        "hit_rate": None,
        "status": "insufficient_data",
        "pending_maturity": 0,
        "insufficient_data": 0,
        "not_applicable": 0,
        "invalid_scored": 0,
    }


def _candidate_metadata(candidate: dict, record: dict) -> dict:
    target = candidate.get("target")
    metric = candidate.get("metric")
    return {
        "record_id": _safe_record_id(candidate.get("record_id", record.get("record_id"))),
        "target": target if isinstance(target, str) and target in {"final", "expert"} else "unknown",
        "school": _safe_school(candidate.get("school")),
        "target_id": _safe_identity(candidate.get("target_id")),
        "metric": metric if isinstance(metric, str) and metric in {"direction", "stock"} else "unknown",
        "status": _safe_status(candidate.get("status")),
    }


def _collect_window(
    records: list[dict], *, start: date, end: date, weeks: int, db_path,
    validation_start: date, integrity_issues=None,
) -> dict:
    start_day = start.isoformat()
    end_day = end.isoformat()
    issue_counts = Counter()
    for issue in integrity_issues or []:
        try:
            issue_day = date.fromisoformat(issue.get("date", ""))
        except (TypeError, ValueError):
            continue
        if start <= issue_day <= end:
            issue_counts[_safe_status(issue.get("code"))] += 1

    selected = []
    for record in records:
        try:
            record_day = date.fromisoformat(record.get("date", ""))
        except (TypeError, ValueError):
            continue
        if start <= record_day <= end:
            track = record.get("track")
            if not isinstance(track, str) or track not in TRACKS:
                issue_counts["unknown_track"] += 1
            else:
                selected.append(record)
    selected.sort(key=_record_sort_key)

    record_counts = Counter()
    valid_days = set()
    for record in selected:
        status = record.get("status")
        normalized = "pending" if status == "pending_maturity" else status
        if isinstance(normalized, str) and normalized in {"pending", "scored", "error", "missing"}:
            record_counts[normalized] += 1
        if status in ("pending_maturity", "scored"):
            valid_days.add(record["date"])

    calendar_start = max(start, validation_start)
    if calendar_start > end:
        calendar, expected_days = "ok", []
    else:
        calendar, expected_days = _calendar(calendar_start, end, db_path)
    if calendar == "insufficient_data":
        missing_days = None
        missing_days_status = "unknown"
    else:
        missing_days = [day for day in expected_days if day not in valid_days]
        missing_days_status = "complete" if calendar == "ok" else "non_exhaustive"
    consecutive_missing = _consecutive_missing(expected_days, missing_days or [])
    groups = {}
    item_status_counts = Counter()
    stage_n = stage_hits = 0
    attribution_statuses = Counter()
    attribution_schools = Counter()
    candidates = []

    for record in selected:
        final = record.get("final_judgment")
        final = final if isinstance(final, dict) else {}
        track = record["track"]
        stage = _safe_stage(final.get("market_stage"))
        stage_hit = record.get("stage_hit")
        if track in {"pre_market", "intraday"} and type(stage_hit) is bool:
            stage_n += 1
            stage_hits += int(stage_hit)
        if record.get("status") not in ("error", "missing"):
            settlement = record.get("settlement")
            settlement = settlement if isinstance(settlement, dict) else {}
            items = settlement.get("items")
            if not isinstance(items, list):
                if items is not None:
                    issue_counts["malformed_settlement_item"] += 1
                items = []
            for item in items:
                if not isinstance(item, dict):
                    issue_counts["malformed_settlement_item"] += 1
                    continue
                target = item.get("target")
                metric = item.get("metric")
                status = item.get("status")
                if not all(isinstance(value, str) for value in (target, metric, status)):
                    issue_counts["malformed_settlement_item"] += 1
                    continue
                if (
                    target not in {"final", "expert"}
                    or metric not in {"direction", "stock"}
                    or status not in ITEM_STATUSES
                ):
                    issue_counts["malformed_settlement_item"] += 1
                    continue
                item_status_counts[status] += 1
                key = (track, target, metric, stage)
                row = groups.setdefault(key, _new_row(track, target, metric, stage))
                if status == "scored":
                    hit = item.get("hit")
                    if type(hit) is bool:
                        row["n"] += 1
                        row["hits"] += int(hit)
                    else:
                        row["invalid_scored"] += 1
                else:
                    row[status] += 1

            attribution = record.get("attribution")
            attribution = attribution if isinstance(attribution, dict) else {}
            entries = attribution.get("candidates")
            for candidate in entries if isinstance(entries, list) else []:
                if not isinstance(candidate, dict):
                    continue
                metadata = _candidate_metadata(candidate, record)
                candidates.append(metadata)
                status = metadata["status"]
                school = metadata["school"] or "unknown"
                attribution_statuses[status] += 1
                attribution_schools[(school, status)] += 1

    for target in ("final", "expert"):
        for metric in ("direction", "stock"):
            if not any(key[1:3] == (target, metric) for key in groups):
                key = ("unknown", target, metric, "unknown")
                groups[key] = _new_row("unknown", target, metric, "unknown")
    rows = []
    for row in groups.values():
        if row["n"]:
            row["hit_rate"] = row["hits"] / row["n"]
            row["status"] = "ok"
        rows.append(row)
    target_order = {"final": 0, "expert": 1}
    metric_order = {"direction": 0, "stock": 1}
    track_order = {track: index for index, track in enumerate((*TRACKS, "unknown"))}
    rows.sort(key=lambda row: (
        target_order[row["target"]], metric_order[row["metric"]], row["market_stage"],
        track_order[row["track"]],
    ))
    candidates.sort(key=lambda item: (
        item["record_id"], item["target"], item["school"],
        item["target_id"], item["metric"], item["status"],
    ))
    other_statuses = {
        status: count for status, count in attribution_statuses.items()
        if status != "pending_review" and status not in REVIEWED_ATTRIBUTION_STATUSES
    }
    return {
        "weeks": weeks,
        "start": start_day,
        "end": end_day,
        "calendar_start": calendar_start.isoformat(),
        "calendar": calendar,
        "expected_days": expected_days,
        "missing_days": missing_days,
        "missing_days_status": missing_days_status,
        "consecutive_missing": consecutive_missing,
        "record_ids": [_safe_record_id(record.get("record_id")) for record in selected],
        "record_counts": {
            status: record_counts[status]
            for status in ("pending", "scored", "error", "missing")
        },
        "item_status_counts": {status: item_status_counts[status] for status in ITEM_STATUSES},
        "integrity_issue_counts": dict(sorted(issue_counts.items())),
        "rows": rows,
        "stage": {
            "n": stage_n,
            "hits": stage_hits,
            "hit_rate": stage_hits / stage_n if stage_n else None,
            "status": "ok" if stage_n else "insufficient_data",
        },
        "attribution": {
            "pending_review": attribution_statuses["pending_review"],
            "human_reviewed": sum(
                attribution_statuses[status] for status in REVIEWED_ATTRIBUTION_STATUSES
            ),
            "other_status_counts": dict(sorted(other_statuses.items())),
            "status_counts": dict(sorted(attribution_statuses.items())),
            "by_school": [
                {"school": school, "status": status, "count": count}
                for (school, status), count in sorted(attribution_schools.items())
            ],
            "candidates": candidates,
        },
    }


def collect_reliability(
    day: str, *, root, db_path=None, validation_start: str | date = "2026-11-02"
) -> dict:
    report_day = date.fromisoformat(normalize_day(day))
    validation_day = (
        date.fromisoformat(normalize_day(validation_start))
        if isinstance(validation_start, str)
        else validation_start
    )
    entries, integrity_issues = load_active_records(Path(root), include_issues=True)
    records = [record for _path, record in entries]
    windows = {}
    for weeks in (4, 8):
        windows[weeks] = _collect_window(
            records,
            start=_window_start(report_day, weeks),
            end=report_day,
            weeks=weeks,
            db_path=db_path,
            validation_start=validation_day,
            integrity_issues=integrity_issues,
        )
    return {"date": report_day.isoformat(), "windows": windows}


def render_daily(daily: dict) -> str:
    counts = daily["status_counts"]
    lines = [
        f"# Qing-Agent 每日完整性报告（{daily['date']}）",
        "",
        "- 状态统计: " + "；".join(f"{key}={value}" for key, value in counts.items()),
        "- 缺失轨道: " + (", ".join(daily["missing_tracks"]) or "无"),
        "",
        "## 分轨记录",
    ]
    for track in (*TRACKS, "invalid"):
        lines.extend(["", f"### {track}", ""])
        entries = daily["tracks"][track]
        if not entries:
            lines.append("- 缺失" if track in TRACKS else "- 无")
        for entry in entries:
            lines.append(
                f"- record_id={entry['record_id']} | status={entry['status']} | "
                f"market_stage={entry['market_stage']} | "
                f"school={','.join(entry['schools']) or '-'}"
            )
            for label, field in (
                ("缺失字段", "missing_fields"),
                ("无效字段", "invalid_fields"),
                ("预测字段缺失", "prediction_missing_fields"),
            ):
                if entry[field]:
                    lines.append(f"  - {label}: {', '.join(entry[field])}")
            if entry["review_passed"] is False or entry["review_note_count"] or entry["review_codes"]:
                lines.append(
                    f"  - review.passed={entry['review_passed']} | "
                    f"note_count={entry['review_note_count']} | "
                    f"codes={','.join(entry['review_codes']) or '-'}"
                )
            for label, field in (
                ("结构化事实错误", "fact_errors"),
                ("学派归属错误", "school_attribution_errors"),
            ):
                if entry[field]:
                    metadata = []
                    for item in entry[field]:
                        value = item["code"]
                        if "school" in item:
                            value += f"(school={item['school']})"
                        metadata.append(value)
                    lines.append(f"  - {label}: {', '.join(metadata)}")
    lines.extend(["", "## 完整性问题", ""])
    if not daily["integrity_issues"]:
        lines.append("- 无")
    for issue in daily["integrity_issues"]:
        lines.append(
            f"- code={issue['code']} | record_id={issue['record_id']} | track={issue['track']}"
        )
    return "\n".join(lines) + "\n"


def _format_rate(n: int, rate) -> str:
    return f"{rate:.1%}" if n and rate is not None else "insufficient_data"


def _render_window(lines: list[str], window: dict) -> None:
    counts = window["item_status_counts"]
    missing_days = window["missing_days"]
    if window["calendar"] == "ok":
        missing_count = str(len(missing_days or []))
    elif window["missing_days_status"] == "non_exhaustive":
        missing_count = "unknown（非完整）"
    else:
        missing_count = "unknown"
    if missing_days is None:
        missing_line = "- 缺报日期: unknown"
    elif window["missing_days_status"] == "non_exhaustive":
        missing_line = "- 缺报日期（非完整）: " + (", ".join(missing_days) or "unknown")
    else:
        missing_line = "- 缺报日期: " + (", ".join(missing_days) or "无")
    lines.extend([
        "",
        f"### {window['weeks']}周",
        "",
        f"- 范围: {window['start']}~{window['end']}；calendar_start={window['calendar_start']}",
        f"- calendar={window['calendar']}；预期交易日={len(window['expected_days'])}；"
        f"缺报={missing_count}；未到期={counts['pending_maturity']}；"
        f"数据不足={counts['insufficient_data']}；not_applicable={counts['not_applicable']}",
        missing_line,
        "- 记录状态: " + "；".join(
            f"{key}={value}" for key, value in window["record_counts"].items()
        ),
        "- 完整性问题: " + json.dumps(window["integrity_issue_counts"], sort_keys=True),
        f"- 阶段一致参考（非预测力）: {_format_rate(window['stage']['n'], window['stage']['hit_rate'])}"
        f"（n={window['stage']['n']}）",
    ])
    for target in ("final", "expert"):
        lines.extend([
            "",
            f"#### {target}",
            "",
            "| target | metric | market_stage | track | n | hits | hit_rate | pending_maturity | insufficient_data | not_applicable | invalid_scored |",
            "|---|---|---|---|---:|---:|---|---:|---:|---:|---:|",
        ])
        for row in window["rows"]:
            if row["target"] != target:
                continue
            lines.append(
                f"| {target} | {row['metric']} | {row['market_stage']} | {row['track']} | {row['n']} | "
                f"{row['hits']} | {_format_rate(row['n'], row['hit_rate'])} | "
                f"{row['pending_maturity']} | {row['insufficient_data']} | "
                f"{row['not_applicable']} | {row['invalid_scored']} |"
            )
    attribution = window["attribution"]
    lines.extend([
        "",
        "#### 候选归因",
        "",
        f"- pending_review={attribution['pending_review']}；已完成人审={attribution['human_reviewed']}",
        "- 状态计数: " + json.dumps(attribution["status_counts"], sort_keys=True),
        "- 其他状态: " + json.dumps(attribution["other_status_counts"], sort_keys=True),
        "",
        "| record_id | target | school | target_id | metric | status |",
        "|---|---|---|---|---|---|",
    ])
    for candidate in attribution["candidates"]:
        lines.append(
            f"| {candidate['record_id']} | {candidate['target']} | {candidate['school']} | "
            f"{candidate['target_id']} | {candidate['metric']} | {candidate['status']} |"
        )


def render_reliability(reliability: dict) -> str:
    lines = [f"# Qing-Agent 滚动可靠性报告（{reliability['date']}）", "", "## 连续缺报告警", ""]
    alerts = []
    for weeks, window in reliability["windows"].items():
        status = window["missing_days_status"]
        suffix = "" if status == "complete" else "；非完整"
        for group in window["consecutive_missing"]:
            alerts.append(
                f"- {weeks}周: {group[0]}~{group[-1]}"
                f"（{len(group)} 个连续预期交易日{suffix}）"
            )
        if status != "complete" and not window["consecutive_missing"]:
            alerts.append(f"- {weeks}周: calendar={window['calendar']}；连续缺报未知（非完整）")
    lines.extend(alerts or ["- 无"])
    lines.extend(["", "## 窗口统计"])
    for weeks in (4, 8):
        _render_window(lines, reliability["windows"][weeks])
    return "\n".join(lines) + "\n"


def write_reports(
    day: str, *, root, db_path=None, out_dir="logs", validation_start: str | date = "2026-11-02"
) -> dict[str, Path]:
    day = normalize_day(day)
    if isinstance(validation_start, str):
        validation_start = normalize_day(validation_start)
    output = Path(out_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths = {
        "daily": output / f"qing-agent-daily-{day}.md",
        "reliability": output / f"qing-agent-reliability-{day}.md",
    }
    daily = collect_daily(day, root=root)
    reliability = collect_reliability(
        day, root=root, db_path=db_path, validation_start=validation_start
    )
    paths["daily"].write_text(render_daily(daily), encoding="utf-8")
    paths["reliability"].write_text(render_reliability(reliability), encoding="utf-8")
    return paths
