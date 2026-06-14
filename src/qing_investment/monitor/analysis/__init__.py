"""Qing-Agent 监控引擎 — 分析引擎层 (Phase 4)

将 stock_monitor.py 中的 AI 分析逻辑（7节点 LangGraph）拆分为独立的分析模块。

设计原则:
    1. 节点独立：每个节点只负责一个分析步骤
    2. 接口统一：所有节点接收 AgentState，返回 AgentState
    3. 向后兼容：现有 nodes.py 的函数签名不变
    4. 可替换：任何节点可被自定义实现替换

架构:
    ┌─────────────────────────────────────────┐
    │           AnalysisEngine                │
    │  ┌─────────────┐  ┌─────────────────┐ │
    │  │  QueryParser │  │  MarketAnalyst  │ │
    │  │  (意图解析)  │  │  (市场分析)      │ │
    │  └─────────────┘  └─────────────────┘ │
    │  ┌─────────────┐  ┌─────────────────┐ │
    │  │  StockAnalyst│  │  StyleWriter     │ │
    │  │  (个股分析)  │  │  (风格化写作)    │ │
    │  └─────────────┘  └─────────────────┘ │
    │  ┌─────────────┐  ┌─────────────────┐ │
    │  │  Reviewer    │  │  ReviewRouter    │ │
    │  │  (事实核查)  │  │  (路由判断)      │ │
    │  └─────────────┘  └─────────────────┘ │
    └─────────────────────────────────────────┘

使用:
    from qing_investment.monitor.analysis import AnalysisEngine
    
    engine = AnalysisEngine()
    result = engine.run(state, analysis_type="market")
    # result 包含 final_output 和 reasoning_steps
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Callable

from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
_CN_TZ = ZoneInfo("Asia/Shanghai")


# ──────────────────────────────────────────
# 数据模型
# ──────────────────────────────────────────


class AgentState(dict):
    """Agent 状态字典（向后兼容）。"""

    pass


@dataclass
class AnalysisResult:
    """分析结果。"""

    final_output: str
    reasoning_steps: list[str]
    market_context: dict | None = None
    stock_analysis: dict | None = None
    review_passed: bool = False
    review_notes: list[str] = field(default_factory=list)
    confidence: str = "medium"
    duration_ms: int = 0


# ──────────────────────────────────────────
# Prompt 加载
# ──────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[4]
_PROMPT_DIR = _REPO_ROOT / "src" / "qing_investment" / "agent" / "prompts" / "system"


def _load_prompt(name: str) -> str:
    """加载 prompt 模板。"""
    path = _PROMPT_DIR / f"{name}.txt"
    if not path.exists():
        return f"[Prompt {name} not found]"
    content = path.read_text(encoding="utf-8")
    # 自动注入交易者人格
    mindset_path = _PROMPT_DIR / "trader_mindset.txt"
    if mindset_path.exists() and name in ("market_analyst", "stock_analyst"):
        mindset = mindset_path.read_text(encoding="utf-8")
        content = f"{mindset}\n\n---\n\n{content}"
    return content


def _load_analysis_framework() -> str:
    """加载市场分析框架 prompt 片段。"""
    path = _PROMPT_DIR / "market_analysis_framework.txt"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return "[market_analysis_framework.txt not found]"


# ──────────────────────────────────────────
# LLM 调用
# ──────────────────────────────────────────


def _safe_llm_invoke(prompt: str) -> str:
    """安全调用 LLM，缺失 API key 时返回空字符串。"""
    try:
        from qing_investment.agent.tools.llm_client import get_llm_client
        llm = get_llm_client()
        return llm.invoke(prompt).content
    except Exception:
        return ""


# ──────────────────────────────────────────
# 节点基类
# ──────────────────────────────────────────


class AnalysisNode:
    """分析节点基类。"""

    name: str = "node"

    def run(self, state: AgentState) -> AgentState:
        """执行节点逻辑。"""
        raise NotImplementedError


# ──────────────────────────────────────────
# 1. 查询解析节点 (QueryParser)
# ──────────────────────────────────────────


class QueryParser(AnalysisNode):
    """意图解析节点：从用户输入提取分析类型、标的、紧急程度。"""

    name = "query_parser"

    def run(self, state: AgentState) -> AgentState:
        query = state.get("query", "")
        prompt = f"""从以下输入中提取信息，返回严格JSON格式（不要markdown代码块）：
- stock_code: 股票代码（如有，如 300394）
- analysis_type: stock(个股) / market(市场) / portfolio(持仓复盘)
- urgency: scheduled(定时) / event(事件触发)
- focus: 用户关注的具体问题

