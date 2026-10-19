"""板块量价硬护栏测试（board_context.forward_blocked）。

背景（2026-10-20）：chain_tracker 的状态机测试因读取本机真实板块缓存而在
PCB 回撤 30.8% 时集体失败，说明该护栏此前**没有任何单测**。此处补齐，
并把它的输入（board_metrics）全部 mock，保证结果不随行情漂移。
"""
import pytest

import investment_engine.chain_tracker.board_context as bc


def _metrics(drawdown: float) -> dict:
    return {
        "board": "PCB概念",
        "board_type": "concept",
        "proxy_strength": "exact",
        "proxy_note": "",
        "as_of": "2026-10-20",
        "drawdown_from_120d_high_pct": drawdown,
        "change_20d_pct": -12.0,
        "volume_ratio_5_60": 0.8,
        "vs_ma60_pct": -9.0,
    }


class TestForwardBlocked:
    @pytest.mark.parametrize("stage", ["阶段1-启动期", "阶段2-加速期"])
    def test_deep_drawdown_blocks_forward_in_early_stages(self, monkeypatch, stage):
        monkeypatch.setattr(bc, "board_metrics", lambda _cid: _metrics(-30.8))
        blocked, reason = bc.forward_blocked("ai-pcb-ccl", stage)
        assert blocked is True
        assert "-30.8%" in reason
        assert "禁止forward" in reason

    @pytest.mark.parametrize("stage", ["阶段3-分歧期", "阶段4-见顶期", "阶段5-退潮期"])
    def test_late_stages_never_blocked(self, monkeypatch, stage):
        monkeypatch.setattr(bc, "board_metrics", lambda _cid: _metrics(-45.0))
        blocked, reason = bc.forward_blocked("ai-pcb-ccl", stage)
        assert blocked is False
        assert reason == ""

    @pytest.mark.parametrize("drawdown", [-30.0, -12.5, 0.0, 8.0])
    def test_shallow_drawdown_not_blocked(self, monkeypatch, drawdown):
        """阈值是 -30.0（含边界）：-30.0 仍触发，-29.9 不触发。"""
        monkeypatch.setattr(bc, "board_metrics", lambda _cid: _metrics(drawdown))
        blocked, _ = bc.forward_blocked("ai-pcb-ccl", "阶段2-加速期")
        assert blocked is (drawdown <= bc.FORWARD_BLOCK_DRAWDOWN_PCT)

    def test_threshold_boundary_just_above(self, monkeypatch):
        monkeypatch.setattr(bc, "board_metrics", lambda _cid: _metrics(-29.9))
        blocked, _ = bc.forward_blocked("ai-pcb-ccl", "阶段2-加速期")
        assert blocked is False

    def test_missing_board_data_fails_open(self, monkeypatch):
        """无映射/无缓存时放行——护栏宁可漏不可错，但没数据不能凭空拦。"""
        monkeypatch.setattr(bc, "board_metrics", lambda _cid: None)
        blocked, reason = bc.forward_blocked("unknown-chain", "阶段2-加速期")
        assert blocked is False
        assert reason == ""

    def test_unmapped_chain_in_real_config_is_not_blocked(self):
        """真实映射表里不存在的 chain_id 不应误拦（不 mock，走真实映射）。"""
        blocked, _ = bc.forward_blocked("__no_such_chain__", "阶段2-加速期")
        assert blocked is False
