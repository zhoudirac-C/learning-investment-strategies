"""DeepSeek 回放测试（mock client，不触网）。"""
import json
from types import SimpleNamespace

import pytest

from investment_engine.blindtest.replay import (
    PROMPT_VERSION, SYSTEM_PROMPT, build_messages, parse_result, run_replay,
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
        assert PROMPT_VERSION == "v2"
