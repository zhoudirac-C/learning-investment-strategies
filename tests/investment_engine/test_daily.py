"""每日编排测试（全 mock）。"""
import json
import tempfile
from pathlib import Path

from investment_engine.shadow.daily import run


class TestDailyRun:
    def setup_method(self):
        self.root = Path(tempfile.mkdtemp(prefix="daily_"))
        self.pred_dir = self.root / "pred"
        self.attr_dir = self.root / "attr"
        self.prop_dir = self.root / "prop"

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)

    def _run(self, monkeypatch, **overrides):
        def fake_predict(day, **kw):
            rec = {"date": day, "result": {"market_stage": "震荡"}, "raw": "",
                   "stage_hit": None, "due_scores": None, "status": "pending_maturity"}
            pred_dir = Path(kw["pred_dir"])
            pred_dir.mkdir(parents=True, exist_ok=True)
            (pred_dir / f"{day}.json").write_text(json.dumps(rec), encoding="utf-8")
            return rec

        monkeypatch.setattr("investment_engine.shadow.daily.has_fresh_data",
                            overrides.get("fresh", lambda day, db_path=None: True))
        monkeypatch.setattr("investment_engine.shadow.daily.run_predict",
                            overrides.get("predict", fake_predict))
        monkeypatch.setattr("investment_engine.shadow.daily.load_truth",
                            overrides.get("truth", lambda **kw: {"2026-08-07": "震荡"}))
        monkeypatch.setattr("investment_engine.shadow.daily.run_maturity",
                            overrides.get("maturity", lambda day, **kw: {"scored": 0}))
        monkeypatch.setattr("investment_engine.shadow.daily.run_attribution",
                            overrides.get("attribute", lambda day, **kw: {"date": day}))
        return run("2026-08-07", config_dir="x",
                   pred_dir=self.pred_dir, attr_dir=self.attr_dir, proposal_dir=self.prop_dir)

    def test_no_data_exits_clean(self, monkeypatch):
        r = self._run(monkeypatch, fresh=lambda day, db_path=None: False)
        assert r["status"] == "no_data"

    def test_happy_path_stage_hit(self, monkeypatch):
        r = self._run(monkeypatch)
        assert r["status"] == "ok"
        assert r["stage_hit"] is True
        assert r["attributed"] is False  # 判对不归因

    def test_stage_miss_triggers_attribution(self, monkeypatch):
        r = self._run(monkeypatch, truth=lambda **kw: {"2026-08-07": "恐慌"})
        assert r["stage_hit"] is False
        assert r["attributed"] is True

    def test_prediction_error_propagates(self, monkeypatch):
        r = self._run(monkeypatch, predict=lambda day, **kw: {"date": day, "status": "error"})
        assert r["status"] == "predict_error"
