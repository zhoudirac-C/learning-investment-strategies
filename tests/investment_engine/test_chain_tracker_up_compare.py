"""「管线判断 vs UP 判断」每日对比工具测试（T23）。全部 tempdir 离线。"""
import json
import tempfile
from pathlib import Path

import pytest
import yaml

from investment_engine.chain_tracker.up_compare import (
    AGREEMENT_LEVELS, agreement_stats, load_claims_for_date, log_comparison,
    match_claims_to_chains, render_compare_draft,
)
from investment_engine.industry_chain.store import save_chain


def _chain(chain_id: str = "ai-pcb-ccl", **over) -> dict:
    """schema 合法的 chain dict（log_comparison 走 store.load_chain 强校验）。"""
    base = {
        "chain_id": chain_id,
        "name": "AI PCB/CCL 产业链",
        "thesis": "AI服务器代际升级 → PCB/CCL 材料升级",
        "last_verified": "2026-08-30",
        "segments": [{"id": "seg-upstream", "name": "上游材料",
                      "materials": ["铜箔(HVLP4)", "玻璃布"]}],
        "mappings": [{"code": "600183", "name": "生益科技",
                      "segment": "seg-upstream", "relation": "CCL龙头",
                      "elasticity": "core"}],
        "current_stage": "阶段2-加速期",
        "stage_confidence": "高",
        "stage_evidence": "满产满销，订单排至2027",
        "timing": {"current_recommendation": "中游CCL，不追高",
                   "next_trigger": None, "risk": None},
        "tracking_metrics": [{"metric": "FR8价格", "current": "260元/张",
                              "signal_direction": "突破300=加强"}],
        "falsification": [],
    }
    base.update(over)
    return base


def _claim(**over) -> dict:
    base = {
        "id": "claim-20260830-001-a",
        "source_date": "2026-08-30",
        "claim_type": "sector-theme",
        "subject": "白酒板块集体走强",
        "statement": "贵州茅台放量上涨。",
        "confidence": "high",
        "related_stocks": [],
        "tags": [],
    }
    base.update(over)
    return base


@pytest.fixture()
def workspace():
    d = Path(tempfile.mkdtemp(prefix="up_compare_test_"))
    return {"dir": d, "claims": d / "claims", "chains": d / "chains",
            "log": d / "up_comparison.jsonl"}


def _write_claims(claims_dir: Path, name: str, claims: list[dict]) -> Path:
    claims_dir.mkdir(parents=True, exist_ok=True)
    path = claims_dir / name
    path.write_text(yaml.safe_dump({"claims": claims}, allow_unicode=True),
                    encoding="utf-8")
    return path


def _write_log(path: Path, entries: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n"
                            for e in entries), encoding="utf-8")
    return path


class TestMatch:
    def test_match_by_stock_code(self):
        c = _claim(related_stocks=[{"code": "600183", "name": "某公司"}])
        matched = match_claims_to_chains([c], [_chain()])
        assert [x["id"] for x in matched["ai-pcb-ccl"]] == [c["id"]]

    def test_match_by_stock_name(self):
        c = _claim(related_stocks=[{"code": "999999", "name": "生益科技"}])
        assert "ai-pcb-ccl" in match_claims_to_chains([c], [_chain()])

    def test_match_by_chain_stock_name_in_subject(self):
        c = _claim(subject="生益科技订单排至2027，满产满销")
        assert "ai-pcb-ccl" in match_claims_to_chains([c], [_chain()])

    def test_match_by_tag_keyword_case_insensitive(self):
        # 链 tracking_metrics "FR8价格" → keyword "FR8"（大写）；tag 小写也命中
        c = _claim(tags=["fr8"])
        assert "ai-pcb-ccl" in match_claims_to_chains([c], [_chain()])

    def test_no_match_chain_absent(self):
        c = _claim(related_stocks=[{"code": "600519", "name": "贵州茅台"}],
                   tags=["白酒"])
        assert match_claims_to_chains([c], [_chain()]) == {}

    def test_multiple_claims_same_chain_accumulate(self):
        c1 = _claim(id="c1", related_stocks=[{"code": "600183", "name": "x"}])
        c2 = _claim(id="c2", subject="生益科技满产")
        matched = match_claims_to_chains([c1, c2], [_chain()])
        assert [x["id"] for x in matched["ai-pcb-ccl"]] == ["c1", "c2"]


class TestLoadClaims:
    def test_flatten_and_date_location(self, workspace):
        _write_claims(workspace["claims"], "claim-20260830-001.yaml",
                      [_claim(id="a"), _claim(id="b")])
        _write_claims(workspace["claims"], "claim-20260830-002.yaml",
                      [_claim(id="c")])
        _write_claims(workspace["claims"], "claim-20260829-001.yaml",
                      [_claim(id="other-day")])
        claims = load_claims_for_date("2026-08-30",
                                      claims_dir=workspace["claims"])
        assert [c["id"] for c in claims] == ["a", "b", "c"]

    def test_missing_dir_or_date_returns_empty(self, workspace):
        assert load_claims_for_date("2026-08-30",
                                    claims_dir=workspace["claims"]) == []


