"""LLM 5 步推理分析测试（T12）。"""
import json

import pytest

from investment_engine.chain_tracker import analysis
from investment_engine.chain_tracker.analysis import (
    VERDICTS, analyze_chain, build_tracking_messages, parse_analysis,
)


def _chain() -> dict:
    return {
        "chain_id": "ai-pcb-ccl",
        "name": "AI PCB/CCL 产业链",
        "thesis": "AI服务器代际升级 → PCB层数提升 → CCL升级 → 上游材料涨价",
        "current_stage": "阶段2-加速期",
        "stage_confidence": "高",
        "stage_evidence": "FR8价格260-270元/张",
        "timing": {"current_recommendation": "中游CCL", "next_trigger": "Rubin认证通过",
                   "risk": "上游涨价见顶"},
        "tracking_metrics": [{"metric": "FR8价格", "current": "260-270元/张",
                              "signal_direction": "突破300=加强"}],
        "falsification": ["FR8价格连续2周回落"],
        "mappings": [{"code": "600183", "name": "生益科技", "segment": "seg-mid"}],
        "segments": [{"id": "seg-mid", "name": "中游CCL"}],
    }


def _items() -> list[dict]:
    return [{"info_id": "AP1", "source": "report", "title": "FR8价格突破300元/张",
             "published_at": "2026-08-31", "org": "测试证券", "stock_code": None,
             "stock_name": None, "industry_name": "电子", "url": None},
            {"info_id": "AN1", "source": "notice", "title": "生益科技：涨价函公告",
             "published_at": "2026-08-31", "org": None, "stock_code": "600183",
             "stock_name": "生益科技", "industry_name": None, "url": None}]


def _good_result(**over) -> dict:
    base = {
        "step1_verification": {"verified": True, "sources": ["研报", "公告"],
                               "confidence": "高"},
        "step2_supply_demand": {"driver": "供给", "affected_segment": "上游"},
        "step3_cycle_position": {"current_stage": "阶段2-加速期",
                                 "distance_to_peak": "未知"},
        "step4_beneficiaries": [{"code": "600183", "name": "生益科技",
                                 "logic": "高端承接"}],
        "step5_recommendation": {"stage_change": "unchanged",
                                 "new_stage": "阶段2-加速期",
                                 "timing": "中游CCL", "action": "持有"},
        "verdict": "strengthening",
        "summary": "FR8涨价确认产业链逻辑加强",
    }
    base.update(over)
    return base


class TestBuildMessages:
    def test_prompt_contains_chain_state_and_items(self):
        msgs = build_tracking_messages(_chain(), _items())
        assert msgs[0]["role"] == "system"
        user = msgs[1]["content"]
        assert "AI PCB/CCL 产业链" in user
        assert "阶段2-加速期" in user
        assert "FR8价格突破300元/张" in user
        assert "生益科技：涨价函公告" in user
        # 5 步框架与证伪条件都要在 prompt 里
        for step in ("Step 1", "Step 2", "Step 3", "Step 4", "Step 5"):
            assert step in user
        assert "FR8价格连续2周回落" in user
        # 2026-08-31 回放校准：阶段变更硬约束必须在 prompt 里
        assert "直接命中本链关键节点" in user

    def test_prompt_contains_step6_and_structure(self):
        """Step 6 演化判断：环节结构/标的映射入 prompt，输出含 logic_update 说明。"""
        user = build_tracking_messages(_chain(), _items())[1]["content"]
        assert "Step 6" in user
        assert "logic_update" in user
        # 环节结构与标的映射（LLM 需引用 segment_id、避免重复提议已有节点）
        assert "环节结构" in user
        assert "seg-mid" in user          # segment id
        assert "中游CCL" in user          # segment 名
        assert "600183" in user           # 已有标的（防重复 add_node）
        # 结构性增量 vs 阶段变化的区分硬约束
        assert "结构性增量" in user

    def test_prompt_truncates_long_batch(self):
        items = _items() * 100  # 200 条
        msgs = build_tracking_messages(_chain(), items, max_items=30)
        assert msgs[1]["content"].count("info_id") <= 30


