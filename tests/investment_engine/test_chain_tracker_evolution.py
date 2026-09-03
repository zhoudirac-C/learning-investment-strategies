"""产业链逻辑演化提案测试（M0-Chain 演化能力）。

覆盖：logic_update 解析校验、pending 去重合并、6 类 change_type 的应用合并、
confirm/reject 人工确认流。全部离线，不调 LLM、不触网。
"""
import json
import tempfile
from pathlib import Path

import pytest

from investment_engine.chain_tracker.evolution import (
    CHANGE_TYPES, apply_evolution, append_evolution_audit, build_proposal,
    confirm_evolution, load_pending, parse_logic_update, reject_evolution,
    upsert_pending,
)
from investment_engine.industry_chain.schema import validate_chain
from investment_engine.industry_chain.store import load_chain, save_chain


DATE = "2026-08-31"


def _chain() -> dict:
    """schema 合法的链 fixture（对齐 test_chain_tracker_core 的 _chain）。"""
    return {
        "chain_id": "ai-pcb-ccl",
        "name": "AI PCB/CCL 产业链",
        "thesis": "AI服务器代际升级 → PCB层数提升 → CCL升级 → 上游材料涨价",
        "last_verified": "2026-08-30",
        "segments": [
            {"id": "seg-upstream", "name": "上游材料",
             "materials": ["铜箔(HVLP4)", "玻璃布(Q-Glass)", "树脂"]},
            {"id": "seg-midstream", "name": "中游CCL", "materials": ["覆铜板(CCL)"]},
        ],
        "mappings": [
            {"code": "600183", "name": "生益科技", "segment": "seg-midstream",
             "relation": "CCL龙头", "elasticity": "core"},
        ],
        "current_stage": "阶段2-加速期",
        "stage_confidence": "高",
        "stage_evidence": "FR8价格260-270元/张",
        "timing": {"current_recommendation": "中游CCL（生益科技）",
                   "next_trigger": "Rubin认证通过", "risk": "上游涨价见顶"},
        "tracking_metrics": [
            {"metric": "FR8价格", "current": "260-270元/张",
             "signal_direction": "突破300=加强/跌破200=削弱"},
        ],
        "falsification": ["FR8价格连续2周回落"],
        "chain_relations": [
            {"target": "ai-server", "relation": "下游需求来源",
             "note": "AI服务器代际升级驱动"},
        ],
    }


def _result(logic_update, verdict: str = "strengthening") -> dict:
    return {"verdict": verdict, "summary": "测试结论",
            "logic_update": logic_update}


def _lu(change_type: str, detail: dict, **over) -> dict:
    base = {"change_type": change_type, "summary": "测试提案",
            "detail": detail, "rationale": "某研报给出结构性增量",
            "confidence": "中"}
    base.update(over)
    return base


class TestParseLogicUpdate:
    def test_all_change_types_accepted(self):
        details = {
            "refine_segment": {"segment_id": "seg-upstream",
                               "add_materials": ["硅微粉"]},
            "add_node": {"metric": {"metric": "玻璃布Q-Glass供给",
                                    "current": "Nittobo主导",
                                    "signal_direction": "大陆切入=加强"}},
            "focus_shift": {"to_segment": "seg-downstream",
                            "recommendation": "转向下游PCB"},
            "update_thesis": {"new_thesis": "新逻辑"},
            "update_falsification": {"add": ["下游砍单"]},
            "add_relation": {"target": "ai-power", "relation": "二级传导"},
        }
        assert set(details) == set(CHANGE_TYPES)
        for ct, detail in details.items():
            p = parse_logic_update(_result(_lu(ct, detail)))
            assert p is not None, ct
            assert p["change_type"] == ct
            assert p["detail"] == detail

    def test_add_node_accepts_stock_only(self):
        p = parse_logic_update(_result(_lu(
            "add_node",
            {"stock": {"code": "000960", "name": "中钨高新",
                       "segment": "seg-upstream", "relation": "钻针"}})))
        assert p is not None

    def test_missing_or_null_returns_none(self):
        assert parse_logic_update({"verdict": "confirmed"}) is None
        assert parse_logic_update(_result(None)) is None

    def test_irrelevant_verdict_drops_proposal(self):
        r = _result(_lu("update_thesis", {"new_thesis": "x"}),
                    verdict="irrelevant")
        assert parse_logic_update(r) is None

    def test_invalid_change_type(self):
        assert parse_logic_update(_result(
            _lu("rewrite_everything", {"new_thesis": "x"}))) is None

    def test_detail_not_dict(self):
        assert parse_logic_update(_result(_lu("update_thesis", "新逻辑"))) is None

    def test_empty_summary(self):
        assert parse_logic_update(_result(_lu(
            "update_thesis", {"new_thesis": "x"}, summary=" "))) is None

    @pytest.mark.parametrize("ct,detail", [
        ("refine_segment", {"add_materials": ["硅微粉"]}),           # 缺 segment_id
        ("add_node", {"note": "什么都没有"}),                          # metric/stock 皆无
        ("focus_shift", {"recommendation": "转下游"}),                 # 缺 to_segment
        ("update_thesis", {"thesis": "字段名不对"}),                   # 缺 new_thesis
        ("update_falsification", {"add": []}),                         # add 空
        ("add_relation", {"target": "ai-power"}),                      # 缺 relation
    ])
    def test_missing_required_detail_fields(self, ct, detail):
        assert parse_logic_update(_result(_lu(ct, detail))) is None

    def test_confidence_normalized(self):
        p = parse_logic_update(_result(_lu(
            "update_thesis", {"new_thesis": "x"}, confidence="爆表")))
        assert p["confidence"] == "中"


