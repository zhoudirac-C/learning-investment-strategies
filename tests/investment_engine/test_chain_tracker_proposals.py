"""提议持久化与人工确认流程测试（T20/T21）。"""
import tempfile
from pathlib import Path

import pytest

from investment_engine.chain_tracker.proposals import (
    append_daily_audit, attach_evidence, confirm_proposal, load_pending,
    reject_proposal, upsert_pending,
)
from investment_engine.industry_chain.store import load_chain


def _proposal(chain_id: str = "solid-state-battery", **over) -> dict:
    base = {
        "chain_id": chain_id,
        "name": "固态电池产业链",
        "driver": "硫化物电解质量产 + 车企装车验证",
        "thesis": "电解质技术突破 → 中试线投产 → 车企定点 → 材料体系重构",
        "chain": {
            "upstream": {
                "materials": ["硫化锂", "锗"],
                "key_nodes": [{"node": "硫化锂价格", "current": "高位",
                               "trend": "上涨", "signal": "上涨=确认"}],
                "stocks": [{"code": "002460.SZ", "name": "赣锋锂业",
                            "role": "电解质", "timing": "量产前介入"},
                            {"code": "abc", "name": "坏代码公司", "role": "x"}],
            },
            "midstream": {"materials": ["电解质膜"], "key_nodes": [], "stocks": []},
            "downstream": {"materials": [], "key_nodes": [], "stocks": []},
        },
        "current_stage": "阶段1-启动期",
        "timing": "上游材料（弹性最大）",
        "confidence": "中",
        "source": "测试证券研报",
        "source_info_ids": ["AP1"],
    }
    base.update(over)
    return base


@pytest.fixture()
def workspace():
    d = Path(tempfile.mkdtemp(prefix="chain_prop_test_"))
    return {"dir": d, "pending": d / "proposals_pending.json",
            "chains": d / "chains", "tracking": d / "tracking"}


class TestPending:
    def test_upsert_and_load_roundtrip(self, workspace):
        added = upsert_pending([_proposal()], path=workspace["pending"])
        assert [p["chain_id"] for p in added] == ["solid-state-battery"]
        loaded = load_pending(workspace["pending"])
        assert loaded[0]["name"] == "固态电池产业链"
        assert loaded[0]["proposed_at"]  # upsert 自动补日期

    def test_upsert_skips_existing_chain_id(self, workspace):
        upsert_pending([_proposal()], path=workspace["pending"])
        added = upsert_pending([_proposal(source_info_ids=["AP2"])],
                               path=workspace["pending"])
        assert added == []
        assert len(load_pending(workspace["pending"])) == 1

    def test_load_missing_file_returns_empty(self, workspace):
        assert load_pending(workspace["pending"]) == []


class TestDailyAudit:
    def test_append_and_merge(self, workspace):
        p1 = append_daily_audit(workspace["tracking"], "2026-08-31",
                                [_proposal()], tick_label="10:30")
        assert p1 and p1.exists()
        append_daily_audit(workspace["tracking"], "2026-08-31",
                           [_proposal("sodium-ion", name="钠离子电池产业链")],
                           tick_label="11:00")
        import json
        data = json.loads(p1.read_text(encoding="utf-8"))
        assert len(data) == 2
        assert data[0]["tick"] == "10:30" and data[1]["tick"] == "11:00"

    def test_empty_proposals_no_file(self, workspace):
        assert append_daily_audit(workspace["tracking"], "2026-08-31", [],
                                  tick_label="10:30") is None
        assert not (workspace["tracking"] / "proposals_2026-08-31.json").exists()


class TestConfirm:
    def test_confirm_creates_schema_valid_chain(self, workspace):
        upsert_pending([_proposal()], path=workspace["pending"])
        path = confirm_proposal("solid-state-battery",
                                pending_path=workspace["pending"],
                                base_dir=workspace["chains"],
                                today="2026-08-31")
        assert path.exists()
        chain = load_chain("solid-state-battery", base_dir=workspace["chains"])
        assert chain["name"] == "固态电池产业链"
        # confirm = 加入观察列表：一律阶段0起步，LLM 初判留痕在 stage_evidence
        assert chain["current_stage"] == "阶段0-观察"
        assert chain["stage_confidence"] == "低"
        assert "人工确认入观察列表" in chain["stage_evidence"]
        assert "阶段1-启动期" in chain["stage_evidence"]
        assert chain["last_verified"] == "2026-08-31"
        seg_ids = {s["id"] for s in chain["segments"]}
        assert seg_ids == {"upstream", "midstream", "downstream"}
        # 股票代码剥 .SZ 后缀；坏代码 mapping 跳过
        assert [m["code"] for m in chain["mappings"]] == ["002460"]
        assert chain["mappings"][0]["segment"] == "upstream"
        assert chain["mappings"][0]["elasticity"] == "concept"
        # key_nodes 映射为 tracking_metrics
        assert chain["tracking_metrics"][0]["metric"] == "硫化锂价格"
        # 确认后从 pending 移除
        assert load_pending(workspace["pending"]) == []

    def test_confirm_unknown_raises(self, workspace):
        with pytest.raises(ValueError):
            confirm_proposal("no-such-chain", pending_path=workspace["pending"],
                             base_dir=workspace["chains"], today="2026-08-31")

    def test_confirm_existing_chain_raises(self, workspace):
        upsert_pending([_proposal()], path=workspace["pending"])
        confirm_proposal("solid-state-battery",
                         pending_path=workspace["pending"],
                         base_dir=workspace["chains"], today="2026-08-31")
        upsert_pending([_proposal()], path=workspace["pending"])
        with pytest.raises(ValueError):
            confirm_proposal("solid-state-battery",
                             pending_path=workspace["pending"],
                             base_dir=workspace["chains"], today="2026-08-31")


class TestEvidence:
    def test_attach_and_dedup(self, workspace):
        upsert_pending([_proposal()], path=workspace["pending"])
        items = [{"info_id": "AP9", "source": "report", "title": "赣锋锂业订单饱满",
                  "published_at": "2026-09-01"}]
        added = attach_evidence({"solid-state-battery": items},
                                path=workspace["pending"], date="2026-09-01")
        assert added == 1
        p = load_pending(workspace["pending"])[0]
        assert p["evidence"][0]["info_id"] == "AP9"
        assert p["last_evidence_at"] == "2026-09-01"
        # 同 info_id 不重复追加
        assert attach_evidence({"solid-state-battery": items},
                               path=workspace["pending"], date="2026-09-01") == 0
        assert len(load_pending(workspace["pending"])[0]["evidence"]) == 1

    def test_unknown_chain_ignored(self, workspace):
        upsert_pending([_proposal()], path=workspace["pending"])
        added = attach_evidence(
            {"no-such": [{"info_id": "X", "source": "report",
                          "title": "t", "published_at": "d"}]},
            path=workspace["pending"], date="2026-09-01")
        assert added == 0
        assert "evidence" not in load_pending(workspace["pending"])[0]

    def test_empty_matches_no_write(self, workspace):
        assert attach_evidence({}, path=workspace["pending"],
                               date="2026-09-01") == 0
        assert not workspace["pending"].exists()


class TestReject:
    def test_reject_removes(self, workspace):
        upsert_pending([_proposal()], path=workspace["pending"])
        removed = reject_proposal("solid-state-battery",
                                  pending_path=workspace["pending"])
        assert removed["chain_id"] == "solid-state-battery"
        assert load_pending(workspace["pending"]) == []

    def test_reject_unknown_raises(self, workspace):
        with pytest.raises(ValueError):
            reject_proposal("no-such-chain", pending_path=workspace["pending"])
