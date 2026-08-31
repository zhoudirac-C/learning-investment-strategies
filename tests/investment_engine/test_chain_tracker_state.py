"""chain.yaml 状态更新测试（T13）。"""
import pytest

from investment_engine.chain_tracker.state import apply_chain_update


def _chain(stage: str = "阶段2-加速期") -> dict:
    return {
        "chain_id": "ai-pcb-ccl",
        "name": "AI PCB/CCL 产业链",
        "current_stage": stage,
        "stage_confidence": "高",
        "stage_evidence": "FR8价格260-270元/张",
        "timing": {"current_recommendation": "中游CCL",
                   "next_trigger": "Rubin认证通过", "risk": "上游涨价见顶"},
    }


def _result(stage_change="unchanged", new_stage="阶段2-加速期", **kw):
    base = {
        "step1_verification": {"verified": True, "confidence": "高"},
        "step5_recommendation": {"stage_change": stage_change,
                                 "new_stage": new_stage,
                                 "timing": "下游PCB", "action": "转向沪电股份"},
        "verdict": "strengthening",
        "summary": "Rubin认证通过，业绩开始兑现",
    }
    base.update(kw)
    return base


class TestApplyChainUpdate:
    def test_unchanged_returns_none_and_no_mutation(self):
        chain = _chain()
        change = apply_chain_update(chain, _result(), today="2026-08-31")
        assert change is None
        assert chain["current_stage"] == "阶段2-加速期"
        assert "history" not in chain

    def test_forward_updates_stage_timing_history(self):
        chain = _chain()
        change = apply_chain_update(
            chain, _result("forward", "阶段3-分歧期"), today="2026-08-31")
        assert change is not None
        assert chain["current_stage"] == "阶段3-分歧期"
        assert chain["timing"]["current_recommendation"] == "下游PCB"
        # 人工域字段不动
        assert chain["timing"]["next_trigger"] == "Rubin认证通过"
        assert chain["history"][-1] == {
            "date": "2026-08-31", "stage": "阶段3-分歧期",
            "action": "转向沪电股份", "result": "待验证"}
        assert change["old_stage"] == "阶段2-加速期"
        assert change["new_stage"] == "阶段3-分歧期"

    def test_backward_moves_down(self):
        chain = _chain("阶段2-加速期")
        apply_chain_update(chain, _result("backward", "阶段1-启动期"),
                           today="2026-08-31")
        assert chain["current_stage"] == "阶段1-启动期"

    def test_multi_step_jump_clamped_to_adjacent(self):
        chain = _chain("阶段1-启动期")
        change = apply_chain_update(
            chain, _result("forward", "阶段4-见顶期"), today="2026-08-31")
        assert chain["current_stage"] == "阶段2-加速期"  # 只走一格
        assert change["clamped"] is True
        assert change["llm_new_stage"] == "阶段4-见顶期"

    def test_boundary_clamp_at_bottom(self):
        chain = _chain("阶段0-观察")
        change = apply_chain_update(
            chain, _result("backward", "阶段0-观察"), today="2026-08-31")
        assert change is None  # 已在底部，无变化

    def test_confidence_updated_from_step1(self):
        chain = _chain()
        apply_chain_update(
            chain,
            _result("forward", "阶段3-分歧期",
                    step1_verification={"verified": True, "confidence": "中"}),
            today="2026-08-31")
        assert chain["stage_confidence"] == "中"

    def test_missing_timing_dict_created(self):
        chain = _chain()
        del chain["timing"]
        apply_chain_update(chain, _result("forward", "阶段3-分歧期"),
                           today="2026-08-31")
        assert chain["timing"]["current_recommendation"] == "下游PCB"

    def test_stage_evidence_records_summary(self):
        chain = _chain()
        apply_chain_update(chain, _result("forward", "阶段3-分歧期"),
                           today="2026-08-31")
        assert "Rubin认证通过" in chain["stage_evidence"]
        assert "2026-08-31" in chain["stage_evidence"]
