from __future__ import annotations

from langgraph.graph import END, StateGraph

from .edges import review_router
from .nodes import (
    devils_advocate,
    market_analyst,
    parse_query,
    retrieve_knowledge,
    reviewer,
    stock_analyst,
    style_writer,
    synthesize,
)
from .state import AgentState


def build_graph():
    builder = StateGraph(AgentState)

    builder.add_node("parse_query", parse_query)
    builder.add_node("retrieve_knowledge", retrieve_knowledge)
    builder.add_node("market_analyst", market_analyst)
    builder.add_node("stock_analyst", stock_analyst)
    builder.add_node("devils_advocate", devils_advocate)  # Subtask 5 新增
    builder.add_node("synthesize", synthesize)
    builder.add_node("style_writer", style_writer)
    builder.add_node("reviewer", reviewer)

    builder.set_entry_point("parse_query")
    builder.add_edge("parse_query", "retrieve_knowledge")
    builder.add_edge("retrieve_knowledge", "market_analyst")
    builder.add_edge("retrieve_knowledge", "stock_analyst")
    # market_analyst 和 stock_analyst 并行完成后 → devils_advocate
    builder.add_edge("market_analyst", "devils_advocate")
    builder.add_edge("stock_analyst", "devils_advocate")
    # devil's advocate 完成后 → synthesize
    builder.add_edge("devils_advocate", "synthesize")
    builder.add_edge("synthesize", "style_writer")
    builder.add_edge("style_writer", "reviewer")
    builder.add_conditional_edges(
        "reviewer",
        review_router,
        {"pass": END, "fail": "style_writer"},
    )

    return builder.compile()
