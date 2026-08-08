"""来源中立推理模式校验器测试。"""
import pytest

from investment_engine.distill.pattern_schema import PatternSchemaError, validate_pattern


def _valid_pattern() -> dict:
    return {
        "pattern_id": "upstream_cycle",
        "name": "上游涨价周期分析框架",
        "description": "当上游出现涨价信号时使用……",
        "trigger": [
            "上游核心品类出现涨价函或现货价连续上行（数据特征，非谁说了什么）",
            "主线核心资产进入高位轮动",
        ],
        "data_requirements": [
            {"name": "环节价值量", "channel": "研报 / knowledge/industry-chains"},
            {"name": "涨价函与现货价", "channel": "公告 / 生意社等公开价格源"},
        ],
        "steps": [
            {"step": 1, "name": "确认涨价真实性",
             "question": "涨价是个别行为还是行业性？",
             "action": "核对涨价函数量、现货价曲线与库存数据，三者至少两者同向才进入下一步",
             "data": ["涨价函与现货价"]},
        ],
        "falsification": ["现货价连续 2 周回落", "下游龙头公开抵制或去库存"],
        "validation": {
            "historical_hit_rate": None,
            "applicable_regime": None,
            "known_failures": [],
            "confidence_indicators": ["多家厂商同步涨价", "库存低位"],
        },
        "applicable_themes": ["MLCC", "存储"],
        "source_raw": ["sources/raw/财经/复盘：26-05-31：xxx.md"],
        "examples": [],
        "merged_from": [],
    }


class TestValidatePattern:
    def test_valid_pattern_passes(self):
        assert validate_pattern(_valid_pattern()) == _valid_pattern()

    def test_missing_field_rejected(self):
        p = _valid_pattern()
        del p["trigger"]
        with pytest.raises(PatternSchemaError, match="trigger"):
            validate_pattern(p)

    def test_up_reference_in_action_rejected(self):
        """来源中立的核心机械保证：action 不得引用 UP。"""
        p = _valid_pattern()
        p["steps"][0]["action"] = "按 UP 的判断，涨价周期启动"
        with pytest.raises(PatternSchemaError, match="UP"):
            validate_pattern(p)

    def test_up_reference_in_falsification_rejected(self):
        p = _valid_pattern()
        p["falsification"] = ["博主转谨慎"]
        with pytest.raises(PatternSchemaError):
            validate_pattern(p)

    def test_up_reference_in_trigger_rejected(self):
        p = _valid_pattern()
        p["trigger"] = ["UP 看好程度上升"]
        with pytest.raises(PatternSchemaError):
            validate_pattern(p)

    def test_source_raw_may_keep_traceability(self):
        """source_raw 保留溯源是允许的（校验不查它）。"""
        p = _valid_pattern()
        p["source_raw"] = ["sources/raw/财经/复盘：26-05-31：UP 原文.md"]
        assert validate_pattern(p) == p

    def test_validation_subfields_required(self):
        p = _valid_pattern()
        del p["validation"]["known_failures"]
        with pytest.raises(PatternSchemaError, match="known_failures"):
            validate_pattern(p)

    def test_hit_rate_pending_m1_allowed(self):
        p = _valid_pattern()
        p["validation"]["historical_hit_rate"] = "pending-m1"
        assert validate_pattern(p) == p

    def test_step_data_must_reference_requirement(self):
        p = _valid_pattern()
        p["steps"][0]["data"] = ["不存在的数据项"]
        with pytest.raises(PatternSchemaError, match="不存在的数据项"):
            validate_pattern(p)

    def test_data_requirement_needs_channel(self):
        p = _valid_pattern()
        p["data_requirements"] = [{"name": "环节价值量"}]
        with pytest.raises(PatternSchemaError, match="channel"):
            validate_pattern(p)
