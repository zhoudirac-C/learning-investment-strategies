"""DeepSeek 回放测试（mock client，不触网）。"""
import json
import re
from types import SimpleNamespace

import pytest

from investment_engine.blindtest.replay import (
    PROMPT_VERSION, SYSTEM_PROMPT, SYSTEM_PROMPT_V15, SYSTEM_PROMPT_V16,
    SYSTEM_PROMPT_V17, SYSTEM_PROMPT_V18, _V18_RULE28C,
    build_messages, parse_result, run_replay,
)


def _fake_client(payload: str):
    """构造 openai 兼容的假 client。"""
    msg = SimpleNamespace(content=payload)
    choice = SimpleNamespace(message=msg)
    completions = SimpleNamespace(create=lambda **kw: SimpleNamespace(choices=[choice]))
    chat = SimpleNamespace(completions=completions)
    return SimpleNamespace(chat=chat)


GOOD_JSON = json.dumps({
    "market_stage": "震荡",
    "stage_reason": "指数缩量横盘",
    "directions": [{"direction_id": "mlcc_super_cycle", "reason": "涨价", "stocks": ["002371"]}],
    "used_patterns": ["upstream_cycle"],
}, ensure_ascii=False)


class TestBuildMessages:
    def test_system_prompt_has_contract(self):
        assert "market_stage" in SYSTEM_PROMPT and "主升" in SYSTEM_PROMPT

    def test_messages_shape(self):
        msgs = build_messages("PACK_TEXT")
        assert msgs[0]["role"] == "system" and msgs[1]["role"] == "user"
        assert "PACK_TEXT" in msgs[1]["content"]


class TestParseResult:
    def test_plain_json(self):
        r = parse_result(GOOD_JSON)
        assert r["market_stage"] == "震荡"
        assert r["directions"][0]["direction_id"] == "mlcc_super_cycle"

    def test_fenced_json(self):
        assert parse_result(f"```json\n{GOOD_JSON}\n```")["market_stage"] == "震荡"

    def test_bad_stage_rejected(self):
        bad = json.dumps({"market_stage": "牛市", "directions": []})
        with pytest.raises(ValueError, match="market_stage"):
            parse_result(bad)

    def test_over_limit_truncated(self):
        payload = json.dumps({
            "market_stage": "主升",
            "directions": [{"direction_id": f"d{i}", "stocks": ["1", "2", "3"]} for i in range(5)],
        })
        r = parse_result(payload)
        assert len(r["directions"]) == 3
        assert len(r["directions"][0]["stocks"]) == 2

    def test_garbage_rejected(self):
        with pytest.raises(ValueError):
            parse_result("我觉得今天不错")


class TestRunReplay:
    def test_resume_skips_done_days(self, tmp_path, monkeypatch):
        out = tmp_path / "results.jsonl"
        out.write_text(
            json.dumps({"date": "2026-06-01", "ok": True, "result": {}, "raw": ""}) + "\n",
            encoding="utf-8",
        )
        calls = []

        def fake_pack(day, **kw):
            return "PACK"

        def fake_call(messages, **kw):
            calls.append(messages)
            return GOOD_JSON

        monkeypatch.setattr(
            "investment_engine.blindtest.replay.pack_to_prompt", lambda pack: pack
        )
        monkeypatch.setattr(
            "investment_engine.blindtest.replay.build_daily_pack", fake_pack
        )
        monkeypatch.setattr(
            "investment_engine.blindtest.replay.call_deepseek", fake_call
        )
        stats = run_replay(["2026-06-01", "2026-06-02"], config_dir="x", out_path=out)
        assert stats["skipped"] == 1 and stats["done"] == 1
        assert len(calls) == 1  # 只跑了新的一天

    def test_error_days_are_retried(self, tmp_path, monkeypatch):
        """error 行不算完成，重跑时必须重试。"""
        out = tmp_path / "results.jsonl"
        out.write_text(
            json.dumps({"date": "2026-06-01", "ok": False, "error": "boom"}) + "\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "investment_engine.blindtest.replay.pack_to_prompt", lambda pack: pack
        )
        monkeypatch.setattr(
            "investment_engine.blindtest.replay.build_daily_pack", lambda day, **kw: "PACK"
        )
        monkeypatch.setattr(
            "investment_engine.blindtest.replay.call_deepseek", lambda m, **kw: GOOD_JSON
        )
        stats = run_replay(["2026-06-01"], config_dir="x", out_path=out)
        assert stats == {"done": 1, "skipped": 0, "error": 0}


