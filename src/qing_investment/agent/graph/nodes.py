from __future__ import annotations

import asyncio
import json
from pathlib import Path

from qing_investment.agent.tools.llm_client import get_llm_client
from qing_investment.agent.tools.mem0_client import Mem0ClientWrapper
from qing_investment.agent.tools.neo4j_client import Neo4jClient
from qing_investment.agent.tools.qdrant_client import QdrantClientWrapper
from .state import AgentState

_REPO_ROOT = Path(__file__).resolve().parents[4]
_PROMPT_DIR = _REPO_ROOT / "src" / "qing_investment" / "agent" / "prompts" / "system"


def _load_prompt(name: str) -> str:
    path = _PROMPT_DIR / f"{name}.txt"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return f"[Prompt {name} not found]"


def _load_analysis_framework() -> str:
    """加载市场分析框架 prompt 片段（独立于主 prompt，方便修改）。"""
    path = _PROMPT_DIR / "market_analysis_framework.txt"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return "[market_analysis_framework.txt not found]"


def _load_few_shot_examples(query: str, max_examples: int = 3) -> list[str]:
    """从 prompts/few_shot/ 加载相似场景的示例。"""
    few_shot_dir = _REPO_ROOT / "src" / "qing_investment" / "agent" / "prompts" / "few_shot"
    if not few_shot_dir.exists():
        return []
    examples = []
    for f in few_shot_dir.glob("*.md"):
        examples.append(f.read_text(encoding="utf-8"))
    return examples[:max_examples]


def _get_tone_by_market_phase(phase: str) -> str:
    mapping = {
        "冰点期": "安抚、鼓励",
        "回暖期": "谨慎乐观",
        "高潮期": "劝退、警示",
        "退潮期": "收缩、防御",
    }
    return mapping.get(phase, "中性")


# ── Framework 显式加载（Phase 1 新增）──
_FRAMEWORK_LOADERS: dict[str, list[str]] = {
    "market": ["market-cycle-framework.md", "sector-diffusion-framework.md", "trading-rules.md"],
    "stock": ["stock-analysis-playbook.md", "technical-analysis-framework.md", "trading-rules.md"],
    "portfolio": ["trading-rules.md", "market-cycle-framework.md", "sector-diffusion-framework.md"],
}


def _load_framework_files(analysis_type: str) -> list[dict]:
    """根据分析类型，显式加载相关的 framework 文件内容。"""
    files = _FRAMEWORK_LOADERS.get(analysis_type, [])
    result: list[dict] = []
    for fname in files:
        path = _REPO_ROOT / "framework" / fname
        if path.exists():
            content = path.read_text(encoding="utf-8")
            # 截断到 4000 字符，避免 prompt 过长；保留文件开头（通常是核心定义）
            result.append({
                "file": fname,
                "content": content[:4000],
                "truncated": len(content) > 4000,
            })
    return result


def _safe_llm_invoke(prompt: str) -> str:
    """安全调用 LLM，缺失 API key 时返回空字符串。"""
    try:
        llm = get_llm_client()
        return llm.invoke(prompt).content
    except Exception as e:
        return f""


def parse_query(state: AgentState) -> AgentState:
    query = state.get("query", "")
    prompt = f"""从以下输入中提取信息，返回严格JSON格式（不要markdown代码块）：
- stock_code: 股票代码（如有，如 300394）
- analysis_type: stock(个股) / market(市场) / portfolio(持仓复盘)
- urgency: scheduled(定时) / event(事件触发)
- focus: 用户关注的具体问题

输入：{query}
"""
    content = _safe_llm_invoke(prompt)
    try:
        parsed = json.loads(content) if content else {}
    except json.JSONDecodeError:
        parsed = {}

    if not parsed:
        parsed = {
            "stock_code": None,
            "analysis_type": "stock",
            "urgency": "scheduled",
            "focus": query,
        }

    return {

        "parsed_intent": parsed,
        "reasoning_steps": [f"意图解析: {parsed.get('analysis_type', 'unknown')}, 标的: {parsed.get('stock_code', 'N/A')}"],
    }


