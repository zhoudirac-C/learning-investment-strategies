"""Tests for scripts/evaluate_agent_vs_up.py.

The script is not inside the package, so we load it via importlib.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "evaluate_agent_vs_up.py"


@pytest.fixture(scope="module")
def eval_mod():
    spec = importlib.util.spec_from_file_location("evaluate_agent_vs_up", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["evaluate_agent_vs_up"] = mod
    spec.loader.exec_module(mod)
    return mod


def _write_claims(claims_dir: Path, filename: str, claims: list[dict]) -> None:
    claims_dir.mkdir(parents=True, exist_ok=True)
    (claims_dir / filename).write_text(
        "claims:\n" + "".join(f"  - {k}: {v!r}\n" for c in claims for k, v in c.items()),
        encoding="utf-8",
    )


def _write_claims_yaml(claims_dir: Path, filename: str, content: str) -> None:
    claims_dir.mkdir(parents=True, exist_ok=True)
    (claims_dir / filename).write_text(content, encoding="utf-8")


class TestLoadClaims:
    def test_filters_by_source_date(self, tmp_path, eval_mod):
        claims_dir = tmp_path / "claims"
        _write_claims_yaml(
            claims_dir,
            "a.yaml",
            """claims:
- id: claim-20260708-001
  source_date: '2026-07-08'
  topic: 今日震荡调整
  statement: 大盘震荡调整
  claim_type: market-cycle
  tags:
  - 震荡
- id: claim-20260708-002
  source_date: '2026-07-08'
  topic: 国产算力
  statement: 国产算力景气
  claim_type: sector-theme
  related_stocks:
  - code: '603881'
    name: 数据港
  tags:
  - 国产算力
""",
        )
        _write_claims_yaml(
            claims_dir,
            "b.yaml",
            """claims:
- id: claim-20260707-001
  source_date: '2026-07-07'
  topic: 机器人
  statement: 机器人分化
  claim_type: sector-theme
  tags:
  - 机器人
