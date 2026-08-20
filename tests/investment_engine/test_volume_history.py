"""volume_history 测试（TDX mock，不触网）。

提案：framework/proposals/2026-08-21-pattern-patch-blind-up-comparison.md（模式三配套）
口径校验：TDX 上证指数+深证成指日K amount 合计 ≡ KPL daban.qscln
（2026-08-19：25110.4 亿；2026-08-20：20793.6 亿，逐位一致）。
"""
import json
import tempfile
from pathlib import Path

from investment_engine.volume_history import (
    compute_volume_history, load_volume_history, save_volume_history,
)
from investment_engine.blindtest.dataset import _load_volume_series


def _idx_rows(rows):
    return [{"date": d, "open": 1, "close": 1, "high": 1, "low": 1,
             "volume": 1, "amount": a} for d, a in rows]


class _FakeTdx:
    def get_index_kline(self, code, category="day", count=70):
        if code == "sh000001":
            return _idx_rows([("2026-08-19", 1.2181e12), ("2026-08-20", 1.0186e12)])
        if code == "sz399001":
            return _idx_rows([("2026-08-19", 1.2929e12), ("2026-08-20", 1.0608e12)])
        return []


class TestCompute:
    def test_sum_and_convert(self):
        data = compute_volume_history(tdx=_FakeTdx())
        assert [p["date"] for p in data["points"]] == ["2026-08-19", "2026-08-20"]
        assert data["points"][0]["成交额_亿"] == 25110.0   # (1.2181+1.2929)e12/1e8
        assert data["points"][1]["成交额_亿"] == 20794.0
        assert "fetched_at" in data and "TDX" in data["source"]

    def test_missing_counterpart_day_skipped(self):
        class _Half(_FakeTdx):
            def get_index_kline(self, code, category="day", count=70):
                if code == "sz399001":
                    return _idx_rows([("2026-08-19", 1.2929e12)])  # 缺 08-20
                return super().get_index_kline(code, category, count)
        data = compute_volume_history(tdx=_Half())
        assert [p["date"] for p in data["points"]] == ["2026-08-19"]

    def test_total_failure_returns_none(self):
        class _Dead:
            def get_index_kline(self, code, category="day", count=70):
                return []
        assert compute_volume_history(tdx=_Dead()) is None


class TestSaveLoad:
    def test_merge_dedupe_and_roundtrip(self, tmp_path):
        path = tmp_path / "vh.json"
        save_volume_history({"points": [{"date": "2026-08-19", "成交额_亿": 25110.4}],
                             "source": "s", "fetched_at": "t"}, path)
        # 重灌：重叠日期新值覆盖，乱序写入后按日期排序
        save_volume_history({"points": [{"date": "2026-08-20", "成交额_亿": 20793.6},
                                        {"date": "2026-08-19", "成交额_亿": 25110.0}],
                             "source": "s", "fetched_at": "t2"}, path)
        d = load_volume_history(path)
        assert [(p["date"], p["成交额_亿"]) for p in d["points"]] == [
            ("2026-08-19", 25110.0), ("2026-08-20", 20793.6)]
        assert d["fetched_at"] == "t2"

    def test_load_missing_returns_none(self, tmp_path):
        assert load_volume_history(tmp_path / "nope.json") is None


class TestPackMerge:
    """_load_volume_series：长历史（volume_history.json）+ 近期覆盖（kpl/emotion）。"""

    def test_history_plus_emotion_overlay(self, tmp_path):
        vh = tmp_path / "vh.json"
        vh.write_text(json.dumps({"points": [
            {"date": "2026-06-15", "成交额_亿": 15234.5},
            {"date": "2026-08-19", "成交额_亿": 25110.4},
        ], "source": "TDX", "fetched_at": "2099-01-01T00:00:00"}), encoding="utf-8")
        kpl = tmp_path / "kpl"
        (kpl / "emotion").mkdir(parents=True)
        (kpl / "emotion" / "2026-08-20.json").write_text(
            json.dumps({"daban": {"qscln": 207936324}}), encoding="utf-8")
        (kpl / "emotion" / "2026-08-21.json").write_text(  # 未来日期排除
            json.dumps({"daban": {"qscln": 999999999}}), encoding="utf-8")
        vs = _load_volume_series("2026-08-20", kpl, vh_path=vh)
        assert [p["date"] for p in vs["points"]] == ["2026-06-15", "2026-08-19", "2026-08-20"]
        assert vs["peak"]["成交额_亿"] == 25110.4
        assert vs["coverage"] == "3/60"
        assert "fetched_at" not in json.dumps(vs)  # 防泄漏：fetched_at 不进包

    def test_history_only(self, tmp_path):
        vh = tmp_path / "vh.json"
        vh.write_text(json.dumps({"points": [{"date": "2026-06-15", "成交额_亿": 15234.5}],
                                  "source": "TDX", "fetched_at": "t"}), encoding="utf-8")
        vs = _load_volume_series("2026-08-20", tmp_path / "kpl_empty", vh_path=vh)
        assert [p["成交额_亿"] for p in vs["points"]] == [15234.5]