# Sector keyword clusters for better claim retrieval
_SECTOR_CLUSTERS: dict[str, list[str]] = {
    "光互连": ["光互连", "光互联", "光模块", "CPO", "光纤", "光通信", "光芯片"],
    "半导体": ["半导体", "芯片", "存储", "封测", "光刻", "设备", "材料"],
    "AI": ["AI", "算力", "大模型", "智能体", "Agent", "AIPC"],
    "机器人": ["机器人", "具身智能", "人形机器人", "特斯拉", "Optimus"],
    "电力": ["电力", "煤炭", "红利", "高股息", "绿电"],
    "新能源": ["新能源", "光伏", "锂电", "储能", "风电"],
    "资源": ["铜", "铝", "锂", "稀土", "黄金", "煤炭", "硫磺"],
}


def _extract_sector_keywords(query: str) -> list[str]:
    """Extract sector keywords from query using predefined clusters."""
    found: set[str] = set()
    for cluster_kws in _SECTOR_CLUSTERS.values():
        for kw in cluster_kws:
            if kw in query:
                found.add(kw)
    # Fallback: use the cleaned query itself if no cluster match
    if not found:
        cleaned = query.replace("分析一下", "").replace("板块", "").strip()
        if cleaned:
            found.add(cleaned)
    return list(found)


async def retrieve_knowledge(state: AgentState) -> AgentState:
    query = state.get("query", "")
    stock_code = state.get("parsed_intent", {}).get("stock_code")
    session_id = state.get("session_id", "default")

    neo4j = Neo4jClient()
    qdrant = QdrantClientWrapper()
    mem0 = Mem0ClientWrapper()

    claims, wiki_snippets, memories, few_shot = [], [], [], []

    try:
        if stock_code:
            # Stock-specific queries: use Neo4j relationship graph
            claims = neo4j.get_claims_about_stock(stock_code, limit=10)
        else:
            # Market/sector queries: use semantic search via Qdrant (Phase 3.3)
            from qing_investment.agent.tools.llm_client import get_embedding_model
            emb_model = get_embedding_model()
            if emb_model:
                query_vec = emb_model.encode(query).tolist()[0]
                claim_results = qdrant.search(
                    query_vec, collection="qing_claims", limit=10
                )
                claim_ids = [
                    (r.get("payload") or {}).get("claim_id", "")
                    for r in claim_results
                ]
                # Fetch full claim details from Neo4j by IDs
                seen_ids: set[str] = set()
                for cid in claim_ids:
                    if cid and cid not in seen_ids:
                        seen_ids.add(cid)
                        c = neo4j.get_claim_evolution(cid)
                        if c:
                            # get_claim_evolution returns list of dicts, take first
                            first = c[0] if isinstance(c, list) else c
                            node = first.get("c", {})
                            claims.append({
                                "id": cid,
                                "statement": node.get("statement", ""),
                                "confidence": node.get("confidence", ""),
                                "source_date": node.get("source_date", ""),
                                "status": node.get("status", ""),
                            })
            else:
                # Fallback to keyword search if embedding model unavailable
                keywords = _extract_sector_keywords(query)
                seen_ids: set[str] = set()
                for kw in keywords:
                    batch = neo4j.get_claims_by_keyword(kw, limit=10)
                    for c in batch:
                        cid = c.get("id")
                        if cid and cid not in seen_ids:
                            seen_ids.add(cid)
                            claims.append(c)
                    if len(claims) >= 15:
                        break
    except Exception as e:
        import traceback, logging
        logging.getLogger(__name__).warning("Claims retrieval failed: %s", traceback.format_exc())
        claims = []

    try:
        qdrant.ensure_collection("qing_knowledge", vector_size=512)
        from qing_investment.agent.tools.llm_client import get_embedding_model
        emb_model = get_embedding_model()
        if emb_model:
            query_vec = emb_model.encode(query).tolist()[0]
            results = qdrant.search(query_vec, collection="qing_knowledge", limit=15)
            wiki_snippets = [
                {
                    "text": (r.get("payload") or {}).get("text", (r.get("payload") or {}).get("chunk_text", "")),
                    "source": (r.get("payload") or {}).get("source_path", (r.get("payload") or {}).get("source", "")),
                    "score": r.get("score", 0),
                }
                for r in results
            ]
            # ── 来源类型 boost 排序（Phase 3.1）──
            _SOURCE_BOOST = {
                "framework/": 0.15,
                "wiki/投资方法论": 0.10,
                "wiki/市场分析": 0.05,
                "wiki/博主": 0.03,
                "wiki/每日复盘": 0.02,
                "sources/raw": 0.00,
            }
            for s in wiki_snippets:
                src = s.get("source", "")
                boost = 0.0
                for prefix, b in _SOURCE_BOOST.items():
                    if prefix in src:
                        boost = b
                        break
                s["boosted_score"] = s.get("score", 0) + boost
            wiki_snippets.sort(key=lambda x: x.get("boosted_score", 0), reverse=True)
            wiki_snippets = wiki_snippets[:10]  # 截断回 10 条
    except Exception as e:
        import traceback, logging
        logging.getLogger(__name__).warning("Wiki retrieval failed: %s", traceback.format_exc())
        wiki_snippets = []

    # Dynamic sector extraction from recent UP raw documents + web search
    sector_context: list[dict] = []
    try:
        from qing_investment.agent.tools.sector_extractor import build_sector_context
        # Only run sector extraction for market/sector queries to save latency
        analysis_type = (state.get("parsed_intent") or {}).get("analysis_type", "stock")
        if analysis_type in ("market", "portfolio") or not stock_code:
            sector_context = await asyncio.to_thread(
                build_sector_context, days_back=3, top_k=3
            )
    except Exception:
        sector_context = []

    try:
        memories = mem0.search(query, user_id=session_id)
    except Exception as e:
        memories = []

    few_shot = _load_few_shot_examples(query)

    neo4j.close()

    # 检索审计日志
    wiki_framework_count = sum(1 for s in wiki_snippets if s.get("source", "").startswith("framework/"))
    wiki_meth_count = sum(1 for s in wiki_snippets if "wiki/投资方法论" in s.get("source", ""))
    print(
        f"[retrieve_knowledge] query='{query}', "
        f"claims={len(claims)}, wiki={len(wiki_snippets)} "
        f"(framework={wiki_framework_count}, meth={wiki_meth_count}), "
        f"memories={len(memories)}, sector_ctx={len(sector_context)}"
    )

    return {
        "claims": claims,
        "wiki_snippets": wiki_snippets,
        "sector_context": sector_context,
        "external_sector_boards": state.get("external_sector_boards", {}),
        "knowledge_graph": {},
        "memories": memories,
        "few_shot_examples": few_shot,
        "reasoning_steps": [
            f"检索到 {len(claims)} 条claims, {len(wiki_snippets)} 个wiki片段, "
            f"{len(memories)} 条记忆, {len(sector_context)} 个动态板块"
        ],
    }


