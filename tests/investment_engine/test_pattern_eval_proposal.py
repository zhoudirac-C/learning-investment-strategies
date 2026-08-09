"""proposal：提案渲染（evidence 全量留档，changes 只含落库补丁）。"""
import yaml

from investment_engine.pattern_eval.proposal import build_proposal, write_proposal


def _fixtures():
    metrics = {
        "sector_rotation": {
            "days_used": 25,
            "stage": {"rate": 0.6, "n": 25},
            "direction": {"rate": 0.62, "n": 50},
            "stock": {"rate": 0.5, "n": 50},
            "regime": {"震荡": {"rate": 0.6, "n": 15}, "调整": {"rate": 0.6, "n": 10}},
        },
        "sentiment_cycle": {
            "days_used": 30,
            "stage": {"rate": 0.4, "n": 30},
            "direction": {"rate": 0.5, "n": 40},
            "stock": {"rate": 0.5, "n": 40},
            "regime": {"震荡": {"rate": 0.4, "n": 30}},
        },
        "technical_timing": {
            "days_used": 10,
            "stage": {"rate": 0.5, "n": 10},
            "direction": {"rate": 0.5, "n": 20},
            "stock": {"rate": 0.45, "n": 20},
            "regime": {},
        },
    }
    buckets = {
        "sector_rotation": {"bucket": "达标", "primary_metric": "direction"},
        "sentiment_cycle": {"bucket": "证伪", "primary_metric": "stage"},
        "technical_timing": {"bucket": "待观察", "primary_metric": "stock"},
        "others": {"bucket": "unused", "note": "m1 未使用"},
    }
    patterns = [
        {"pattern_id": "sector_rotation",
         "validation": {"historical_hit_rate": "pending-m1",
                        "applicable_regime": None, "known_failures": []}},
        {"pattern_id": "sentiment_cycle",
         "validation": {"historical_hit_rate": "pending-m1",
                        "applicable_regime": None, "known_failures": []}},
        {"pattern_id": "technical_timing",
         "validation": {"historical_hit_rate": 0.5182,
                        "applicable_regime": None, "known_failures": []}},
        {"pattern_id": "others",
         "validation": {"historical_hit_rate": "pending-m1",
                        "applicable_regime": None, "known_failures": ["已有条目"]}},
    ]
    window = {"start": "2026-04-27", "end": "2026-08-07", "scored_days": 69}
    return metrics, buckets, patterns, window


def test_changes_only_pending_patterns():
    metrics, buckets, patterns, window = _fixtures()
    proposal = build_proposal(metrics, buckets, patterns, window=window)
    ids = [c["pattern_id"] for c in proposal["changes"]]
    # technical_timing 已有实测值（M0 回测），不进 changes；others 未被使用不进
    assert ids == ["sector_rotation", "sentiment_cycle"]  # 按 pattern_id ASCII 排序


def test_change_payload_and_falsification_note():
    metrics, buckets, patterns, window = _fixtures()
    proposal = build_proposal(metrics, buckets, patterns, window=window)
    sr = next(c for c in proposal["changes"] if c["pattern_id"] == "sector_rotation")
    assert sr["set"]["validation.historical_hit_rate"] == 0.62  # 主指标 direction
    assert sr["set"]["validation.applicable_regime"] == {"震荡": 0.6, "调整": 0.6}
    assert "append_known_failures" not in sr                     # 达标桶不追加
    sc = next(c for c in proposal["changes"] if c["pattern_id"] == "sentiment_cycle")
    assert sc["set"]["validation.historical_hit_rate"] == 0.4    # 主指标 stage
    assert len(sc["append_known_failures"]) == 1                 # 证伪桶追加
    assert "0.4" in sc["append_known_failures"][0] or "40.0%" in sc["append_known_failures"][0]


def test_evidence_covers_all_patterns_including_unused():
    metrics, buckets, patterns, window = _fixtures()
    proposal = build_proposal(metrics, buckets, patterns, window=window)
    ev = proposal["evidence"]["metrics"]
    assert set(ev) == {"sector_rotation", "sentiment_cycle", "technical_timing", "others"}
    assert ev["others"] == {"bucket": "unused", "note": "m1 未使用"}
    assert ev["technical_timing"]["bucket"] == "待观察"  # 只进证据区
    assert "使用归因" in proposal["evidence"]["attribution"]
    assert proposal["source"] == "m1-blindtest"


def test_write_proposal(tmp_path):
    metrics, buckets, patterns, window = _fixtures()
    proposal = build_proposal(metrics, buckets, patterns, window=window)
    path = write_proposal(proposal, tmp_path)
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert loaded["proposal_id"] == proposal["proposal_id"]
    assert loaded["changes"] == proposal["changes"]
