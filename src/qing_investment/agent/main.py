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
    """Chat endpoint with memory + knowledge-base retrieval + real-time data fetching."""
    mem0 = Mem0ClientWrapper()
    memories = mem0.search(req.message, user_id=req.session_id)

    # ── 知识库检索 ──
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
        for cluster_kws in _SECTOR_KEYWORDS.values():
            for kw in cluster_kws:
                if kw in req.message and kw not in keywords:
                    keywords.append(kw)
        seen_ids: set[str] = set()
        for kw in keywords[:3]:
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

    # ── 【新增】主动获取实时数据 ──
    market_snapshot: dict = {"quotes": []}
    external_sector_boards: dict = {"available": False}
    fetched_stock_code: str | None = None

    # 1. 检测查询类型
    query_lower = req.message.lower()
    is_market_query = any(kw in query_lower for kw in ["大盘", "市场", "行情", "指数", "上证", "创业板", "科创"])
    is_sector_query = any(kw in query_lower for kw in ["板块", "行业", "概念"])
    is_stock_query = any(kw in query_lower for kw in ["股", "走势", "分析", "低点", "高点", "买入", "卖出", "抄底", "减仓", "加仓", "持仓", "套牢", "解套", "止损", "止盈", "目标价", "支撑", "压力"])
    
    # 2. 提取股票代码
    import re
    stock_code_match = re.search(r'(\d{6})', req.message)
    if stock_code_match:
        fetched_stock_code = stock_code_match.group(1)
    
    # 2.1 如果没有提取到代码，从持仓配置中匹配股票名称
    if not fetched_stock_code:
        try:
            import yaml
            positions_path = "/home/ubuntu/learning-investment-strategies/config/stock_monitor/positions.yaml"
            with open(positions_path, "r", encoding="utf-8") as f:
                positions_data = yaml.safe_load(f)
            
            for account in positions_data.get("accounts", []):
                for pos in account.get("positions", []):
                    name = pos.get("name", "")
                    code = pos.get("code", "")
                    if name and code and name in req.message:
                        fetched_stock_code = code.replace(".SZ", "").replace(".SH", "").replace(".sz", "").replace(".sh", "")
                        break
                if fetched_stock_code:
                    break
        except Exception:
            pass
    
    # 3. 获取指数/大盘数据（如果是市场相关查询 或 个股查询也需要大盘环境）
    if is_market_query or is_sector_query or is_stock_query or not fetched_stock_code:
        try:
            from qing_investment.agent.tools.stock_data import fetch_index_quotes
            index_quotes = fetch_index_quotes()
            market_snapshot["quotes"] = index_quotes
            market_snapshot["date"] = ""
        except Exception:
            pass
    
    # 4. 获取板块数据（如果是板块相关查询）
    if is_sector_query or is_market_query:
        try:
            from qing_investment.agent.tools.sector_data import get_sector_strength_snapshot
            sector_data = get_sector_strength_snapshot(top_n=15)
            external_sector_boards = {
                "available": True,
                **sector_data,
            }
        except Exception:
            external_sector_boards = {"available": False, "error": "板块数据获取失败"}
    
    # 5. 获取个股数据（如果提取到股票代码，或明确是股票分析类查询）
    stock_klines: list[dict] = []
    stock_intraday: list[dict] = []
    if fetched_stock_code or is_stock_query:
        try:
            from qing_investment.agent.tools.stock_data import fetch_single_stock, fetch_stock_kline, fetch_stock_intraday
            # 优先使用提取到的代码，否则尝试从名称匹配（简化版）
            code_to_fetch = fetched_stock_code
            if not code_to_fetch:
                # 尝试从常见股票名称映射（可扩展）
                name_to_code = {
                    "中国长城": "000066",
                    "贵州茅台": "600519",
                    "比亚迪": "002594",
                    "宁德时代": "300750",
                }
                for name, code in name_to_code.items():
                    if name in req.message:
                        code_to_fetch = code
                        break
            if code_to_fetch:
                # 获取实时行情
                stock_quote = fetch_single_stock(code_to_fetch)
                if stock_quote:
                    market_snapshot["quotes"].append(stock_quote)
                # 获取历史K线（90日）
                stock_klines = fetch_stock_kline(code_to_fetch, days=90)
                # 获取当日分时
                stock_intraday = fetch_stock_intraday(code_to_fetch)
        except Exception:
            pass

    # ── 过滤知识库内容（只保留方法论） ──
    methodology_wiki = [
        s for s in wiki_snippets
        if s.get("source", "").startswith("framework/") or "投资方法论" in s.get("source", "")
    ]
    methodology_claims = []
    for c in claims:
        stmt = (c.get("statement") or "").lower()
        subj = (c.get("subject") or "").lower()
        if any(kw in stmt or kw in subj for kw in [
            "框架", "周期", "方法论", "规则", "纪律", "策略", "体系",
            "冰点", "回暖", "高潮", "退潮", "轮动", "主线", "扩散",
        ]):
            methodology_claims.append(c)

    # ── 构建 prompt ──
    context_parts = []

    # 实时数据部分
    has_realtime_data = bool(market_snapshot.get("quotes")) or external_sector_boards.get("available")
    if has_realtime_data:
        context_parts.append("【实时行情数据】（✅ 主要分析依据）")
        if market_snapshot.get("quotes"):
            context_parts.append("- 个股/指数行情:")
            for q in market_snapshot["quotes"]:
                name = q.get("name", "")
                code = q.get("code", "")
                price = q.get("price", "")
                open_p = q.get("open", "")
                high = q.get("high", "")
                low = q.get("low", "")
                pct = q.get("pct_change", "")
                context_parts.append(f"  {name}({code}): 开{open_p} 收{price} 高{high} 低{low} 涨跌{pct}%")
        
        # 【新增】添加历史K线数据
        if stock_klines:
            from qing_investment.agent.tools.stock_data import format_kline_for_prompt
            context_parts.append("\n- 个股历史K线（近90日）:")
            context_parts.append(format_kline_for_prompt(stock_klines))
        
        # 【新增】添加当日分时数据
        if stock_intraday:
            from qing_investment.agent.tools.stock_data import format_intraday_for_prompt
            # 找到昨收价
            prev_close = None
            for q in market_snapshot.get("quotes", []):
                if not q.get("is_index"):
                    prev_close = q.get("prev_close")
                    break
            context_parts.append("\n- 个股当日分时:")
            context_parts.append(format_intraday_for_prompt(stock_intraday, prev_close))
        
        if external_sector_boards.get("available"):
            context_parts.append("\n- 板块数据:")
            concept_leaders = external_sector_boards.get("concept", {}).get("leaders", [])
            for item in concept_leaders[:5]:
                context_parts.append(f"  {item['name']}: {item['pct_change']}%")
    else:
        context_parts.append("【实时行情数据】（❌ 无法获取）")

    if methodology_wiki:
        context_parts.append("\n【博主分析方法论】（仅供参考UP的分析框架和概念定义）")
        for s in methodology_wiki:
            src = s["source"].replace("framework/", "[框架] ").replace("knowledge/wiki/", "[Wiki] ")
            context_parts.append(f"- {src}: {s['text'][:300]}")

    if methodology_claims:
        context_parts.append("\n【博主历史观点卡】（⚠️ 历史观点，仅供参考，不得作为当前判断依据）")
        for c in methodology_claims:
            context_parts.append(f"- {c.get('id', 'N/A')} ({c.get('source_date','')}): {c.get('statement', '')[:200]}")

    if memories:
        context_parts.append("\n【用户历史记忆】")
        for m in memories:
            content = m.get("content", "") if isinstance(m, dict) else str(m)
            context_parts.append(f"- {content}")

    prompt_lines = [
        "你是青枫浦上Q的助手，风格犀利但不劝赌，不用机构研报腔。",
        "",
        "【核心原则】",
        "1. 所有判断必须基于【实时行情数据】，不能基于历史观点",
        "2. 【博主分析方法论】是UP的分析框架和概念定义，可以引用作为方法论指导",
        "3. 【博主历史观点卡】是历史观点，仅供参考，不得作为当前判断的依据",
        "4. 禁止引用claim ID支持当前观点",
        "5. 如果【实时行情数据】为空，请明确说明无法获取数据，不要编造",
        "6. 如果知识库中没有相关信息，请明确说明，不要编造",
        "7. 【输出格式】回复开头必须标注：'[Qing-Agent 分析]'，然后空一行再写正文",
        "",
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
