"""毕业判据 3（路径 A 假设证伪率）v1 可计算口径。

spec: docs/superpowers/specs/2026-10-25-criterion3-computable-definition.md
"""
import json
import textwrap
from datetime import date

import pytest

from investment_engine.shadow.graduation import (
    aggregate, criterion3, judge, load_baseline, run,
)

TODAY = date(2026, 8, 9)


def _rec(day, *, stage_hit=None, status="scored", dirs=None):
    rec = {"date": day, "status": status, "stage_hit": stage_hit}
    if dirs is not None:
        rec["due_scores"] = {"directions": dirs}
    return rec


def _eight_week_records(stage_hit=True, dir_hits=2, dir_samples=2):
    """8 个连续自然周各一条已结算记录（与 test_shadow_graduation 同构）。"""
    from datetime import timedelta
    start = date(2026, 6, 15)
    return [
        _rec((start + timedelta(weeks=i) + timedelta(days=2)).isoformat(),
             stage_hit=stage_hit,
             dirs={"samples": dir_samples, "hits": dir_hits})
        for i in range(8)
    ]

_CLAIMS_YAML = textwrap.dedent("""
    claims:
      - id: c-hit
        source_path: sources/raw/a.md
        claim_type: stock-view
        direction: {label: bullish, as_of: "2026-06-01"}
        outcome: {result: hit, window_days: 5}
      - id: c-miss
        source_path: sources/raw/b.md
        claim_type: sector-theme
        direction: {label: bearish, as_of: "2026-06-02"}
        outcome: {result: miss, window_days: 5}
      - id: c-neutral
        source_path: sources/raw/c.md
        claim_type: stock-view
        direction: {label: bullish, as_of: "2026-06-03"}
        outcome: {result: neutral_window, window_days: 5}
      - id: c-pending
        source_path: sources/raw/d.md
        claim_type: stock-view
        direction: {label: bullish, as_of: "2026-06-04"}
        outcome: {result: pending_data, window_days: 5}
      - id: c-insufficient
        source_path: sources/raw/e.md
        claim_type: stock-view
        direction: {label: bullish, as_of: "2026-06-05"}
        outcome: {result: insufficient_data, window_days: 5}
      - id: c-nodirection
        source_path: sources/raw/f.md
        claim_type: stock-view
        outcome: {result: hit, window_days: 5}
      - id: c-research
        source_path: sources/research/g.pdf
        claim_type: stock-view
        direction: {label: bullish, as_of: "2026-06-06"}
        outcome: {result: miss, window_days: 5}
""")


@pytest.fixture
def claims_dir(tmp_path):
    d = tmp_path / "claims"
    d.mkdir()
    (d / "batch.yaml").write_text(_CLAIMS_YAML, encoding="utf-8")
    return d


def test_load_baseline_counts_only_up_directed_hit_miss(claims_dir):
    base = load_baseline(claims_dir)
    assert base["hit"] == 1 and base["miss"] == 1
    assert base["n"] == 2 and base["falsification"] == 0.5


def test_load_baseline_missing_dir(tmp_path):
    base = load_baseline(tmp_path / "nonexistent")
    assert base["n"] == 0 and base["falsification"] is None


def test_criterion3_math_and_pass():
    base = {"hit": 218, "miss": 300, "n": 518, "falsification": 300 / 518}
    c3 = criterion3({"rate": 0.409, "n": 93}, base)
    assert c3["agent_falsification"] == pytest.approx(1 - 0.409)
    assert c3["threshold"] == pytest.approx(base["falsification"] + 0.10)
    assert c3["passed"] is True


def test_criterion3_fails_when_above_threshold():
    base = {"hit": 1, "miss": 1, "n": 2, "falsification": 0.5}
    c3 = criterion3({"rate": 0.3, "n": 10}, base)
    assert c3["passed"] is False


@pytest.mark.parametrize("direction,baseline", [
    ({"rate": None, "n": 0}, {"hit": 1, "miss": 1, "n": 2, "falsification": 0.5}),
    ({"rate": 0.5, "n": 10}, {"hit": 0, "miss": 0, "n": 0, "falsification": None}),
])
def test_criterion3_insufficient_when_either_side_n_zero(direction, baseline):
    assert criterion3(direction, baseline)["passed"] is None


def test_judge_graduated_requires_c3_pass():
    stats = aggregate(_eight_week_records())
    assert judge(stats, weeks=8, covered_weeks=8, c3_passed=True) == "graduated"
    assert judge(stats, weeks=8, covered_weeks=8, c3_passed=False) == "not_yet"
    assert judge(stats, weeks=8, covered_weeks=8, c3_passed=None) == "not_yet"


def _seed_predictions(tmp_path):
    pred_dir = tmp_path / "predictions"
    pred_dir.mkdir()
    rec = {"date": "2026-08-07", "status": "scored", "stage_hit": True,
           "due_scores": {"directions": {"samples": 2, "hits": 1, "hit_rate": 0.5}}}
    (pred_dir / "2026-08-07.json").write_text(
        json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    return pred_dir


def test_run_report_renders_criterion3_numbers(tmp_path, claims_dir):
    pred_dir = _seed_predictions(tmp_path)
    out = run(pred_dir, weeks=8, out_dir=tmp_path / "logs", today=TODAY,
              claims_dir=claims_dir)
    text = out.read_text(encoding="utf-8")
    # agent 证伪率 50.0%（n=2）；基准 50.0%（n=2）；阈值 60.0% → 达标
    assert "第三判据" in text
    assert "50.0%（n=2）" in text
    assert "阈值 60.0%" in text
    assert "达标" in text
    assert "spec docs/superpowers/specs/2026-10-25-criterion3-computable-definition.md" in text


def test_run_report_c3_insufficient_without_claims_dir(tmp_path):
    pred_dir = _seed_predictions(tmp_path)
    out = run(pred_dir, weeks=8, out_dir=tmp_path / "logs", today=TODAY)
    text = out.read_text(encoding="utf-8")
    assert "第三判据" in text and "数据不足" in text
