"""qing 复盘臂评分测试。"""
import json
import tempfile
from pathlib import Path

import pytest

from investment_engine.qing_review import (
    STAGE_MAP, load_summaries, normalize_stage, score_vs_truth,
    shadow_stage_records,
)


class TestNormalizeStage:
    def test_families(self):
        assert normalize_stage("回暖期") == "震荡"
        assert normalize_stage("高位震荡尾期→调整预警") == "震荡"
        assert normalize_stage("退潮期") == "调整"
        assert normalize_stage("磨底期") == "调整"
        assert normalize_stage("调整期/恐慌冰点") == "恐慌"

    def test_excluded_and_unmapped(self):
        assert normalize_stage("未判断") is None
        assert normalize_stage(None) is None
        with pytest.raises(KeyError, match="未映射"):
            normalize_stage("主升浪")

    def test_real_file_labels_all_mapped(self):
        """真实 summary 里出现的每个 stage 标签都必须在映射表中（防新增标签漏评）。"""
        path = Path("config/stock_monitor/daily_review_summary.json")
        if not path.exists():
            pytest.skip("summary 文件不存在")
        summaries = load_summaries(path)
        labels = {(m.get("stage") or "") for m in summaries.values()} - {""}
        assert labels <= set(STAGE_MAP), f"未映射标签: {labels - set(STAGE_MAP)}"


class TestScoreVsTruth:
    def test_smoke(self):
        summaries = {
            "2026-08-01": {"stage": "回暖期"},     # → 震荡
            "2026-08-02": {"stage": "退潮期"},     # → 调整
            "2026-08-03": {"stage": "未判断"},     # 剔除
        }
        truth = {"2026-08-01": "震荡", "2026-08-02": "主升", "2026-08-03": "调整"}
        r = score_vs_truth(summaries, truth)
        assert r["samples"] == 2 and r["hits"] == 1
        assert r["excluded"] == ["2026-08-03"]
        assert r["by_label"]["震荡"]["samples"] == 1

    def test_no_truth_day_skipped(self):
        r = score_vs_truth({"2026-08-01": {"stage": "回暖期"}}, {})
        assert r["samples"] == 0


class TestShadowRecords:
    def test_skips_pre_and_error(self):
        d = Path(tempfile.mkdtemp(prefix="pred_"))
        (d / "2026-08-07.json").write_text(json.dumps({
            "date": "2026-08-07", "result": {"market_stage": "震荡"},
            "stage_hit": True}), encoding="utf-8")
        (d / "2026-08-07-pre.json").write_text(json.dumps({
            "date": "2026-08-07", "result": {"market_stage": "调整"}}), encoding="utf-8")
        (d / "2026-08-08.json").write_text(json.dumps({
            "date": "2026-08-08", "status": "error"}), encoding="utf-8")
        recs = shadow_stage_records(d)
        assert list(recs) == ["2026-08-07"]
        assert recs["2026-08-07"]["stage"] == "震荡"
