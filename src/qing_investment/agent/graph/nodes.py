from __future__ import annotations

import json

from qing_investment.agent.tools.llm_client import get_llm_client
from .state import AgentState


def parse_query(state: AgentState) -> AgentState:
    """意图解析：从用户输入中提取股票代码、分析类型等。"""
    query = state.get("query", "")
    llm = get_llm_client()
    prompt = f"""从以下输入中提取信息，返回严格JSON格式（不要markdown代码块）：
- stock_code: 股票代码（如有，如 300394）
- analysis_type: stock(个股) / market(市场) / portfolio(持仓复盘)
- urgency: scheduled(定时) / event(事件触发)
- focus: 用户关注的具体问题

输入：{query}
"""
    try:
        resp = llm.invoke(prompt)
        parsed = json.loads(resp.content)
    except Exception:
        parsed = {"stock_code": None, "analysis_type": "stock", "urgency": "scheduled", "focus": query}

    return {
        **state,
        "parsed_intent": parsed,
        "reasoning_steps": [f"意图解析: {parsed.get('analysis_type', 'unknown')}, 标的: {parsed.get('stock_code', 'N/A')}"],
    }


def retrieve_knowledge(state: AgentState) -> AgentState:
    """知识检索：并行查询 Neo4j + Qdrant + Mem0。（Stub：后续填充）"""
    return {
        **state,
        "claims": [],
        "wiki_snippets": [],
        "knowledge_graph": {},
        "memories": [],
        "few_shot_examples": [],
        "reasoning_steps": state.get("reasoning_steps", []) + ["知识检索: stub（待实现）"],
    }


def market_analyst(state: AgentState) -> AgentState:
    """市场分析：判断周期、主线、板块。（Stub：后续填充）"""
    return {
        **state,
        "market_context": {"market_phase": "未配置", "main_themes": []},
        "reasoning_steps": state.get("reasoning_steps", []) + ["市场分析: stub（待实现）"],
    }


def stock_analyst(state: AgentState) -> AgentState:
    """个股分析：判断地位、技术、基本面。（Stub：后续填充）"""
    return {
        **state,
        "stock_analysis": {"stock_role": "未配置"},
        "reasoning_steps": state.get("reasoning_steps", []) + ["个股分析: stub（待实现）"],
    }


def synthesize(state: AgentState) -> AgentState:
    """综合合成：合并市场+个股分析。"""
    market = state.get("market_context", {})
    stock = state.get("stock_analysis", {})
    draft = f"【周期定位】{market.get('market_phase', 'N/A')}\n【个股地位】{stock.get('stock_role', 'N/A')}"
    return {
        **state,
        "draft_analysis": draft,
        "reasoning_steps": state.get("reasoning_steps", []) + ["综合合成完成"],
    }


def style_writer(state: AgentState) -> AgentState:
    """风格化：注入UP人格。（Stub：后续填充）"""
    draft = state.get("draft_analysis", "")
    return {
        **state,
        "styled_output": f"[UP风格化] {draft}",
        "reasoning_steps": state.get("reasoning_steps", []) + ["风格化: stub（待实现）"],
    }


def reviewer(state: AgentState) -> AgentState:
    """事实核查：检查无条件指令、claim引用、矛盾。（Stub：后续填充）"""
    output = state.get("styled_output", "")
    has_forbidden = "无条件买入" in output or "无条件卖出" in output
    return {
        **state,
        "review_passed": not has_forbidden,
        "review_notes": ["检测到无条件指令"] if has_forbidden else [],
        "claims_cited": [],
        "data_sources": [],
        "confidence": "medium",
        "final_output": output,
        "reasoning_steps": state.get("reasoning_steps", []) + [f"事实核查: {'通过' if not has_forbidden else '未通过'}"],
    }