输入：{query}
"""
        content = _safe_llm_invoke(prompt)
        try:
            parsed = json.loads(content) if content else {}
        except json.JSONDecodeError:
            parsed = {}

        if not parsed:
            parsed = {
                "stock_code": None,
                "analysis_type": "stock",
                "urgency": "scheduled",
                "focus": query,
            }

        return {
            "parsed_intent": parsed,
            "reasoning_steps": [f"意图解析: {parsed.get('analysis_type', 'unknown')}, 标的: {parsed.get('stock_code', 'N/A')}"],
        }


# ──────────────────────────────────────────
# 2. 市场分析节点 (MarketAnalyst)
# ──────────────────────────────────────────


class MarketAnalyst(AnalysisNode):
    """市场分析节点：分析大盘周期、板块强度、情绪信号。"""

    name = "market_analyst"

    def __init__(self, max_quotes: int = 50):
        self.max_quotes = max_quotes

    def run(self, state: AgentState) -> AgentState:
        _t0 = time.time()
        prompt_template = _load_prompt("market_analyst")
        analysis_type = (state.get("parsed_intent") or {}).get("analysis_type", "stock")

        # 获取市场快照
        market_snapshot = dict(state.get("market_snapshot") or {})
        quotes = market_snapshot.get("quotes", []) or []

        # 截断行情数据
        if len(quotes) > self.max_quotes:
            quotes = self._filter_quotes(quotes, state)
            market_snapshot["quotes"] = quotes

        # 构建上下文
        context = self._build_context(state, market_snapshot)

        prompt = f"""{prompt_template}

{state.get("_data_missing_note", "")}

检索到的知识：
{json.dumps(context, ensure_ascii=False, indent=2)}

当前持仓：
{json.dumps(state.get('positions', []), ensure_ascii=False, indent=2)}

