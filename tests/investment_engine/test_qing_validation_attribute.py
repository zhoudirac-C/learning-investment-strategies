import copy

import pytest

from investment_engine.qing_validation.attribute import attribute_record


CATEGORIES = {
    "data_gap",
    "missing_step",
    "concept_misuse",
    "information_gap",
    "school_attribution_error",
}


def _item(**overrides):
    item = {
        "record_id": "record-1",
        "target": "expert",
        "school": "qing",
        "target_id": "direction-1",
        "metric": "direction",
        "status": "scored",
        "hit": False,
    }
    item.update(overrides)
    return item


def _record(items, *, record_id="record-1"):
    return {
        "record_id": record_id,
        "date": "2026-06-01",
        "settlement": {"items": items},
        "attribution": None,
        "standing": {"qing": "unchanged"},
        "rules_version": "rules-v1",
        "proposal": {"status": "unchanged"},
        "input_availability": {"missing": ["expert_daily"]},
    }


def test_market_miss_creates_review_candidate_without_automatic_cause():
    record = _record([_item()])
    before = copy.deepcopy(record)

    attributed = attribute_record(record)

    assert record == before
    candidates = attributed["attribution"]["candidates"]
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["status"] == "pending_review"
    assert {
        key: candidate[key]
        for key in ("record_id", "target", "target_id", "metric")
    } == {
        "record_id": "record-1",
        "target": "expert",
        "target_id": "direction-1",
        "metric": "direction",
    }
    assert candidate["school"] == "qing"
    assert {item["category"] for item in candidate["review_items"]} == CATEGORIES
    assert all(item["evidence"] == [] for item in candidate["review_items"])
    assert all(item["conclusion"] is None for item in candidate["review_items"])
    assert "cause" not in candidate and "category" not in candidate
    for field in ("standing", "rules_version", "proposal", "input_availability"):
        assert attributed[field] == before[field]


def test_final_and_expert_with_same_target_id_do_not_share_candidate():
    record = _record(
        [
            _item(target="final", school=None),
            _item(target="expert", school="gator"),
        ]
    )

    candidates = attribute_record(record)["attribution"]["candidates"]

    assert len(candidates) == 2
    assert {(c["target"], c["school"]) for c in candidates} == {
        ("final", None),
        ("expert", "gator"),
    }
    assert all(
        c["target_id"] == "direction-1" and c["metric"] == "direction"
        for c in candidates
    )


def test_same_date_different_experts_remain_record_scoped():
    qing = attribute_record(
        _record([_item(record_id="qing-record")], record_id="qing-record")
    )
    gator = attribute_record(
        _record(
            [_item(record_id="gator-record", school="gator")],
            record_id="gator-record",
        )
    )

    first = qing["attribution"]["candidates"][0]
    second = gator["attribution"]["candidates"][0]
    assert first["record_id"] == "qing-record" and first["school"] == "qing"
    assert second["record_id"] == "gator-record" and second["school"] == "gator"


@pytest.mark.parametrize(
    "item",
    [
        _item(hit=True),
        _item(status="pending_maturity", hit=None),
        _item(status="insufficient_data", hit=None),
        _item(status="not_applicable", hit=None),
        _item(status="insufficient_data", hit=False),
        _item(status="scored", hit=None),
    ],
)
def test_hit_pending_nonlong_and_insufficient_do_not_create_candidates(item):
    attributed = attribute_record(_record([item]))

    assert attributed["attribution"]["candidates"] == []


def test_stage_reference_miss_alone_does_not_create_market_attribution():
    record = _record([])
    record["stage_hit"] = False

    assert attribute_record(record)["attribution"]["candidates"] == []


def test_repeated_attribution_is_idempotent():
    first = attribute_record(_record([_item()]))

    second = attribute_record(first)

    assert second == first
    assert len(second["attribution"]["candidates"]) == 1


def test_reviewed_candidate_and_history_survive_regeneration_without_duplicates():
    first = attribute_record(_record([_item()]))
    candidate = first["attribution"]["candidates"][0]
    candidate["status"] = "reviewed"
    candidate["reviewer"] = "human"
    candidate["review_items"][0]["evidence"] = [{"note": "人工核对完成"}]
    candidate["review_items"][0]["conclusion"] = "confirmed"
    first["attribution"]["history"] = [{"event": "reviewed", "by": "human"}]
    before = copy.deepcopy(first)

    second = attribute_record(first)

    assert second == before
    assert len(second["attribution"]["candidates"]) == 1


def test_preexisting_reviewed_candidate_is_not_deleted_when_current_item_hits():
    reviewed = attribute_record(_record([_item()]))
    candidate = reviewed["attribution"]["candidates"][0]
    candidate["status"] = "reviewed"
    candidate["review_items"][0]["conclusion"] = "confirmed"
    hit_record = _record([_item(hit=True)])
    hit_record["attribution"] = copy.deepcopy(reviewed["attribution"])

    attributed = attribute_record(hit_record)

    assert attributed == hit_record
    assert len(attributed["attribution"]["candidates"]) == 1


def test_existing_candidate_identity_includes_school():
    first = attribute_record(
        _record([_item(school="qing"), _item(school="gator")])
    )
    for candidate in first["attribution"]["candidates"]:
        candidate["status"] = "reviewed"
        candidate["review_items"][0]["conclusion"] = candidate["school"]

    second = attribute_record(first)

    assert len(second["attribution"]["candidates"]) == 2
    assert {
        candidate["school"]: candidate["review_items"][0]["conclusion"]
        for candidate in second["attribution"]["candidates"]
    } == {"qing": "qing", "gator": "gator"}
