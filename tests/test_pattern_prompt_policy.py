"""推理模式生产准入与双学派元数据契约。"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest
import yaml

from qing_investment.agent.graph import nodes
from qing_investment.agent.tools.pattern_policy import (
    filter_production_patterns,
    is_pattern_production_eligible,
    project_pattern,
)


@pytest.mark.parametrize("hit_rate", [0, 1, 0.5667])
def test_qing_numeric_hit_rate_is_production_eligible(hit_rate):
    pattern = {
        "pattern_id": "qing-validated",
        "school": "qing",
        "validation": {"historical_hit_rate": hit_rate},
    }

    assert is_pattern_production_eligible(pattern)
    assert filter_production_patterns([pattern]) == [pattern]


@pytest.mark.parametrize(
    "hit_rate",
    [float("nan"), float("inf"), float("-inf"), -0.1, 1.1],
)
def test_qing_non_finite_or_out_of_range_hit_rate_is_rejected(hit_rate):
    pattern = {
        "pattern_id": "qing-invalid-rate",
        "school": "qing",
        "validation": {"historical_hit_rate": hit_rate},
    }

    assert not is_pattern_production_eligible(pattern)
    assert filter_production_patterns([pattern]) == []


@pytest.mark.parametrize(
    "pattern",
    [
        {"pattern_id": "qing-missing-validation", "school": "qing"},
        {"pattern_id": "qing-missing-rate", "school": "qing", "validation": {}},
        {"pattern_id": "qing-null-validation", "school": "qing", "validation": None},
        {
            "pattern_id": "qing-null-rate",
            "school": "qing",
            "validation": {"historical_hit_rate": None},
        },
        {
            "pattern_id": "qing-pending",
            "school": "qing",
            "validation": {"historical_hit_rate": "pending"},
        },
        {
            "pattern_id": "qing-pending-m1",
            "school": "qing",
            "validation": {"historical_hit_rate": "pending-m1"},
        },
        {
            "pattern_id": "qing-bool-true",
            "school": "qing",
            "validation": {"historical_hit_rate": True},
        },
        {
            "pattern_id": "qing-bool-false",
            "school": "qing",
            "validation": {"historical_hit_rate": False},
        },
    ],
)
def test_qing_unvalidated_pattern_is_rejected(pattern):
    assert not is_pattern_production_eligible(pattern)
    assert filter_production_patterns([pattern]) == []


def test_gator_does_not_need_validation_and_projection_is_truthful():
    without_validation = {"pattern_id": "gator-no-validation", "school": "gator"}
    draft = {
        "pattern_id": "gator-draft",
        "school": "gator",
        "validation": {},
    }

    assert is_pattern_production_eligible(without_validation)
    assert filter_production_patterns([without_validation, draft]) == [
        without_validation,
        draft,
    ]
    projected = project_pattern(draft)
    assert projected["school"] == "gator"
    assert projected["validation"] == {}


def _pattern(pattern_id: str, school: str, validation=None, **kwargs) -> dict:
    pattern = {
        "pattern_id": pattern_id,
        "school": school,
        "name": pattern_id,
        "description": f"{pattern_id} 的共同主题方法",
        "applicable_themes": ["共同主题"],
        "reasoning_chain": [],
        "risk_factors": [],
        "confidence_indicators": [],
    }
    if validation is not None:
        pattern["validation"] = validation
    pattern.update(kwargs)
    return pattern


@pytest.fixture
def pattern_library(tmp_path, monkeypatch):
    framework = tmp_path / "framework"
    framework.mkdir()
    qing_patterns = [
        _pattern("qing-validated", "qing", {"historical_hit_rate": 0.6}),
        _pattern("qing-pending", "qing", {"historical_hit_rate": "pending"}),
        _pattern("qing-null", "qing", {"historical_hit_rate": None}),
        _pattern("qing-missing", "qing"),
        _pattern("qing-bool", "qing", {"historical_hit_rate": True}),
    ]
    gator_patterns = [_pattern("gator-draft", "gator", {})]
    (framework / "reasoning-patterns.yaml").write_text(
        yaml.safe_dump({"patterns": qing_patterns}, allow_unicode=True),
        encoding="utf-8",
    )
    (framework / "reasoning-patterns-gator.yaml").write_text(
        yaml.safe_dump({"patterns": gator_patterns}, allow_unicode=True),
        encoding="utf-8",
    )

    monkeypatch.setattr(nodes, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(nodes, "_PATTERNS_CACHE", [])
    monkeypatch.setattr(nodes, "_PATTERN_INDEX_CACHE", None)
    monkeypatch.setattr(nodes, "_PATTERN_EMBEDDINGS_CACHE", None)


def _assert_recalled_pattern_metadata(recalled: list[dict]) -> None:
    assert {p["pattern_id"] for p in recalled} == {"qing-validated", "gator-draft"}
    by_id = {p["pattern_id"]: p for p in recalled}
    assert by_id["qing-validated"]["school"] == "qing"
    assert by_id["qing-validated"]["validation"] == {"historical_hit_rate": 0.6}
    assert by_id["gator-draft"]["school"] == "gator"
    assert by_id["gator-draft"]["validation"] == {}


class _FakeEmbeddingModel:
    def encode(self, texts):
        if isinstance(texts, str):
            texts = [texts]
        return np.tile(np.array([[1.0, 0.0]]), (len(texts), 1))


def test_embedding_recall_applies_gate_before_cache_and_preserves_metadata(
    pattern_library, monkeypatch
):
    model = _FakeEmbeddingModel()
    monkeypatch.setattr(nodes, "_get_embedding_model", lambda: model)
    monkeypatch.setattr(
        nodes,
        "_llm_rerank_patterns",
        lambda query, candidates, patterns: [
            {
                "pattern_id": patterns[idx]["pattern_id"],
                "reason": "test rerank",
            }
            for idx, _ in candidates
        ],
    )

    recalled = nodes._load_reasoning_patterns({"query": "共同主题"})

    _assert_recalled_pattern_metadata(recalled)
    cached_patterns, embeddings = nodes._PATTERN_EMBEDDINGS_CACHE
    assert cached_patterns == nodes._PATTERNS_CACHE
    assert len(embeddings) == len(cached_patterns) == 2
    assert {p["pattern_id"] for p in cached_patterns} == {
        "qing-validated",
        "gator-draft",
    }


def test_keyword_fallback_uses_same_gate_and_preserves_metadata(
    pattern_library, monkeypatch
):
    monkeypatch.setattr(nodes, "_get_embedding_model", lambda: None)

    recalled = nodes._load_reasoning_patterns({"query": "共同主题"})

    _assert_recalled_pattern_metadata(recalled)
    assert nodes._PATTERN_INDEX_CACHE is not None
    indexed_pattern_ids = {
        nodes._PATTERNS_CACHE[idx]["pattern_id"]
        for hits in nodes._PATTERN_INDEX_CACHE.values()
        for idx, _, _ in hits
    }
    assert indexed_pattern_ids == {"qing-validated", "gator-draft"}


def test_only_actually_recalled_gator_pattern_triggers_contract(
    pattern_library, monkeypatch
):
    monkeypatch.setattr(nodes, "_get_embedding_model", lambda: None)
    recalled = nodes._load_reasoning_patterns({"query": "共同主题"})
    qing_only = [p for p in recalled if p["school"] == "qing"]

    assert qing_only
    assert nodes._load_dual_school_contract({"reasoning_patterns": qing_only}) == ""
    contract = nodes._load_dual_school_contract({"reasoning_patterns": recalled})
    assert "双学派输出契约" in contract


_REAL_FRAMEWORK_DIR = Path(__file__).resolve().parents[1] / "framework"


def _load_real_patterns(filename: str) -> list[dict]:
    data = yaml.safe_load((_REAL_FRAMEWORK_DIR / filename).read_text(encoding="utf-8"))
    return data["patterns"]


def test_real_gator_patterns_keep_ids_order_and_validation():
    patterns = _load_real_patterns("reasoning-patterns-gator.yaml")
    original_validations = deepcopy([p.get("validation") for p in patterns])
    assert len(patterns) == 51

    admitted = filter_production_patterns(patterns)

    assert len(admitted) == 51
    assert [p["pattern_id"] for p in admitted] == [p["pattern_id"] for p in patterns]
    for pattern, original_validation in zip(admitted, original_validations):
        assert pattern["school"] == "gator"
        assert pattern.get("validation") == original_validation
        projected = project_pattern(pattern)
        assert projected["school"] == "gator"
        assert projected["validation"] == original_validation
        assert "historical_hit_rate" not in original_validation
        assert "historical_hit_rate" not in projected["validation"]


def test_real_qing_patterns_default_to_qing_and_match_numeric_validation_gate(
    monkeypatch,
):
    patterns = _load_real_patterns("reasoning-patterns.yaml")
    assert len(patterns) == 25
    assert all("school" not in p for p in patterns)

    def has_numeric_hit_rate(pattern: dict) -> bool:
        validation = pattern.get("validation") or {}
        hit_rate = validation.get("historical_hit_rate")
        return isinstance(hit_rate, (int, float)) and not isinstance(hit_rate, bool)

    expected_admitted_ids = [p["pattern_id"] for p in patterns if has_numeric_hit_rate(p)]
    expected_rejected_ids = [p["pattern_id"] for p in patterns if not has_numeric_hit_rate(p)]
    assert len(expected_admitted_ids) == 7
    assert len(expected_rejected_ids) == 18

    monkeypatch.setattr(nodes, "_PATTERNS_CACHE", [])
    monkeypatch.setattr(nodes, "_PATTERN_INDEX_CACHE", None)
    monkeypatch.setattr(nodes, "_PATTERN_EMBEDDINGS_CACHE", None)

    cached = nodes._ensure_patterns_cache()
    cached_qing = [p for p in cached if p.get("school") == "qing"]

    assert [p["pattern_id"] for p in cached_qing] == expected_admitted_ids
    assert all(p["school"] == "qing" for p in cached_qing)
    cached_qing_ids = {p["pattern_id"] for p in cached_qing}
    assert [p["pattern_id"] for p in patterns if p["pattern_id"] not in cached_qing_ids] == expected_rejected_ids