请输出JSON：
"""
        content = _safe_llm_invoke(prompt)
        _t1 = time.time()
        logger.info(f"market_analyst: duration={_t1-_t0:.1f}s prompt_len={len(prompt)}")

        try:
            result = json.loads(content) if content else {}
        except json.JSONDecodeError:
            result = {}

        if not result:
            result = {
                "market_phase": "未配置",
                "phase_reasoning": "LLM未返回结果或API未配置",
                "main_themes": [],
                "sector_strength": {},
                "emotion_signals": {},
                "opportunity_scan": [],
                "position_plans": [],
            }

        return {
            "market_context": result,
            "reasoning_steps": [f"市场周期: {result.get('market_phase', 'N/A')}"],
        }

    def _filter_quotes(self, quotes: list[dict], state: AgentState) -> list[dict]:
        """截断行情数据，保留关键标的。"""
        codes_to_keep: set[str] = set()

        # 保留指数
        for q in quotes:
            label = q.get("label") or ""
            name = q.get("name") or ""
            if "指数" in label or "指数" in name or label in ("上证指数", "深证成指", "创业板指", "科创50"):
                codes_to_keep.add(q.get("secid", ""))
                codes_to_keep.add(q.get("code", ""))

        # 保留持仓和watchlist
        for p in state.get("positions", []) or []:
            code = str(p.get("code", "")).replace(".SH", "").replace(".SZ", "")
            if code:
                codes_to_keep.add(code)
        for w in state.get("watchlist", []) or []:
            code = str(w.get("code", "")).replace(".SH", "").replace(".SZ", "")
            if code:
                codes_to_keep.add(code)

        # 保留Top 15 movers
        sorted_quotes = sorted(
            [q for q in quotes if isinstance(q, dict)],
            key=lambda x: abs(x.get("pct_change", 0) or 0),
            reverse=True,
        )
        for q in sorted_quotes[:15]:
            codes_to_keep.add(q.get("secid", ""))
            codes_to_keep.add(q.get("code", ""))

        return [q for q in quotes if q.get("secid", "") in codes_to_keep or q.get("code", "") in codes_to_keep]

    def _build_context(self, state: AgentState, market_snapshot: dict) -> dict:
        """构建市场分析上下文。"""
        # 过滤claims（只保留方法论）
        claims = state.get("claims", [])
        methodology_claims = self._filter_methodology_only(claims)

        # 过滤wiki（只保留framework）
        wiki_snippets = state.get("wiki_snippets", [])
        methodology_wiki = [
            s for s in wiki_snippets
            if s.get("source", "").startswith("framework/") or "投资方法论" in s.get("source", "")
        ]

        # 加载框架文件
        framework_context = self._load_framework_files("market")

        # 加载推理模式
        reasoning_patterns = self._load_reasoning_patterns(state)

        return {
            "claims": methodology_claims,
            "wiki_snippets": methodology_wiki,
            "framework_rules": framework_context,
            "reasoning_patterns": reasoning_patterns,
            "market_snapshot": market_snapshot,
            "sector_strengths": state.get("sector_strengths", []),
            "external_sector_boards": state.get("external_sector_boards", {}),
            "sector_context": state.get("sector_context", []),
            "memories": state.get("memories", []),
            "stock_contexts": state.get("stock_contexts", []),
            "direction_signals": state.get("direction_signals", {}),
            "watchlist_summary": state.get("watchlist_summary", []),
            "reference_stocks": state.get("reference_stocks", []),
        }

    def _filter_methodology_only(self, claims: list[dict]) -> list[dict]:
        """过滤claims，只保留方法论相关的。"""
        methodology_keywords = {
            "框架", "周期", "方法论", "规则", "纪律", "策略", "体系",
            "冰点", "回暖", "高潮", "退潮", "轮动", "主线", "扩散",
            "upstream", "downstream", "产业链", "估值", "仓位",
        }
        filtered = []
        for c in claims:
            stmt = (c.get("statement") or "").lower()
            if any(kw in stmt for kw in methodology_keywords):
                filtered.append(c)
                continue
            subj = (c.get("subject") or "").lower()
            if any(kw in subj for kw in methodology_keywords):
                filtered.append(c)
                continue
            ct = c.get("claim_type", "")
            days = c.get("days_ago", 999)
            if ct == "market-cycle" and days <= 7:
                filtered.append(c)
        return filtered

    def _load_framework_files(self, analysis_type: str) -> list[dict]:
        """加载框架文件。"""
        loaders = {
            "market": ["market-cycle-framework.md", "sector-diffusion-framework.md", "trading-rules.md", "market-breadth-framework.md"],
            "stock": ["stock-analysis-playbook.md", "technical-analysis-framework.md", "trading-rules.md"],
            "portfolio": ["trading-rules.md", "market-cycle-framework.md", "sector-diffusion-framework.md"],
        }
        files = loaders.get(analysis_type, [])
        result = []
        for fname in files:
            path = _REPO_ROOT / "framework" / fname
            if path.exists():
                content = path.read_text(encoding="utf-8")
                result.append({
                    "file": fname,
                    "content": content[:4000],
                    "truncated": len(content) > 4000,
                })
        return result

    def _load_reasoning_patterns(self, state: AgentState) -> list[dict]:
        """加载推理模式（简化版，实际应调用完整逻辑）。"""
        # 这里简化处理，实际应调用 nodes.py 中的 _load_reasoning_patterns
        return state.get("reasoning_patterns", [])


# ──────────────────────────────────────────
# 3. 个股分析节点 (StockAnalyst)
# ──────────────────────────────────────────


class StockAnalyst(AnalysisNode):
    """个股分析节点：分析个股地位、赔率、触发条件。"""

    name = "stock_analyst"

    def run(self, state: AgentState) -> AgentState:
        stock_code = state.get("parsed_intent", {}).get("stock_code")
        analysis_type = state.get("parsed_intent", {}).get("analysis_type", "stock")

        # 跳过非个股查询
        if analysis_type in ("market", "portfolio") or not stock_code:
            return {
                "stock_analysis": {},
                "reasoning_steps": ["个股分析: 跳过（market/portfolio查询或无标的）"],
            }

        prompt_template = _load_prompt("stock_analyst")
        market_snapshot = state.get("market_snapshot", {})
        watchlist = state.get("watchlist", [])
        stock_name = self._get_stock_name(stock_code, market_snapshot, watchlist)

        # 构建上下文
        context = {
            "stock_code": stock_code,
            "stock_name": stock_name,
            "positions": state.get("positions", []),
            "watchlist": watchlist,
            "claims": state.get("claims", []),
            "market_context": state.get("market_context", {}),
            "stock_context": self._get_stock_context(state, stock_code),
            "direction_signals": state.get("direction_signals", {}),
        }

        prompt = f"""{prompt_template}

上下文：
{json.dumps(context, ensure_ascii=False, indent=2)}