def market_analyst(state: AgentState) -> AgentState:
    prompt_template = _load_prompt("market_analyst")
    esb = state.get("external_sector_boards", {})
    analysis_type = (state.get("parsed_intent") or {}).get("analysis_type", "stock")
    if analysis_type in ("market", "portfolio") and not esb.get("available"):
        return {
            "market_context": {
                "market_phase": "数据不可用",
                "phase_reasoning": f"外部板块数据不可用，无法生成市场分析: {esb.get('error', 'unknown')}",
                "main_themes": [],
                "sector_map": {},
                "themes_in_focus": [],
                "index_discipline": {},
                "volume_note": "",
                "emotion_signals": {},
                "tomorrow_watch": [],
                "position_plans": [],
                "risk_notes": "外部行情源板块数据缺失，本次分析被中止。请检查网络连接或等行情源恢复后重试。",
                "citations": [],
            },
            "reasoning_steps": ["market_analyst: 外部板块数据不可用，拒绝生成分析"],
        }

    # Truncate market_snapshot quotes to keep prompt size reasonable
    market_snapshot = dict(state.get("market_snapshot") or {})
    all_quotes = market_snapshot.get("quotes", []) or []
    if isinstance(all_quotes, list) and len(all_quotes) > 50:
        # Keep indexes + position/watchlist stocks + top movers
        codes_to_keep: set[str] = set()
        for q in all_quotes:
            label = q.get("label") or ""
            name = q.get("name") or ""
            # Keep indexes
            if "指数" in label or "指数" in name or label in ("上证指数", "深证成指", "创业板指", "科创50"):
                codes_to_keep.add(q.get("secid", ""))
                codes_to_keep.add(q.get("code", ""))
        # Keep positions and watchlist stocks
        for p in state.get("positions", []) or []:
            code = str(p.get("code", "")).replace(".SH", "").replace(".SZ", "")
            if code:
                codes_to_keep.add(code)
        for w in state.get("watchlist", []) or []:
            code = str(w.get("code", "")).replace(".SH", "").replace(".SZ", "")
            if code:
                codes_to_keep.add(code)
        # Top 15 movers by abs(pct_change)
        sorted_quotes = sorted(
            [q for q in all_quotes if isinstance(q, dict)],
            key=lambda x: abs(x.get("pct_change") or 0),
            reverse=True,
        )[:15]
        for q in sorted_quotes:
            codes_to_keep.add(q.get("secid", ""))
            codes_to_keep.add(q.get("code", ""))
        filtered = [q for q in all_quotes if (q.get("secid") in codes_to_keep or q.get("code") in codes_to_keep)]
        market_snapshot["quotes"] = filtered
        market_snapshot["_total_quotes"] = len(all_quotes)
        market_snapshot["_filtered_quotes"] = len(filtered)

    # 显式加载相关 framework 文件（Phase 1 新增）
    framework_context = _load_framework_files(analysis_type)
    print(
        f"[market_analyst] framework_loaded={len(framework_context)}, "
        f"files={[f['file'] for f in framework_context]}, "
        f"analysis_type={analysis_type}"
    )

    # 动态加载分析框架片段（不改 framework/ 目录）
    analysis_framework = _load_analysis_framework()
    prompt_template_filled = prompt_template.replace("{analysis_framework}", analysis_framework)

    context = {
        "claims": state.get("claims", []),
        "wiki_snippets": state.get("wiki_snippets", []),
        "framework_rules": framework_context,  # 显式注入方法论框架
        "market_snapshot": market_snapshot,
        "sector_strengths": state.get("sector_strengths", []),
        "external_sector_boards": esb,
        "sector_context": state.get("sector_context", []),
        "memories": state.get("memories", []),
    }
    prompt = f"""{prompt_template_filled}

检索到的知识：
{json.dumps(context, ensure_ascii=False, indent=2)}

当前持仓：
{json.dumps(state.get('positions', []), ensure_ascii=False, indent=2)}

请输出JSON：
"""
    content = _safe_llm_invoke(prompt)
    try:
        result = json.loads(content) if content else {}
    except json.JSONDecodeError:
        result = {}

    if not result:
        result = {
            "market_phase": "未配置",
            "phase_reasoning": "LLM未返回结果或API未配置",
            "main_themes": [],
            "sector_strength": {},
            "emotion_signals": {},
            "position_plans": [],
        }

    return {

        "market_context": result,
        "reasoning_steps": [
            f"市场周期: {result.get('market_phase', 'N/A')}"
        ],
    }