GOOD_JSON_V2 = json.dumps({
    "market_stage": "震荡",
    "stage_reason": "缩量整理，封板率87.6%",
    "scenarios": [{"name": "A", "condition": "低开有承接", "conclusion": "反弹延续", "key": "承接"}],
    "watch_next": ["二板家数能否达13家"],
    "invalidation": ["情绪龙头集体断板"],
    "directions": [{"direction_id": "mlcc_super_cycle", "reason": "涨价",
                    "posture": "右侧确认", "stocks": ["002371"]}],
    "used_patterns": ["upstream_cycle"],
}, ensure_ascii=False)


class TestParseResultV2:
    def test_v2_fields(self):
        r = parse_result(GOOD_JSON_V2)
        assert r["scenarios"][0]["key"] == "承接"
        assert r["watch_next"] == ["二板家数能否达13家"]
        assert r["invalidation"] == ["情绪龙头集体断板"]
        assert r["directions"][0]["posture"] == "右侧确认"

    def test_v1_backward_compat(self):
        r = parse_result(GOOD_JSON)
        assert r["scenarios"] == [] and r["watch_next"] == [] and r["invalidation"] == []
        assert r["directions"][0]["posture"] == ""

    def test_invalid_posture_dropped(self):
        bad = json.loads(GOOD_JSON_V2)
        bad["directions"][0]["posture"] = "梭哈"
        r = parse_result(json.dumps(bad, ensure_ascii=False))
        assert r["directions"][0]["posture"] == ""

    def test_prompt_version_constant(self):
        # 契约版本格式合法即可（v+数字，允许 minor 如 v10.1）；具体版本号随契约演进，不硬编码
        assert re.fullmatch(r"v\d+(\.\d+)?", PROMPT_VERSION)


class TestPromptV16:
    """v16 压缩 prompt（迭代基线，非生产默认）：37 条经验规则 → 推理链 + 元原则。

    2026-09-05 A/B 未通过（阶段 70% vs 50% 但方向 50% vs 66.7%、重试 8 vs 4），
    生产默认回退 v15；以下断言锁定 v16 作为后续迭代的压缩基线。
    """

    def test_v16_is_compressed(self):
        assert len(SYSTEM_PROMPT_V16) < len(SYSTEM_PROMPT_V15) * 0.7

    def test_v15_frozen(self):
        # v15 原样保留（生产默认）；「23b」乱序编号是其历史形态标记
        assert "23b" in SYSTEM_PROMPT_V15

    def test_v16_keeps_output_contract(self):
        for field in ("market_stage", "nature", "stage_reason", "scenarios",
                      "watch_next", "invalidation", "directions", "used_patterns",
                      "operation", "cycle_state",
                      "放量攻击", "缩量企稳", "主升", "反弹超预期"):
            assert field in SYSTEM_PROMPT_V16, field

    def test_v16_keeps_validator_anchors(self):
        # validate_result 的关键词校验依赖 prompt 教会模型输出这些锚点
        for kw in ("补跌", "多杀多", "流动性", "机构", "梯队", "宏观三条件",
                   "确认位", "过热", "冲量滑落", "盘前", "外力扰动", "同簇",
                   "信息差风险", "失效条件"):
            assert kw in SYSTEM_PROMPT_V16, kw

    def test_v16_no_stale_rule_numbering(self):
        # 新版按 1..N 连续编号，不再出现 23b 这类补丁编号
        assert "23b" not in SYSTEM_PROMPT_V16


