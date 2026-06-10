from __future__ import annotations

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


def _merge_reasoning(existing: list[str], new_steps: list[str]) -> list[str]:
    return existing + new_steps


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

    # 【新增】数据降级标记
    _data_missing_note: str     # 实时数据缺失时的降级说明

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
    reasoning_steps: Annotated[list[str], _merge_reasoning]

    # 内部控制
    _retry_count: int