""",
        )
        claims = eval_mod.load_claims_by_date(claims_dir, "2026-07-08")
        assert len(claims) == 2
        assert {c["id"] for c in claims} == {"claim-20260708-001", "claim-20260708-002"}


class TestCompareDirections:
    def test_score_and_unmatched(self, eval_mod):
        directions = [
            {"direction": "国产算力", "intensity": "🔥🔥🔥"},
            {"direction": "机器人", "intensity": "🔥"},
        ]
        claims = [
            {
                "id": "c1",
                "topic": "国产算力",
                "subject": "科技中期主线判断",
                "tags": ["国产算力", "IDC"],
                "related_stocks": [],
                "claim_type": "sector-theme",
            }
        ]
        result = eval_mod.compare_directions(directions, claims)
        assert result["score"] == 0.5
        assert result["matched"] == ["国产算力"]
        assert result["unmatched"] == ["机器人"]

    def test_empty_directions(self, eval_mod):
        result = eval_mod.compare_directions([], [])
        assert result["score"] == 0.0


class TestCompareAssumptions:
    def test_jaccard_score(self, eval_mod):
        agent_text = "短期大环境偏震荡调整，降低预期"
        claims = [
            {
                "id": "c1",
                "topic": "短期大环境判断",
                "subject": "短期大环境判断",
                "statement": "短期大环境偏震荡调整为主，操作难度大，应降低预期、合理安排仓位。",
                "tags": ["震荡调整", "降低预期"],
                "claim_type": "market-cycle",
            }
        ]
        result = eval_mod.compare_assumptions(agent_text, claims)
        assert 0 < result["score"] <= 1.0
        assert result["best_claim_id"] == "c1"

    def test_no_claims_zero_score(self, eval_mod):
        result = eval_mod.compare_assumptions("震荡调整", [])
        assert result["score"] == 0.0


class TestCompareScenarios:
    def test_returns_score(self, eval_mod):
        narratives = ["开盘量能温和收敛，日韩市场平稳，指数低开或平开后震荡修复。"]
        claims = [
            {
                "id": "c1",
                "topic": "情形A走势判断",
                "statement": "若开盘量能继续温和收敛且日韩市场平稳，指数可能低开或平开后震荡修复。",
                "tags": ["缩量企稳", "情形A"],
                "claim_type": "operation",
            }
        ]
        result = eval_mod.compare_scenarios(narratives, claims)
        assert 0 < result["score"] <= 1.0


class TestCompareOpportunities:
    def test_hit_rate(self, eval_mod):
        opportunities = [
            {"stock": "数据港", "code": "603881.SH", "pattern": "国产算力IDC"},
            {"stock": "未知科技", "code": "000001.SZ", "pattern": "神秘题材"},
        ]
        claims = [
            {
                "id": "c1",
                "topic": "国产算力IDC分层逻辑",
                "related_stocks": [
                    {"code": "603881", "name": "数据港"},
                ],
                "tags": ["国产算力", "IDC"],
                "claim_type": "sector-theme",
            }
        ]
        result = eval_mod.compare_opportunities(opportunities, claims)
        assert result["score"] == 0.5
        assert len(result["hits"]) == 1
        assert result["hits"][0]["stock"] == "数据港"
        assert len(result["misses"]) == 1


class TestEvaluate:
    def test_report_structure(self, tmp_path, eval_mod):
        archive_dir = tmp_path / "daily_state_archive"
        claims_dir = tmp_path / "claims"
        archive_dir.mkdir(parents=True, exist_ok=True)
        claims_dir.mkdir(parents=True, exist_ok=True)

        agent_state = {
            "date": "2026-07-08",
            "market_stage": {"phase": "震荡调整", "detail": "短期大环境偏震荡调整"},
            "position_stance": "降低预期，轻仓",
            "direction_priority": [
                {"direction": "国产算力", "intensity": "🔥🔥🔥"},
            ],
            "intraday_narrative": [
                {"time": "09:26", "summary": "开盘量能温和收敛，日韩市场平稳。"}
            ],
            "active_opportunities": [
                {"stock": "数据港", "code": "603881.SH", "pattern": "国产算力IDC"}
            ],
        }
        (archive_dir / "daily_state_2026-07-08.json").write_text(
            json.dumps(agent_state, ensure_ascii=False), encoding="utf-8"
        )

        _write_claims_yaml(
            claims_dir,
            "2026-07-08.yaml",
            """claims:
- id: claim-20260708-001
  source_date: '2026-07-08'
  topic: 国产算力
  subject: 科技中期主线
  statement: 科技方向的中期逻辑贯穿整个下半年。
  claim_type: sector-theme
  tags:
  - 国产算力
  related_stocks:
  - code: '603881'
    name: 数据港
- id: claim-20260708-002
  source_date: '2026-07-08'
  topic: 短期大环境判断
  subject: 短期大环境判断
  statement: 短期大环境偏震荡调整为主，应降低预期。
  claim_type: market-cycle
  tags:
  - 震荡调整
