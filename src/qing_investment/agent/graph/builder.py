from __future__ import annotations

import logging
from langgraph.graph import END, StateGraph

logger = logging.getLogger(__name__)

from .edges import review_router
from .nodes import (
    citation_validator,
    devils_advocate,
    market_summary,
    parse_query,
    retrieve_knowledge,
    reviewer,
    stock_analyst,
    stock_scanner,
    style_writer,
    synthesize,
)
from .state import AgentState


def build_graph():
    logger.info("[build_graph] starting with %d nodes", 10)
    logger.info("[build_graph] topology: parse_query → retrieve_knowledge → market_summary → stock_scanner + stock_analyst → devils_advocate → synthesize → style_writer → citation_validator → reviewer → END")
    builder = StateGraph(AgentState)

    builder.add_node("parse_query", parse_query)
    builder.add_node("retrieve_knowledge", retrieve_knowledge)
    builder.add_node("market_summary", market_summary)
    builder.add_node("stock_scanner", stock_scanner)
    builder.add_node("stock_analyst", stock_analyst)
    builder.add_node("devils_advocate", devils_advocate)
    builder.add_node("synthesize", synthesize)
    builder.add_node("style_writer", style_writer)
    builder.add_node("citation_validator", citation_validator)
    builder.add_node("reviewer", reviewer)

    builder.set_entry_point("parse_query")
    builder.add_edge("parse_query", "retrieve_knowledge")
    builder.add_edge("retrieve_knowledge", "market_summary")
    builder.add_edge("retrieve_knowledge", "stock_analyst")
    builder.add_edge("market_summary", "stock_scanner")
    builder.add_edge("stock_scanner", "devils_advocate")
    builder.add_edge("stock_analyst", "devils_advocate")
    # devil's advocate 完成后 → synthesize
    builder.add_edge("devils_advocate", "synthesize")
    builder.add_edge("synthesize", "style_writer")
    builder.add_edge("style_writer", "citation_validator")
    builder.add_edge("citation_validator", "reviewer")
    builder.add_conditional_edges(
        "reviewer",
        review_router,
        {"pass": END, "fail": "style_writer"},
    )

    compiled = builder.compile()
    logger.info("[build_graph] compilation complete, nodes=%d", len([n for n in compiled.nodes]))
    return compiled
