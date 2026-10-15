"""双学派输出契约与冲突辩论卡单测（P4）。

设计文档：docs/design/dual-school-architecture.md §5.2 / §5.3
"""

from __future__ import annotations

from pathlib import Path

import pytest

from qing_investment.agent.tools.school_conflicts import (
    UNRESOLVED_STATUSES,
    SchoolConflict,
    load_conflicts,
    load_conflicts_block,
    render_conflicts_block,
    select_relevant,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFLICTS_FILE = REPO_ROOT / "framework" / "school-conflicts.yaml"


class TestConflictsFile:
    def test_file_exists_and_loads(self):
        assert CONFLICTS_FILE.exists(), "framework/school-conflicts.yaml 应存在"
        conflicts = load_conflicts()
        assert len(conflicts) >= 5, "初版应至少 5 条冲突"

    def test_all_have_dual_views(self):
        """每条冲突必须同时有 qing 和 gator 两派视角。"""
        for c in load_conflicts():
            assert "qing" in c.school_views, f"{c.conflict_id} 缺 qing 视角"
            assert "gator" in c.school_views, f"{c.conflict_id} 缺 gator 视角"
            assert c.school_views["qing"].get("view"), f"{c.conflict_id} qing 视角为空"
            assert c.school_views["gator"].get("view"), f"{c.conflict_id} gator 视角为空"

    def test_all_have_cross_exam(self):
        """辩论卡必须有交叉反驳。"""
        for c in load_conflicts():
            assert c.round1_cross_exam.get("qing_critique"), f"{c.conflict_id} 缺对 qing 的反驳"
            assert c.round1_cross_exam.get("gator_critique"), f"{c.conflict_id} 缺对 gator 的反驳"

    def test_unresolved_has_no_resolution(self):
        """未裁决的冲突不得有 resolution（防止 agent 自行裁决）。"""
        for c in load_conflicts():
            if c.is_unresolved:
                assert not c.resolution, f"{c.conflict_id} 未裁决却带了 resolution"

    def test_status_enum_valid(self):
        valid = {"pending_backtest", "backtesting", "resolved", "agreed"}
        for c in load_conflicts():
            assert c.status in valid, f"{c.conflict_id} 状态非法: {c.status}"


class TestRendering:
    def test_render_card_marks_unresolved(self):
        c = SchoolConflict(
            conflict_id="CF-999", question="测试冲突", theme="测试",
            school_views={"qing": {"view": "A"}, "gator": {"view": "B"}},
            status="pending_backtest",
        )
        card = c.render_card()
        assert "双列呈现" in card
        assert "不得自行选边" in card

    def test_render_resolved_shows_resolution(self):
        c = SchoolConflict(
            conflict_id="CF-998", question="已裁决", status="resolved",
            resolution={"conclusion": "回测支持 gator", "date": "2026-10-15"},
        )
        card = c.render_card()
        assert "裁决" in card

    def test_conflicts_block_nonempty(self):
        block = render_conflicts_block(load_conflicts())
        assert "学派冲突" in block
        for c in load_conflicts():
            assert c.conflict_id in block

    def test_load_block_unresolved_only(self):
        block = load_conflicts_block(unresolved_only=True)
        # 全部为 pending → 应包含全部 cf
        assert "CF-001" in block


class TestSelection:
    def test_select_by_theme(self):
        allc = load_conflicts()
        sel = select_relevant(allc, themes=["底部判定"])
        assert len(sel) >= 2
        assert all(c.theme == "底部判定" for c in sel)

    def test_select_by_keyword(self):
        allc = load_conflicts()
        sel = select_relevant(allc, keywords=["护盘"])
        assert any("护盘" in c.question for c in sel)

    def test_select_no_filter_returns_all(self):
        allc = load_conflicts()
        assert len(select_relevant(allc)) == len(allc)

    def test_missing_file_returns_empty(self, tmp_path):
        assert load_conflicts(tmp_path / "nope.yaml") == []


class TestDualSchoolContract:
    def test_prompt_file_exists(self):
        p = REPO_ROOT / "src/qing_investment/agent/prompts/system/dual_school_output.txt"
        assert p.exists()
        text = p.read_text(encoding="utf-8")
        # 六段式结构 + 关键纪律
        for seg in ["共识区", "青枫浦上Q", "鳄鱼派", "矛盾与裁决", "操作建议", "涌现发现"]:
            assert seg in text, f"契约缺段落: {seg}"
        assert "不得自行选边" in text or "严禁自行选边" in text

    def test_contract_gating_no_gator(self):
        """context 无 gator 内容 → 不注入契约（保持既有输出形态）。"""
        from qing_investment.agent.graph.nodes import _load_dual_school_contract

        assert _load_dual_school_contract({}) == ""
        assert _load_dual_school_contract({"reasoning_patterns": [{"school": "qing"}]}) == ""

    def test_contract_gating_with_gator(self):
        from qing_investment.agent.graph.nodes import _load_dual_school_contract

        block = _load_dual_school_contract(
            {"gator_rules_snapshot": {"available": True}}
        )
        assert "双学派输出契约" in block

    def test_contract_gating_with_conflicts(self):
        from qing_investment.agent.graph.nodes import _load_dual_school_contract

        block = _load_dual_school_contract({"school_conflicts": "【CF-001】..."})
        assert "双学派输出契约" in block
