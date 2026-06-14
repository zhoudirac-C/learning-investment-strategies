from __future__ import annotations

import logging
import os
import re
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from fastapi import FastAPI

# ── 日志配置（Phase 8 新增：按天轮转日志，保留30天）──
_log_dir = Path(__file__).resolve().parents[3] / "logs"
_log_dir.mkdir(parents=True, exist_ok=True)
_log_file = _log_dir / "qing-agent.log"

_handler = TimedRotatingFileHandler(
    str(_log_file),
    when="midnight",
    interval=1,
    backupCount=30,
    encoding="utf-8",
)

# 自定义 namer：将 qing-agent.log → qing-agent.YYYY-MM-DD.log
def _log_namer(default_name: str) -> str:
    # default_name = "qing-agent.log.2026-06-12" → "qing-agent.2026-06-12.log"
    base = _log_file.stem  # "qing-agent"
    ext = _log_file.suffix  # ".log"
    date_part = Path(default_name).suffix.lstrip(".")  # "2026-06-12"
    return str(_log_dir / f"{base}.{date_part}{ext}")

_handler.namer = _log_namer
_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
))

# Clear default handlers and add file handler
_root_logger = logging.getLogger()
_root_logger.setLevel(logging.DEBUG if os.environ.get("QING_AGENT_LOG_LEVEL", "").upper() == "DEBUG" else logging.INFO)
# Remove existing handlers to avoid duplicate logs
for h in _root_logger.handlers[:]:
    _root_logger.removeHandler(h)
_root_logger.addHandler(_handler)

# Also log to stderr for docker/k8s environments
_console = logging.StreamHandler()
_console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
_root_logger.addHandler(_console)

# Set module-specific loggers
for mod_name in [
    "qing_investment.agent.graph.nodes",
    "qing_investment.agent.graph.builder",
    "qing_investment.agent.tools.llm_client",
    "qing_investment.agent.tools.neo4j_client",
    "qing_investment.agent.tools.qdrant_client",
]:
    logging.getLogger(mod_name).setLevel(logging.DEBUG if os.environ.get("QING_AGENT_LOG_LEVEL", "").upper() == "DEBUG" else logging.INFO)

logger = logging.getLogger(__name__)
logger.info(f"日志初始化完成，路径={_log_file}")

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
from qing_investment.agent.tools.claim_freshness import apply_claim_freshness

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


def _format_claim_line(c: dict) -> str:
    """Format a single claim for display in the prompt context."""
    parts = [f"- {c.get('id', 'N/A')} ({c.get('source_date','')})"]
    if c.get('claim_type'):
        parts.append(f" [{c.get('claim_type')}]")
    label = c.get("freshness_label", "")
    if label:
        parts.append(f" [{label}]")
    intensity = c.get("intensity", "medium")
    intensity_tag = {"high": "🔴", "medium": "🟡", "low": "⚪"}.get(intensity, "⚪")
    parts.append(f" [{intensity_tag}]")
    parts.append(f": {c.get('statement', '')[:200]}")
    if c.get('superseded_by'):
        parts.append(f" [已被 {', '.join(c['superseded_by'][:2])} 取代]")
    if c.get('contradicts'):
        parts.append(f" [与 {', '.join(c['contradicts'][:2])} 矛盾]")
    return "".join(parts)


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