class TestBuildProposal:
    def test_identity_fields(self):
        items = [{"info_id": "AP1", "title": "玻璃布深度", "source": "report"}]
        p = build_proposal("ai-pcb-ccl", _result(_lu(
            "add_node", {"metric": {"metric": "玻璃布Q-Glass供给"}})),
            items=items, date=DATE)
        assert p["chain_id"] == "ai-pcb-ccl"
        assert p["target_key"] == "玻璃布Q-Glass供给"
        assert p["proposal_id"] == "ai-pcb-ccl:add_node:玻璃布Q-Glass供给"
        assert p["proposed_at"] == DATE  # 对齐信息日期（回放语义）
        assert p["source_info_ids"] == ["AP1"]
        assert p["evidence"] == [{"date": DATE, "info_id": "AP1",
                                  "title": "玻璃布深度", "source": "report"}]

    def test_add_node_stock_identity_fallback(self):
        p = build_proposal("ai-pcb-ccl", _result(_lu(
            "add_node", {"stock": {"name": "中钨高新", "code": "000960"}})),
            items=[], date=DATE)
        assert p["target_key"] == "000960"
        p2 = build_proposal("ai-pcb-ccl", _result(_lu(
            "add_node", {"stock": {"name": "中钨高新"}})),
            items=[], date=DATE)
        assert p2["target_key"] == "中钨高新"

    def test_invalid_returns_none(self):
        assert build_proposal("c", _result(None), items=[], date=DATE) is None


@pytest.fixture()
def workspace():
    d = Path(tempfile.mkdtemp(prefix="chain_evo_test_"))
    return {"dir": d, "pending": d / "evolution_pending.json",
            "chains": d / "chains", "tracking": d / "tracking"}


class TestUpsertPending:
    def test_new_proposal_added(self, workspace):
        p = build_proposal("ai-pcb-ccl", _result(_lu(
            "add_node", {"metric": {"metric": "玻璃布Q-Glass供给"}})),
            items=[{"info_id": "AP1", "title": "t", "source": "report"}],
            date=DATE)
        added = upsert_pending([p], path=workspace["pending"])
        assert [x["proposal_id"] for x in added] == [p["proposal_id"]]
        loaded = load_pending(workspace["pending"])
        assert len(loaded) == 1
        assert loaded[0]["proposed_at"]

    def test_duplicate_merges_evidence_not_new_entry(self, workspace):
        p1 = build_proposal("ai-pcb-ccl", _result(_lu(
            "add_node", {"metric": {"metric": "玻璃布Q-Glass供给"}})),
            items=[{"info_id": "AP1", "title": "t1", "source": "report"}],
            date="2026-08-30")
        p2 = build_proposal("ai-pcb-ccl", _result(_lu(
            "add_node", {"metric": {"metric": "玻璃布Q-Glass供给",
                                    "current": "更新值"}})),
            items=[{"info_id": "AP2", "title": "t2", "source": "report"},
                   {"info_id": "AP1", "title": "t1", "source": "report"}],
            date=DATE)
        upsert_pending([p1], path=workspace["pending"])
        added = upsert_pending([p2], path=workspace["pending"])
        assert added == []
        loaded = load_pending(workspace["pending"])
        assert len(loaded) == 1
        ev = loaded[0]["evidence"]
        assert [e["info_id"] for e in ev] == ["AP1", "AP2"]  # 按 info_id 去重
        assert set(loaded[0]["source_info_ids"]) == {"AP1", "AP2"}
        assert loaded[0]["last_evidence_at"] == DATE

    def test_different_target_key_coexist(self, workspace):
        p1 = build_proposal("ai-pcb-ccl", _result(_lu(
            "add_node", {"metric": {"metric": "玻璃布Q-Glass供给"}})),
            items=[], date=DATE)
        p2 = build_proposal("ai-pcb-ccl", _result(_lu(
            "add_node", {"metric": {"metric": "钻针供给"}})),
            items=[], date=DATE)
        added = upsert_pending([p1, p2], path=workspace["pending"])
        assert len(added) == 2

    def test_load_missing_returns_empty(self, workspace):
        assert load_pending(workspace["pending"]) == []


