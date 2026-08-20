"""影子双轨盲判测试（mock client，不触网）。"""
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

from investment_engine.shadow.predict import (
    has_fresh_data, prediction_path, run_predict,
)


def _fake_client(payload: str):
    msg = SimpleNamespace(content=payload)
    choice = SimpleNamespace(message=msg)
    completions = SimpleNamespace(create=lambda **kw: SimpleNamespace(choices=[choice]))
    return SimpleNamespace(chat=SimpleNamespace(completions=completions))


GOOD_JSON = json.dumps({
    "market_stage": "震荡", "stage_reason": "缩量横盘",
    "directions": [{"direction_id": "d1", "reason": "r", "stocks": ["002371"]}],
    "used_patterns": ["upstream_cycle"],
}, ensure_ascii=False)


class TestPredictionPath:
    def test_path_layout(self):
        p = prediction_path("2026-08-07", pred_dir=Path("/tmp/x"))
        assert p.name == "2026-08-07.json"


class TestHasFreshData:
    def test_fresh_when_cache_covers_day(self):
        from qing_investment.kline_cache import init_db, save_klines
        db = Path(tempfile.gettempdir()) / f"test_pred_{id(self)}.db"
        init_db(db_path=db)
        save_klines("002371", [{"code": "002371", "date": "2026-08-07", "open": 1,
                                "high": 1, "low": 1, "close": 1, "volume": 1,
                                "turnover": 1, "amplitude": 1, "pct_change": 1}], db_path=db)
        assert has_fresh_data("2026-08-07", db_path=db) is True
        assert has_fresh_data("2026-08-08", db_path=db) is False
        db.unlink(missing_ok=True)


class TestRunPredict:
    def setup_method(self):
        self.pred_dir = Path(tempfile.mkdtemp(prefix="pred_"))

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.pred_dir, ignore_errors=True)

    def _run(self, monkeypatch, day="2026-08-07", **kw):
        monkeypatch.setattr(
            "investment_engine.shadow.predict.build_daily_pack",
            lambda d, **k: {"stocks": []})
        monkeypatch.setattr(
            "investment_engine.shadow.predict.pack_to_prompt", lambda p: p)
        monkeypatch.setattr(
            "investment_engine.shadow.predict.call_deepseek",
            lambda m, **k: GOOD_JSON)
        return run_predict(day, config_dir="x", pred_dir=self.pred_dir, **kw)

    def test_writes_prediction(self, monkeypatch):
        r = self._run(monkeypatch)
        assert r["status"] == "pending_maturity"
        rec = json.loads(prediction_path("2026-08-07", pred_dir=self.pred_dir).read_text(encoding="utf-8"))
        assert rec["result"]["market_stage"] == "震荡"
        assert rec["stage_hit"] is None and rec["due_scores"] is None

    def test_idempotent_skip(self, monkeypatch):
        self._run(monkeypatch)
        r2 = self._run(monkeypatch)
        assert r2["status"] == "skipped"

    def test_overnight_injected_in_replay(self, monkeypatch, tmp_path):
        """2026-08-20 复盘路径补注入 overnight_us（与盘前同一精简结构）。"""
        captured = {}
        monkeypatch.setattr(
            "investment_engine.shadow.predict.build_daily_pack",
            lambda d, **k: {"stocks": []})
        monkeypatch.setattr(
            "investment_engine.shadow.predict.pack_to_prompt",
            lambda p: captured.update(p) or p)
        monkeypatch.setattr(
            "investment_engine.shadow.predict.call_deepseek",
            lambda m, **k: GOOD_JSON)
        (tmp_path / "2026-08-07.json").write_text(json.dumps({
            "date": "2026-08-07",
            "themes": [{"id": "ai", "name": "AI算力",
                        "stocks": [{"symbol": "NVDA", "name": "英伟达",
                                    "pct_change": 4.35, "earnings_note": ""}]}],
        }, ensure_ascii=False), encoding="utf-8")
        r = run_predict("2026-08-07", config_dir="x", pred_dir=self.pred_dir,
                        overnight_root=tmp_path)
        assert r["status"] == "pending_maturity"
        assert captured["overnight_us"]["themes"][0]["stocks"][0]["symbol"] == "NVDA"

    def test_overnight_absent_not_injected(self, monkeypatch, tmp_path):
        captured = {}
        monkeypatch.setattr(
            "investment_engine.shadow.predict.build_daily_pack",
            lambda d, **k: {"stocks": []})
        monkeypatch.setattr(
            "investment_engine.shadow.predict.pack_to_prompt",
            lambda p: captured.update(p) or p)
        monkeypatch.setattr(
            "investment_engine.shadow.predict.call_deepseek",
            lambda m, **k: GOOD_JSON)
        r = run_predict("2026-08-07", config_dir="x", pred_dir=self.pred_dir,
                        overnight_root=tmp_path)  # 空目录 → 无文件
        assert r["status"] == "pending_maturity"
        assert "overnight_us" not in captured

    def test_error_status_retried(self, monkeypatch):
        # 先制造 error 记录
        path = prediction_path("2026-08-07", pred_dir=self.pred_dir)
        path.write_text(json.dumps({"date": "2026-08-07", "status": "error"}), encoding="utf-8")
        r = self._run(monkeypatch)
        assert r["status"] == "pending_maturity"  # error 日被重跑覆盖

    def test_force_rerun_supersedes_attribution(self, monkeypatch):
        attr_dir = Path(tempfile.mkdtemp(prefix="attr_"))
        prop_dir = Path(tempfile.mkdtemp(prefix="prop_"))
        try:
            self._run(monkeypatch)
            r_skip = self._run(monkeypatch)
            assert r_skip["status"] == "skipped"
            # 伪造该日归因 + open 提案
            prop = prop_dir / "2026-08-07-data-channel-x.md"
            prop.write_text("---\nstatus: open\n---\n", encoding="utf-8")
            (attr_dir / "2026-08-07.json").write_text(json.dumps({
                "date": "2026-08-07", "triggers": ["stage_miss"],
                "proposal_refs": [str(prop)]}), encoding="utf-8")
            r = self._run(monkeypatch, force=True,
                          attr_dir=attr_dir, proposal_dir=prop_dir)
            assert r["status"] == "pending_maturity"  # force 覆盖重跑
            old_attr = json.loads((attr_dir / "2026-08-07.json").read_text(encoding="utf-8"))
            assert old_attr["superseded"] is True
            assert "status: retracted" in prop.read_text(encoding="utf-8")
        finally:
            import shutil
            shutil.rmtree(attr_dir, ignore_errors=True)
            shutil.rmtree(prop_dir, ignore_errors=True)