def stock_analyst(state: AgentState) -> AgentState:
    stock_code = state.get("parsed_intent", {}).get("stock_code")
    analysis_type = state.get("parsed_intent", {}).get("analysis_type", "stock")

    # Skip individual stock analysis for market-level or portfolio queries
    if analysis_type in ("market", "portfolio") or not stock_code:
        return {
            "stock_analysis": {},
            "reasoning_steps": ["个股分析: 跳过（market/portfolio查询或无标的）"],
        }

    prompt_template = _load_prompt("stock_analyst")
    context = {
        "stock_code": stock_code,
        "positions": state.get("positions", []),
        "watchlist": state.get("watchlist", []),
        "claims": state.get("claims", []),
        "market_context": state.get("market_context", {}),
    }
    prompt = f"""{prompt_template}

上下文：
{json.dumps(context, ensure_ascii=False, indent=2)}

请输出JSON：
"""
    content = _safe_llm_invoke(prompt)
    try:
        result = json.loads(content) if content else {}
    except json.JSONDecodeError:
        result = {}

    if not result:
        result = {
            "stock_code": stock_code or "N/A",
            "stock_name": "N/A",
            "stock_role": "未配置",
            "role_reasoning": "LLM未返回结果或API未配置",
            "bullish_evidence": [],
            "bearish_evidence": [],
            "trigger_conditions": "未配置",
            "invalidation_conditions": "未配置",
            "risk_notes": "",
        }

    return {

        "stock_analysis": result,
        "reasoning_steps": [
            f"个股地位: {result.get('stock_role', 'N/A')}"
        ],
    }