class TestRenderDraft:
    def test_contains_pipeline_claim_and_blank_line(self):
        c = _claim(subject="CCL涨价持续", statement="覆铜板满产满销。")
        text = render_compare_draft("2026-08-30", {"ai-pcb-ccl": [c]},
                                    {"ai-pcb-ccl": _chain()})
        assert "每日对比 2026-08-30" in text
        assert "阶段2-加速期" in text and "置信度 高" in text
        assert "中游CCL，不追高" in text
        assert "【sector-theme/high】CCL涨价持续" in text
        assert "覆铜板满产满销。" in text
        assert "> 对比结论（agree/partial/disagree）：___  备注：___" in text

    def test_statement_truncated_at_200(self):
        c = _claim(statement="长" * 300)
        text = render_compare_draft("2026-08-30", {"ai-pcb-ccl": [c]},
                                    {"ai-pcb-ccl": _chain()})
        assert "长" * 201 not in text
        assert ("长" * 200 + "…") in text

    def test_empty_matched_keeps_trace_note(self):
        text = render_compare_draft("2026-08-30", {}, {"ai-pcb-ccl": _chain()})
        assert "当日无 UP 判断命中任何链" in text
        assert "生益科技" not in text  # 无命中的链不出现


class TestLogComparison:
    def test_writes_entry_with_pipeline_snapshot(self, workspace):
        save_chain(_chain(), base_dir=workspace["chains"])
        entry = log_comparison(date="2026-08-30", chain_id="ai-pcb-ccl",
                               agreement="partial", note="UP更保守",
                               path=workspace["log"],
                               base_dir=workspace["chains"])
        assert entry["agreement"] == "partial"
        assert entry["note"] == "UP更保守"
        assert entry["pipeline_stage"] == "阶段2-加速期"
        assert entry["pipeline_timing"] == "中游CCL，不追高"
        assert entry["ts"]
        lines = workspace["log"].read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0])["chain_id"] == "ai-pcb-ccl"

    def test_invalid_agreement_raises(self, workspace):
        with pytest.raises(ValueError):
            log_comparison(date="2026-08-30", chain_id="ai-pcb-ccl",
                           agreement="agree-ish", path=workspace["log"],
                           base_dir=workspace["chains"])
        assert not workspace["log"].exists()  # 校验失败不落账
        assert "partial" in AGREEMENT_LEVELS

    def test_missing_chain_still_logged_with_none(self, workspace):
        entry = log_comparison(date="2026-08-30", chain_id="no-such-chain",
                               agreement="agree", path=workspace["log"],
                               base_dir=workspace["chains"])
        assert entry["pipeline_stage"] is None
        assert entry["pipeline_timing"] is None


class TestAgreementStats:
    def test_window_rates_and_by_chain(self, workspace):
        _write_log(workspace["log"], [
            {"date": "2026-08-31", "chain_id": "ai-pcb-ccl", "agreement": "agree"},
            {"date": "2026-08-30", "chain_id": "ai-pcb-ccl", "agreement": "partial"},
            {"date": "2026-08-25", "chain_id": "robotics", "agreement": "disagree"},
            {"date": "2026-08-01", "chain_id": "robotics", "agreement": "agree"},
            # 窗口外（cutoff = 2026-08-01，不含更早）
            {"date": "2026-07-15", "chain_id": "robotics", "agreement": "agree"},
        ])
        s = agreement_stats(days=30, today="2026-08-31", path=workspace["log"])
        assert s["days"] == 30
        assert s["total"] == 4
        assert (s["agree"], s["partial"], s["disagree"]) == (2, 1, 1)
        assert s["overlap_rate"] == pytest.approx(0.625)  # (2 + 0.5) / 4
        assert s["full_rate"] == pytest.approx(0.5)
        assert s["dates"] == ["2026-08-01", "2026-08-25",
                              "2026-08-30", "2026-08-31"]
        pcb = s["by_chain"]["ai-pcb-ccl"]
        assert pcb["total"] == 2 and pcb["overlap_rate"] == pytest.approx(0.75)
        rob = s["by_chain"]["robotics"]
        assert rob["total"] == 2 and rob["disagree"] == 1
        assert rob["overlap_rate"] == pytest.approx(0.5)

    def test_empty_returns_none_rates(self, workspace):
        s = agreement_stats(days=30, today="2026-08-31", path=workspace["log"])
        assert s["total"] == 0
        assert s["overlap_rate"] is None and s["full_rate"] is None
        assert s["by_chain"] == {} and s["dates"] == []
