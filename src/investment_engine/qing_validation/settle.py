from __future__ import annotations

import copy
import json
import os
import re
import tempfile
from pathlib import Path

from investment_engine.backtest.history import list_trading_days
from investment_engine.blindtest.score import direction_scores, stock_scores
from investment_engine.blindtest.truth import load_truth
from investment_engine.qing_validation.attribute import attribute_record
from investment_engine.qing_validation.records import normalize_day, record_directory_lock


_HORIZON = 5
_ITEM_STATUSES = (
    "scored",
    "pending_maturity",
    "insufficient_data",
    "not_applicable",
)


def _integrity_issue(path: Path, code: str) -> dict:
    return {
        "code": code,
        "record_id": path.stem,
        "date": path.parent.parent.name,
        "track": path.parent.name,
    }


def _ambiguous_lineages(entries: list[tuple[Path, dict]]) -> tuple[set[Path], list[dict]]:
    paths = {path for path, _record in entries}
    supersedes = {}
    adjacency = {path: set() for path in paths}
    target_sources = {}
    for path, record in entries:
        target_id = record.get("supersedes_record_id")
        if not isinstance(target_id, str) or not target_id or Path(target_id).name != target_id:
            continue
        target = path.parent / f"{target_id}.json"
        if target not in paths:
            continue
        supersedes[path] = target
        adjacency[path].add(target)
        adjacency[target].add(path)
        target_sources.setdefault(target, set()).add(path)

    branch_seeds = set()
    for target, sources in target_sources.items():
        if len(sources) > 1:
            branch_seeds.add(target)
            branch_seeds.update(sources)
    cycle_seeds = set()
    visited = set()
    for start in supersedes:
        if start in visited:
            continue
        chain = []
        positions = {}
        current = start
        while current in supersedes and current not in positions and current not in visited:
            positions[current] = len(chain)
            chain.append(current)
            current = supersedes[current]
        if current in positions:
            cycle_seeds.update(chain[positions[current]:])
        visited.update(chain)

    ambiguous = set()
    issues = []
    seeds = branch_seeds | cycle_seeds
    for seed in sorted(seeds, key=str):
        if seed in ambiguous:
            continue
        component = set()
        pending = [seed]
        while pending:
            current = pending.pop()
            if current in component:
                continue
            component.add(current)
            pending.extend(adjacency[current] - component)
        if component & branch_seeds and component & cycle_seeds:
            code = "supersession_ambiguous"
        elif component & branch_seeds:
            code = "supersession_branch"
        else:
            code = "supersession_cycle"
        for path in component:
            issues.append(_integrity_issue(path, code))
        ambiguous.update(component)
    return ambiguous, issues


