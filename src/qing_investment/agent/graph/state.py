from __future__ import annotations

from typing import TypedDict


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
    knowledge_graph: dict
    memories: list[dict]
    few_shot_examples: list[str]

    # 分析层
    market_context: dict
    stock_analysis: dict
    draft_analysis: str

    # 生成层
    styled_output: str
    review_notes: list[str]

    # 输出层
    final_output: str
    claims_cited: list[str]
    data_sources: list[str]
    confidence: str
    review_passed: bool
    reasoning_steps: list[str]

    # 内部控制
    _retry_count: int
