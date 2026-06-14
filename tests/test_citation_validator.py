"""Tests for CitationValidator.

覆盖场景：
- 正例：数字 claim 有来源标注
- 反例：数字 claim 无来源标注
- 边界：日期/时间/序号不应被检测为 claim
- 覆盖率计算
- 章节跳过（操作建议/风险提示等）
"""

import pytest

from qing_investment.agent.validators.citation_validator import (
    CitationIssue,
    CitationReport,
    CitationValidator,
    validate_citations,
)


# ── 正例 ─────────────────────────────────────────────────────────

class TestPositiveCases:
    """数字 claim 有正确来源标注的场景."""

    def test_price_with_framework_source(self):
        text = "万泽股份回调到30.5-31.0元是买点（来源：framework/operation-rules.md）。"
        report = validate_citations(text)
        assert report.valid is True
        assert report.coverage == 1.0
        assert len(report.issues) == 0

    def test_percentage_with_data_source(self):
        text = "燃气轮机板块涨幅超5%（数据：东方财富板块数据 2024-06-14）。"
        report = validate_citations(text)
        assert report.valid is True
        assert report.coverage == 1.0

    def test_claim_id_citation(self):
        text = """
## 个股分析

万泽股份(000534) 当前价格 31.5 元，建议仓位 0.5 成。
依据 claim-20260611-002 的买点判断。

## 参考来源
- claim-20260611-002: 万泽股份回调到30.5-31.0是买点
"""
        report = validate_citations(text)
        # 31.5元、0.5成 都应有引用（段落含 claim ID 和 ## 参考来源）
        assert report.coverage >= 0.5

    def test_multiple_claims_all_cited(self):
        text = """
## 市场数据

上证指数涨 0.5%（数据：新浪财经）。
深成指跌 1.2%（数据：新浪财经）。
成交额 8500 亿（数据：东方财富）。
"""
        report = validate_citations(text)
        assert report.valid is True
        assert report.coverage == 1.0
        assert report.total_claims >= 3


# ── 反例 ─────────────────────────────────────────────────────────

class TestNegativeCases:
    """数字 claim 缺少来源标注的场景."""

    def test_price_without_citation(self):
        text = "万泽股份回调到30.5-31.0元是买点。"
        report = validate_citations(text)
        assert report.valid is False
        assert report.coverage == 0.0
        assert len(report.issues) >= 1
        assert report.issues[0].issue_type == "missing_citation"

    def test_percentage_without_citation(self):
        text = "燃气轮机板块涨幅超5%，建议关注。"
        report = validate_citations(text)
        assert report.valid is False
        assert len(report.issues) >= 1

    def test_mixed_cited_and_uncited(self):
        text = """
## 分析

上证指数涨 0.5%（数据：新浪财经）。
深成指跌 1.2%。
"""
        report = validate_citations(text)
        # 0.5% 有引用，1.2% 无引用 → 覆盖率 50%
        assert report.coverage == 0.5
        assert len(report.issues) == 1
        assert "1.2%" in report.issues[0].claim_text

    def test_volume_without_citation(self):
        text = "今日成交额突破 8500 亿元，市场情绪回暖。"
        report = validate_citations(text)
        assert report.valid is False
        assert any("8500" in issue.claim_text for issue in report.issues)


# ── 边界：不应被检测为 claim ─────────────────────────────────────

class TestBoundaryCases:
    """日期、时间、序号等不应被误判为数字 claim."""

    def test_date_not_claim(self):
        text = "2024年6月14日，市场开盘。"
        report = validate_citations(text)
        # 2024年 不应被检测为 claim
        assert report.total_claims == 0
        assert report.valid is True

    def test_time_not_claim(self):
        text = "14:30 出现异动，建议关注。"
        report = validate_citations(text)
        assert report.total_claims == 0

    def test_sequence_number_not_claim(self):
        text = """
1. 第一点分析
2. 第二点分析
（3）补充说明
"""
        report = validate_citations(text)
        # 序号不应被检测
        assert all("1." not in issue.claim_text for issue in report.issues)
        assert all("2." not in issue.claim_text for issue in report.issues)

    def test_year_not_claim(self):
        text = "2024年股市表现良好。"
        report = validate_citations(text)
        assert report.total_claims == 0