def load_active_records(root: Path, *, include_issues: bool = False):
    """Load active records and optionally return per-file integrity issues."""
    entries = []
    issues = []
    if root.exists():
        for path in sorted(root.rglob("*.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                issues.append(_integrity_issue(path, "invalid_json"))
                continue
            except (OSError, UnicodeError):
                issues.append(_integrity_issue(path, "unreadable_record"))
                continue
            if not isinstance(record, dict):
                issues.append(_integrity_issue(path, "nonobject_record"))
                continue
            entries.append((path, record))

    ambiguous, lineage_issues = _ambiguous_lineages(entries)
    issues.extend(lineage_issues)
    superseded = set()
    for path, record in entries:
        record_id = record.get("supersedes_record_id")
        if isinstance(record_id, str) and record_id and Path(record_id).name == record_id:
            superseded.add(path.parent / f"{record_id}.json")
    active = [
        (path, record) for path, record in entries
        if path not in superseded and path not in ambiguous
    ]
    if include_issues:
        return active, sorted(issues, key=lambda issue: (
            issue["date"], issue["track"], issue["record_id"], issue["code"]
        ))
    return active


_load_records = load_active_records


def _is_due(record_day: str, day: str, *, db_path=None) -> bool:
    if record_day >= day:
        return False
    trading_days = list_trading_days(record_day, day, db_path=db_path)
    return sum(trading_day > record_day for trading_day in trading_days) >= _HORIZON


def _score_targets(record: dict):
    final = record.get("final_judgment") or {}
    if final.get("score_eligible") is True:
        for item in record.get("directions") or []:
            if isinstance(item, dict) and item.get("score_eligible") is True:
                yield item, "final", None
    for item in record.get("expert_views") or []:
        if isinstance(item, dict) and item.get("score_eligible") is True:
            yield item, "expert", item.get("school")


def _base_item(record: dict, item: dict, target: str, school, metric: str) -> dict:
    return {
        "record_id": record["record_id"],
        "date": record["date"],
        "target": target,
        "school": school,
        "target_id": item["direction_id"],
        "metric": metric,
    }


def _scored_item(base: dict, score: dict) -> dict:
    if score.get("samples") != 1 or len(score.get("details", [])) != 1:
        return {**base, "status": "insufficient_data"}
    return {**base, **score["details"][0], "status": "scored"}


def _scoring_stock_code(value) -> str:
    matches = re.findall(r"(?<!\d)\d{6}(?!\d)", str(value))
    return matches[0] if len(matches) == 1 else str(value)


def _market_items(
    record: dict,
    item: dict,
    target: str,
    school,
    *,
    day: str,
    config_dir,
    db_path,
) -> list[dict]:
    direction_base = _base_item(record, item, target, school, "direction")
    stock_base = _base_item(record, item, target, school, "stock")
    stock_code = _scoring_stock_code(item["stock_code"])
    results = [
        {
            "date": record["date"],
            "ok": True,
            "result": {
                "directions": [
                    {
                        "direction_id": item["direction_id"],
                        "stocks": [stock_code],
                    }
                ]
            },
        }
    ]
    directions = direction_scores(
        results,
        config_dir=config_dir,
        db_path=db_path,
        horizon=_HORIZON,
        as_of=day,
    )
    stocks = stock_scores(
        results,
        db_path=db_path,
        horizon=_HORIZON,
        as_of=day,
    )
    return [
        _scored_item(direction_base, directions),
        _scored_item(stock_base, stocks),
    ]


def _derive_status(items: list[dict]) -> str:
    statuses = {item["status"] for item in items}
    for status in ("pending_maturity", "scored", "insufficient_data", "not_applicable"):
        if status in statuses:
            return status
    return "not_applicable"


def _update_stage_hit(record: dict, truth: dict[str, str]) -> None:
    if record.get("track") == "closing":
        record["stage_hit"] = "not_applicable"
        return
    stage = (record.get("final_judgment") or {}).get("market_stage")
    actual = truth.get(record.get("date"))
    if stage is not None and actual is not None:
        record["stage_hit"] = stage == actual


class SettlementConcurrencyError(RuntimeError):
    pass


def _read_json_object(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _replace_if_current(path: Path, frozen: dict, updated: dict) -> None:
    with record_directory_lock(path):
        current = _read_json_object(path)
        if current != frozen:
            raise SettlementConcurrencyError(
                "settlement concurrency conflict: record changed during scoring"
            )
        record_id = frozen.get("record_id")
        for candidate_path in path.parent.glob("*.json"):
            if candidate_path == path:
                continue
            candidate = _read_json_object(candidate_path)
            if candidate and candidate.get("supersedes_record_id") == record_id:
                raise SettlementConcurrencyError(
                    "settlement concurrency conflict: record was superseded during scoring"
                )
        _write_atomic(path, updated)


def _write_atomic(path: Path, record: dict) -> None:
    serialized = json.dumps(
        record,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    ) + "\n"
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.stem}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def settle_records(day: str, *, root, config_dir, db_path=None) -> dict:
    """Settle eligible frozen records through day without changing their judgments."""
    day = normalize_day(day)
    entries = [
        (path, record)
        for path, record in _load_records(Path(root))
        if record.get("status") not in {"error", "missing"}
    ]
    truth = load_truth(db_path=db_path) if entries else {}
    stats = {"records": 0, "updated": 0, "items": 0}
    stats.update({status: 0 for status in _ITEM_STATUSES})

    for path, frozen in entries:
        try:
            record_day = frozen["date"]
            due = _is_due(record_day, day, db_path=db_path)
        except (KeyError, TypeError, ValueError):
            continue

        items = []
        for item, target, school in _score_targets(frozen):
            if item.get("horizon") != "T+5" or not item.get("direction_id"):
                continue
            polarity = item.get("polarity")
            if polarity in {"short", "neutral"}:
                for metric in ("direction", "stock"):
                    items.append(
                        {
                            **_base_item(frozen, item, target, school, metric),
                            "status": "not_applicable",
                        }
                    )
                continue
            if polarity != "long":
                continue
            if not due:
                for metric in ("direction", "stock"):
                    items.append(
                        {
                            **_base_item(frozen, item, target, school, metric),
                            "status": "pending_maturity",
                        }
                    )
                continue
            items.extend(
                _market_items(
                    frozen,
                    item,
                    target,
                    school,
                    day=day,
                    config_dir=config_dir,
                    db_path=db_path,
                )
            )

        updated = copy.deepcopy(frozen)
        updated["settlement"] = {
            "day": day,
            "status": _derive_status(items),
            "items": items,
        }
        if any(item["status"] == "scored" for item in items):
            updated["status"] = "scored"
        _update_stage_hit(updated, truth)
        updated = attribute_record(updated)

        stats["records"] += 1
        stats["items"] += len(items)
        for item in items:
            stats[item["status"]] += 1
        if updated != frozen:
            _replace_if_current(path, frozen, updated)
            stats["updated"] += 1
    return stats
