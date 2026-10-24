"""影子双轨完整性报告测试。"""
import json
import tempfile
from pathlib import Path

from investment_engine.shadow.status import collect_status, render_status


class TestCollectStatus:
    def setup_method(self):
        self.pred_dir = Path(tempfile.mkdtemp(prefix="sp_"))
        self.attr_dir = Path(tempfile.mkdtemp(prefix="sa_"))
        self.prop_dir = Path(tempfile.mkdtemp(prefix="spr_"))

    def teardown_method(self):
        import shutil
        for d in (self.pred_dir, self.attr_dir, self.prop_dir):
            shutil.rmtree(d, ignore_errors=True)

    def _pred(self, day, stage_hit=True, status="scored"):
        rec = {"date": day, "result": {"market_stage": "震荡"},
               "stage_hit": stage_hit, "due_scores": {}, "status": status}
        (self.pred_dir / f"{day}.json").write_text(json.dumps(rec), encoding="utf-8")

    def test_calendar_and_counts(self):
        self._pred("2026-08-03", stage_hit=True)
        self._pred("2026-08-04", stage_hit=False)
        (self.attr_dir / "2026-08-04.json").write_text(
            json.dumps({"date": "2026-08-04", "triggers": ["stage_miss"], "types": ["数据缺"]}),
            encoding="utf-8")
        (self.prop_dir / "2026-08-04-data-channel-x.md").write_text(
            "---\nstatus: open\n---\n", encoding="utf-8")
        s = collect_status(pred_dir=self.pred_dir, attr_dir=self.attr_dir,
                           proposal_dir=self.prop_dir)
        assert s["days_total"] == 2
        assert s["days_complete"] == 2  # 判对日无需归因；判错日已有归因
        assert s["proposals"]["open"] == 1

    def test_miss_without_attribution_is_incomplete(self):
        self._pred("2026-08-04", stage_hit=False)
        s = collect_status(pred_dir=self.pred_dir, attr_dir=self.attr_dir,
                           proposal_dir=self.prop_dir)
        assert s["days_complete"] == 0

    def test_render_contains_sections(self):
        self._pred("2026-08-03")
        s = collect_status(pred_dir=self.pred_dir, attr_dir=self.attr_dir,
                           proposal_dir=self.prop_dir)
        text = render_status(s)
        assert "影子双轨" in text and "提案" in text

    def test_frontmatter_only_status_and_yaml_included(self):
        # 正文代码块里的 status: 行不得计入；yaml 提案纳入统计
        (self.prop_dir / "2026-08-30-pipeline.md").write_text(
            "---\nstatus: open\ndate: 2026-08-30\n---\n"
            "```yaml\n示例:\n  status: active\n```\n", encoding="utf-8")
        (self.prop_dir / "20261020-nomination.yaml").write_text(
            "---\nstatus: pending-review\n---\n", encoding="utf-8")
        s = collect_status(pred_dir=self.pred_dir, attr_dir=self.attr_dir,
                           proposal_dir=self.prop_dir)
        assert s["proposals"]["open"] == 1
        assert s["proposals"]["pending-review"] == 1
        assert "active" not in [st for st in s["proposals"] if st != "open_files"]

    def test_render_resolved_bucket_counts_history_words(self):
        for i, st in enumerate(("applied", "merged", "implemented", "done")):
            (self.prop_dir / f"2026-08-1{i}-{st}.md").write_text(
                f"---\nstatus: {st}\n---\n", encoding="utf-8")
        s = collect_status(pred_dir=self.pred_dir, attr_dir=self.attr_dir,
                           proposal_dir=self.prop_dir)
        text = render_status(s)
        assert "已解决 4" in text
