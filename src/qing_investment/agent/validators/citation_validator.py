"""CitationValidator — 纯规则驱动的引用校验器.

职责：
1. 从 Agent 输出中提取数字型 claim（价格、百分比、成交量、市值等）
2. 检查每个数字 claim 是否有来源标注
3. 输出结构化报告（含覆盖率统计）

设计原则（from architecture-optimization-plan.md §更新5）：
- 不依赖 LLM，纯正则规则判断
- 可独立运行，不阻断主流程
- 与 LLM reviewer 职责分离：LLM 管语义，Validator 管格式
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterator


# ── 数字 claim 检测正则 ──────────────────────────────────────────
# 匹配：价格(元)、百分比(%)、成交量/市值(亿/万/手)、倍数(x/倍)、区间(30.5-31.0元)
_NUMERIC_PATTERN = re.compile(
    r"""
    (?:
        # 区间价格：30.5-31.0元、73-76区间
        \d+(?:\.\d+)?\s*[\-~至]\s*\d+(?:\.\d+)?\s*(?:元|块|人民币|USD|美元|港元|港币| EUR|欧元|区间)?
        |
        # 价格：30.5元、31.0块
        \d+(?:\.\d+)?\s*(?:元|块|人民币|USD|美元|港元|港币| EUR|欧元)
        |
        # 百分比：+3.5%、下跌5%、涨幅超10%
        [+-]?\d+(?:\.\d+)?\s*%+
        |
        # 成交量/市值：500亿、3000万手、1.2万亿
        \d+(?:\.\d+)?\s*(?:亿|万|千|百万|千万|万亿|兆)\s*(?:手|股|元|美元|市值|成交额|成交量)?
        |
        # 倍数：3倍、2.5x、赔率3:1
        \d+(?:\.\d+)?\s*(?:倍|x|X)(?!\w)
        |
        # 比率：3:1、1:2.5
        \d+(?:\.\d+)?\s*:\s*\d+(?:\.\d+)?
        |
        # 纯数字+量词（在中文语境中常是数据 claim）
        \d{4,}\s*(?:亿|万|千|百万|千万|万亿|兆)
    )
    """,
    re.VERBOSE,
)

# 更宽松的数字提取（用于段落定位）
_LOOSE_NUMBER = re.compile(r"\d+(?:\.\d+)?(?:\s*[\-~至]\s*\d+(?:\.\d+)?)?")

# ── 来源标注检测正则 ─────────────────────────────────────────────
# 有效来源格式（按优先级排序）
_CITATION_PATTERNS = [
    re.compile(r"（来源：[^）]+）"),           # （来源：framework/xxx.md）
    re.compile(r"（数据：[^）]+）"),           # （数据：xxx）
    re.compile(r"（[^）]*claim[\-\w]+[^）]*）"),  # （claim-xxx）
    re.compile(r"claim-\d{8}-\d{3}-[a-z]"),   # claim ID 直接引用
    re.compile(r"##\s*参考来源"),              # ## 参考来源 段落标记
    re.compile(r"`[^`]+`\s*来源"),           # `xxx` 来源
    re.compile(r"(?:据|根据|来源于|来自)[^，。；\n]{2,30}"),  # 据xxx、根据xxx
]

# 段落分隔符
_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n|\n(?=[\d一二三四五六七八九十]、|#+\s)")


@dataclass
class CitationIssue:
    """单条引用问题."""

    section: str          # 所在段落/章节标题
    claim_text: str       # 问题 claim 的文本片段
    issue_type: str       # missing_citation | stale_data | format_error
    suggestion: str       # 修复建议


@dataclass
class CitationReport:
    """引用校验报告."""

    valid: bool                       # 是否通过（coverage >= 阈值）
    issues: list[CitationIssue] = field(default_factory=list)
    coverage: float = 0.0             # 有来源标注的 claim 比例 (0-1)
    total_claims: int = 0             # 检测到的数字 claim 总数
    cited_claims: int = 0             # 有来源标注的 claim 数


class CitationValidator:
    """纯规则驱动的引用校验器.

    使用方式：
        validator = CitationValidator()
        report = validator.validate(text)
        if not report.valid:
            for issue in report.issues:
                print(issue)
    """

    # 覆盖率阈值：低于此值视为不通过
    COVERAGE_THRESHOLD: float = 0.6

    # 忽略段落（这些段落通常不需要数字来源）
    SKIP_SECTIONS: tuple[str, ...] = (
        "操作建议",
        "风险提示",
        "免责声明",
        "情绪判断",
        "个人看法",
        "主观判断",
    )

    def __init__(self, coverage_threshold: float | None = None) -> None:
        self.coverage_threshold = coverage_threshold or self.COVERAGE_THRESHOLD

    # ── 公共 API ──────────────────────────────────────────────────

    def validate(self, text: str) -> CitationReport:
        """对完整文本执行引用校验."""
        issues: list[CitationIssue] = []
        total_claims = 0
        cited_claims = 0

        for section, paragraph in self._iter_sections(text):
            if self._should_skip_section(section):
                continue

            for claim_text in self._extract_claims(paragraph):
                total_claims += 1
                has_citation = self._has_citation(paragraph, claim_text)

                if has_citation:
                    cited_claims += 1
                else:
                    issues.append(
                        CitationIssue(
                            section=section[:80],
                            claim_text=claim_text[:120],
                            issue_type="missing_citation",
                            suggestion=f'为 "{claim_text[:40]}..." 添加来源标注，如（来源：framework/xxx.md）或 claim ID',
                        )
                    )

        coverage = cited_claims / total_claims if total_claims > 0 else 1.0
        valid = coverage >= self.coverage_threshold or total_claims == 0

        return CitationReport(
            valid=valid,
            issues=issues,
            coverage=coverage,
            total_claims=total_claims,
            cited_claims=cited_claims,
        )

    def quick_check(self, text: str) -> bool:
        """快速检查：只返回是否通过，不生成详细报告."""
        return self.validate(text).valid

    # ── 内部方法 ──────────────────────────────────────────────────

    def _iter_sections(self, text: str) -> Iterator[tuple[str, str]]:
        """将文本拆分为段落，返回 (章节标题, 段落内容)."""
        paragraphs = _PARAGRAPH_SPLIT.split(text)
        current_section = "正文"

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            # 检测章节标题
            heading_match = re.search(r"^(?:#{1,4}\s+|[一二三四五六七八九十]、)(.+)", para)
            if heading_match:
                current_section = heading_match.group(1).strip()
                # 标题段落本身也作为内容检查（可能含数字）
                yield current_section, para
            else:
                yield current_section, para

    def _should_skip_section(self, section: str) -> bool:
        """判断该章节是否跳过引用检查."""
        section_lower = section.lower()
        return any(skip in section_lower for skip in self.SKIP_SECTIONS)

    def _extract_claims(self, paragraph: str) -> Iterator[str]:
        """从段落中提取数字 claim."""
        # 使用严格模式匹配
        for match in _NUMERIC_PATTERN.finditer(paragraph):
            claim = match.group(0).strip()
            # 过滤掉纯日期、时间、编号
            if self._is_numerical_claim(claim):
                yield claim

    def _is_numerical_claim(self, text: str) -> bool:
        """判断文本片段是否属于需要来源标注的数字 claim.

        排除：
        - 纯日期（2024年、06-15）
        - 纯时间（14:30、09:00）
        - 序号（1.、2、（3））
        - 页码/编号
        """
        # 纯日期模式
        if re.match(r"^\d{4}[年/\-]\d{1,2}[月/\-]?\d{0,2}[日]?$", text):
            return False
        # 纯时间模式
        if re.match(r"^\d{1,2}:\d{2}(?::\d{2})?$", text):
            return False
        # 纯序号
        if re.match(r"^[（(]?\d+[)）]?[.、]?$", text):
            return False
        # 纯年份
        if re.match(r"^\d{4}[年]?$", text):
            return False
        # 必须包含数字+量词/单位
        if not re.search(r"\d.*(?:元|块|%|亿|万|千|手|股|倍|x|X|:)", text, re.IGNORECASE):
            return False
        return True

    def _has_citation(self, paragraph: str, claim_text: str) -> bool:
        """检查 claim 附近是否有来源标注.

        策略：
        1. 引用必须出现在 claim 之前（同一句/分句内，前80字符）
           或紧邻之后（后20字符内）
        2. 跨句的引用不算（避免同段落中前面句子的引用被后面句子借用）
        """
        claim_pos = paragraph.find(claim_text)
        if claim_pos < 0:
            return False

        # 前80字符，但只取到最近的句号/分号/换行（避免跨句）
        before_start = max(0, claim_pos - 80)
        before_raw = paragraph[before_start:claim_pos]
        # 从后往前找最近的句末标点，只保留该标点之后的内容
        for split_char in "。；\n":
            idx = before_raw.rfind(split_char)
            if idx >= 0:
                before_raw = before_raw[idx + 1:]
                break
        before = before_raw

        # 后40字符：引用必须在紧邻 claim 之后（中文括号+来源可能较长）
        after_end = min(len(paragraph), claim_pos + len(claim_text) + 40)
        after = paragraph[claim_pos:after_end]

        for pattern in _CITATION_PATTERNS:
            if pattern.search(before) or pattern.search(after):
                return True

        return False

    # ── 格式化输出 ───────────────────────────────────────────────

    @staticmethod
    def format_report(report: CitationReport) -> str:
        """将报告格式化为人类可读文本."""
        lines = [
            f"📊 Citation 校验报告",
            f"━━━━━━━━━━━━━━━━━━━━",
            f"总数: {report.total_claims} | 有引用: {report.cited_claims} | 覆盖率: {report.coverage:.1%}",
            f"状态: {'✅ 通过' if report.valid else '❌ 未通过'} (阈值: 60%)",
            "",
        ]

        if report.issues:
            lines.append(f"⚠️ 发现 {len(report.issues)} 个问题：")
            for i, issue in enumerate(report.issues[:10], 1):  # 最多显示10条
                lines.append(
                    f"  {i}. [{issue.issue_type}] {issue.claim_text[:50]}...\n"
                    f"     建议: {issue.suggestion[:80]}"
                )
            if len(report.issues) > 10:
                lines.append(f"  ... 还有 {len(report.issues) - 10} 个问题未显示")

        return "\n".join(lines)


# ── 便捷函数 ────────────────────────────────────────────────────

def validate_citations(text: str, threshold: float = 0.6) -> CitationReport:
    """一键校验函数."""
    validator = CitationValidator(coverage_threshold=threshold)
    return validator.validate(text)
