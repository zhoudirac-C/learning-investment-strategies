"""到期回填测试（合成 K 线 + 合成 prediction）。"""
import json
import tempfile
from pathlib import Path

from qing_investment.kline_cache import init_db, save_index_klines, save_klines
from investment_engine.shadow.maturity import due_predictions, run_maturity


def _klines(code: str, closes: list[float]) -> list[dict]:
    return [
        {"code": code, "date": f"2026-06-{i + 1:02d}", "open": c, "high": c, "low": c,
         "close": c, "volume": 100, "turnover": 1.0, "amplitude": 1.0, "pct_change": 0.0}
        for i, c in enumerate(closes)
    ]


def _write_pred(pred_dir: Path, day: str, stage="震荡") -> None:
    rec = {"date": day,
           "result": {"market_stage": stage,
                      "directions": [{"direction_id": "d1", "stocks": ["002371"]}],
                      "used_patterns": []},
           "raw": "", "stage_hit": True, "due_scores": None, "status": "pending_maturity"}
    (pred_dir / f"{day}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")


class TestMaturity:
    def setup_method(self):
        self.db = Path(tempfile.gettempdir()) / f"test_mat_{id(self)}.db"
        init_db(db_path=self.db)
        save_index_klines("sh000300", _klines("IDX000300", [4000.0] * 12), db_path=self.db)
        save_klines("002371", _klines("002371", [10.0, 10, 10, 10, 10, 11, 11, 11, 11, 11, 11, 11]), db_path=self.db)
        self.pred_dir = Path(tempfile.mkdtemp(prefix="mat_"))

    def teardown_method(self):
        import shutil
        self.db.unlink(missing_ok=True)
        shutil.rmtree(self.pred_dir, ignore_errors=True)

    def test_due_only_after_5_trading_days(self):
        _write_pred(self.pred_dir, "2026-06-01")
        # 06-01 之后第 4 个交易日（06-05）：未到期
        assert due_predictions("2026-06-05", db_path=self.db, pred_dir=self.pred_dir) == []
        # 第 5 个交易日（06-06）：到期
        due = due_predictions("2026-06-06", db_path=self.db, pred_dir=self.pred_dir)
        assert len(due) == 1

    def test_run_maturity_writes_scores(self, monkeypatch):
        _write_pred(self.pred_dir, "2026-06-01")
        monkeypatch.setattr(
            "investment_engine.shadow.maturity._direction_members",
            lambda config_dir, direction_id: ["002371"],
        )
        stats = run_maturity("2026-06-06", config_dir="x", db_path=self.db, pred_dir=self.pred_dir)
        assert stats["scored"] == 1
        rec = json.loads((self.pred_dir / "2026-06-01.json").read_text(encoding="utf-8"))
        assert rec["status"] == "scored"
        assert rec["due_scores"]["stocks"]["hits"] == 1  # 002371 涨 10% vs 指数 0