def _format_source_block(state: AgentState) -> str:
    """从检索到的知识构建参考来源段落，强制注入到草稿末尾。"""
    sources: list[str] = []
    seen: set[str] = set()

    # Framework rules
    for f in state.get("framework_rules", []):
        src = f"framework/{f.get('file', '')}"
        if src and src not in seen:
            seen.add(src)
            sources.append(src)

    # Wiki snippets (top 5)
    for s in state.get("wiki_snippets", [])[:5]:
        src = s.get("source", "")
        if src and src not in seen:
            seen.add(src)
            sources.append(src)

    # Claims (top 5)
    for c in state.get("claims", [])[:5]:
        cid = c.get("id", "")
        if cid and cid not in seen:
            seen.add(cid)
            sources.append(cid)

    if not sources:
        return ""

    return "\n\n【参考来源】\n" + "\n".join(f"- {s}" for s in sources)


def _build_position_plan_lines(market_context: dict, positions: list[dict]) -> list[str]:
    """Build structured position plan lines from market_context.position_plans.

    Falls back to a plain inventory list if no plans were generated.
    """
    if not positions:
        return []

    plans = market_context.get("position_plans") or []
    plan_by_code: dict[str, dict] = {}
    for plan in plans:
        code = plan.get("code", "")
        if code:
            plan_by_code[code] = plan

    lines = ["", "【持仓操作计划】"]
    for p in positions:
        code = p.get("code", "N/A")
        name = p.get("name", "N/A")
        shares = p.get("shares", 0)
        cost = p.get("cost", "N/A")
        latest = p.get("latest", p.get("price", "N/A"))
        pct = p.get("pct_change", "N/A")
        plan = plan_by_code.get(code) or {}
        if plan:
            lines.append(
                f"- {name}({code})：持仓{shares}股，成本{cost}，现价{latest}，今日{pct}%\n"
                f"  触发：{plan.get('trigger', 'N/A')}\n"
                f"  失效：{plan.get('invalidation', 'N/A')}\n"
                f"  仓位：{plan.get('position_advice', 'N/A')}"
            )
        else:
            lines.append(
                f"- {name}({code})：持仓{shares}股，成本{cost}，现价{latest}，今日{pct}%\n"
                f"  触发：待补充\n"
                f"  失效：待补充\n"
                f"  仓位：按大盘纪律控制"
            )
    return lines


def synthesize(state: AgentState) -> AgentState:
    market = state.get("market_context", {})
    stock = state.get("stock_analysis", {})
    positions = state.get("positions", [])

    if stock:
        draft = f"""【盘面】{market.get('market_summary', '暂无')}

【周期定位】{market.get('market_phase', 'N/A')}，{market.get('phase_reasoning', '')}

【主线判断】{', '.join(market.get('main_themes', []))}

【个股地位】{stock.get('stock_name', 'N/A')}({stock.get('stock_code', 'N/A')}) 当前为 {stock.get('stock_role', 'N/A')}。
{stock.get('role_reasoning', '')}

【技术位置】{stock.get('technical_position', 'N/A')}

【多空证据】
利多：{'；'.join(stock.get('bullish_evidence', []))}
利空：{'；'.join(stock.get('bearish_evidence', []))}

【触发条件】{stock.get('trigger_conditions', 'N/A')}
【失效条件】{stock.get('invalidation_conditions', 'N/A')}

【风险提示】{stock.get('risk_notes', '')}
"""
        # Append position plans for any held positions even in stock mode
        draft += "\n".join(_build_position_plan_lines(market, positions))
        draft += _format_source_block(state)
    else:
        sector_map = market.get("sector_map", {})
        sector_lines = []
        for layer, items in sector_map.items():
            if items:
                sector_lines.append(f"{layer}：")
                for item in items:
                    stocks = "、".join(item.get("key_stocks", []))
                    sector_lines.append(f"  - {item.get('name', '')}（{item.get('status', '')}）→ {item.get('logic', '')}；标的：{stocks}")

        themes = market.get("themes_in_focus", [])
        theme_lines = []
        for t in themes:
            theme_lines.append(f"【{t.get('theme', '')}】")
            theme_lines.append(f"催化：{t.get('catalyst', '')}")
            theme_lines.append(f"风险：{t.get('risk', '')}")
            theme_lines.append(f"相关：{'、'.join(t.get('key_stocks', []))}")

        idx = market.get("index_discipline", {})
        index_lines = []
        if idx:
            index_lines.append(f"支撑{idx.get('support', 'N/A')} / 压力{idx.get('resistance', 'N/A')}")
            index_lines.append(f"跌破→{idx.get('action_below', 'N/A')}；突破→{idx.get('action_above', 'N/A')}；中间→{idx.get('middle_zone', 'N/A')}")

        position_lines = _build_position_plan_lines(market, positions)

        sector_joined = '\n'.join(sector_lines) if sector_lines else '暂无'
        theme_joined = '\n'.join(theme_lines) if theme_lines else '暂无'
        index_joined = '\n'.join(index_lines) if index_lines else '暂无'
        position_joined = '\n'.join(position_lines) if position_lines else ''

        draft = f"""【盘面】{market.get('market_summary', '暂无')}

【周期定位】{market.get('market_phase', 'N/A')}，{market.get('phase_reasoning', '')}

【主线判断】{', '.join(market.get('main_themes', []))}

【板块结构地图】
{sector_joined}

【题材落地】
{theme_joined}

【指数纪律】
{index_joined}

【量能观察】{market.get('volume_note', '暂无')}

【情绪信号】{json.dumps(market.get('emotion_signals', {}), ensure_ascii=False)}

【明日跟踪】{'; '.join(market.get('tomorrow_watch', []))}

【风险提示】{market.get('risk_notes', '')}
{position_joined}
"""
        draft += _format_source_block(state)

    return {

        "draft_analysis": draft,
        "reasoning_steps": ["综合合成完成"],
    }