class TestParseAnalysis:
    def test_parse_good_json(self):
        result = parse_analysis(json.dumps(_good_result(), ensure_ascii=False))
        assert result["verdict"] == "strengthening"
        assert result["step5_recommendation"]["stage_change"] == "unchanged"

    def test_parse_tolerates_markdown_fence(self):
        raw = "```json\n" + json.dumps(_good_result(), ensure_ascii=False) + "\n```"
        result = parse_analysis(raw)
        assert result["verdict"] == "strengthening"

    def test_invalid_verdict_normalized_to_irrelevant(self):
        result = parse_analysis(json.dumps(_good_result(verdict="胡说")))
        assert result["verdict"] == "irrelevant"

    def test_invalid_stage_change_normalized_to_unchanged(self):
        result = parse_analysis(json.dumps(
            _good_result(step5_recommendation={"stage_change": "飞跃", "new_stage": "x"})))
        assert result["step5_recommendation"]["stage_change"] == "unchanged"

    def test_forward_requires_valid_new_stage(self):
        bad = _good_result(step5_recommendation={
            "stage_change": "forward", "new_stage": "阶段9-飞天", "timing": "t",
            "action": "a"})
        with pytest.raises(ValueError):
            parse_analysis(json.dumps(bad))

    def test_non_json_raises(self):
        with pytest.raises(ValueError):
            parse_analysis("这不是JSON")

    def test_logic_update_passes_through(self):
        """logic_update 原样透传（语义校验在 evolution.parse_logic_update）。"""
        lu = {"change_type": "add_node", "summary": "新增节点",
              "detail": {"metric": {"metric": "玻璃布Q-Glass供给"}},
              "rationale": "深度报告", "confidence": "中"}
        result = parse_analysis(json.dumps(
            _good_result(logic_update=lu), ensure_ascii=False))
        assert result["logic_update"] == lu
        # 缺失时不多事（保持缺失/原样）
        result2 = parse_analysis(json.dumps(_good_result(), ensure_ascii=False))
        assert "logic_update" not in result2

    def test_verdict_values(self):
        assert set(VERDICTS) == {"confirmed", "strengthening", "weakening",
                                 "falsified", "irrelevant"}


class TestAnalyzeChain:
    def test_calls_llm_and_parses(self):
        captured = {}

        def fake_call(messages, **kw):
            captured["messages"] = messages
            return json.dumps(_good_result(), ensure_ascii=False)

        result = analyze_chain(_chain(), _items(), call_fn=fake_call)
        assert result["verdict"] == "strengthening"
        assert "AI PCB/CCL" in captured["messages"][1]["content"]

    def test_llm_error_propagates(self):
        def boom(messages, **kw):
            raise RuntimeError("API down")

        with pytest.raises(RuntimeError):
            analyze_chain(_chain(), _items(), call_fn=boom)


class TestDefaultLlmCall:
    """通道优先级：逃生口 → Hermes 全局 → .env sensenova → GLM 兜底。"""

    @pytest.fixture(autouse=True)
    def _reset(self, monkeypatch):
        monkeypatch.setattr(analysis, "_HERMES_CACHE", None)
        monkeypatch.setattr(analysis, "_HERMES_TRIED", False)
        monkeypatch.delenv("CHAIN_TRACKER_LLM", raising=False)

    def _capture(self, monkeypatch, side_effects):
        from investment_engine.blindtest import replay

        calls = []

        def fake(messages, **kw):
            calls.append(kw)
            eff = side_effects[len(calls) - 1]
            if isinstance(eff, Exception):
                raise eff
            return eff

        monkeypatch.setattr(replay, "call_deepseek", fake)
        return calls

    def test_hermes_global_preferred(self, monkeypatch):
        monkeypatch.setattr(analysis, "_hermes_global", lambda: {
            "api_key": "k", "base_url": "http://x", "model": "glm-9",
            "source": "test"})
        calls = self._capture(monkeypatch, ["{}"])
        analysis.default_llm_call([{"role": "user", "content": "hi"}])
        assert calls[0]["model"] == "glm-9"
        assert calls[0]["tag"] == "chain_tracker:hermes:glm-9"
        assert len(calls) == 1

    def test_fallback_to_env_channel_without_hermes(self, monkeypatch):
        monkeypatch.setattr(analysis, "_hermes_global", lambda: None)
        calls = self._capture(monkeypatch, ["{}"])
        analysis.default_llm_call([{"role": "user", "content": "hi"}],
                                  tag="chain_discovery")
        assert calls[0]["tag"] == "chain_discovery"  # 默认 sensenova 通道
        assert "model" not in calls[0]

    def test_hermes_failure_falls_to_env_then_glm(self, monkeypatch):
        monkeypatch.setattr(analysis, "_hermes_global", lambda: {
            "api_key": "k", "base_url": "http://x", "model": "glm-9",
            "source": "test"})
        monkeypatch.setenv("ZHIPU_API_KEY", "fake")
        calls = self._capture(monkeypatch, [RuntimeError("down"),
                                            RuntimeError("down"), "{}"])
        analysis.default_llm_call([{"role": "user", "content": "hi"}])
        assert calls[0]["model"] == "glm-9"          # hermes 全局失败
        assert "model" not in calls[1]               # .env sensenova 失败
        assert calls[2]["model"] == "glm-4.7-flash"  # GLM 兜底
        assert calls[2]["tag"].endswith(":glm")

    def test_glm_escape_hatch(self, monkeypatch):
        monkeypatch.setenv("CHAIN_TRACKER_LLM", "glm")
        monkeypatch.setenv("ZHIPU_API_KEY", "fake")
        monkeypatch.setattr(analysis, "_hermes_global",
                            lambda: pytest.fail("逃生口不应解析 hermes"))
        calls = self._capture(monkeypatch, ["{}"])
        analysis.default_llm_call([{"role": "user", "content": "hi"}])
        assert calls[0]["model"] == "glm-4.7-flash"
        assert len(calls) == 1