请输出JSON：
"""
        content = _safe_llm_invoke(prompt)
        try:
            result = json.loads(content) if content else {}
        except json.JSONDecodeError:
            result = {}

        if not result:
            result = {
                "stock_code": stock_code or "N/A",
                "stock_name": "N/A",
                "stock_role": "未配置",
                "role_reasoning": "LLM未返回结果或API未配置",
                "bullish_evidence": [],
                "bearish_evidence": [],
                "odds_analysis": {},
                "trigger_conditions": "未配置",
                "invalidation_conditions": "未配置",
                "risk_notes": "",
            }

        return {
            "stock_analysis": result,
            "reasoning_steps": [f"个股地位: {result.get('stock_role', 'N/A')}"],
        }

    def _get_stock_name(self, stock_code: str, market_snapshot: dict, watchlist: list[dict]) -> str:
        """获取股票名称。"""
        for q in market_snapshot.get("quotes", []) or []:
            if q.get("code") == stock_code or q.get("secid") == stock_code:
                return q.get("name", "")
        for w in watchlist or []:
            if w.get("code") == stock_code:
                return w.get("name", "")
        return ""

    def _get_stock_context(self, state: AgentState, stock_code: str) -> dict | None:
        """从 stock_contexts 中找到当前标的的增强上下文。"""
        for ctx in state.get("stock_contexts", []) or []:
            if ctx.get("stock_code") == stock_code:
                return ctx
        return None


# ──────────────────────────────────────────
# 4. 风格化写作节点 (StyleWriter)
# ──────────────────────────────────────────


class StyleWriter(AnalysisNode):
    """风格化写作节点：将分析结果转为大白话输出。"""

    name = "style_writer"

    def run(self, state: AgentState) -> AgentState:
        prompt_template = _load_prompt("style_writer")
        market_context = state.get("market_context", {})
        stock_analysis = state.get("stock_analysis", {})

        # 构建输入
        analysis_input = {
            "market": market_context,
            "stock": stock_analysis,
        }

        prompt = f"""{prompt_template}

分析结果：
{json.dumps(analysis_input, ensure_ascii=False, indent=2)}

请输出：
"""
        content = _safe_llm_invoke(prompt)
        if not content:
            content = "[分析完成，但LLM未返回输出]"

        return {
            "draft_output": content,
            "reasoning_steps": ["风格化写作: 完成"],
        }


# ──────────────────────────────────────────
# 5. 事实核查节点 (Reviewer)
# ──────────────────────────────────────────


class Reviewer(AnalysisNode):
    """事实核查节点：检查输出中的事实错误。"""

    name = "reviewer"

    def __init__(self, max_retries: int = 3):
        self.max_retries = max_retries

    def run(self, state: AgentState) -> AgentState:
        _t0 = time.time()
        prompt_template = _load_prompt("reviewer")
        output = state.get("draft_output", "")
        retry_count = state.get("_retry_count", 0)

        # 构建claims引用列表
        claims = state.get("claims", [])
        claims_list = []
        for c in claims[:10]:
            claims_list.append({
                "id": c.get("id", ""),
                "subject": c.get("subject", ""),
                "statement": c.get("statement", "")[:100],
                "source_date": c.get("source_date", ""),
            })

        prompt = f"""{prompt_template}

待核查输出：
{output}

参考claims（最多10条）：
{json.dumps(claims_list, ensure_ascii=False, indent=2)}