""",
        )

        report = eval_mod.evaluate(
            "2026-07-08",
            archive_dir=archive_dir,
            claims_dir=claims_dir,
        )
        assert report["date"] == "2026-07-08"
        assert "direction_overlap" in report
        assert "assumption_accuracy" in report
        assert "scenario_accuracy" in report
        assert "opportunity_hit_rate" in report
        assert "overall_score" in report
        assert report["direction_overlap"]["score"] == 1.0
        assert report["assumption_accuracy"]["score"] > 0
        assert report["opportunity_hit_rate"]["score"] == 1.0


class TestRenderMarkdown:
    def test_contains_scores_and_details(self, eval_mod):
        report = {
            "date": "2026-07-08",
            "direction_overlap": {
                "score": 1.0,
                "matched": ["国产算力"],
                "unmatched": [],
                "total": 1,
            },
            "assumption_accuracy": {
                "score": 0.75,
                "best_claim_id": "claim-20260708-002",
                "best_topic": "短期大环境判断",
            },
            "scenario_accuracy": {"score": 0.6, "best_claim_id": "c1", "best_topic": "情形A"},
            "opportunity_hit_rate": {
                "score": 1.0,
                "hits": [{"stock": "数据港", "code": "603881.SH", "matched_claims": ["c1"]}],
                "misses": [],
                "total": 1,
            },
            "overall_score": 0.84,
            "notes": [],
        }
        md = eval_mod.render_markdown([report])
        assert "2026-07-08" in md
        assert "方向重合度" in md
        assert "国产算力" in md
        assert "0.84" in md or "84%" in md


class TestCLI:
    def test_date_flag_writes_markdown(self, tmp_path):
        archive_dir = tmp_path / "daily_state_archive"
        claims_dir = tmp_path / "claims"
        output_dir = tmp_path / "evals"
        archive_dir.mkdir(parents=True, exist_ok=True)
        claims_dir.mkdir(parents=True, exist_ok=True)

        agent_state = {
            "date": "2026-07-08",
            "market_stage": {"phase": "震荡调整", "detail": ""},
            "position_stance": "轻仓",
            "direction_priority": [],
            "intraday_narrative": [],
            "active_opportunities": [],
        }
        (archive_dir / "daily_state_2026-07-08.json").write_text(
            json.dumps(agent_state, ensure_ascii=False), encoding="utf-8"
        )
        _write_claims_yaml(
            claims_dir,
            "x.yaml",
            """claims:
- id: claim-20260708-001
  source_date: '2026-07-08'
  topic: 大环境
  statement: 震荡调整
  claim_type: market-cycle
""",
        )

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--date",
                "2026-07-08",
                "--archive-dir",
                str(archive_dir),
                "--claims-dir",
                str(claims_dir),
                "--output-dir",
                str(output_dir),
            ],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        expected = output_dir / "agent-up-consistency" / "2026-07-08.md"
        assert expected.exists(), f"expected {expected} to exist"
        assert "2026-07-08" in expected.read_text(encoding="utf-8")

    def test_week_flag_writes_weekly_markdown(self, tmp_path):
        archive_dir = tmp_path / "daily_state_archive"
        claims_dir = tmp_path / "claims"
        output_dir = tmp_path / "evals"
        archive_dir.mkdir(parents=True, exist_ok=True)
        claims_dir.mkdir(parents=True, exist_ok=True)

        # Create weekday archives for the last 5 trading days anchored on 2026-07-08 (Wed).
        for d in ["2026-07-08", "2026-07-07", "2026-07-06", "2026-07-03", "2026-07-02"]:
            (archive_dir / f"daily_state_{d}.json").write_text(
                json.dumps({
                    "date": d,
                    "market_stage": {"phase": "震荡", "detail": ""},
                    "position_stance": "轻仓",
                    "direction_priority": [],
                    "intraday_narrative": [],
                    "active_opportunities": [],
                }, ensure_ascii=False),
                encoding="utf-8",
            )
            _write_claims_yaml(
                claims_dir,
                f"{d}.yaml",
                f"""claims:
- id: claim-{d.replace('-', '')}-001
  source_date: '{d}'
  topic: 大环境
  statement: 震荡调整
  claim_type: market-cycle
""",
            )

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--week",
                "--date",
                "2026-07-08",
                "--archive-dir",
                str(archive_dir),
                "--claims-dir",
                str(claims_dir),
                "--output-dir",
                str(output_dir),
            ],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        expected = output_dir / "agent-up-consistency" / "week-2026-07-08.md"
        assert expected.exists(), f"expected {expected} to exist"
        text = expected.read_text(encoding="utf-8")
        assert "周一致性报告" in text
        assert "2026-07-08" in text