class TestPromptV17:
    """v17（A/B 检验中，非生产默认）：v16 骨架 + 引用清单 + 硬门槛逐条 + 池锚定。"""

    def test_v17_compressed_vs_v15(self):
        assert len(SYSTEM_PROMPT_V17) < len(SYSTEM_PROMPT_V15) * 0.75

    def test_v17_keeps_output_contract(self):
        for field in ("market_stage", "nature", "stage_reason", "scenarios",
                      "watch_next", "invalidation", "directions", "used_patterns",
                      "operation", "cycle_state", "direction_pool",
                      "放量攻击", "缩量企稳", "主升", "反弹超预期"):
            assert field in SYSTEM_PROMPT_V17, field

    def test_v17_keeps_validator_anchors(self):
        # validate_result 的关键词校验依赖 prompt 教会模型输出这些锚点
        for kw in ("补跌", "多杀多", "流动性", "机构", "梯队", "宏观三条件",
                   "确认位", "过热", "冲量滑落", "盘前", "外力扰动", "同簇",
                   "信息差风险", "失效条件", "钝化", "外盘"):
            assert kw in SYSTEM_PROMPT_V17, kw

    def test_v17_direction_gates_are_itemized(self):
        # 硬门槛逐条独立成行（v16 教训：大段落会稀释门槛）
        for gate in ("催化溯源", "历史战绩", "同簇限选", "资金性质",
                     "连续性", "失效条件"):
            assert f"- {gate}" in SYSTEM_PROMPT_V17, gate

    def test_v17_no_stale_rule_numbering(self):
        assert "23b" not in SYSTEM_PROMPT_V17


class TestPromptV18:
    """v18 = v15 + 规则28(c)「调整需结构确认」（v15 系统性悲观偏置的手术式修复）。"""

    def test_v18_contains_adjustment_gate(self):
        assert "「调整」需结构确认" in SYSTEM_PROMPT_V18
        assert "破位收跌" in SYSTEM_PROMPT_V18

    def test_v18_differs_from_v15_only_by_gate(self):
        # 与 v15 的唯一差异 = 规则28(c) 追加（replace 拼装防漂移）
        assert SYSTEM_PROMPT_V18.replace(_V18_RULE28C, "") == SYSTEM_PROMPT_V15
        assert 0 < len(SYSTEM_PROMPT_V18) - len(SYSTEM_PROMPT_V15) < 400


class TestPromptSelection:
    def test_build_messages_default_prompt(self):
        msgs = build_messages("PACK")
        assert msgs[0]["content"] == SYSTEM_PROMPT

    def test_build_messages_prompt_override(self):
        msgs = build_messages("PACK", system_prompt="S")
        assert msgs[0]["content"] == "S"

    def test_run_replay_records_prompt_version(self, tmp_path, monkeypatch):
        out = tmp_path / "results.jsonl"
        monkeypatch.setattr(
            "investment_engine.blindtest.replay.build_daily_pack", lambda day, **kw: {})
        monkeypatch.setattr(
            "investment_engine.blindtest.replay.pack_to_prompt", lambda pack: "TEXT")
        seen = []

        def fake_call(messages, **kw):
            seen.append(messages)
            return GOOD_JSON

        monkeypatch.setattr(
            "investment_engine.blindtest.replay.call_deepseek", fake_call)
        stats = run_replay(["2026-06-01"], config_dir="x", out_path=out,
                           system_prompt=SYSTEM_PROMPT_V15, prompt_version="v15")
        assert stats["done"] == 1
        row = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
        assert row["prompt_version"] == "v15"
        assert seen[0][0]["content"] == SYSTEM_PROMPT_V15  # 用了覆盖的 prompt

    def test_run_replay_use_validation(self, tmp_path, monkeypatch):
        """use_validation=True 时走确定性校验层并在行内记录 validation。"""
        out = tmp_path / "results.jsonl"
        monkeypatch.setattr(
            "investment_engine.blindtest.replay.build_daily_pack", lambda day, **kw: {})
        monkeypatch.setattr(
            "investment_engine.blindtest.replay.pack_to_prompt", lambda pack: "TEXT")
        monkeypatch.setattr(
            "investment_engine.blindtest.replay.call_deepseek", lambda m, **kw: GOOD_JSON)
        stats = run_replay(["2026-06-01"], config_dir="x", out_path=out,
                           use_validation=True)
        assert stats["done"] == 1
        row = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
        assert row["validation"]["status"] == "passed"