def style_writer(state: AgentState) -> AgentState:
    prompt_template = _load_prompt("style_writer")
    draft = state.get("draft_analysis", "")
    market_phase = state.get("market_context", {}).get("market_phase", "")
    examples = "\n\n".join(state.get("few_shot_examples", []))
    tone = _get_tone_by_market_phase(market_phase)
    review_notes = state.get("review_notes", [])
    revision_hint = ""
    if review_notes:
        revision_hint = f"【上一轮修改意见】{'；'.join(review_notes)}\n请按以上意见修正。"

    prompt = prompt_template.format(
        draft=draft,
        persona="[UP人格定义待加载]",
        examples=examples or "[暂无示例]",
        tone=tone,
        revision_hint=revision_hint,
    )

    content = _safe_llm_invoke(prompt)
    styled = content if content else f"[UP风格化] {draft}"

    return {

        "styled_output": styled,
        "reasoning_steps": ["风格化生成完成"],
    }


def reviewer(state: AgentState) -> AgentState:
    prompt_template = _load_prompt("reviewer")
    output = state.get("styled_output", "")
    claims = state.get("claims", [])

    prompt = f"""{prompt_template}

待审核输出：
{output}

检索到的 claims：
{json.dumps([c.get('id', 'N/A') for c in claims], ensure_ascii=False)}

请输出JSON：
"""
    content = _safe_llm_invoke(prompt)
    try:
        result = json.loads(content) if content else {}
    except json.JSONDecodeError:
        result = {}

    if not result:
        # 简单规则检查 fallback
        has_forbidden = any(w in output for w in ["无条件买入", "无条件卖出", "一定涨", "一定跌"])
        result = {
            "passed": not has_forbidden,
            "issues": ["检测到禁用词汇"] if has_forbidden else [],
            "verified_claims": [],
        }

    # Ensure review_notes are strings (LLM may return dicts in issues list)
    raw_issues = result.get("issues", []) or []
    review_notes: list[str] = []
    for item in raw_issues:
        if isinstance(item, str):
            review_notes.append(item)
        elif isinstance(item, dict):
            review_notes.append(json.dumps(item, ensure_ascii=False))
        else:
            review_notes.append(str(item))

    return {

        "review_passed": result.get("passed", False),
        "review_notes": review_notes,
        "claims_cited": result.get("verified_claims", []),
        "data_sources": [],
        "confidence": "high" if result.get("passed") else "low",
        "final_output": output,
        "reasoning_steps": [
            f"事实核查: {'通过' if result.get('passed') else '未通过'}"
        ],
    }
