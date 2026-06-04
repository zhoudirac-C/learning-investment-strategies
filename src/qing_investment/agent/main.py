from __future__ import annotations

from fastapi import FastAPI

from qing_investment.agent.graph.builder import build_graph
from qing_investment.agent.models.schemas import (
    ChatRequest,
    ChatResponse,
    TriggerRequest,
    TriggerResponse,
)

app = FastAPI(title="Qing-Agent", version="0.1.0")
graph = build_graph()


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


@app.post("/analyze/trigger", response_model=TriggerResponse)
async def analyze_trigger(req: TriggerRequest):
    state = {
        "query": req.query or f"{req.trigger.get('title', '')}：{req.trigger.get('reason', '')}",
        "session_id": req.session_id,
        "trigger": req.trigger,
        "alerts": req.alerts,
        "market_snapshot": req.market_snapshot,
        "positions": req.positions,
        "watchlist": req.watchlist,
        "claims": [],
        "wiki_snippets": [],
        "knowledge_graph": {},
        "memories": [],
        "few_shot_examples": [],
        "market_context": {},
        "stock_analysis": {},
        "draft_analysis": "",
        "styled_output": "",
        "review_notes": [],
        "final_output": "",
        "claims_cited": [],
        "data_sources": [],
        "confidence": "medium",
        "review_passed": False,
        "reasoning_steps": [],
    }

    result = await graph.ainvoke(state)

    return TriggerResponse(
        final_output=result.get("final_output", ""),
        claims_cited=result.get("claims_cited", []),
        data_sources=result.get("data_sources", []),
        confidence=result.get("confidence", "medium"),
        review_passed=result.get("review_passed", False),
        reasoning_steps=result.get("reasoning_steps", []),
    )


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    return ChatResponse(reply="chat stub")


@app.post("/memory/add")
async def add_memory(session_id: str, content: str, memory_type: str = "fact"):
    return {"status": "ok"}
