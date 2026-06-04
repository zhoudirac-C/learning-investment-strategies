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
            claims = neo4j.get_claims_about_stock(stock_code, limit=10)
        else:
            # For market/sector queries, search by keyword
            keywords = [query.replace("分析一下", "").replace("板块", "").strip()]
            for kw in keywords:
                if kw:
                    claims = neo4j.get_claims_by_keyword(kw, limit=10)
                    if claims:
                        break
    except Exception as e:
        claims = []

    try:
        qdrant.ensure_collection("qing_knowledge", vector_size=1024)
        from qing_investment.agent.tools.llm_client import get_embedding_model
        emb_model = get_embedding_model()
        if emb_model:
            query_vec = emb_model.encode(query).tolist()
            results = qdrant.search(query_vec, collection="qing_knowledge", limit=5)
            wiki_snippets = [
                {"text": r.payload.get("text", r.payload.get("chunk_text", "")), "source": r.payload.get("source_path", r.payload.get("source", "")), "score": r.score}
                for r in results
            ]
    except Exception as e:
        wiki_snippets = []

    try:
        memories = mem0.search(query, user_id=session_id)
    except Exception as e:
        memories = []

    few_shot = _load_few_shot_examples(query)

    neo4j.close()

    return {

        "claims": claims,
        "wiki_snippets": wiki_snippets,
        "knowledge_graph": {},
        "memories": memories,
        "few_shot_examples": few_shot,
        "reasoning_steps": [
            f"检索到 {len(claims)} 条claims, {len(wiki_snippets)} 个wiki片段, {len(memories)} 条记忆"
        ],
    }


def market_analyst(state: AgentState) -> AgentState:
    prompt_template = _load_prompt("market_analyst")
    context = {
        "claims": state.get("claims", []),
        "wiki_snippets": state.get("wiki_snippets", []),
        "market_snapshot": state.get("market_snapshot", {}),
        "memories": state.get("memories", []),
    }
    prompt = f"""{prompt_template}

检索到的知识：
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
            "market_phase": "未配置",
            "phase_reasoning": "LLM未返回结果或API未配置",
            "main_themes": [],
            "sector_strength": {},
            "emotion_signals": {},
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


def synthesize(state: AgentState) -> AgentState:
    market = state.get("market_context", {})
    stock = state.get("stock_analysis", {})

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
    else:
        draft = f"""【盘面】{market.get('market_summary', '暂无')}

【周期定位】{market.get('market_phase', 'N/A')}，{market.get('phase_reasoning', '')}

【主线判断】{', '.join(market.get('main_themes', []))}

【板块强弱】{json.dumps(market.get('sector_strength', {}), ensure_ascii=False)}

【情绪信号】{json.dumps(market.get('emotion_signals', {}), ensure_ascii=False)}

【风险提示】{market.get('risk_notes', '')}
"""

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
