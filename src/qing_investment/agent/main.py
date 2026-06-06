from __future__ import annotations

import re

from fastapi import FastAPI

from qing_investment.agent.graph.builder import build_graph
from qing_investment.agent.models.schemas import (
    ChatRequest,
    ChatResponse,
    TriggerRequest,
    TriggerResponse,
)
from qing_investment.agent.tools.llm_client import get_embedding_model, get_llm_client
from qing_investment.agent.tools.mem0_client import Mem0ClientWrapper
from qing_investment.agent.tools.neo4j_client import Neo4jClient
from qing_investment.agent.tools.qdrant_client import QdrantClientWrapper

app = FastAPI(title="Qing-Agent", version="0.1.0")
graph = build_graph()


# ── 轻量级关键词提取（用于 /chat 的 Neo4j claims 检索） ──
_STOP_WORDS: set[str] = {
    "什么是", "怎么", "如何", "分析一下", "告诉我", "请问",
    "一下", "的", "了", "吗", "呢", "啊", "吧", "吗",
}
_SECTOR_KEYWORDS: dict[str, list[str]] = {
    "光互连": ["光互连", "光互联", "光模块", "CPO", "光纤", "光通信", "光芯片"],
    "半导体": ["半导体", "芯片", "存储", "封测", "光刻", "设备", "材料"],
    "AI": ["AI", "算力", "大模型", "智能体", "Agent", "AIPC"],
    "机器人": ["机器人", "具身智能", "人形机器人", "特斯拉", "Optimus"],
    "电力": ["电力", "煤炭", "红利", "高股息", "绿电"],
    "新能源": ["新能源", "光伏", "锂电", "储能", "风电"],
    "资源": ["铜", "铝", "锂", "稀土", "黄金", "煤炭", "硫磺"],
}


def _extract_keywords(text: str) -> list[str]:
    """从用户查询中提取可用于 Neo4j claims 检索的关键词。"""
    # 去掉常见疑问前缀
    cleaned = text.strip()
    for sw in sorted(_STOP_WORDS, key=len, reverse=True):
        cleaned = cleaned.replace(sw, "")
    cleaned = cleaned.strip()
    # 去掉标点和数字
    cleaned = re.sub(r"[^\u4e00-\u9fa5a-zA-Z]", " ", cleaned)
    tokens = [t for t in cleaned.split() if len(t) >= 2]
    # 去重保留
    seen: set[str] = set()
    result: list[str] = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            result.append(t)
    return result


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
        "sector_strengths": req.sector_strengths,
        "external_sector_boards": req.external_sector_boards,
        "sector_context": [],
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
    """Chat endpoint with memory + knowledge-base retrieval."""
    mem0 = Mem0ClientWrapper()
    memories = mem0.search(req.message, user_id=req.session_id)

    # ── 知识库检索（新增）──
    wiki_snippets: list[dict] = []
    claims: list[dict] = []

    try:
        qdrant = QdrantClientWrapper()
        emb_model = get_embedding_model()
        if emb_model:
            vec = emb_model.encode(req.message).tolist()[0]
            results = qdrant.search(vec, collection="qing_knowledge", limit=5)
            wiki_snippets = [
                {
                    "text": r.payload.get("text", ""),
                    "source": r.payload.get("source_path", ""),
                    "source_type": r.payload.get("source_type", ""),
                }
                for r in results
            ]
    except Exception:
        pass

    try:
        neo4j = Neo4jClient()
        keywords = _extract_keywords(req.message)
        # 也尝试用板块关键词做更精准的 claims 检索
        for cluster_kws in _SECTOR_KEYWORDS.values():
            for kw in cluster_kws:
                if kw in req.message and kw not in keywords:
                    keywords.append(kw)
        seen_ids: set[str] = set()
        for kw in keywords[:3]:  # 最多查 3 个关键词，避免过多
            batch = neo4j.get_claims_by_keyword(kw, limit=5)
            for c in batch:
                cid = c.get("id")
                if cid and cid not in seen_ids:
                    seen_ids.add(cid)
                    claims.append(c)
            if len(claims) >= 10:
                break
        neo4j.close()
    except Exception:
        pass

    # ── 构建增强 prompt ──
    context_parts = []

    # ── 【修改】区分方法论内容与历史观点 ──
    # wiki_snippets: 只保留framework和方法论相关内容
    methodology_wiki = [
        s for s in wiki_snippets
        if s.get("source", "").startswith("framework/") or "投资方法论" in s.get("source", "")
    ]
    # claims: 只保留方法论相关的claim
    methodology_claims = []
    for c in claims:
        stmt = (c.get("statement") or "").lower()
        subj = (c.get("subject") or "").lower()
        if any(kw in stmt or kw in subj for kw in [
            "框架", "周期", "方法论", "规则", "纪律", "策略", "体系",
            "冰点", "回暖", "高潮", "退潮", "轮动", "主线", "扩散",
        ]):
            methodology_claims.append(c)

    if methodology_wiki:
        context_parts.append("【博主分析方法论】（仅供参考UP的分析框架和概念定义，不得作为当前判断依据）")
        for s in methodology_wiki:
            src = s["source"].replace("framework/", "[框架] ").replace("knowledge/wiki/", "[Wiki] ")
            context_parts.append(f"- {src}: {s['text'][:300]}")

    if methodology_claims:
        context_parts.append("【博主历史观点卡】（⚠️ 历史观点，仅供参考，不得作为当前判断依据）")
        for c in methodology_claims:
            context_parts.append(f"- {c.get('id', 'N/A')} ({c.get('source_date','')}): {c.get('statement', '')[:200]}")

    if memories:
        context_parts.append("【用户历史记忆】")
        for m in memories:
            content = m.get("content", "") if isinstance(m, dict) else str(m)
            context_parts.append(f"- {content}")

    prompt_lines = [
        "你是青枫浦上Q的助手，风格犀利但不劝赌，不用机构研报腔。",
        "【核心原则】",
        "1. 所有判断必须基于用户提供的实时数据或当前市场事实，不能基于历史观点",
        "2. 【博主分析方法论】是UP的分析框架和概念定义（如冰点期、劣性轮动等），可以引用作为方法论指导",
        "3. 【博主历史观点卡】是历史观点，仅供参考，不得作为当前判断的依据",
        "4. 禁止引用claim ID支持当前观点",
        "5. 如果用户没有提供实时数据，请明确说明无法获取实时数据，不要编造",
        "6. 如果知识库中没有相关信息，请明确说明，不要编造",
        *context_parts,
        f"\n用户：{req.message}\n",
        "请直接回复：",
    ]
    prompt = "\n".join(prompt_lines)

    try:
        llm = get_llm_client()
        reply = llm.invoke(prompt).content or ""
    except Exception as e:
        reply = f"[服务暂时不可用] {e}"

    return ChatResponse(
        reply=reply,
        memories_used=memories if memories else [],
    )


@app.post("/memory/add")
async def add_memory(session_id: str, content: str, memory_type: str = "fact"):
    """Add a memory entry. Falls back to local JSON if mem0 server unavailable."""
    mem0 = Mem0ClientWrapper()
    result = mem0.add(
        content=content,
        user_id=session_id,
        metadata={"memory_type": memory_type},
    )
    return {"status": "ok", "result": result}
