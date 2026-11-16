from pathlib import Path

import pytest
import yaml

from scripts import evolve_gator_patterns as evolution


def test_iter_gator_claims_supports_single_claims_and_up_id(tmp_path: Path, monkeypatch):
    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    fixtures = {
        "claim-single-up-id.yaml": {
            "id": "claim-single-up-id",
            "up_id": "gator-ecyu-0001",
        },
        "claim-single-school.yaml": {
            "id": "claim-single-school",
            "school": "gator",
        },
        "claim-list-school.yaml": [
            {"id": "claim-list-school", "school": "gator"}
        ],
        "claim-container-school.yaml": {
            "claims": [{"id": "claim-container-school", "school": "gator"}]
        },
        "claim-single-other.yaml": {
            "id": "claim-single-other",
            "up_id": "other",
        },
        "claim-container-other.yaml": {
            "claims": [{"id": "claim-container-other", "school": "qing"}]
        },
    }
    for filename, data in fixtures.items():
        (claims_dir / filename).write_text(
            yaml.safe_dump(data, allow_unicode=True), encoding="utf-8"
        )
    monkeypatch.setattr(evolution, "CLAIMS_DIR", claims_dir)

    claims = evolution.iter_gator_claims()

    assert {claim["id"] for claim in claims} == {
        "claim-single-up-id",
        "claim-single-school",
        "claim-list-school",
        "claim-container-school",
    }
    assert all(claim["_claim_file"] == f"{claim['id']}.yaml" for claim in claims)


def test_iter_gator_claims_rejects_duplicate_claim_ids(tmp_path: Path, monkeypatch):
    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    fixtures = {
        "claim-duplicate-a.yaml": {"id": "claim-duplicate", "school": "gator"},
        "claim-duplicate-b.yaml": [
            {"id": "claim-duplicate", "up_id": "gator-ecyu-0001"}
        ],
    }
    for filename, data in fixtures.items():
        (claims_dir / filename).write_text(
            yaml.safe_dump(data, allow_unicode=True), encoding="utf-8"
        )
    monkeypatch.setattr(evolution, "CLAIMS_DIR", claims_dir)

    with pytest.raises(ValueError, match="重复 claim_id: claim-duplicate"):
        evolution.iter_gator_claims()


def test_filter_new_claims_skips_only_processed_and_classified_claims():
    claims = [
        {"id": "claim-processed-classified"},
        {"id": "claim-processed-only"},
        {"id": "claim-unprocessed-classified"},
        {"id": "claim-new"},
    ]

    selected = evolution.filter_new_claims(
        claims,
        {"claim-processed-classified", "claim-processed-only"},
        {"claim-processed-classified", "claim-unprocessed-classified"},
        None,
    )

    assert [claim["id"] for claim in selected] == [
        "claim-processed-only",
        "claim-unprocessed-classified",
        "claim-new",
    ]


def test_reclassify_selection_ignores_processed_and_classification_filters():
    claims = [{"id": "claim-processed-classified"}, {"id": "claim-new"}]

    selected = evolution.filter_new_claims(
        claims,
        set(),
        {"claim-processed-classified"},
        None,
    )

    assert [claim["id"] for claim in selected] == [
        "claim-processed-classified",
        "claim-new",
    ]


def test_classify_claims_does_not_mutate_cached_classification():
    cached = {
        "category": "reinforce",
        "pattern_id": "gator-ch01-stop-falling-5-signals",
        "rationale": "已有分类",
    }
    original = dict(cached)
    existing = {"claim-cached": cached}

    class UnexpectedLLM:
        def invoke(self, prompt):
            raise AssertionError("已有 classification 不应调用 LLM")

    enriched = [{"id": "claim-cached", "_candidates": [], "_weak_match": False}]
    results = evolution.classify_claims(enriched, [], existing, UnexpectedLLM())

    assert results[0]["_classification"] is not cached
    assert results[0]["_classification"] == {**original, "_from_state": True}
    assert cached == original
    assert existing == {"claim-cached": original}


@pytest.mark.parametrize(
    "window_desc",
    ["近 7 天（自 2026-11-08）", "自 2026-10-15（reclassify 模式）"],
)
def test_render_report_labels_processed_count_for_window_modes(window_desc):
    enriched = [{"id": "claim-1", "source_date": "2026-11-15", "_candidates": []}]

    report = evolution.render_report(enriched, window_desc, 99, "test")

    assert "gator claims 总数：99 ｜ 本次处理：1" in report
    assert "本周新增：" not in report