请输出JSON：
"""
        content = _safe_llm_invoke(prompt)
        _t1 = time.time()

        try:
            result = json.loads(content) if content else {}
        except json.JSONDecodeError:
            result = {}

        passed = result.get("passed", False)
        raw_issues = result.get("issues", []) or []
        review_notes = []
        for item in raw_issues:
            if isinstance(item, str):
                review_notes.append(item)
            elif isinstance(item, dict):
                review_notes.append(json.dumps(item, ensure_ascii=False))
            else:
                review_notes.append(str(item))

        logger.info(
            f"reviewer: passed={passed} retry={retry_count} "
            f"issues={len(raw_issues)} duration={_t1-_t0:.1f}s"
        )

        return {
            "review_passed": passed,
            "review_notes": review_notes,
            "claims_cited": result.get("verified_claims", []),
            "confidence": "high" if passed else "low",
            "final_output": output if passed else "",
            "reasoning_steps": [f"事实核查: {'通过' if passed else '未通过'}"],
        }


# ──────────────────────────────────────────
# 6. 路由判断节点 (ReviewRouter)
# ──────────────────────────────────────────


class ReviewRouter:
    """路由判断：根据review结果决定下一步。"""

    name = "review_router"

    def route(self, state: AgentState) -> str:
        """返回路由决策："pass" | "fail" | "retry"。"""
        passed = state.get("review_passed", False)
        if passed:
            logger.info("review_router: passed → end")
            return "pass"

        retry_count = state.get("_retry_count", 0)
        if retry_count >= 3:
            logger.info(f"review_router: retry={retry_count} max reached → force pass")
            return "pass"

        logger.info(f"review_router: retry={retry_count} → back to style_writer")
        return "fail"


# ──────────────────────────────────────────
# 7. 分析引擎统一入口
# ──────────────────────────────────────────


class AnalysisEngine:
    """分析引擎统一入口。

    Usage:
        engine = AnalysisEngine()
        result = engine.run(state, analysis_type="market")
        print(result.final_output)
    """

    def __init__(self):
        self.query_parser = QueryParser()
        self.market_analyst = MarketAnalyst()
        self.stock_analyst = StockAnalyst()
        self.style_writer = StyleWriter()
        self.reviewer = Reviewer()
        self.router = ReviewRouter()

    def run(self, state: AgentState, analysis_type: str | None = None) -> AnalysisResult:
        """执行完整分析流程。

        流程:
            1. 查询解析
            2. 市场分析（如果是market/portfolio）
            3. 个股分析（如果是stock且指定了标的）
            4. 风格化写作
            5. 事实核查
            6. 路由判断（未通过则重试）
        """
        _t0 = time.time()
        steps: list[str] = []

        # 1. 查询解析
        parse_result = self.query_parser.run(state)
        state.update(parse_result)
        steps.extend(parse_result.get("reasoning_steps", []))

        # 确定分析类型
        if analysis_type is None:
            analysis_type = state.get("parsed_intent", {}).get("analysis_type", "stock")

        # 2. 市场分析
        if analysis_type in ("market", "portfolio"):
            market_result = self.market_analyst.run(state)
            state.update(market_result)
            steps.extend(market_result.get("reasoning_steps", []))

        # 3. 个股分析
        if analysis_type in ("stock", "portfolio"):
            stock_result = self.stock_analyst.run(state)
            state.update(stock_result)
            steps.extend(stock_result.get("reasoning_steps", []))

        # 4-6. 写作 + 审查 + 路由（支持重试）
        retry_count = 0
        while retry_count < 3:
            # 风格化写作
            writer_result = self.style_writer.run(state)
            state.update(writer_result)

            # 事实核查
            review_result = self.reviewer.run(state)
            state.update(review_result)
            steps.extend(review_result.get("reasoning_steps", []))

            # 路由判断
            route = self.router.route(state)
            if route == "pass":
                break

            # 重试
            retry_count += 1
            state["_retry_count"] = retry_count
            steps.append(f"第{retry_count}次重试")

        _t1 = time.time()
        duration_ms = int((_t1 - _t0) * 1000)

        return AnalysisResult(
            final_output=state.get("final_output", state.get("draft_output", "")),
            reasoning_steps=steps,
            market_context=state.get("market_context"),
            stock_analysis=state.get("stock_analysis"),
            review_passed=state.get("review_passed", False),
            review_notes=state.get("review_notes", []),
            confidence=state.get("confidence", "medium"),
            duration_ms=duration_ms,
        )

    def run_node(self, node_name: str, state: AgentState) -> AgentState:
        """运行单个节点（用于调试或自定义流程）。"""
        nodes: dict[str, AnalysisNode] = {
            "query_parser": self.query_parser,
            "market_analyst": self.market_analyst,
            "stock_analyst": self.stock_analyst,
            "style_writer": self.style_writer,
            "reviewer": self.reviewer,
        }
        node = nodes.get(node_name)
        if not node:
            raise ValueError(f"Unknown node: {node_name}")
        return node.run(state)


# ──────────────────────────────────────────
# 向后兼容：委托函数
# ──────────────────────────────────────────


def parse_query(state: AgentState) -> AgentState:
    """向后兼容：委托给 QueryParser。"""
    return QueryParser().run(state)


def market_analyst(state: AgentState) -> AgentState:
    """向后兼容：委托给 MarketAnalyst。"""
    return MarketAnalyst().run(state)


def stock_analyst(state: AgentState) -> AgentState:
    """向后兼容：委托给 StockAnalyst。"""
    return StockAnalyst().run(state)


def style_writer(state: AgentState) -> AgentState:
    """向后兼容：委托给 StyleWriter。"""
    return StyleWriter().run(state)


def reviewer(state: AgentState) -> AgentState:
    """向后兼容：委托给 Reviewer。"""
    return Reviewer().run(state)


def review_router(state: AgentState) -> str:
    """向后兼容：委托给 ReviewRouter。"""
    return ReviewRouter().route(state)
