"""盲测评分测试（合成记录 + 合成 K 线）。"""
import json
import tempfile
from pathlib import Path

from qing_investment.kline_cache import init_db, save_klines
from investment_engine.blindtest.score import (
    direction_scores, load_results, stage_accuracy, stock_scores,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def _klines(code: str, closes: list[float]) -> list[dict]:
    return [
        {"code": code, "date": f"2026-06-{i + 1:02d}", "open": c, "high": c, "low": c,
         "close": c, "volume": 100, "turnover": 1.0, "amplitude": 1.0, "pct_change": 0.0}
        for i, c in enumerate(closes)
    ]


class TestLoadResults:
    def test_only_ok_rows(self, tmp_path):
        p = tmp_path / "r.jsonl"
        _write_jsonl(p, [
            {"date": "d1", "ok": True, "result": {"market_stage": "震荡"}},
            {"date": "d2", "ok": False, "error": "x"},
        ])
        rows = load_results(p)
        assert len(rows) == 1 and rows[0]["date"] == "d1"


class TestStageAccuracy:
    def test_accuracy_and_by_label(self, tmp_path):
        p = tmp_path / "r.jsonl"
        _write_jsonl(p, [
            {"date": "d1", "ok": True, "result": {"market_stage": "主升"}},
            {"date": "d2", "ok": True, "result": {"market_stage": "震荡"}},
            {"date": "d3", "ok": True, "result": {"market_stage": "调整"}},
        ])
        truth = {"d1": "主升", "d2": "调整", "d3": "调整"}
        s = stage_accuracy(load_results(p), truth)
        assert s["samples"] == 3 and s["hits"] == 2
        assert abs(s["accuracy"] - 2 / 3) < 1e-9
        assert s["by_label"]["调整"]["samples"] == 2


class TestDirectionAndStockScores:
    def setup_method(self):
        self.db = Path(tempfile.gettempdir()) / f"test_score_{id(self)}.db"
        init_db(db_path=self.db)
        # 指数：平稳；个股 a 涨、个股 b 跌
        save_klines("IDX000300", _klines("IDX000300", [4000.0] * 12), db_path=self.db)
        save_klines("002371", _klines("002371", [10.0, 10, 10, 10, 10, 11, 11, 11, 11, 11, 11, 11]), db_path=self.db)
        save_klines("300054", _klines("300054", [10.0, 10, 10, 10, 10, 9, 9, 9, 9, 9, 9, 9]), db_path=self.db)

    def teardown_method(self):
        self.db.unlink(missing_ok=True)

    def _results(self, tmp_path):
        p = tmp_path / "r.jsonl"
        _write_jsonl(p, [
            {"date": "2026-06-01", "ok": True, "result": {
                "market_stage": "震荡",
                "directions": [{"direction_id": "semiconductor", "stocks": ["002371", "300054"]}],
            }},
        ])
        return load_results(p)

    def test_stock_scores(self, tmp_path):
        s = stock_scores(self._results(tmp_path), db_path=self.db, horizon=5)
        # 002371: +10% vs 指数 0 → 命中；300054: -10% → 不中
        assert s["samples"] == 2 and s["hits"] == 1

    def test_direction_scores(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "investment_engine.blindtest.score._direction_members",
            lambda config_dir, direction_id: ["002371", "300054"],
        )
        s = direction_scores(self._results(tmp_path), config_dir="x", db_path=self.db, horizon=5)
        # 等权 (10% + -10%)/2 = 0 → 超额 0，不记命中（严格 >0）
        assert s["samples"] == 1 and s["hits"] == 0