def _aggregate_cost(cost_tracking: list[dict]) -> dict:
    """从 Annotated 合并的 cost_tracking 列表中提取总成本快照。

    cost_tracking 格式: [{"llm_calls": int, "total_cost_usd": str}]
    """
    from decimal import Decimal

    total_calls = 0
    total_cost = Decimal("0")
    for entry in cost_tracking:
        total_calls += entry.get("llm_calls", 0)
        try:
            total_cost += Decimal(entry.get("total_cost_usd", "0"))
        except Exception:
            pass
    return {
        "llm_calls": total_calls,
        "total_cost_usd": str(total_cost),
    }


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
        "buy_signal_candidates": req.buy_signal_candidates,
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
        "parsed_intent": {
            "analysis_type": req.analysis_type,
            "stock_code": req.market_snapshot.get("stock_code", ""),
        },
    }

    import logging, time
    _req_logger = logging.getLogger("qing_investment.agent.main")
    _req_t0 = time.time()
    _req_logger.info(f"analyze_trigger start: type={req.analysis_type} trigger={req.trigger.get('title','')}")

    result = await graph.ainvoke(state)

    _req_dur = time.time() - _req_t0
    _req_logger.info(
        f"analyze_trigger end: duration={_req_dur:.1f}s "
        f"passed={result.get('review_passed')} "
        f"output_len={len(result.get('final_output', ''))} "
        f"claims_cited={len(result.get('claims_cited', []))}"
    )

    return TriggerResponse(
        final_output=result.get("final_output", ""),
        claims_cited=result.get("claims_cited", []),
        data_sources=result.get("data_sources", []),
        confidence=result.get("confidence", "medium"),
        review_passed=result.get("review_passed", False),
        reasoning_steps=result.get("reasoning_steps", []),
        cost_info=_aggregate_cost(result.get("cost_tracking", [])),
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
                    "claim_type": payload.get("claim_type", ""),
                    "score": r.get("score", 0),
                })
    except Exception as e:
        print(f"Knowledge retrieval error: {e}")

    seen_ids: set[str] = set(c.get("id") or "" for c in claims)

    # ── 股票代码提取（先于 Neo4j 检索，供后续复用）──
    fetched_stock_code: str | None = None
    try:
        import re
        stock_code_match = re.search(r'(\d{6})', req.message)
        if stock_code_match:
            fetched_stock_code = stock_code_match.group(1)
    except Exception:
        pass

    # ── Neo4j 检索（单次连接，合并图遍历补充）──
    try:
        neo4j = Neo4jClient()

        # 若未提取到股票代码，尝试按名称从 Neo4j 模糊匹配
        if not fetched_stock_code:
            try:
                name_matches = neo4j.get_stock_by_name(req.message)
                if name_matches:
                    fetched_stock_code = name_matches[0]["code"]
            except Exception:
                pass
        
        # 如果提取到股票代码，使用图遍历获取相关 claims（包括演化关系）
        if fetched_stock_code:
            stock_claims = neo4j.get_claims_with_evolution(fetched_stock_code, limit=8)
            for c in stock_claims:
                c["source"] = "neo4j_graph"  # 标记来源
                claims.append(c)
        else:
            # 否则使用关键词匹配
            keywords = _extract_keywords(req.message)
            for cluster_kws in _SECTOR_KEYWORDS.values():
                for kw in cluster_kws:
                    if kw in req.message and kw not in keywords:
                        keywords.append(kw)
            for kw in keywords[:3]:
                batch = neo4j.get_claims_by_keyword(kw, limit=5)
                for c in batch:
                    cid = c.get("id")
                    if cid and cid not in seen_ids:
                        seen_ids.add(cid)
                        c["source"] = "neo4j_keyword"
                        claims.append(c)
                if len(claims) >= 15:
                    break

        # ── 图遍历补充：通过共享实体发现相关 claims（方案1）──
        if claims:
            graph_related_ids: set[str] = set()
            for c in claims[:3]:
                cid = c.get("id", "")
                if cid:
                    related = neo4j.get_related_claims(cid, limit=5)
                    for rc in related:
                        rid = rc.get("id", "")
                        if rid and rid not in seen_ids:
                            graph_related_ids.add(rid)
            for rid in graph_related_ids:
                rc = neo4j.get_claim_evolution(rid)
                if rc:
                    first = rc[0] if isinstance(rc, list) else rc
                    if first and first.get("id"):
                        first["source"] = "graph_traversal"
                        claims.append(first)
                        seen_ids.add(rid)

        neo4j.close()
    except Exception:
        pass


    market_snapshot: dict = {"quotes": []}
    external_sector_boards: dict = {"available": False}

    # 1. 检测查询类型
    query_lower = req.message.lower()
    is_market_query = any(kw in query_lower for kw in ["大盘", "市场", "行情", "指数", "上证", "创业板", "科创"])
    is_sector_query = any(kw in query_lower for kw in ["板块", "行业", "概念"])
    is_stock_query = any(kw in query_lower for kw in ["股", "走势", "分析", "低点", "高点", "买入", "卖出", "抄底", "减仓", "加仓", "持仓", "套牢", "解套", "止损", "止盈", "目标价", "支撑", "压力"])
    
    # 2. 如果没有提取到代码，从持仓配置中匹配股票名称
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
            code_to_fetch = fetched_stock_code
            if not code_to_fetch:
                # 从 Neo4j 按名称模糊匹配股票代码（若 Neo4j 检索段失败时的再尝试）
                try:
                    from qing_investment.agent.tools.neo4j_client import Neo4jClient
                    n4j = Neo4jClient()
                    name_matches = n4j.get_stock_by_name(req.message)
                    n4j.close()
                    if name_matches:
                        code_to_fetch = name_matches[0]["code"]
                except Exception:
                    pass
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
        # 应用时效分级
        fresh_claims = apply_claim_freshness(all_claims)

        # 分离方法论类和观点类
        method_claims = [
            c for c in fresh_claims
            if c.get('claim_type') in ('methodology', 'operation')
        ]
        view_claims = [
            c for c in fresh_claims
            if c.get('claim_type') not in ('methodology', 'operation')
        ]

        # 方法论块（不受时效限制）
        if method_claims:
            context_parts.append("\n【博主选股方法论/操作框架】（🔧 UP的分析框架，可以作为方法论指导引用）")
            for c in method_claims[:5]:
                claim_line = _format_claim_line(c)
                context_parts.append(claim_line)

        # 按时效等级分组
        fresh_views = [c for c in view_claims if c.get("freshness_label") == "最新"]
        recent_views = [c for c in view_claims if c.get("freshness_label") == "近期"]
        historical_views = [c for c in view_claims if c.get("freshness_label") == "历史"]

        # 个股查询：过滤 low intensity，避免 UP 随口一提被当作操作依据
        if fetched_stock_code:
            fresh_views = [c for c in fresh_views if c.get("intensity") != "low"]
            recent_views = [c for c in recent_views if c.get("intensity") != "low"]

        if fresh_views:
            context_parts.append("\n【UP最新观点】（≤7天，可作为判断的辅助参考，需搭配实时数据使用）")
            for c in fresh_views[:5]:
                context_parts.append(_format_claim_line(c))

        if recent_views:
            context_parts.append("\n【UP近期观点】（8-30天，参考价值递减，请注意时效）")
            for c in recent_views[:4]:
                context_parts.append(_format_claim_line(c))

        if historical_views:
            context_parts.append("\n【UP历史观点】（31-90天，仅供参考，不得作为当前判断依据）")
            for c in historical_views[:3]:
                context_parts.append(_format_claim_line(c))

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
        "【分析框架——必须严格按此顺序执行】",
        "",
        "第一步：判断市场周期和情绪阶段",
        "- 看大盘指数（上证/深证/创业板/科创50）的涨跌和量能",
        "- 🔑 优先使用【UP最新观点】中的周期判断（如有≤7天的market-cycle观点）",
        "  UP每天复盘解读盘面，他的周期定位比LLM自己看几个数字更准",
        "- 实时数据用来验证UP的周期判断，而不是推翻（除非出现明显背离：如UP说磨底但指数放量跌破关键位）",
        "- 结论格式：「UP观点：...（采纳/修正/放弃，原因是...）」",
        "",
        "第二步：判断所属板块是否是当前主线",
        "- 🔒 此步只能基于实时板块数据（板块涨跌幅、资金流向）",
        "- 板块轮动快，以当日数据为准，UP的方向判断仅作补充参考",
        "- 判断板块是主线/支线/边缘/退潮方向",
        "- 如果是支线或边缘，要说明为什么",
        "",
        "第三步：判断个股地位",
        "- ⭐ 如果UP在claim中明确给出了个股地位标签（龙头/中军/核心/趋势/跟风），优先采用",
        "  UP的个股定位经过产业逻辑验证，比看一天K线准，且大票定性不频繁变化",
        "- 如果UP从未提及该股，用量化数据判断（板块内相对强弱、市值、换手率）",
        "- 个股地位不受时效衰减影响（中军就是中军，不会因为两周过去变成跟风）",
        "",
        "第四步：检索博主历史提及（如有）",
        "- 查看【UP最新观点】中是否有该票或相关方向的提及——≤7天的可作为辅助参考",
        "- 查看【UP近期观点】——参考价值递减，需注意时效",
        "- 查看【UP历史观点】——仅供参考，不得作为判断依据",
        "- ⚠️ 【引用纪律——每引用一条claim必须配对至少一条实时数据】",
        "  格式：（数据）...→（UP观点）...→（结论）...",
        "  如果找不到对应的数据支撑，该claim不得引用",
        "- 🔧 如果存在【博主选股方法论/操作框架】，必须明确引用UP的选股方法/操作纪律",
        "（如「找低位+一季报超预期」），方法论指导不受时效限制",
        "",
        "第五步：结合技术位置和资金面判断风险收益",
        "- 看90日K线：趋势、支撑、压力、量能变化",
        "- 看当日分时：开盘/盘中/尾盘结构，资金流向",
        "- 看实时行情：价格、涨跌幅、换手率（如有）",
        "- 判断当前位置的风险收益比",
        "- 引用UP方法论时，必须同时给出对应的实时数据交叉验证",
        "  ✅ 正确：该票自5月初下跌30%（数据），Q1净利润+150%（数据）→ 符合UP「找低位+业绩」方法论",
        "  ❌ 错误：UP说磨底期做低位方向，所以买这个票（用claim替代了数据分析）",
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
        "1. 【实时数据是客观基准】——所有判断起点必须是实时数据，不能编造，获取不到时明确说明",
        "2. 【UP周期判断优先】——≤7天的market-cycle观点优先于LLM自主周期判断（UP每天复盘更准）",
        "3. 【UP个股定位优先】——UP点名过的个股地位是权威来源，不随时效衰减",
        "4. 【UP方法论可引用】——选股方法论/操作框架不受时效限制，但必须和当前数据配合使用",
        "5. 【引用纪律——数据必在claim前】——每引用一条claim必须有对应实时数据交叉验证",
        "6. 【UP最新观点（≤7天）可作为辅助参考，但不得替代实时数据】",
        "7. 【UP近期观点（8-30天）参考价值递减，需标注时效】",
        "8. 【UP历史观点（31-90天）仅供背景参考，不得作为判断依据】",
        "9. 禁止引用claim ID支持当前观点",
        "10. 如果【实时行情数据】为空，请明确说明无法获取数据，不要编造",
        "11. 如果知识库中没有相关信息，请明确说明，不要编造\n"
        "12. 【输出格式】回复开头必须标注：'[Qing-Agent 分析]'，然后空一行再写正文\n"
        "13. 分析必须按上述六步框架执行，不能跳过步骤\n"
        "14. 【intensity分级】UP观点按分析深度分级，引用时需注意：\n"
        "    🔴 high = UP专题分析/视频重点推荐 → 可引用，但必须配实时数据交叉验证\n"
        "    🟡 medium = UP复盘提及/方向判断 → 参考价值中等，需标注时效\n"
        "    ⚪ low = UP盘中随口/转发/评论回复 → 仅供参考背景，不得作为操作依据\n"
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