class TestDailyAudit:
    def test_evolution_prefixed_file(self, workspace):
        p = build_proposal("ai-pcb-ccl", _result(_lu(
            "update_thesis", {"new_thesis": "x"})), items=[], date=DATE)
        out = append_evolution_audit(workspace["tracking"], DATE, [p],
                                     tick_label="10:30")
        assert out is not None
        assert out.name == f"evolution_{DATE}.json"
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data[0]["proposal_id"] == p["proposal_id"]

    def test_empty_silent(self, workspace):
        assert append_evolution_audit(workspace["tracking"], DATE, [],
                                      tick_label="10:30") is None


class TestApplyEvolution:
    def test_add_node_metric_dedupe(self):
        chain = _chain()
        p = parse_logic_update(_result(_lu(
            "add_node",
            {"metric": {"metric": "玻璃布Q-Glass供给", "current": "Nittobo主导",
                        "signal_direction": "大陆切入=加强"}})))
        change = apply_evolution(chain, p, today=DATE)
        metrics = [m["metric"] for m in chain["tracking_metrics"]]
        assert metrics == ["FR8价格", "玻璃布Q-Glass供给"]
        # 幂等：同 metric 再 apply 不重复
        apply_evolution(chain, p, today=DATE)
        assert [m["metric"] for m in chain["tracking_metrics"]] == metrics
        assert change["applied"]
        validate_chain(chain)

    def test_add_node_stock_append_and_skip(self):
        chain = _chain()
        p = parse_logic_update(_result(_lu("add_node", {"stock": {
            "code": "000960", "name": "中钨高新", "segment": "seg-upstream",
            "relation": "PCB钻针龙头"}})))
        apply_evolution(chain, p, today=DATE)
        assert chain["mappings"][-1]["code"] == "000960"
        assert chain["mappings"][-1]["elasticity"] == "concept"  # 未经验证保守标
        # 坏代码跳过
        p_bad = parse_logic_update(_result(_lu("add_node", {"stock": {
            "code": "abc", "name": "坏代码", "segment": "seg-upstream",
            "relation": "x"}})))
        change = apply_evolution(chain, p_bad, today=DATE)
        assert len(chain["mappings"]) == 2
        assert change["skipped"]
        # 未知 segment 跳过（防 schema 炸）
        p_seg = parse_logic_update(_result(_lu("add_node", {"stock": {
            "code": "000001", "name": "x", "segment": "seg-ghost",
            "relation": "x"}})))
        apply_evolution(chain, p_seg, today=DATE)
        assert len(chain["mappings"]) == 2
        validate_chain(chain)

    def test_refine_segment_existing_and_new(self):
        chain = _chain()
        p = parse_logic_update(_result(_lu("refine_segment", {
            "segment_id": "seg-upstream",
            "add_materials": ["硅微粉", "树脂"]})))  # 树脂已存在 → 去重
        apply_evolution(chain, p, today=DATE)
        assert chain["segments"][0]["materials"] == [
            "铜箔(HVLP4)", "玻璃布(Q-Glass)", "树脂", "硅微粉"]
        # 新环节
        p_new = parse_logic_update(_result(_lu("refine_segment", {
            "segment_id": "seg-equipment", "segment_name": "设备",
            "add_materials": ["钻孔机"]})))
        apply_evolution(chain, p_new, today=DATE)
        assert chain["segments"][-1] == {
            "id": "seg-equipment", "name": "设备", "materials": ["钻孔机"]}
        validate_chain(chain)

    def test_focus_shift_updates_timing_only_given_fields(self):
        chain = _chain()
        p = parse_logic_update(_result(_lu("focus_shift", {
            "from_segment": "seg-midstream", "to_segment": "seg-downstream",
            "recommendation": "下游PCB（沪电/景旺）",
            "next_trigger": "Rubin放量"})))  # risk 未给 → 不动
        apply_evolution(chain, p, today=DATE)
        assert chain["timing"]["current_recommendation"] == "下游PCB（沪电/景旺）"
        assert chain["timing"]["next_trigger"] == "Rubin放量"
        assert chain["timing"]["risk"] == "上游涨价见顶"
        assert "重心" in chain["stage_evidence"]  # 附注留痕
        validate_chain(chain)

    def test_update_thesis_replaces(self):
        chain = _chain()
        p = parse_logic_update(_result(_lu(
            "update_thesis", {"new_thesis": "Rubin Ultra → 材料体系重构"})))
        apply_evolution(chain, p, today=DATE)
        assert chain["thesis"] == "Rubin Ultra → 材料体系重构"
        validate_chain(chain)

    def test_update_falsification_add_remove(self):
        chain = _chain()
        p = parse_logic_update(_result(_lu("update_falsification", {
            "add": ["下游PCB厂砍单", "FR8价格连续2周回落"],  # 后者已存在 → 去重
        })))
        apply_evolution(chain, p, today=DATE)
        assert chain["falsification"] == ["FR8价格连续2周回落", "下游PCB厂砍单"]
        p_rm = parse_logic_update(_result(_lu("update_falsification", {
            "add": ["板块核心标放量滞涨"],
            "remove": ["下游PCB厂砍单"]})))
        apply_evolution(chain, p_rm, today=DATE)
        assert chain["falsification"] == ["FR8价格连续2周回落", "板块核心标放量滞涨"]
        validate_chain(chain)

    def test_add_relation_dedupe(self):
        chain = _chain()
        p = parse_logic_update(_result(_lu("add_relation", {
            "target": "ai-server", "relation": "下游需求来源",  # 已存在 → 去重
            "note": "重复"})))
        apply_evolution(chain, p, today=DATE)
        assert len(chain["chain_relations"]) == 1
        p2 = parse_logic_update(_result(_lu("add_relation", {
            "target": "ai-power", "relation": "二级传导", "note": "算力→电力"})))
        apply_evolution(chain, p2, today=DATE)
        assert chain["chain_relations"][-1]["target"] == "ai-power"
        validate_chain(chain)

    def test_history_appended(self):
        chain = _chain()
        p = parse_logic_update(_result(_lu(
            "update_thesis", {"new_thesis": "x"}, summary="逻辑修正")))
        apply_evolution(chain, p, today=DATE)
        assert chain["history"][-1] == {
            "date": DATE, "stage": "阶段2-加速期",
            "action": "演化:update_thesis 逻辑修正", "result": "待验证"}


