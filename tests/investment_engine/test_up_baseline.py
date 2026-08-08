"""vs UP 对照测试。"""
import json
from types import SimpleNamespace

from investment_engine.blindtest.up_baseline import (
    build_comparison, find_up_docs, parse_up_view, pick_sample_days,
)


def _fake_client(payload: str):
    msg = SimpleNamespace(content=payload)
    choice = SimpleNamespace(message=msg)
    completions = SimpleNamespace(create=lambda **kw: SimpleNamespace(choices=[choice]))
    return SimpleNamespace(chat=SimpleNamespace(completions=completions))


class TestPickSampleDays:
    def test_stratified_and_deterministic(self):
        truth = {f"2026-06-{i:02d}": label for i, label in enumerate(
            ["主升"] * 10 + ["震荡"] * 10 + ["调整"] * 5 + ["恐慌"] * 5, start=1)}
        days = pick_sample_days(truth, n=10)
        assert len(days) == 10
        assert days == pick_sample_days(truth, n=10)  # 确定性
        labels = {truth[d] for d in days}
        assert len(labels) >= 3  # 分层覆盖


class TestFindUpDocs:
    def test_match_by_date_token(self, tmp_path):
        (tmp_path / "复盘：26-06-15：缩量.md").write_text("x", encoding="utf-8")
        (tmp_path / "复盘：26-06-16：放量.md").write_text("y", encoding="utf-8")
        docs = find_up_docs("2026-06-15", up_dir=tmp_path)
        assert len(docs) == 1 and "06-15" in docs[0].name

    def test_no_doc_returns_empty(self, tmp_path):
        assert find_up_docs("2026-06-20", up_dir=tmp_path) == []


class TestParseUpView:
    def test_valid(self):
        raw = json.dumps({"stage": "调整", "directions": ["半导体"], "mentioned": True})
        v = parse_up_view(raw)
        assert v["stage"] == "调整" and v["mentioned"] is True

    def test_unmentioned(self):
        raw = json.dumps({"stage": None, "directions": [], "mentioned": False})
        assert parse_up_view(raw)["mentioned"] is False


class TestBuildComparison:
    def test_verdict_classes(self):
        results = [
            {"date": "d1", "ok": True, "result": {"market_stage": "主升", "directions": []}},
            {"date": "d2", "ok": True, "result": {"market_stage": "调整", "directions": []}},
        ]
        truth = {"d1": "主升", "d2": "震荡"}
        up_views = {"d1": {"stage": "主升", "mentioned": True},
                    "d2": {"stage": "主升", "mentioned": True}}
        rows = build_comparison(results, truth, up_views)
        assert rows[0]["verdict"] == "AI对UP对"
        assert rows[1]["verdict"] == "都错"