# ── 章节跳过 ─────────────────────────────────────────────────────

class TestSectionSkip:
    """操作建议、风险提示等章节应跳过检查."""

    def test_operation_section_skipped(self):
        text = """
## 操作建议

在 31.0 元买入 0.5 成仓，止损 30.0 元。

## 数据分析

万泽股份 PE 25 倍（数据：同花顺 F10）。
"""
        report = validate_citations(text)
        # 操作建议中的数字不应被检测
        # 数据分析中的 25 倍应有引用
        assert report.valid is True

    def test_risk_section_skipped(self):
        text = """
## 风险提示

若跌破 30 元支撑位，需果断止损。

## 基本面

营收增长 15%（来源：2023年报）。
"""
        report = validate_citations(text)
        assert report.valid is True


# ── 覆盖率阈值 ───────────────────────────────────────────────────

class TestCoverageThreshold:
    """覆盖率阈值行为."""

    def test_custom_threshold_pass(self):
        text = "A涨 1%（来源：X）。B跌 2%。"  # 50% 覆盖率
        validator = CitationValidator(coverage_threshold=0.4)
        report = validator.validate(text)
        assert report.valid is True  # 50% >= 40%

    def test_custom_threshold_fail(self):
        text = "A涨 1%（来源：X）。B跌 2%。"  # 50% 覆盖率
        validator = CitationValidator(coverage_threshold=0.6)
        report = validator.validate(text)
        assert report.valid is False  # 50% < 60%

    def test_no_claims_always_pass(self):
        text = "今天天气不错，市场氛围良好。"
        report = validate_citations(text)
        assert report.valid is True
        assert report.coverage == 1.0


# ── 格式化输出 ───────────────────────────────────────────────────

class TestFormatReport:
    """报告格式化."""

    def test_format_passed(self):
        text = "涨 5%（来源：X）。"
        report = validate_citations(text)
        formatted = CitationValidator.format_report(report)
        assert "✅ 通过" in formatted
        assert "覆盖率" in formatted

    def test_format_failed(self):
        text = "涨 5%。"
        report = validate_citations(text)
        formatted = CitationValidator.format_report(report)
        assert "❌ 未通过" in formatted
        assert "missing_citation" in formatted


# ── 集成：模拟真实 Agent 输出 ─────────────────────────────────────

class TestRealAgentOutput:
    """模拟真实 Agent 分析输出."""

    def test_full_analysis_with_citations(self):
        text = """
## 大盘判断

当前处于调整第17天（来源：framework/market-cycle.md），接近尾声。
上证指数 3050 点，成交额 7200 亿（数据：新浪财经 2024-06-14 14:30）。

## 板块机会

燃气轮机方向类比上一轮锂电池（claim-20240601-001），机构都要买。
杰瑞股份(002353) 当前 35.2 元，PE 18 倍（数据：同花顺 F10）。

## 个股机会

万泽股份(000534) 回调到 30.5-31.0 元是买点（来源：claim-20260611-002）。
建议仓位 0.5 成，止损 30.0 元，赔率 3:1。

## 参考来源
- framework/market-cycle.md
- claim-20240601-001
- claim-20260611-002
"""
        report = validate_citations(text)
        # 大部分数字应有引用
        assert report.coverage >= 0.6

    def test_full_analysis_missing_citations(self):
        text = """
## 大盘判断

当前处于调整第17天，接近尾声。
上证指数 3050 点，成交额 7200 亿。

## 板块机会

燃气轮机方向类比上一轮锂电池，机构都要买。
杰瑞股份 35.2 元，PE 18 倍。

## 个股机会

万泽股份回调到 30.5-31.0 元是买点。
建议仓位 0.5 成，止损 30.0 元，赔率 3:1。
"""
        report = validate_citations(text)
        # 无引用 → 应不通过
        assert report.valid is False
        assert report.coverage == 0.0
        assert len(report.issues) >= 5


# ── 便捷函数 ─────────────────────────────────────────────────────

class TestConvenienceFunctions:
    """便捷函数行为."""

    def test_quick_check_true(self):
        text = "涨 5%（来源：X）。"
        assert CitationValidator().quick_check(text) is True

    def test_quick_check_false(self):
        text = "涨 5%。"
        assert CitationValidator().quick_check(text) is False
