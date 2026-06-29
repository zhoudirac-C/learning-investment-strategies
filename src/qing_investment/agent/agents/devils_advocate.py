"""Devil's Advocate — 反向质疑 Agent。

对标 AlphaAnalyst 的 Devil's Advocate 模式：
    - 强制使用与主分析不同家族的 LLM（默认 Kimi vs DeepSeek）
    - 输出结构化质疑点（target/concern/severity/confidence）
    - 不自行下结论，只找逻辑漏洞
"""

from __future__ import annotations

import asyncio
import json
import logging

from qing_investment.agent.base import Agent, AgentOutput

logger = logging.getLogger(__name__)


class DevilsAdvocateAgent(Agent):
    """对已有分析结论进行反向质疑。

    设计原则:
        - 强制使用与主分析不同的模型（主分析 DeepSeek → 这里用 Zhipu GLM-4-Flash 免费版）
        - 输出结构化质疑点，不自行下结论
        - 记录每个质疑点的置信度
        - 主分析失败不影响 DA 正常执行
    """

    name = "devils_advocate"

    def __init__(self, llm=None):
        super().__init__(llm=llm)
        self._target_model = "deepseek"
        self._last_used_provider: str | None = None  # 实际使用的 provider（可能 fallback）
        self._used_provider: str | None = None        # 供外部查询

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
        self._last_used_provider = None
        self._used_provider = None
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
            content = await self._invoke_llm(prompt)
            # 记录实际使用的 provider（可能 fallback 过）
            actual_provider = self._last_used_provider or self._target_model
            self._track_llm_call(provider=actual_provider)
            self._used_provider = actual_provider  # 供外部查询
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

    async def _invoke_llm(self, prompt: str) -> str:
        """调用 LLM。兼容 ChatOpenAI.invoke() 和 LLMProtocol.chat()。

        支持 fallback：如果 Kimi 失败（API key 无效或网络问题），
        自动降级到 DeepSeek 以确保 Devil's Advocate 仍能输出。

        所有同步调用都通过 asyncio.to_thread 放到线程池执行，并加 60s 硬超时，
        避免在 async 事件循环中阻塞导致整个服务 hang 死。
        """
        prompt_len = len(prompt)

        # ── 情况1：外部注入了 llm（测试或替换场景）──
        if self.llm is not None:
            logger.info("[DevilsAdvocate] _invoke_llm: using injected llm, prompt_len=%d", prompt_len)
            if hasattr(self.llm, "chat") and callable(self.llm.chat):
                response = await asyncio.wait_for(
                    asyncio.to_thread(self.llm.chat, [{"role": "user", "content": prompt}]),
                    timeout=60.0,
                )
                content = response.get("content", "")
            elif hasattr(self.llm, "invoke") and callable(self.llm.invoke):
                result = await asyncio.wait_for(
                    asyncio.to_thread(self.llm.invoke, prompt),
                    timeout=60.0,
                )
                content = result.content if hasattr(result, "content") else str(result)
            else:
                logger.error("[DevilsAdvocate] _invoke_llm: llm has no chat() or invoke()")
                return ""
            logger.info("[DevilsAdvocate] _invoke_llm: response_len=%d", len(content))
            return content

        # ── 情况2：走配置的 provider（默认 Kimi），带 fallback ──
        from qing_investment.agent.tools.llm_client import get_llm_client

        fallback_order = [self._target_model, "kimi-coding", "zhipu"]
        last_error = None

        for idx, provider in enumerate(fallback_order):
            try:
                logger.info(
                    "[DevilsAdvocate] _invoke_llm: attempt %d/%d provider=%s",
                    idx + 1, len(fallback_order), provider,
                )
                llm = get_llm_client(provider=provider)
                result = await asyncio.wait_for(
                    asyncio.to_thread(llm.invoke, prompt),
                    timeout=60.0,
                )
                content = result.content if hasattr(result, "content") else str(result)
                if content and len(content) > 20:
                    self._last_used_provider = provider  # 记录成功 provider
                    logger.info(
                        "[DevilsAdvocate] _invoke_llm: success provider=%s response_len=%d",
                        provider, len(content),
                    )
                    return content
                else:
                    logger.warning(
                        "[DevilsAdvocate] _invoke_llm: short/empty response from %s (len=%d), trying fallback",
                        provider, len(content),
                    )
                    last_error = f"Empty/short response from {provider}"
            except Exception as e:
                logger.warning(
                    "[DevilsAdvocate] _invoke_llm: failed provider=%s error=%s, trying fallback",
                    provider, e,
                )
                last_error = str(e)

        logger.error(
            "[DevilsAdvocate] _invoke_llm: all providers failed. last_error=%s",
            last_error,
        )
        raise RuntimeError(
            f"Devil's Advocate LLM call failed on all providers: {last_error}"
        )

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
