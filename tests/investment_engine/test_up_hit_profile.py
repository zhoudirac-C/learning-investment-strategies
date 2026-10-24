"""Tests for up_hit_profile：UP 命中率画像聚合与渲染。

口径：hit_rate = hit / (hit + miss)；neutral_window / pending_data /
insufficient_data 不入分子分母；hit+miss < 10 标样本不足。
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from investment_engine.up_hit_profile import (  # noqa: E402
    MIN_SAMPLE,
    aggregate_profile,
    render_markdown,
)


def _c(up, ctype, sd, result, value="bullish"):
    return {
        "up_name": up, "claim_type": ctype, "source_date": sd,
        "direction": {"value": value},
        "outcome": {"result": result},
    }


class TestAggregate:
    def test_hit_rate_excludes_neutral_and_pending(self):
        claims = (
            [_c("U1", "market-cycle", f"2026-10-{d:02d}", "hit") for d in range(1, 11)]
            + [_c("U1", "market-cycle", f"2026-10-{d:02d}", "miss") for d in range(11, 16)]
            + [
                _c("U1", "market-cycle", "2026-10-06", "neutral_window"),
                _c("U1", "market-cycle", "2026-10-07", "pending_data"),
                _c("U1", "market-cycle", "2026-10-08", "insufficient_data"),
            ]
        )
        stats = aggregate_profile(claims)
        g = stats[("U1", "market-cycle")]["total"]
        assert g["hit"] == 10 and g["miss"] == 5
        assert g["neutral"] == 1 and g["pending"] == 1 and g["insufficient"] == 1
        assert abs(g["hit_rate"] - 10 / 15) < 1e-9

    def test_small_sample_flagged(self):
        claims = [_c("U1", "macro", "2026-10-01", "hit")]
        g = aggregate_profile(claims)[("U1", "macro")]["total"]
        assert g["hit"] + g["miss"] < MIN_SAMPLE

    def test_grouping_by_month_and_type(self):
        claims = [
            _c("U1", "market-cycle", "2026-09-15", "hit"),
            _c("U1", "market-cycle", "2026-10-15", "miss"),
            _c("U2", "market-cycle", "2026-10-15", "hit"),
        ]
        stats = aggregate_profile(claims)
        assert ("U1", "market-cycle", "2026-09") in stats
        assert ("U2", "market-cycle", "2026-10") in stats

    def test_unevaluated_claims_ignored(self):
        claims = [{"up_name": "U1", "claim_type": "x", "source_date": "2026-10-01"}]
        assert aggregate_profile(claims) == {}


class TestRender:
    def test_markdown_table(self):
        claims = [
            _c("青枫浦上Q", "market-cycle", "2026-10-01", "hit"),
            _c("青枫浦上Q", "market-cycle", "2026-10-02", "miss"),
        ]
        md = render_markdown(aggregate_profile(claims), generated_on="2026-10-24")
        assert "青枫浦上Q" in md and "market-cycle" in md
        assert "样本不足" in md  # 2 < MIN_SAMPLE
        assert "hit_rate" in md or "命中率" in md
