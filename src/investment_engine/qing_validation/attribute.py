from __future__ import annotations

import copy


_REVIEW_CATEGORIES = (
    "data_gap",
    "missing_step",
    "concept_misuse",
    "information_gap",
    "school_attribution_error",
)


_CANDIDATE_KEY_FIELDS = ("record_id", "target", "school", "target_id", "metric")


def _candidate_key(candidate: dict) -> tuple:
    return tuple(candidate.get(field) for field in _CANDIDATE_KEY_FIELDS)


def _new_candidate(item: dict, record: dict) -> dict:
    return {
        "record_id": item.get("record_id", record.get("record_id")),
        "target": item.get("target"),
        "school": item.get("school"),
        "target_id": item.get("target_id"),
        "metric": item.get("metric"),
        "status": "pending_review",
        "review_items": [
            {
                "category": category,
                "evidence": [],
                "conclusion": None,
            }
            for category in _REVIEW_CATEGORIES
        ],
    }


def attribute_record(record: dict) -> dict:
    """Return a copy with review history preserved and new scored misses appended."""
    attributed = copy.deepcopy(record)
    settlement = attributed.get("settlement") or {}
    items = settlement.get("items", []) if isinstance(settlement, dict) else []
    attribution = attributed.get("attribution")
    if not isinstance(attribution, dict):
        attribution = {}
        attributed["attribution"] = attribution
    candidates = attribution.get("candidates")
    if not isinstance(candidates, list):
        candidates = []
        attribution["candidates"] = candidates
    seen = {
        _candidate_key(candidate)
        for candidate in candidates
        if isinstance(candidate, dict)
    }
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("status") != "scored" or item.get("hit") is not False:
            continue
        candidate = _new_candidate(item, attributed)
        key = _candidate_key(candidate)
        if key in seen:
            continue
        candidates.append(candidate)
        seen.add(key)
    return attributed
