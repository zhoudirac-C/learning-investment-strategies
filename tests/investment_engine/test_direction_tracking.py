"""方向层 T+5 周度跟踪聚合测试（合成 prediction 文件）。"""
import json
import tempfile
from pathlib import Path

import pytest

from investment_engine.shadow.tracking import build_tracking, render_markdown


def _detail(day, direction_id, hit, dir_ret=0.05, bench_ret=0.01):
    return {"date": day, "direction_id": direction_id,
            "dir_ret": dir_ret, "bench_ret": bench_ret, "hit": hit}


def _scored(day, details, stock_hits=0, stock_samples=0):
    return {"date": day, "status": "scored",
            "due_scores": {
                "directions": {"samples": len(details),
                               "hits": sum(1 for d in details if d["hit"]),
                               "hit_rate": None},
                "stocks": {"samples": stock_samples, "hits": stock_hits, "hit_rate": None},
                "direction_details": details}}


@pytest.fixture
def pred_dir():
    d = Path(tempfile.mkdtemp(prefix="tracking_"))
    # 盘前轨：2 方向 1 命中
    (d / "2026-08-21-pre.json").write_text(json.dumps(_scored(
        "2026-08-21", [_detail("2026-08-21", "医药", False, -0.027, -0.002),
                       _detail("2026-08-21", "通信设备", True, 0.048, -0.002)],
        stock_hits=0, stock_samples=1), ensure_ascii=False), encoding="utf-8")
    # 收盘轨：1 方向 1 命中
    (d / "2026-08-21.json").write_text(json.dumps(_scored(
        "2026-08-21", [_detail("2026-08-21", "贵金属", True)],
        stock_hits=1, stock_samples=2), ensure_ascii=False), encoding="utf-8")
    # 未到期：应被排除
    (d / "2026-08-24.json").write_text(json.dumps(
        {"date": "2026-08-24", "status": "pending_maturity", "due_scores": None},
        ensure_ascii=False), encoding="utf-8")
    # 坏 JSON：应跳过
    (d / "2026-08-25.json").write_text("{broken", encoding="utf-8")
    yield d


class TestBuildTracking:
    def test_cumulative_totals(self, pred_dir):
        t = build_tracking(pred_dir=pred_dir)
        assert t["totals"]["dir_hits"] == 2
        assert t["totals"]["dir_samples"] == 3
        assert t["totals"]["dir_hit_rate"] == pytest.approx(2 / 3)
        assert t["totals"]["stock_hits"] == 1
        assert t["totals"]["stock_samples"] == 3

    def test_weekly_and_track_split(self, pred_dir):
        t = build_tracking(pred_dir=pred_dir)
        # 2026-08-21 属 ISO W34；两轨分开统计
        w34_pre = t["weeks"][("2026-W34", "pre")]
        assert (w34_pre["dir_hits"], w34_pre["dir_samples"]) == (1, 2)
        w34_close = t["weeks"][("2026-W34", "close")]
        assert (w34_close["dir_hits"], w34_close["dir_samples"]) == (1, 1)
        # 未到期记录不进入任何周
        assert all(k[0] != "2026-W35" for k in t["weeks"])

    def test_per_direction(self, pred_dir):
        t = build_tracking(pred_dir=pred_dir)
        dirs = t["directions"]
        assert dirs["医药"]["hits"] == 0 and dirs["医药"]["samples"] == 1
        assert dirs["通信设备"]["hit_rate"] == 1.0
        # 平均超额 = dir_ret - bench_ret
        assert dirs["医药"]["avg_excess"] == pytest.approx(-0.025)

    def test_empty_dir(self, tmp_path):
        t = build_tracking(pred_dir=tmp_path / "nonexist")
        assert t["totals"]["dir_samples"] == 0
        assert t["totals"]["dir_hit_rate"] is None


class TestRenderMarkdown:
    def test_report_content(self, pred_dir):
        t = build_tracking(pred_dir=pred_dir)
        md = render_markdown(t, today="2026-09-03")
        assert "66.7%" in md  # 2/3
        assert "毕业线" in md and "60.0%" in md
        assert "2026-W34" in md
        assert "医药" in md and "通信设备" in md
        # 方向表按命中率升序：医药（0%）排在通信设备（100%）前
        assert md.index("医药") < md.index("通信设备")
