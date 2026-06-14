"""Devil's Advocate 单元测试。"""
from __future__ import annotations

import json

from qing_investment.agent.agents.devils_advocate import DevilsAdvocateAgent
from qing_investment.agent.graph.nodes import (
    _format_devils_advocate_block,
    _market_ctx_summary,
    _stock_analysis_summary,
)


class TestDevilsAdvocateAgent:
    """DevilsAdvocateAgent 单元测试（不调 LLM）。"""

    def test_no_analysis_returns_error(self):
        """无分析输入时返回 error 而不是崩溃。"""
        agent = DevilsAdvocateAgent(llm=None)

        async def _run():
            return await agent.run()

        import asyncio
        output = asyncio.run(_run())
        assert len(output.errors) > 0
        assert "No analysis" in output.errors[0]
        assert output.agent_name == "devils_advocate"
        assert output.llm_calls == 0

    def test_parse_findings_valid_json(self):
        """解析合法 JSON 返回正确列表。"""
        agent = DevilsAdvocateAgent(llm=None)
        content = json.dumps([
            {"target": "周期判断", "concern": "量能判断标准不清晰", "severity": "medium", "confidence": 0.7},
        ])
        findings = agent._parse_findings(content)
        assert len(findings) == 1
        assert findings[0]["target"] == "周期判断"
        assert findings[0]["severity"] == "medium"

    def test_parse_findings_markdown_wrapped(self):
        """LLM 用 markdown 代码块包裹 JSON 时能正常解析。"""
        agent = DevilsAdvocateAgent(llm=None)
        content = "```json\n[{\"target\": \"测试\", \"concern\": \"内容\", \"severity\": \"high\", \"confidence\": 0.9}]\n```"
        findings = agent._parse_findings(content)
        assert len(findings) == 1
        assert findings[0]["target"] == "测试"

    def test_parse_findings_invalid_json(self):
        """非法 JSON 不崩溃，返回兜底质疑点。"""
        agent = DevilsAdvocateAgent(llm=None)
        content = "这不是 JSON，只是 LLM 返回的普通文本"
        findings = agent._parse_findings(content)
        assert len(findings) == 1
        assert findings[0]["target"] == "解析错误"
        assert findings[0]["confidence"] == 0.3

    def test_parse_findings_empty(self):
        """空内容返回空列表。"""
        agent = DevilsAdvocateAgent(llm=None)
        assert agent._parse_findings("") == []
        assert agent._parse_findings(None) == []


class TestAnalysisSummaryHelpers:
    """分析摘要提取测试。"""

    def test_market_ctx_summary(self):
        ctx = {
            "market_phase": "磨底期",
            "phase_reasoning": "缩量震荡",
            "main_themes": ["半导体", "AI算力"],
            "risk_notes": "北向资金持续流出",
        }
        summary = _market_ctx_summary(ctx)
        assert "磨底期" in summary
        assert "半导体" in summary
        assert "AI算力" in summary
        assert "北向" in summary

    def test_market_ctx_summary_empty(self):
        summary = _market_ctx_summary({})
        assert "N/A" in summary

    def test_stock_analysis_summary(self):
        analysis = {
            "stock_role": "板块龙头",
            "bullish_evidence": ["放量突破", "主力净流入"],
            "bearish_evidence": ["上方压力位"],
        }
        summary = _stock_analysis_summary(analysis)
        assert "板块龙头" in summary
        assert "放量突破" in summary
        assert "上方压力位" in summary

    def test_stock_analysis_summary_empty(self):
        summary = _stock_analysis_summary({})
        assert "N/A" in summary


class TestFormatDevilsAdvocateBlock:
    """质疑点格式化测试。"""

    def test_empty_findings(self):
        result = _format_devils_advocate_block({"devils_advocate_findings": []})
        assert result == ""

    def test_no_findings_key(self):
        result = _format_devils_advocate_block({})
        assert result == ""

    def test_single_finding(self):
        result = _format_devils_advocate_block({
            "devils_advocate_findings": [
                {"target": "周期判断", "concern": "量能不足", "severity": "high", "confidence": 0.85},
            ]
        })
        assert "⚠️ 反向质疑" in result
        assert "🔴" in result
        assert "周期判断" in result
        assert "量能不足" in result

    def test_multiple_findings(self):
        result = _format_devils_advocate_block({
            "devils_advocate_findings": [
                {"target": "A", "concern": "X", "severity": "high", "confidence": 0.9},
                {"target": "B", "concern": "Y", "severity": "low", "confidence": 0.4},
            ]
        })
        assert result.count("\n") >= 3  # 标题 + 2条质疑
        assert "🔴" in result
        assert "⚪" in result
