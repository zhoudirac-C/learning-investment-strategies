"""每日编排测试（全 mock）。"""
import json
import tempfile
from pathlib import Path

from investment_engine.shadow.daily import run


class TestDailyPromptVersion:
    def test_prompt_version_is_v13(self):
        """pattern-patch 合并裁决 2026-08-30：版本号 v12→v13（规则29 方向失效条件 +
        规则5扩展 双轨互证）。"""
        from investment_engine.blindtest import replay
        assert replay.PROMPT_VERSION == "v13"

    def test_daily_prompt_contains_discipline_rules(self):
        """v6/v8 纪律规则关键词须出现在盘后 prompt（B1/B2/A2-A5/C5引用/C8降级/规则9并列）。"""
        from investment_engine.blindtest import replay
        text = replay.SYSTEM_PROMPT
        assert "±15%" in text  # B1 证据-结论一致性硬约束（v8 校准后重定）
        assert "环比前日_pct" in text and "并列" in text  # v8 规则9 形态/环比并列口径
        assert "数据缺失，信息差风险" in text  # B2(c)/C8 降级标注
        assert "冲量滑落" in text and "分时" in text  # A2 形态禁判
        assert "量从哪来" in text  # A3 量能源头
        assert "反弹修复段" in text and "补缺回踩" in text  # A4 位置决定意义
        assert "守住前日量级" in text and "24000 亿以上算放量" in text  # A5 相对口径
        assert "promotion_rate" in text and "晋级率" in text  # C5 梯队引用/A8 折算
        assert "forming/divergence" in text  # v7 规则17 顶部结构信号引用

    def test_daily_prompt_contains_v9_up_patterns(self):
        """v9 规则18-22（2026-08-21 三方对比提案）关键词须在盘后 prompt。"""
        from investment_engine.blindtest import replay
        text = replay.SYSTEM_PROMPT
        assert "三信号见底清单" in text and "强势股" in text and "多杀多" in text  # 规则18
        assert "宽度修复" in text and "谁在涨" in text  # 规则19 宽度/强度两步
        assert "下台阶" in text  # 规则20 量能台阶锚定
        assert "防御方向默认退潮" in text  # 规则21 弱市防御禁止顺延
        assert "个股级验证节点" in text  # 规则22 watch_next 首条
        assert "催化溯源" in text and "无显性催化" in text  # 规则23 方向催化溯源
        assert "外力/内生归因前置" in text and "外部链条检验结论" in text  # 规则24

    def test_daily_prompt_contains_v11_cluster_limit(self):
        """v11 规则27（2026-08-24 方向同簇限选提案）关键词须在盘后 prompt。"""
        from investment_engine.blindtest import replay
        text = replay.SYSTEM_PROMPT
        assert "同簇限选" in text and "相关簇" in text  # 规则27 核心约束
        assert "C1 AI硬件链" in text and "C7 主题事件" in text  # 分簇表在场
        assert "无其它簇合格候选" in text  # 合规出口

    def test_daily_prompt_contains_v12_price_structure_veto(self):
        """v12 规则28（2026-08-30 合并裁决：价格结构前置否决）关键词须在盘后 prompt。"""
        from investment_engine.blindtest import replay
        text = replay.SYSTEM_PROMPT
        assert "价格结构前置否决" in text and "无权单独定" in text  # 规则28 核心约束
        assert "跌破 5 日均线或近期波段低点" in text  # (a) 破位校验
        assert "只按反抽处理" in text  # 破位收跌日宽度修复定性
        assert "禁止判「主升」" in text  # (b) 顶部结构结论级压制

    def test_daily_prompt_contains_v13_rules(self):
        """v13 规则29（方向失效条件）+ 规则5扩展（双轨互证）关键词须在盘后 prompt。"""
        from investment_engine.blindtest import replay
        text = replay.SYSTEM_PROMPT
        assert "方向必须带失效条件" in text and "连续两日跑输大盘" in text  # 规则29
        assert "premarket_today" in text and "盘前预判兑现" in text  # 规则5扩展 双轨互证


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
            pre = {"date": day, "result": {"market_stage": "震荡"}, "raw": "",
                   "stage_hit": None, "due_scores": None, "status": "pending_maturity"}
            if "pre_stage" in overrides:
                pre["result"]["market_stage"] = overrides["pre_stage"]
                rec["result"]["market_stage"] = overrides.get("stage", "震荡")
            pred_dir = Path(kw["pred_dir"])
            pred_dir.mkdir(parents=True, exist_ok=True)
            (pred_dir / f"{day}.json").write_text(json.dumps(rec), encoding="utf-8")
            (pred_dir / f"{day}-pre.json").write_text(json.dumps(pre), encoding="utf-8")
            return rec

        monkeypatch.setattr("investment_engine.shadow.daily.has_fresh_data",
                            overrides.get("fresh", lambda day, db_path=None: True))
        monkeypatch.setattr("investment_engine.shadow.daily.run_predict",
                            overrides.get("predict", fake_predict))
        monkeypatch.setattr("investment_engine.shadow.daily.load_truth",
                            overrides.get("truth", lambda **kw: {"2026-08-07": "震荡"}))
        monkeypatch.setattr("investment_engine.shadow.daily.run_maturity",
                            overrides.get("maturity", lambda day, **kw: {"scored": 0}))
        calls = []

        def fake_attr(day, **kw):
            calls.append({"day": day, "trigger": kw.get("trigger"), "pred": kw.get("pred")})
            return {"date": day}

        monkeypatch.setattr("investment_engine.shadow.daily.run_attribution",
                            overrides.get("attribute", fake_attr))
        r = run("2026-08-07", config_dir="x",
                pred_dir=self.pred_dir, attr_dir=self.attr_dir, proposal_dir=self.prop_dir)
        r["_attr_calls"] = calls
        return r

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
        assert any(c["trigger"] == "stage_miss" for c in r["_attr_calls"])

    def test_premarket_stage_miss_triggers_attribution(self, monkeypatch):
        """早盘 -pre 判错也须触发归因（2026-08-27 补管线缺口：8-20/8-24 漏归因根因）。"""
        r = self._run(monkeypatch, pre_stage="调整", truth=lambda **kw: {"2026-08-07": "震荡"})
        assert r["attributed"] is True
        pre_calls = [c for c in r["_attr_calls"] if c["trigger"] == "stage_miss_premarket"]
        assert len(pre_calls) == 1
        assert pre_calls[0]["day"] == "2026-08-07"
        assert pre_calls[0]["pred"]["result"]["market_stage"] == "调整"

    def test_premarket_stage_hit_no_attribution(self, monkeypatch):
        """早盘判对不归因。"""
        r = self._run(monkeypatch, pre_stage="震荡")
        assert r["attributed"] is False
        assert not any(c["trigger"] == "stage_miss_premarket" for c in r["_attr_calls"])

    def test_prediction_error_propagates(self, monkeypatch):
        r = self._run(monkeypatch, predict=lambda day, **kw: {"date": day, "status": "error"})
        assert r["status"] == "predict_error"
