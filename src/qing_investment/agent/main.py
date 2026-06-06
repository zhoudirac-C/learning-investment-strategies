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
            vec = emb_model.encode(req.message)
            
            # 检索wiki和raw文档
            results = qdrant.search(vec, collection="qing_knowledge", limit=8)
            wiki_snippets = [
                {
                    "text": r.get("payload", {}).get("text", ""),
                    "source": r.get("payload", {}).get("source_path", ""),
                    "source_type": r.get("payload", {}).get("source_type", ""),
                }
                for r in results
            ]
            
            # 检索结构化claims
            claim_results = qdrant.search(vec, collection="qing_claims", limit=8)
            for r in claim_results:
                payload = r.get("payload", {})
                claims.append({
                    "id": payload.get("claim_id", ""),
                    "statement": payload.get("statement", ""),
                    "subject": payload.get("subject", ""),
                    "source_date": payload.get("source_date", ""),
                    "confidence": payload.get("confidence", ""),
                    "score": r.get("score", 0),
                })
    except Exception as e:
        print(f"Knowledge retrieval error: {e}")

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

    # ── 过滤知识库内容 ──
    # 保留所有 wiki（包括市场分析、投资方法论、每日复盘等）
    all_wiki = [
        s for s in wiki_snippets
        if s.get("source", "").startswith(("knowledge/wiki/", "framework/"))
    ]
    
    # 保留所有 claims（不过滤，让 LLM 自己判断相关性）
    all_claims = claims

    # ── 读取持仓数据（如果匹配到个股） ──
    position_data: dict | None = None
    if fetched_stock_code:
        try:
            import yaml
            positions_path = "/home/ubuntu/learning-investment-strategies/config/stock_monitor/positions.yaml"
            with open(positions_path, "r", encoding="utf-8") as f:
                positions_data = yaml.safe_load(f)
            
            for account in positions_data.get("accounts", []):
                for pos in account.get("positions", []):
                    code = pos.get("code", "").replace(".SZ", "").replace(".SH", "").replace(".sz", "").replace(".sh", "")
                    if code == fetched_stock_code and pos.get("shares", 0) > 0:
                        position_data = {
                            "account": account.get("name", ""),
                            "name": pos.get("name", ""),
                            "code": code,
                            "shares": pos.get("shares", 0),
                            "cost": pos.get("cost", 0),
                            "risk_line": pos.get("risk_line", ""),
                            "risk_zone": pos.get("risk_zone", ""),
                            "reduce_zone": pos.get("reduce_zone", ""),
                            "notes": pos.get("notes", ""),
                        }
                        break
                if position_data:
                    break
        except Exception:
            pass

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

    if all_wiki:
        context_parts.append("\n【博主知识库】（Wiki专题分析、投资方法论、市场复盘等）")
        for s in all_wiki[:8]:  # 限制数量避免prompt过长
            src = s["source"].replace("knowledge/wiki/", "[Wiki] ").replace("framework/", "[框架] ")
            context_parts.append(f"- {src}: {s['text'][:300]}")

    if all_claims:
        context_parts.append("\n【博主历史观点卡】（⚠️ 历史观点，仅供参考，不得作为当前判断依据）")
        for c in all_claims[:8]:  # 限制数量
            context_parts.append(f"- {c.get('id', 'N/A')} ({c.get('source_date','')}): {c.get('statement', '')[:200]}")

    # 注入持仓数据
    if position_data:
        context_parts.append("\n【用户持仓数据】")
        context_parts.append(f"- 标的: {position_data['name']}({position_data['code']})")
        context_parts.append(f"- 持仓: {position_data['shares']}股")
        context_parts.append(f"- 成本: {position_data['cost']}元")
        if position_data.get('risk_zone') or position_data.get('risk_line'):
            context_parts.append(f"- 风控线: {position_data.get('risk_zone') or position_data.get('risk_line')}")
        if position_data.get('reduce_zone'):
            context_parts.append(f"- 减仓区: {position_data['reduce_zone']}")
        if position_data.get('notes'):
            context_parts.append(f"- 备注: {position_data['notes']}")

    if memories:
        context_parts.append("\n【用户历史记忆】")
        for m in memories:
            content = m.get("content", "") if isinstance(m, dict) else str(m)
            context_parts.append(f"- {content}")

    prompt_lines = [
        "你是青枫浦上Q的助手，风格犀利但不劝赌，不用机构研报腔。",
        "",
        "【分析框架——必须按此顺序执行】",
        "",
        "第一步：判断市场周期和情绪阶段",
        "- 看大盘指数（上证/深证/创业板/科创50）的涨跌和量能",
        "- 判断当前是冰点/回暖/高潮/退潮/混沌轮动中的哪个阶段",
        "- 结论必须基于【实时行情数据】",
        "",
        "第二步：判断所属板块是否是当前主线",
        "- 看板块数据（如果有），判断该票所属板块今日表现",
        "- 判断是主线/支线/边缘/退潮方向",
        "- 如果是支线或边缘，要说明为什么",
        "",
        "第三步：判断个股地位",
        "- 核心（产业链最核心、资金最认可）",
        "- 跟风（跟随核心标的涨跌）",
        "- 补涨（板块后期才启动的标的）",
        "- 案例（博主用来举例说明逻辑的标的）",
        "- 过期（逻辑已兑现或已退潮）",
        "- 地位判断必须基于量价结构和板块内相对强弱",
        "",
        "第四步：检索博主历史提及（如有）",
        "- 查看【博主历史观点卡】中是否有该票或相关方向的提及",
        "- 提取产业逻辑、角色定位、置信度",
        "- ⚠️ 历史观点仅供参考，不能作为当前判断依据",
        "",
        "第五步：结合技术位置和资金面判断风险收益",
        "- 看90日K线：趋势、支撑、压力、量能变化",
        "- 看当日分时：开盘/盘中/尾盘结构，资金流向",
        "- 看实时行情：价格、涨跌幅、换手率（如有）",
        "- 判断当前位置的风险收益比",
        "",
        "第六步：输出证伪条件和跟踪字段",
        "- 如果看多，什么信号出现会证伪这个判断？",
        "- 如果看空，什么信号出现会证伪这个判断？",
        "- 下一交易日需要跟踪的关键指标",
        "",
        "【持仓关联分析（如适用）】",
        "- 如果用户提到持仓，必须结合成本、仓位、风控线给出建议",
        "- 区分：浮盈/浮亏、仓位轻重、是否符合原计划",
        "- 所有操作建议必须附带条件（'若X则Y'），禁止无条件买卖指令",
        "",
        "【核心原则】",
        "1. 所有判断必须基于【实时行情数据】，不能基于历史观点",
        "2. 【博主分析方法论】是UP的分析框架和概念定义，可以引用作为方法论指导",
        "3. 【博主历史观点卡】是历史观点，仅供参考，不得作为当前判断的依据",
        "4. 禁止引用claim ID支持当前观点",
        "5. 如果【实时行情数据】为空，请明确说明无法获取数据，不要编造",
        "6. 如果知识库中没有相关信息，请明确说明，不要编造",
        "7. 【输出格式】回复开头必须标注：'[Qing-Agent 分析]'，然后空一行再写正文",
        "8. 分析必须按上述六步框架执行，不能跳过步骤",
        "",
        *context_parts,
        f"\n用户：{req.message}\n",
        "请按上述六步框架直接回复：",
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
