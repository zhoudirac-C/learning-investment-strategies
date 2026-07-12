from __future__ import annotations

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


def _merge_reasoning(existing: list[str], new_steps: list[str]) -> list[str]:
    return existing + new_steps


def _merge_cost_tracking(existing: list[dict], new: list[dict]) -> list[dict]:
    """合并多个节点的成本追踪（并行节点累加）。"""
    if not existing and not new:
        return []
    total_calls = 0
    total_cost = __import__("decimal").Decimal("0")
    for d in existing + new:
        if isinstance(d, dict):
            total_calls += d.get("llm_calls", 0)
            try:
                total_cost += __import__("decimal").Decimal(d.get("total_cost_usd", "0"))
            except Exception:
                pass
    return [{"llm_calls": total_calls, "total_cost_usd": str(total_cost)}]


class AgentState(TypedDict, total=False):
    # 输入层
    query: str
    session_id: str
    trigger: dict | None
    alerts: list[dict]
    market_snapshot: dict
    positions: list[dict]
    watchlist: list[dict]
    parsed_intent: dict

    # 检索层
    claims: list[dict]
    wiki_snippets: list[dict]
    sector_context: list[dict]
    knowledge_graph: dict
    memories: list[dict]
    few_shot_examples: list[str]
    potential_conflicts: list[dict]  # 同一主题矛盾检测（P1）

    # 实时数据
    sector_strengths: list[dict]
    external_sector_boards: dict

    # Phase 2 新增：Context Builder 增强上下文
    stock_contexts: list[dict]  # 每只标的的 claims 摘要
    direction_signals: dict     # 方向优先级信号

    # Phase 2 新增：watchlist 分片输入
    watchlist_shard: dict | None  # 当前批次需要分析的标的子集

    # 【新增】数据降级标记
    _data_missing_note: str     # 实时数据缺失时的降级说明

    # 分析层
    market_context: dict
    # 拆分 market_analyst 后的中间状态：精简市场背景，供 stock_scanner 使用
    market_summary_context: dict | None
    stock_analysis: dict
    draft_analysis: str

    # 生成层
    styled_output: str
    citation_report: dict | None  # CitationValidator 校验报告
    review_notes: list[str]

    # 输出层
    final_output: str
    claims_cited: list[str]
    data_sources: list[str]
    confidence: str
    review_passed: bool
    reasoning_steps: Annotated[list[str], _merge_reasoning]

    # 成本追踪（Subtask 3 新增，Annotated reducer 实现在并行节点间累加）
    cost_tracking: Annotated[list[dict], _merge_cost_tracking]

    # Devin's Advocate 质疑点（Subtask 5 新增）
    devils_advocate_findings: list[dict]

    # 内部控制
    _retry_count: int