class TestConfirmReject:
    def test_confirm_applies_and_removes(self, workspace):
        save_chain(_chain(), base_dir=workspace["chains"])
        p = build_proposal("ai-pcb-ccl", _result(_lu(
            "add_node", {"metric": {"metric": "玻璃布Q-Glass供给",
                                    "current": "Nittobo主导",
                                    "signal_direction": "大陆切入=加强"}})),
            items=[], date=DATE)
        upsert_pending([p], path=workspace["pending"])
        path = confirm_evolution(p["proposal_id"],
                                 pending_path=workspace["pending"],
                                 base_dir=workspace["chains"], today=DATE)
        chain = load_chain("ai-pcb-ccl", base_dir=workspace["chains"])
        assert [m["metric"] for m in chain["tracking_metrics"]] == [
            "FR8价格", "玻璃布Q-Glass供给"]
        assert load_pending(workspace["pending"]) == []
        assert path.name == "chain.yaml"

    def test_confirm_missing_proposal(self, workspace):
        with pytest.raises(ValueError, match="不存在"):
            confirm_evolution("ai-pcb-ccl:add_node:不存在",
                              pending_path=workspace["pending"],
                              base_dir=workspace["chains"])

    def test_confirm_missing_chain(self, workspace):
        p = build_proposal("ghost-chain", _result(_lu(
            "update_thesis", {"new_thesis": "x"})), items=[], date=DATE)
        upsert_pending([p], path=workspace["pending"])
        with pytest.raises(ValueError, match="chain.yaml"):
            confirm_evolution(p["proposal_id"],
                              pending_path=workspace["pending"],
                              base_dir=workspace["chains"])

    def test_reject_removes(self, workspace):
        p = build_proposal("ai-pcb-ccl", _result(_lu(
            "update_thesis", {"new_thesis": "x"})), items=[], date=DATE)
        upsert_pending([p], path=workspace["pending"])
        removed = reject_evolution(p["proposal_id"],
                                   pending_path=workspace["pending"])
        assert removed["proposal_id"] == p["proposal_id"]
        assert load_pending(workspace["pending"]) == []
        with pytest.raises(ValueError, match="不存在"):
            reject_evolution(p["proposal_id"],
                             pending_path=workspace["pending"])
