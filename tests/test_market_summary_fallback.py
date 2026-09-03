"""market_summary 节点 fallback 可靠性测试（2026-08-11 早盘 3/5 次"未配置"摆烂归因驱动）。

覆盖：LLM 空返回（含重试一次）、JSON 解析失败、prompt 超上限——三条路径都必须
带 _fallback_reason 且 market_summary 含规则拼装的原始数据（情绪/板块/指数），
market_phase 保持"未配置"（daily_state 持久化守卫不动）。
"""

from __future__ import annotations

import pytest

from qing_investment.agent.graph import nodes

QUOTES = [
    {"label": "上证指数", "secid": "1.000001", "code": "000001",
     "pct_change": -0.13, "amount": "67565913"},
    {"label": "深证成指", "secid": "0.399001", "code": "399001",
     "pct_change": 0.44, "amount": "80777218"},
    {"label": "创业板指", "secid": "0.399006", "code": "399006",
     "pct_change": 1.13, "amount": "38662532"},
    {"label": "恩捷股份(002812.SZ)", "code": "002812", "pct_change": 0.71},
]
SENTIMENT = {"up_count": 1878, "down_count": 3443, "limit_up_count": 47,
             "limit_down_count": 0, "consecutive_height": 6,
             "broken_board_rate": 0.447}
ESB = {
    "available": True,
    "concept": {"leaders": [
        {"name": "被动元件", "pct_change": 4.29},
        {"name": "影视动漫", "pct_change": 2.51},
    ]},
    "industry": {"leaders": [
        {"name": "线下药店", "pct_change": 6.28},
        {"name": "石油和天然气开采业", "pct_change": 2.05},
    ]},
}
VALID_JSON = '{"market_phase": "回暖期", "phase_reasoning": "x", "main_themes": ["MLCC"]}'


def _state() -> dict:
    return {
        "trigger": {"id": "any_10:21"},
        "parsed_intent": {"analysis_type": "market"},
        "market_snapshot": {"quotes": QUOTES, "sentiment": SENTIMENT},
        "claims": [], "wiki_snippets": [],
        "external_sector_boards": ESB,
    }


@pytest.fixture
def patched(monkeypatch):
    """隔离 LLM 与外部副作用；calls 记录 _safe_llm_invoke 调用次数。"""
    calls = []
    monkeypatch.setattr(nodes, "_load_reasoning_patterns", lambda state: [])
    monkeypatch.setattr(nodes, "_load_framework_files", lambda analysis_type: [])
    monkeypatch.setattr(nodes, "_persist_daily_state_from_market_context",
                        lambda *a, **kw: None)
    monkeypatch.setattr(nodes, "_safe_llm_invoke", lambda prompt, **kw: calls.append(prompt) or "")
    return calls


class TestDegradedDigest:
    def test_digest_contains_all_blocks(self):
        out = nodes._build_degraded_digest(
            {"quotes": QUOTES, "sentiment": SENTIMENT}, ESB)
        text = out["summary_text"]
        assert "未加工原始数据" in text
        assert "上证指数-0.13%" in text and "创业板指+1.13%" in text
        assert "沪深合计约14834亿" in text  # (67565913+80777218)万 → 亿
        assert "涨停47" in text and "炸板率44.7%" in text and "涨1878/跌3443家" in text
        assert "被动元件+4.3%" in text and "线下药店+6.3%" in text
        assert out["emotion_signals"]["consecutive_height"] == 6

    def test_digest_tolerates_empty_input(self):
        out = nodes._build_degraded_digest({}, {})
        assert out["summary_text"] == "【未加工原始数据】"
        assert out["emotion_signals"] == {}


class TestMarketSummaryFallback:
    def test_llm_empty_retries_once_and_degrades(self, patched):
        result = nodes.market_summary(_state())["market_summary_context"]
        assert len(patched) == 2  # 空返回重试一次
        assert result["_fallback_reason"] == "llm_empty"
        assert result["market_phase"] == "未配置"  # 持久化守卫依赖该值，不变
        assert result["main_themes"] == []  # 不污染 direction_priority
        assert "涨停47" in result["market_summary"]
        assert "被动元件" in result["market_summary"]
        assert result["emotion_signals"]["limit_up_count"] == 47
        assert "LLM 子节点失败" in result["phase_reasoning"]

    def test_json_parse_error_distinguished(self, monkeypatch, patched):
        monkeypatch.setattr(nodes, "_safe_llm_invoke",
                            lambda prompt, **kw: "这不是JSON{{")
        result = nodes.market_summary(_state())["market_summary_context"]
        assert result["_fallback_reason"] == "json_parse_error"
        assert "涨1878/跌3443家" in result["market_summary"]

    def test_reasoning_step_carries_reason(self, patched):
        steps = nodes.market_summary(_state())["reasoning_steps"]
        assert "fallback: llm_empty" in steps[0]

    def test_success_after_retry(self, monkeypatch, patched):
        seq = iter(["", VALID_JSON])
        monkeypatch.setattr(nodes, "_safe_llm_invoke",
                            lambda prompt, **kw: next(seq))
        result = nodes.market_summary(_state())["market_summary_context"]
        assert result["market_phase"] == "回暖期"
        assert "_fallback_reason" not in result

    def test_missing_phase_reasoning_not_filled_with_sentinel(self, monkeypatch, patched):
        """LLM 成功但省略 phase_reasoning 时，不得用 fallback 哨兵串填充——
        该字段会持久化进 daily_state.market_stage.detail（2026-08-31 曾因此
        把 "LLM未返回结果或API未配置" 当作真实推理写入）。"""
        monkeypatch.setattr(nodes, "_safe_llm_invoke",
                            lambda prompt, **kw: '{"market_phase": "震荡", "main_themes": []}')
        result = nodes.market_summary(_state())["market_summary_context"]
        assert result["market_phase"] == "震荡"
        assert result["phase_reasoning"] == ""

    def test_prompt_too_large_path(self, monkeypatch, patched):
        monkeypatch.setattr(nodes, "_MAX_MARKET_SUMMARY_PROMPT_BYTES", 1)
        out = nodes.market_summary(_state())
        result = out["market_summary_context"]
        assert result["_fallback_reason"] == "prompt_too_large"
        assert "涨停47" in result["market_summary"]  # 降级摘要同样填充
        assert "fallback: prompt_too_large" in out["reasoning_steps"][0]


class TestDateAnchor:
    def test_today_injected_into_context(self, monkeypatch, patched):
        captured = {}

        def _spy(prompt, **kw):
            captured["prompt"] = prompt
            return VALID_JSON

        monkeypatch.setattr(nodes, "_safe_llm_invoke", _spy)
        nodes.market_summary(_state())
        assert '"today"' in captured["prompt"]
        assert "周" in captured["prompt"]
