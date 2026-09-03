"""增量报告输出测试（T14）。"""
import json
import tempfile
from pathlib import Path

from investment_engine.chain_tracker.report import (
    append_daily_report, append_tick_log, render_changes_section,
)


def _change() -> dict:
    return {
        "chain_id": "ai-pcb-ccl", "chain_name": "AI PCB/CCL 产业链",
        "old_stage": "阶段2-加速期", "new_stage": "阶段3-分歧期",
        "stage_change": "forward", "verdict": "strengthening",
        "confidence": "高", "action": "转向下游PCB",
        "timing": "下游PCB（沪电/景旺）",
        "summary": "Rubin认证通过",
        "info_ids": ["AP1", "AN2"],
    }


class TestRenderSection:
    def test_renders_markdown_with_key_fields(self):
        md = render_changes_section([_change()], tick_label="10:30")
        assert "10:30" in md
        assert "AI PCB/CCL 产业链" in md
        assert "阶段2-加速期" in md and "阶段3-分歧期" in md
        assert "转向下游PCB" in md
        assert "Rubin认证通过" in md


class TestAppendDailyReport:
    def setup_method(self):
        self.dir = Path(tempfile.mkdtemp(prefix="chain_report_test_"))

    def test_creates_file_with_header_then_appends(self):
        path = self.dir / "daily_report_2026-08-31.md"
        out = append_daily_report(path, [_change()], tick_label="10:00")
        assert out == path
        text1 = path.read_text(encoding="utf-8")
        assert "产业链跟踪日报" in text1 and "2026-08-31" in text1
        append_daily_report(path, [_change()], tick_label="10:30")
        text2 = path.read_text(encoding="utf-8")
        assert text2.count("10:00") == 1 and text2.count("10:30") == 1

    def test_empty_changes_silent(self):
        path = self.dir / "daily_report_2026-08-31.md"
        out = append_daily_report(path, [], tick_label="10:00")
        assert out is None
        assert not path.exists()

    def test_evolution_only_still_writes(self):
        """无阶段变化但有演化提案 → 日报写演化附节（不静默）。"""
        path = self.dir / "daily_report_2026-08-31.md"
        proposal = {"chain_id": "ai-pcb-ccl", "chain_name": "AI PCB/CCL 产业链",
                    "change_type": "add_node", "summary": "新增玻璃布供给节点",
                    "confidence": "中", "rationale": "深度报告给出国产切入证据",
                    "proposal_id": "ai-pcb-ccl:add_node:玻璃布Q-Glass供给"}
        out = append_daily_report(path, [], tick_label="10:30",
                                  evolution=[proposal])
        assert out == path
        text = path.read_text(encoding="utf-8")
        assert "演化提案" in text
        assert "ai-pcb-ccl:add_node:玻璃布Q-Glass供给" in text
        assert "新增玻璃布供给节点" in text

    def test_evolution_and_changes_both_rendered(self):
        path = self.dir / "daily_report_2026-08-31.md"
        proposal = {"chain_id": "ai-pcb-ccl", "change_type": "focus_shift",
                    "summary": "重心转向下游", "confidence": "中",
                    "rationale": "Rubin放量", "proposal_id": "ai-pcb-ccl:focus_shift:seg-downstream"}
        append_daily_report(path, [_change()], tick_label="10:30",
                            evolution=[proposal])
        text = path.read_text(encoding="utf-8")
        assert "阶段3-分歧期" in text and "演化提案" in text


class TestTickLog:
    def setup_method(self):
        self.dir = Path(tempfile.mkdtemp(prefix="chain_ticklog_test_"))

    def test_appends_jsonl(self):
        path = self.dir / "ticks.jsonl"
        append_tick_log(path, {"ts": "t1", "new_items": 3})
        append_tick_log(path, {"ts": "t2", "new_items": 0})
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["new_items"] == 3
