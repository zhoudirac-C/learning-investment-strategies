"""每日编排测试（全 mock）。"""
import json
import tempfile
from pathlib import Path

from investment_engine.shadow.daily import run


class TestDailyPromptVersion:
    def test_prompt_version_is_v6(self):
        """P0 prompt 纪律批次：盘后 prompt 版本号 v5→v6。"""
        from investment_engine.blindtest import replay
        assert replay.PROMPT_VERSION == "v6"

    def test_daily_prompt_contains_discipline_rules(self):
        """v6 新增纪律规则关键词须出现在盘后 prompt（B1/B2/A2-A5/C5引用/C8降级）。"""
        from investment_engine.blindtest import replay
        text = replay.SYSTEM_PROMPT
        assert "±30%" in text  # B1 证据-结论一致性硬约束
        assert "数据缺失，信息差风险" in text  # B2(c)/C8 降级标注
        assert "冲量滑落" in text and "分时" in text  # A2 形态禁判
        assert "量从哪来" in text  # A3 量能源头
        assert "反弹修复段" in text and "补缺回踩" in text  # A4 位置决定意义
        assert "守住前日量级" in text and "24000 亿以上算放量" in text  # A5 相对口径
        assert "promotion_rate" in text and "晋级率" in text  # C5 梯队引用/A8 折算


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
