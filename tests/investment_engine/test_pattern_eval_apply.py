"""apply：守卫 + 双次 schema 校验 + 幂等 + dry-run。"""
import pytest
import yaml

from investment_engine.pattern_eval.apply import apply_proposal

PATTERNS_YAML = """\
patterns:
- pattern_id: sector_rotation
  name: 板块轮动
  description: d
  trigger: t
  data_requirements: []
  steps: []
  falsification: []
  validation:
    historical_hit_rate: pending-m1
    applicable_regime: null
    known_failures: []
- pattern_id: technical_timing
  name: 技术择时
  description: d
  trigger: t
  data_requirements: []
  steps: []
  falsification: []
  validation:
    historical_hit_rate: 0.5182
    applicable_regime: null
    known_failures: []
"""


def _write(tmp_path, changes):
    patterns_path = tmp_path / "patterns.yaml"
    patterns_path.write_text(PATTERNS_YAML, encoding="utf-8")
    proposal_path = tmp_path / "proposal.yaml"
    proposal_path.write_text(yaml.safe_dump(
        {"proposal_id": "t1", "changes": changes}, allow_unicode=True),
        encoding="utf-8")
    return patterns_path, proposal_path


def _change(pid, rate):
    return {"pattern_id": pid,
            "set": {"validation.historical_hit_rate": rate,
                    "validation.applicable_regime": {"震荡": rate}}}


def test_apply_sets_validation_fields(tmp_path):
    patterns_path, proposal_path = _write(tmp_path, [_change("sector_rotation", 0.62)])
    report = apply_proposal(proposal_path, patterns_path=patterns_path)
    assert report["applied"] == ["sector_rotation"]
    doc = yaml.safe_load(patterns_path.read_text(encoding="utf-8"))
    v = doc["patterns"][0]["validation"]
    assert v["historical_hit_rate"] == 0.62
    assert v["applicable_regime"] == {"震荡": 0.62}


def test_apply_idempotent_second_run_skips(tmp_path):
    patterns_path, proposal_path = _write(tmp_path, [_change("sector_rotation", 0.62)])
    apply_proposal(proposal_path, patterns_path=patterns_path)
    report = apply_proposal(proposal_path, patterns_path=patterns_path)
    assert report["applied"] == []
    assert report["skipped"][0]["pattern_id"] == "sector_rotation"
    assert "pending-m1" in report["skipped"][0]["reason"]


def test_apply_skips_pattern_with_real_rate(tmp_path):
    patterns_path, proposal_path = _write(tmp_path, [_change("technical_timing", 0.45)])
    report = apply_proposal(proposal_path, patterns_path=patterns_path)
    assert report["applied"] == []
    assert report["skipped"][0]["pattern_id"] == "technical_timing"
    doc = yaml.safe_load(patterns_path.read_text(encoding="utf-8"))
    assert doc["patterns"][1]["validation"]["historical_hit_rate"] == 0.5182


def test_apply_rejects_unknown_pattern(tmp_path):
    patterns_path, proposal_path = _write(tmp_path, [_change("no_such", 0.5)])
    with pytest.raises(ValueError, match="no_such"):
        apply_proposal(proposal_path, patterns_path=patterns_path)


def test_apply_rejects_forbidden_field(tmp_path):
    bad = {"pattern_id": "sector_rotation", "set": {"name": "改名"}}
    patterns_path, proposal_path = _write(tmp_path, [bad])
    with pytest.raises(ValueError, match="禁止修改"):
        apply_proposal(proposal_path, patterns_path=patterns_path)


def test_apply_appends_known_failures_once(tmp_path):
    ch = _change("sector_rotation", 0.4)
    ch["append_known_failures"] = ["m1 证伪条目"]
    patterns_path, proposal_path = _write(tmp_path, [ch])
    apply_proposal(proposal_path, patterns_path=patterns_path)
    doc = yaml.safe_load(patterns_path.read_text(encoding="utf-8"))
    assert doc["patterns"][0]["validation"]["known_failures"] == ["m1 证伪条目"]


def test_dry_run_does_not_write(tmp_path):
    patterns_path, proposal_path = _write(tmp_path, [_change("sector_rotation", 0.62)])
    report = apply_proposal(proposal_path, patterns_path=patterns_path, dry_run=True)
    assert report["applied"] == ["sector_rotation"]
    assert patterns_path.read_text(encoding="utf-8") == PATTERNS_YAML
