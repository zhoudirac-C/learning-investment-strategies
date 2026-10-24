"""Tests for claim_direction：LLM 判向（direction 字段标注）。

scope（spec 2026-10-24-m3-outcome-writeback）：
- 输入 claim 的 statement/source_date/related_stocks
- 输出 {value: bullish|bearish|neutral, basis_kind, basis_code, rationale}
- basis_code 股票代码规范化（600519→600519.SH）；index 缺省落 sh000300
- parse 容错：```fence、越界 value 降级 neutral、缺键补默认
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from investment_engine.claim_direction import (  # noqa: E402
    ANNOTATOR,
    annotate_claim,
    build_direction_prompt,
    parse_direction_response,
)


class _LLM:
    def __init__(self, payload):
        self._payload = payload
        self.prompts = []

    def invoke(self, prompt):
        class _R:
            def __init__(self, content):
                self.content = content
        self.prompts.append(prompt)
        return _R(self._payload if isinstance(self._payload, str)
                  else json.dumps(self._payload, ensure_ascii=False))


def _claim(**kw):
    base = {
        "id": "claim-x",
        "source_date": "2026-10-17",
        "claim_type": "stock-view",
        "subject": "测试主题",
        "statement": "看好某标的后续表现",
        "related_stocks": [{"code": "600519", "name": "贵州茅台"}],
        "stance": "view",
    }
    base.update(kw)
    return base


class TestPrompt:
    def test_prompt_contains_key_fields(self):
        p = build_direction_prompt(_claim())
        assert "看好某标的后续表现" in p
        assert "2026-10-17" in p
        assert "600519" in p
        assert "bullish" in p and "bearish" in p and "neutral" in p

    def test_prompt_regime_uses_index_default(self):
        p = build_direction_prompt(_claim(claim_type="market-cycle",
                                          related_stocks=[]))
        assert "sh000300" in p


class TestParse:
    def test_plain_json(self):
        d = parse_direction_response(
            '{"value": "bullish", "basis_kind": "stock", "basis_code": "600519", "rationale": "看多"}')
        assert d["value"] == "bullish"

    def test_code_fence(self):
        d = parse_direction_response(
            '```json\n{"value": "bearish", "basis_kind": "index", "basis_code": "sh000300", "rationale": "x"}\n```')
        assert d["value"] == "bearish"

    def test_out_of_enum_downgraded_to_neutral(self):
        d = parse_direction_response(
            '{"value": "very_bullish", "basis_kind": "stock", "basis_code": "1", "rationale": "x"}')
        assert d["value"] == "neutral"

    def test_missing_keys_filled(self):
        d = parse_direction_response('{}')
        assert d["value"] == "neutral"
        assert d["basis_kind"] in ("stock", "index")

    def test_garbage_returns_neutral(self):
        d = parse_direction_response("不是 JSON")
        assert d["value"] == "neutral"

    def test_index_default_code(self):
        d = parse_direction_response(
            '{"value": "bullish", "basis_kind": "index", "basis_code": "", "rationale": "x"}')
        assert d["basis_code"] == "sh000300"


class TestAnnotate:
    def test_stock_code_normalized(self):
        llm = _LLM({"value": "bullish", "basis_kind": "stock",
                    "basis_code": "600519", "rationale": "看多"})
        d = annotate_claim(_claim(), llm)
        assert d["value"] == "bullish"
        assert d["basis_code"] == "600519.SH"
        assert d["annotator"] == ANNOTATOR
        assert d["annotated_at"]

    def test_neutral_kept(self):
        llm = _LLM({"value": "neutral", "basis_kind": "stock",
                    "basis_code": "600519", "rationale": "方法论非方向"})
        assert annotate_claim(_claim(), llm)["value"] == "neutral"

    def test_error_response_degrades_gracefully(self):
        llm = _LLM("garbage<<<")
        d = annotate_claim(_claim(), llm)
        assert d["value"] == "neutral"
        assert "解析失败" in (d.get("rationale") or "")
