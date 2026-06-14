"""Devil's Advocate — 反向质疑 Agent。

对标 AlphaAnalyst 的 Devil's Advocate 模式：
    - 强制使用与主分析不同家族的 LLM（默认 Kimi vs DeepSeek）
    - 输出结构化质疑点（target/concern/severity/confidence）
    - 不自行下结论，只找逻辑漏洞
"""

from __future__ import annotations

import json
import logging

from qing_investment.agent.base import Agent, AgentOutput

logger = logging.getLogger(__name__)


class DevilsAdvocateAgent(Agent):
    """对已有分析结论进行反向质疑。

    设计原则:
        - 强制使用与主分析不同的模型（主分析 DeepSeek → 这里用 Kimi）
        - 输出结构化质疑点，不自行下结论
        - 记录每个质疑点的置信度
        - 主分析失败不影响 DA 正常执行
    """

    name = "devils_advocate"

    def __init__(self, llm=None):
        super().__init__(llm=llm)
        self._target_model = "kimi"

    # ── 公开方法 ──

    async def run(self, **kwargs) -> AgentOutput:
        """对已有分析结论进行反向质疑。

        Args:
            market_analysis: 大盘分析文本
            stock_analysis: 个股分析文本
            claims_cited: 引用的 claim IDs

        Returns:
            AgentOutput，findings 为质疑点 JSON 数组
        """
        self._reset_stats()
        logger.info("[DevilsAdvocate] run: starting, target_model=%s", self._target_model)

        market_analysis = kwargs.get("market_analysis", "")
        stock_analysis = kwargs.get("stock_analysis", "")
        claims_cited = kwargs.get("claims_cited", [])
        logger.info("[DevilsAdvocate] run: market_len=%d stock_len=%d claims=%d",
                    len(market_analysis), len(stock_analysis), len(claims_cited))

        if not market_analysis and not stock_analysis:
            logger.warning("[DevilsAdvocate] run: no analysis to challenge, skipping")
            return self._build_output(
                findings=[],
                errors=["No analysis to challenge"],
            )

        try:
            prompt = self._build_prompt(market_analysis, stock_analysis, claims_cited)
            logger.info("[DevilsAdvocate] run: prompt_len=%d", len(prompt))
            content = self._invoke_llm(prompt)
            self._track_llm_call(provider=self._target_model)
            findings = self._parse_findings(content)
            logger.info("[DevilsAdvocate] run: findings=%d errors=%d", len(findings), 0)
            return self._build_output(findings=findings)
        except Exception as e:
            logger.error("[DevilsAdvocate] run: failed: %s", e, exc_info=True)
            return self._build_output(
                findings=[],
                errors=[f"Devil's Advocate failed: {e}"],
            )

    # ── 内部方法 ──

    def _build_prompt(
        self,
        market_analysis: str,
        stock_analysis: str,
        claims_cited: list[str],
    ) -> str:
        """构建 DA 提示词。"""
        lines = [
            "你是 Qing-Agent 的 Devil's Advocate（反向质疑者）。",
            "其他分析师已产出看多/看空结论。你的任务是:",
            "1. 找出分析中的逻辑漏洞和假设缺陷",
            "2. 针对 claims 引用提出替代解释",
            "3. 对数据时效性提出质疑",
            "4. 检查分析是否遗漏了关键风险因素",
            "5. 不自行下结论，只输出质疑点",
            "",
            "输出格式（严格JSON数组，不要markdown代码块）:",
            "[",
            '  {',
            '    "target": "质疑的对象（如 市场周期判断/个股地位）",',
            '    "concern": "具体质疑内容",',
            '    "severity": "high/medium/low",',
            '    "confidence": 0.85',
            "  }",
            "]",
            "",
            "注意：如果分析结论合理、逻辑严密，也应质疑其前提假设和时效性。",
        ]
        system_prompt = "\n".join(lines)
        return (
            f"{system_prompt}\n\n"
            f"## 大盘分析\n{market_analysis or '(无)'}\n\n"
            f"## 个股分析\n{stock_analysis or '(无)'}\n\n"
            f"## 引用 Claims\n{json.dumps(claims_cited, ensure_ascii=False)}"
        )

    def _invoke_llm(self, prompt: str) -> str:
        """调用 LLM。"""
        prompt_len = len(prompt)
        if self.llm is not None:
            logger.info("[DevilsAdvocate] _invoke_llm: using injected llm, prompt_len=%d", prompt_len)
            response = self.llm.chat([{"role": "user", "content": prompt}])
            content = response.get("content", "")
            logger.info("[DevilsAdvocate] _invoke_llm: response_len=%d", len(content))
            return content

        logger.info("[DevilsAdvocate] _invoke_llm: using get_llm_client(provider=%s), prompt_len=%d", self._target_model, prompt_len)
        from qing_investment.agent.tools.llm_client import get_llm_client

        llm = get_llm_client(provider=self._target_model)
        result = llm.invoke(prompt)
        content = result.content if hasattr(result, "content") else str(result)
        logger.info("[DevilsAdvocate] _invoke_llm: response_len=%d", len(content))
        return content

    def _parse_findings(self, content: str) -> list[dict]:
        """解析 LLM 响应为质疑点列表。"""
        if not content:
            logger.warning("[DevilsAdvocate] _parse_findings: empty content")
            return []

        # 尝试清理 markdown 代码块包裹
        cleaned = content.strip()
        had_markdown_fence = cleaned.startswith("```")
        if had_markdown_fence:
            cleaned = cleaned.split("\n", 1)[-1]
            if "```" in cleaned:
                cleaned = cleaned.rsplit("```", 1)[0]
            cleaned = cleaned.strip()

        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, list):
                logger.info("[DevilsAdvocate] _parse_findings: %d items (markdown_fence=%s)", len(parsed), had_markdown_fence)
                return parsed
            if isinstance(parsed, dict):
                logger.info("[DevilsAdvocate] _parse_findings: 1 item (dict) (markdown_fence=%s)", had_markdown_fence)
                return [parsed]
            logger.warning("[DevilsAdvocate] _parse_findings: unexpected type=%s", type(parsed).__name__)
            return []
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning("[DevilsAdvocate] _parse_findings: JSON decode failed: %s (len=%d)", e, len(content))
            return [{"target": "解析错误", "concern": content[:200], "severity": "low", "confidence": 0.3}]
