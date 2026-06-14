from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np

from qing_investment.agent.tools.daily_state import (
    load_daily_state,
    save_daily_state,
    update_market_stage,
    update_direction_priority,
    update_position_stance,
    add_opportunity,
    add_intraday_narrative,
)
from qing_investment.agent.tools.llm_client import get_llm_client
from qing_investment.agent.tools.mem0_client import Mem0ClientWrapper
from qing_investment.agent.tools.neo4j_client import Neo4jClient
from qing_investment.agent.tools.qdrant_client import QdrantClientWrapper
from qing_investment.agent.tools.cost_tracker import CostTracker
from qing_investment.agent.config import settings
from qing_investment.kline_cache import format_multi_tf_macd_report, compute_td_report, compute_fibonacci_time_report
from .state import AgentState

logger = logging.getLogger(__name__)
_CN_TZ = timezone(timedelta(hours=8))

_REPO_ROOT = Path(__file__).resolve().parents[4]
_PROMPT_DIR = _REPO_ROOT / "src" / "qing_investment" / "agent" / "prompts" / "system"


def _load_prompt(name: str) -> str:
    path = _PROMPT_DIR / f"{name}.txt"
    if not path.exists():
        return f"[Prompt {name} not found]"
    content = path.read_text(encoding="utf-8")
    # 自动注入交易者人格（Phase 1 新增）
    mindset_path = _PROMPT_DIR / "trader_mindset.txt"
    if mindset_path.exists() and name in ("market_analyst", "stock_analyst"):
        mindset = mindset_path.read_text(encoding="utf-8")
        content = f"{mindset}\n\n---\n\n{content}"
    return content


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


# ── Daily State 提取与持久化（新增）──
def _extract_daily_state_block(content: str) -> dict | None:
    """从 LLM 原始输出中提取 ```daily_state 代码块。"""
    if not content:
        return None
    pattern = re.compile(r"```daily_state\s*\n(.*?)```", re.DOTALL)
    match = pattern.search(content)
    if not match:
        return None
    json_str = match.group(1).strip()
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        return None


def _now_cn_str(fmt: str = "%H:%M") -> str:
    return datetime.now(_CN_TZ).strftime(fmt)


def _persist_daily_state_from_market_context(
    market_context: dict,
    daily_state_override: dict | None,
    source_tag: str,
) -> None:
    """根据 market_analyst 输出更新 daily_state.json。

    优先使用 LLM 显式输出的 ```daily_state 代码块；
    若不存在，则从 market_context 的规范化字段推导。
    """
    try:
        state = load_daily_state()
        now_iso = datetime.now(_CN_TZ).isoformat()
        now_time = _now_cn_str("%H:%M")

        # 1) 应用 LLM 显式输出的 daily_state 块
        if daily_state_override:
            # market_stage
            if "market_stage" in daily_state_override:
                ms = daily_state_override["market_stage"]
                if isinstance(ms, dict) and ms.get("phase"):
                    state = update_market_stage(
                        state,
                        phase=ms["phase"],
                        detail=ms.get("detail", ""),
                        updated_by=source_tag,
                    )
            # direction_priority
            dp = daily_state_override.get("direction_priority")
            if dp:
                if isinstance(dp, list) and dp:
                    if isinstance(dp[0], str):
                        dp = [{"direction": d, "intensity": "", "source": source_tag} for d in dp]
                    else:
                        dp = [{**d, "source": d.get("source", source_tag)} for d in dp]
                    state = update_direction_priority(state, dp, source_tag)
            # position_stance
            ps = daily_state_override.get("position_stance")
            if ps:
                state = update_position_stance(state, str(ps), source_tag)
            # active_opportunities
            for opp in daily_state_override.get("active_opportunities", []):
                if isinstance(opp, dict) and opp.get("code"):
                    state = add_opportunity(
                        state,
                        stock=opp.get("stock", opp.get("code", "")),
                        code=opp["code"],
                        pattern=opp.get("pattern", ""),
                        trigger=opp.get("trigger", ""),
                        upside=opp.get("upside", opp.get("upside_pct", "")),
                        downside=opp.get("downside", opp.get("downside_pct", "")),
                        ratio=opp.get("ratio", opp.get("odds", "")),
                        status=opp.get("status", "未触发"),
                    )
            # intraday narrative keys (various node-specific fields)
            narrative_keys = {
                "core_assumption": "核心假设",
                "assumption_validation": "假设验证",
                "corrected_assumption": "假设修正",
                "morning_character": "早盘定性",
                "active_direction": "活跃方向",
                "morning_summary": "上午总结",
                "afternoon_plan_continue": "午后计划(延续)",
                "afternoon_plan_reverse": "午后计划(反转)",
                "discipline_check": "纪律检查",
                "risk_status": "风险状态",
                "pullback_alert": "回调预警",
                "morning_validation": "早盘验证",
                "afternoon_assessment": "午后评估",
                "tail_risk": "尾盘风险",
                "position_adjustment": "仓位调整",
                "tail_buy": "尾盘买入",
                "tail_sell": "尾盘卖出",
                "overnight_stance": "过夜策略",
                "tomorrow_preview": "明日预览",
                "tomorrow_assumption": "明日假设",
            }
            for key, label in narrative_keys.items():
                val = daily_state_override.get(key)
                if val:
                    summary = str(val)[:200]
                    state = add_intraday_narrative(state, f"{now_time} {label}", summary)

        # 2) 从 market_context 推导补充（如果显式块没给）
        if not daily_state_override or not daily_state_override.get("market_stage"):
            phase = market_context.get("market_phase", "")
            if phase and phase not in ("未配置", "数据不可用"):
                state = update_market_stage(
                    state,
                    phase=phase,
                    detail=market_context.get("phase_reasoning", "")[:200],
                    updated_by=f"{source_tag}:derived",
                )

        if not daily_state_override or not daily_state_override.get("direction_priority"):
            main_themes = market_context.get("main_themes", [])
            if main_themes:
                dp = [{"direction": str(t), "intensity": "", "source": f"{source_tag}:derived"} for t in main_themes[:5]]
                state = update_direction_priority(state, dp, source_tag)

        if not daily_state_override or not daily_state_override.get("position_stance"):
            position_plans = market_context.get("position_plans", [])
            if position_plans:
                # Derive a simple stance from first position plan advice
                first = position_plans[0]
                advice = first.get("position_advice", "")
                if advice:
                    state = update_position_stance(state, advice, f"{source_tag}:derived")

        # 3) 补充机会扫描到 active_opportunities
        if not daily_state_override or not daily_state_override.get("active_opportunities"):
            for opp in market_context.get("opportunity_scan", []):
                if isinstance(opp, dict) and opp.get("code"):
                    state = add_opportunity(
                        state,
                        stock=opp.get("stock", opp.get("code", "")),
                        code=opp["code"],
                        pattern=opp.get("pattern", ""),
                        trigger=opp.get("trigger", ""),
                        upside=opp.get("upside_pct", ""),
                        downside=opp.get("downside_pct", ""),
                        ratio=opp.get("odds", ""),
                        status=opp.get("status", "未触发"),
                    )

        # 4) 添加本节点综合叙事
        market_summary = market_context.get("market_summary", "")
        if market_summary:
            state = add_intraday_narrative(
                state, f"{now_time} 节点分析", str(market_summary)[:200]
            )

        # 写入元数据
        state.setdefault("_meta", {})
        state["_meta"]["last_persisted_by"] = source_tag
        state["_meta"]["last_persisted_at"] = now_iso

        save_daily_state(state)
        logger.info("Persisted daily_state from %s", source_tag)
    except Exception as e:
        logger.warning("Failed to persist daily_state: %s", e)


# ── Framework 显式加载（Phase 1 新增）──
_FRAMEWORK_LOADERS: dict[str, list[str]] = {
    "market": ["market-cycle-framework.md", "sector-diffusion-framework.md", "trading-rules.md", "market-breadth-framework.md"],
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


# ── 推理模式加载（Phase 4 新增，Phase 5 优化匹配算法，Phase 6 增加Embedding+LLM rerank）──
# 预加载的推理模式缓存（启动时从 reasoning-patterns.yaml 加载一次）
_PATTERNS_CACHE: list[dict] = []
# 多字段倒排索引缓存：包含 themes + name + description + step_names
_PATTERN_INDEX_CACHE: dict | None = None
# 框架 embedding 缓存（ONNX）
_PATTERN_EMBEDDINGS_CACHE: tuple[list[dict], np.ndarray] | None = None


def _ensure_patterns_cache() -> list[dict]:
    """加载 reasoning-patterns.yaml 到内存缓存（懒加载，首次调用时加载）。"""
    global _PATTERNS_CACHE
    if _PATTERNS_CACHE:
        return _PATTERNS_CACHE
    import yaml
    patterns_file = _REPO_ROOT / "framework" / "reasoning-patterns.yaml"
    if not patterns_file.exists():
        _PATTERNS_CACHE = []
        return []
    try:
        with open(patterns_file, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        _PATTERNS_CACHE = data.get("patterns", []) if data else []
    except Exception:
        _PATTERNS_CACHE = []
    return _PATTERNS_CACHE


def _get_embedding_model():
    """获取ONNX embedding模型，失败返回None。"""
    try:
        from qing_investment.agent.tools.embedding_utils import OnnxEmbeddingModel
        return OnnxEmbeddingModel()
    except Exception:
        return None


def _ensure_pattern_embeddings() -> tuple[list[dict], np.ndarray] | None:
    """预计算并缓存所有框架的embedding（基于name+description）。"""
    global _PATTERN_EMBEDDINGS_CACHE
    if _PATTERN_EMBEDDINGS_CACHE is not None:
        return _PATTERN_EMBEDDINGS_CACHE

    patterns = _ensure_patterns_cache()
    if not patterns:
        return None

    model = _get_embedding_model()
    if model is None:
        return None

    texts = [f"{p.get('name', '')}。{p.get('description', '')}" for p in patterns]
    try:
        embeddings = model.encode(texts)
        _PATTERN_EMBEDDINGS_CACHE = (patterns, embeddings)
        return _PATTERN_EMBEDDINGS_CACHE
    except Exception:
        return None


def _extract_keywords_from_text(text: str) -> set[str]:
    """从文本中提取有意义的 keywords（过滤停用词和短词）。"""
    _STOP_WORDS = {
        "怎么", "是否", "什么", "今天", "当前", "最近", "现在", "这种", "应该", "可以",
        "需要", "关注", "注意", "一个", "还有", "有没有", "哪些", "处于", "如何", "怎么样",
        "的", "了", "是", "在", "和", "与", "或", "对", "为", "有", "不", "就", "都", "而",
        "及", "等", "之", "以", "被", "把", "从", "到", "向", "让", "给", "但", "也", "却",
        "因为", "所以", "因此", "如果", "虽然", "然而", "而且", "并且", "或者", "还是",
    }
    keywords = set()
    for size in (2, 3, 4):
        for i in range(len(text) - size + 1):
            chunk = text[i:i+size]
            if (chunk.strip() and not chunk.isdigit()
                    and not all(c in '，。！？；：""''（）【】 \t\n-—…' for c in chunk)
                    and chunk not in _STOP_WORDS
                    and len(chunk.strip()) >= 2):
                keywords.add(chunk)
    return keywords


def _build_pattern_index(patterns: list[dict]) -> dict:
    """构建多字段倒排索引（Phase 5 优化）。

    索引字段按优先级排序：
    1. applicable_themes（精确匹配，权重最高）
    2. pattern_id + name（框架标识，权重高）
    3. description（描述文本，权重中）
    4. reasoning_chain step names（推理步骤名，权重中）

    返回: {"kw": [(pattern_idx, field_type, weight), ...], ...}
    """
    index: dict[str, list[tuple[int, str, float]]] = {}

    for pi, p in enumerate(patterns):
        # 1. applicable_themes — 精确匹配，权重=3.0
        for theme in p.get("applicable_themes", []):
            theme = theme.lower().strip()
            if theme:
                index.setdefault(theme, []).append((pi, "theme", 3.0))
                # 长主题词额外拆分为2字片段（权重降低）
                if len(theme) > 4:
                    for j in range(len(theme) - 1):
                        fragment = theme[j:j+2]
                        if len(fragment) >= 2:
                            index.setdefault(fragment, []).append((pi, "theme_fragment", 1.0))

        # 2. pattern_id + name — 权重=2.5
        name_text = f"{p.get('pattern_id', '')} {p.get('name', '')}".lower()
        for kw in _extract_keywords_from_text(name_text):
            index.setdefault(kw, []).append((pi, "name", 2.5))

        # 3. description — 权重=1.5
        desc = (p.get("description") or "").lower()
        for kw in _extract_keywords_from_text(desc):
            index.setdefault(kw, []).append((pi, "description", 1.5))

        # 4. reasoning_chain step names — 权重=1.0
        for step in p.get("reasoning_chain", []):
            step_name = (step.get("name") or "").lower()
            for kw in _extract_keywords_from_text(step_name):
                index.setdefault(kw, []).append((pi, "step_name", 1.0))

    return index


def _extract_themes_from_state(state: AgentState) -> set[str]:
    """从 query + claims + sector_context 中提取涉及的主题关键词（Phase 5 优化）。

    改进：
    1. 优先提取完整词（如"MLCC"、"半导体"）
    2. 滑动窗口只作为补充
    """
    _STOP_WORDS = {
        "怎么", "是否", "什么", "今天", "当前", "最近", "现在",
        "这种", "应该", "可以", "需要", "关注", "注意", "一个",
        "还有", "有没有", "哪些", "处于", "如何", "怎么样",
    }

    query = state.get("query", "")
    keywords: set[str] = set()

    # 1. 从 query 提取完整主题词（优先）
    q = query.lower()
    patterns = _ensure_patterns_cache()
    all_themes = set()
    for p in patterns:
        all_themes.update(t.lower() for t in p.get("applicable_themes", []))

    for theme in all_themes:
        if theme in q and len(theme) >= 2:
            keywords.add(theme)

    # 2. 从 query 提取2-4字滑动窗口（补充）
    for size in (2, 3, 4):
        for i in range(len(q) - size + 1):
            chunk = q[i:i+size]
            if (chunk.strip() and not chunk.isdigit()
                    and not all(c in '，。！？；：""''（）【】 \t\n-—…' for c in chunk)
                    and chunk not in _STOP_WORDS):
                keywords.add(chunk)

    # 3. 从 claims 的 subject 提取
    for c in state.get("claims", []):
        subj = (c.get("subject") or "").strip()
        if subj:
            keywords.add(subj.lower())

    # 4. 从 sector_context 提取
    for sc in state.get("sector_context", []):
        name = sc.get("name", "")
        if name:
            keywords.add(name.lower())

    return keywords


def _embed_recall_candidates(state: AgentState, top_k: int = 5) -> list[tuple[int, float]]:
    """阶段一：用ONNX embedding召回候选框架（Phase 6新增）。

    返回: [(pattern_idx, similarity), ...] 按相似度降序
    """
    query = state.get("query", "")
    if not query:
        return []

    emb_result = _ensure_pattern_embeddings()
    if emb_result is None:
        return []

    patterns, pattern_embeddings = emb_result
    model = _get_embedding_model()
    if model is None:
        return []

    try:
        query_vec = model.encode(query)
        # 余弦相似度（embedding已L2归一化）
        similarities = (query_vec @ pattern_embeddings.T)[0]
        top_indices = np.argsort(similarities)[::-1][:top_k]
        return [(int(idx), float(similarities[idx])) for idx in top_indices]
    except Exception:
        return []


def _llm_rerank_patterns(query: str, candidates: list[tuple[int, float]], patterns: list[dict]) -> list[dict]:
    """阶段二：用LLM对候选框架重排序（Phase 6新增）。

    输入候选框架的name+description+embedding相似度，LLM返回最相关的1-3个pattern_id。
    """
    if not candidates:
        return []

    router_prompt = _load_prompt("pattern_router")

    candidate_texts = []
    for idx, sim in candidates:
        p = patterns[idx]
        candidate_texts.append(
            f"- {p.get('pattern_id')}: {p.get('name')}\n"
            f"  description: {p.get('description', '')[:150]}\n"
            f"  embedding_similarity: {sim:.3f}"
        )

    prompt = f"""{router_prompt}

用户查询：{query}

候选推理框架：
{chr(10).join(candidate_texts)}

请输出JSON数组（不要markdown代码块）：
"""
    content = _safe_llm_invoke(prompt)
    if not content:
        # LLM失败，返回embedding Top3
        return [
            {
                "pattern_id": patterns[idx]["pattern_id"],
                "reason": f"embedding相似度 {sim:.3f}",
            }
            for idx, sim in candidates[:3]
        ]

    try:
        result = json.loads(content)
    except json.JSONDecodeError:
        # 尝试从代码块提取
        import re
        match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', content, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group(1))
            except json.JSONDecodeError:
                result = []
        else:
            result = []

    if not isinstance(result, list):
        result = []

    return result


def _load_reasoning_patterns(state: AgentState) -> list[dict]:
    """从 reasoning-patterns.yaml 加载与当前分析主题匹配的推理模式（Phase 6版）。

    匹配逻辑（两阶段：Embedding召回 + LLM重排序）：
    1. ONNX embedding计算query与所有框架的相似度，召回Top 5候选
    2. LLM根据候选框架的name/description做最终判断，返回Top 1-3
    3. 如果embedding或LLM失败，fallback到多字段关键词匹配

    改进点：
    - 语义匹配替代字符级滑动窗口
    - LLM解决框架边界模糊问题（如MLCC属于upstream_cycle而非ai_industry_chain）
    - 保留关键词匹配作为fallback
    """
    patterns = _ensure_patterns_cache()
    if not patterns:
        return []

    query = state.get("query", "")

    # 阶段一：Embedding召回
    candidates = _embed_recall_candidates(state, top_k=5)

    if candidates:
        # 阶段二：LLM重排序
        reranked = _llm_rerank_patterns(query, candidates, patterns)

        # 根据LLM结果过滤并排序
        selected_ids = {r["pattern_id"] for r in reranked if "pattern_id" in r}
        selected_patterns = []
        for r in reranked:
            pid = r.get("pattern_id")
            reason = r.get("reason", "")
            for idx, sim in candidates:
                p = patterns[idx]
                if p.get("pattern_id") == pid:
                    selected_patterns.append({
                        "pattern_id": p.get("pattern_id", ""),
                        "name": p.get("name", ""),
                        "description": p.get("description", ""),
                        "reasoning_chain": p.get("reasoning_chain", []),
                        "risk_factors": p.get("risk_factors", []),
                        "confidence_indicators": p.get("confidence_indicators", []),
                        "match_themes": [],
                        "match_name_keywords": [],
                        "match_score": round(sim, 3),
                        "rerank_reason": reason,
                    })
                    break

        if selected_patterns:
            print(
                f"[_load_reasoning_patterns] embedding_recall={len(candidates)}, "
                f"llm_rerank={len(selected_patterns)}, "
                f"selected={[p['pattern_id'] for p in selected_patterns]}"
            )
            return selected_patterns[:3]

    # Fallback: 多字段关键词匹配（Phase 5逻辑）
    print("[_load_reasoning_patterns] fallback to keyword matching")
    keywords = _extract_themes_from_state(state)
    if not keywords:
        return []

    global _PATTERN_INDEX_CACHE
    if _PATTERN_INDEX_CACHE is None:
        _PATTERN_INDEX_CACHE = _build_pattern_index(patterns)
    index = _PATTERN_INDEX_CACHE

    import math
    pattern_scores: dict[int, float] = {}
    matched_fields: dict[int, list[tuple[str, str, float]]] = {}

    for kw in keywords:
        hits = index.get(kw, [])
        if not hits:
            continue
        for pi, field_type, weight in hits:
            idf = 1.0 / math.log(len(set(h[0] for h in hits)) + 2)
            score = weight * idf
            pattern_scores[pi] = pattern_scores.get(pi, 0.0) + score
            matched_fields.setdefault(pi, []).append((kw, field_type, score))

    if not pattern_scores:
        return []

    MIN_MATCH_SCORE = 1.5
    sorted_pairs = sorted(pattern_scores.items(), key=lambda x: x[1], reverse=True)
    sorted_pairs = [(pi, round(s, 2)) for pi, s in sorted_pairs if s >= MIN_MATCH_SCORE]

    matched: list[dict] = []
    for pi, score in sorted_pairs[:3]:
        p = patterns[pi]
        fields = matched_fields.get(pi, [])
        matched_themes = list(set(kw for kw, ft, _ in fields if ft == "theme"))[:5]
        matched_name_kws = list(set(kw for kw, ft, _ in fields if ft == "name"))[:3]

        matched.append({
            "pattern_id": p.get("pattern_id", ""),
            "name": p.get("name", ""),
            "description": p.get("description", ""),
            "reasoning_chain": p.get("reasoning_chain", []),
            "risk_factors": p.get("risk_factors", []),
            "confidence_indicators": p.get("confidence_indicators", []),
            "match_themes": matched_themes,
            "match_name_keywords": matched_name_kws,
            "match_score": score,
            "rerank_reason": "keyword fallback",
        })

    return matched


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


def _apply_claim_freshness(claims: list[dict]) -> list[dict]:
    """对 claims 做时效性衰减排序和标注。

    委托给共享模块 tools/claim_freshness.py，保证 /chat 和 /analyze/trigger 两路径一致。

    - ≤7 天: 标为 [最新] — 当前观点，可作为辅助参考
    - 8-30 天: 标为 [近期] — 近期观点，参考价值递减
    - 31-90 天: 标为 [历史] — 仅作背景参考，不得作为判断依据
    - >90 天 / superseded: 直接过滤
    """
    from qing_investment.agent.tools.claim_freshness import apply_claim_freshness
    return apply_claim_freshness(claims)


# 方向词表用于矛盾检测（P1）
_BULLISH_WORDS = {"看多", "看好", "主升", "接棒", "主线", "配置", "加仓", "买入", "机会", "突破", "上涨", "领涨", "强势"}
_BEARISH_WORDS = {"看空", "回避", "规避", "减仓", "卖出", "风险", "调整", "退潮", "规避", "破位", "下跌", "领跌", "弱势"}


def _detect_claim_conflicts(claims: list[dict]) -> list[dict]:
    """检测同一 subject 下是否存在方向相反的 active claims。

    优先使用 Neo4j 的 CONTRADICTS 边，其次用关键词启发式作为补充。

    返回格式：
    [
      {
        "subject": "半导体",
        "source": "graph",     # "graph" | "keyword"
        "claims": [
          {"id": "claim-A", "statement": "...", "source_date": "2026-06-03", "direction": "bullish"},
          {"id": "claim-B", "statement": "...", "source_date": "2026-06-04", "direction": "bearish"}
        ]
      }
    ]
    """
    from collections import defaultdict

    # 构建 id → claim 映射
    claim_map: dict[str, dict] = {}
    by_subject: dict[str, list[dict]] = defaultdict(list)
    for c in claims:
        cid = c.get("id", "")
        if cid:
            claim_map[cid] = c
        subj = (c.get("subject") or "").strip()
        if subj:
            by_subject[subj].append(c)

    conflicts: list[dict] = []
    seen_pairs: set[tuple[str, str]] = set()

    # ── 阶段一：基于 Neo4j CONTRADICTS 边 ──
    for c in claims:
        cid = c.get("id", "")
        contradicts = c.get("contradicts", []) or []
        if not contradicts:
            continue
        for opp_id in contradicts:
            if opp_id not in claim_map:
                continue
            # 检查是否属于同一 subject，避免跨主题误报
            c_subj = (c.get("subject") or "").strip()
            opp_subj = (claim_map[opp_id].get("subject") or "").strip()
            if c_subj and opp_subj and c_subj == opp_subj:
                pair_key = tuple(sorted([cid, opp_id]))
                if pair_key not in seen_pairs:
                    seen_pairs.add(pair_key)
                    conflicts.append({
                        "subject": c_subj,
                        "source": "graph",
                        "claims": [
                            {"id": cid, "statement": c.get("statement", ""),
                             "source_date": c.get("source_date", ""), "direction": "unknown"},
                            {"id": opp_id, "statement": claim_map[opp_id].get("statement", ""),
                             "source_date": claim_map[opp_id].get("source_date", ""), "direction": "unknown"},
                        ],
                    })

    # ── 阶段二：关键词启发式补充（仅检出未被 graph 覆盖的矛盾）──
    for subj, group in by_subject.items():
        if len(group) < 2:
            continue
        directed: list[dict] = []
        for c in group:
            cid = c.get("id", "")
            # 如果该 claim 已通过 graph 检出矛盾，跳过
            already_in_conflict = any(
                cid in [cl["id"] for cl in conf["claims"]]
                for conf in conflicts
                if conf.get("source") == "graph" and conf["subject"] == subj
            )
            if already_in_conflict:
                continue
            stmt = c.get("statement", "")
            bull = any(w in stmt for w in _BULLISH_WORDS)
            bear = any(w in stmt for w in _BEARISH_WORDS)
            if bull and not bear:
                direction = "bullish"
            elif bear and not bull:
                direction = "bearish"
            else:
                direction = "neutral"
            directed.append({
                "id": cid,
                "statement": stmt,
                "source_date": c.get("source_date", ""),
                "direction": direction,
            })
        has_bull = any(d["direction"] == "bullish" for d in directed)
        has_bear = any(d["direction"] == "bearish" for d in directed)
        if has_bull and has_bear:
            conflicts.append({
                "subject": subj,
                "source": "keyword",
                "claims": directed,
            })

    return conflicts


def _apply_intensity_weight(claims: list[dict], is_stock_query: bool = False) -> list[dict]:
    """对个股查询，低强度 claims 降权/过滤（方案C）。

    - 个股查询: intensity=low → 排到末尾 + 标记 penalty
    - intensity=high → boost 往前排7天
    - 大盘/板块查询: 不影响排序（大盘走 _filter_methodology_only）
    """
    for c in claims:
        intensity = c.get("intensity", "medium")
        days = c.get("days_ago", 999)

        if is_stock_query and intensity == "low":
            # 个股查询：low intensity 排到末尾
            c["intensity_penalty"] = True
            c["_sort_key"] = days + 365
        elif intensity == "high":
            c["_sort_key"] = max(0, days - 7)  # boost 7天
        else:
            c["_sort_key"] = days

    claims.sort(key=lambda x: x.get("_sort_key", 999))
    return claims


async def retrieve_knowledge(state: AgentState) -> AgentState:
    query = state.get("query", "")
    stock_code = state.get("parsed_intent", {}).get("stock_code")
    session_id = state.get("session_id", "default")

    neo4j = Neo4jClient()
    qdrant = QdrantClientWrapper()
    mem0 = Mem0ClientWrapper()

    claims, wiki_snippets, memories, few_shot = [], [], [], []
    seen_ids: set[str] = set()

    try:
        if stock_code:
            # Stock-specific queries: use Neo4j relationship graph with evolution info
            claims = neo4j.get_claims_with_evolution(stock_code, limit=10)
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
                                "subject": node.get("subject", ""),
                            })
            else:
                # Fallback to keyword search if embedding model unavailable
                keywords = _extract_sector_keywords(query)
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

    # ── 图遍历补充：通过共享实体发现相关 claims（方案1）──
    if claims:
        try:
            graph_related_ids: set[str] = set()
            # 取 top-3 检索 claims，遍历同实体相关 claims
            for c in claims[:3]:
                cid = c.get("id", "")
                if cid:
                    related = neo4j.get_related_claims(cid, limit=5)
                    for rc in related:
                        rid = rc.get("id", "")
                        if rid and rid not in seen_ids:
                            graph_related_ids.add(rid)
            
            # 获取全文并合并
            for rid in graph_related_ids:
                rc = neo4j.get_claim_evolution(rid)
                if rc:
                    first = rc[0] if isinstance(rc, list) else rc
                    if first and first.get("id"):
                        first["source"] = "graph_traversal"
                        claims.append(first)
                        seen_ids.add(rid)
        except Exception:
            pass  # 图遍历失败不阻断主流程

    # ── Claims 时效衰减排序（P0 新增）──
    claims = _apply_claim_freshness(claims)

    # ── Intensity boost/penalty（方案C）──
    claims = _apply_intensity_weight(claims, is_stock_query=bool(stock_code))

    # ── 个股查询过滤 low intensity（与 /chat 保持一致）──
    if stock_code:
        claims = [c for c in claims if c.get("intensity") != "low"]

    # ── 同一主题矛盾检测（P1 新增）──
    potential_conflicts = _detect_claim_conflicts(claims)

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
                    "source_date": (r.get("payload") or {}).get("source_date", ""),
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

    # ── Phase 2 新增：Context Builder — Claims 实时注入 ──
    stock_contexts: list[dict] = []
    direction_signals: dict = {}
    try:
        from qing_investment.agent.tools.context_builder import build_market_context
        from qing_investment.agent.tools.llm_client import get_embedding_model

        positions = state.get("positions", [])
        watchlist = state.get("watchlist", [])

        # 读取 entry_points（从 strategy_pack.yaml）
        entry_points: list[dict] = []
        try:
            import yaml
            strategy_pack_path = _REPO_ROOT / "config" / "stock_monitor" / "strategy_pack.yaml"
            if strategy_pack_path.exists():
                with open(strategy_pack_path, encoding="utf-8") as f:
                    sp = yaml.safe_load(f) or {}
                entry_points = sp.get("entry_points", [])
        except Exception:
            pass

        # Phase 6: 预计算 active reasoning patterns 用于 claims 排序
        # 注意：这里使用简化版匹配（基于 query 关键词），
        # 而非 market_analyst 中的完整 Embedding+LLM rerank
        # 目的是在 retrieve_knowledge 阶段就给匹配到 pattern 的 claims 加分
        active_patterns = _load_reasoning_patterns(state)

        emb_model = get_embedding_model()
        ctx_result = build_market_context(
            positions=positions,
            watchlist=watchlist,
            entry_points=entry_points,
            neo4j_client=neo4j,
            qdrant_client=qdrant,
            embedding_model=emb_model,
            active_patterns=active_patterns,  # Phase 6: 传入激活的 reasoning patterns
        )
        stock_contexts = ctx_result.get("stock_contexts", [])
        direction_signals = ctx_result.get("direction_signals", {})
        print(
            f"[retrieve_knowledge] context_builder: "
            f"stocks={len(stock_contexts)}, directions={list(direction_signals.keys())}, "
            f"active_patterns={[p['pattern_id'] for p in active_patterns]}"
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Context Builder failed: %s", e)
        stock_contexts = []
        direction_signals = {}

    neo4j.close()

    # ── 上下文压缩：确保不超过 token 预算 ──
    try:
        from qing_investment.monitor.context import TokenBudgetManager
        _tbm = TokenBudgetManager()
        _state_update = {
            "claims": claims,
            "wiki_snippets": wiki_snippets,
            "sector_context": sector_context,
            "memories": memories,
            "few_shot_examples": few_shot,
            "stock_contexts": stock_contexts,
        }
        _compressed = _tbm.compress(_state_update, max_tokens=8000, strategy="priority")
        claims = _compressed.get("claims", claims)
        wiki_snippets = _compressed.get("wiki_snippets", wiki_snippets)
        sector_context = _compressed.get("sector_context", sector_context)
        memories = _compressed.get("memories", memories)
        few_shot = _compressed.get("few_shot_examples", few_shot)
    except Exception:
        pass  # 压缩失败不影响主流程

    # 检索审计日志
    wiki_framework_count = sum(1 for s in wiki_snippets if s.get("source", "").startswith("framework/"))
    wiki_meth_count = sum(1 for s in wiki_snippets if "wiki/投资方法论" in s.get("source", ""))
    conflict_subjects = [c["subject"] for c in potential_conflicts]
    print(
        f"[retrieve_knowledge] query='{query}', "
        f"claims={len(claims)}, wiki={len(wiki_snippets)} "
        f"(framework={wiki_framework_count}, meth={wiki_meth_count}), "
        f"memories={len(memories)}, sector_ctx={len(sector_context)}, "
        f"conflicts={len(potential_conflicts)} {conflict_subjects}"
    )

    return {
        "claims": claims,
        "wiki_snippets": wiki_snippets,
        "sector_context": sector_context,
        "external_sector_boards": state.get("external_sector_boards", {}),
        "knowledge_graph": {},
        "memories": memories,
        "few_shot_examples": few_shot,
        "potential_conflicts": potential_conflicts,
        "stock_contexts": stock_contexts,       # Phase 2 新增
        "direction_signals": direction_signals,  # Phase 2 新增
        "reasoning_steps": [
            f"检索到 {len(claims)} 条claims, {len(wiki_snippets)} 个wiki片段, "
            f"{len(memories)} 条记忆, {len(sector_context)} 个动态板块"
            f"{f', 发现 {len(potential_conflicts)} 组潜在矛盾: {conflict_subjects}' if potential_conflicts else ''}"
            f", Context Builder: {len(stock_contexts)} 只标的增强上下文"
        ],
    }


def _filter_methodology_only(claims: list[dict]) -> list[dict]:
    """过滤claims，只保留方法论相关的，移除具体观点claim。

    保留：
    - 含方法论关键词的claim（如"框架"、"周期"、"冰点"、"纪律"）
    - ≤7天的 market-cycle 周期判断（UP近期观点）
    移除：具体看多/看空某股的claim
    """
    methodology_keywords = {
        "框架", "周期", "方法论", "规则", "纪律", "策略", "体系",
        "冰点", "回暖", "高潮", "退潮", "轮动", "主线", "扩散",
        "upstream", "downstream", "产业链", "估值", "仓位",
    }
    filtered = []
    for c in claims:
        stmt = (c.get("statement") or "").lower()
        # 如果claim包含方法论关键词，保留
        if any(kw in stmt for kw in methodology_keywords):
            filtered.append(c)
            continue
        subj = (c.get("subject") or "").lower()
        if any(kw in subj for kw in methodology_keywords):
            filtered.append(c)
            continue
        # ≤7天的 market-cycle claim 保留（UP近期周期判断）
        ct = c.get("claim_type", "")
        days = c.get("days_ago", 999)
        if ct == "market-cycle" and days <= 7:
            filtered.append(c)
            continue
        # 否则过滤掉（具体观点claim）
    return filtered


def market_analyst(state: AgentState) -> AgentState:
    logger = logging.getLogger(__name__)
    _t0 = time.time()
    prompt_template = _load_prompt("market_analyst")
    esb = state.get("external_sector_boards", {})
    analysis_type = (state.get("parsed_intent") or {}).get("analysis_type", "stock")

    # ── Log input data stats ──
    market_snapshot = dict(state.get("market_snapshot") or {})
    quotes = market_snapshot.get("quotes", []) or []
    claims = state.get("claims", []) or []
    positions = state.get("positions", []) or []
    watchlist = state.get("watchlist", []) or []
    logger.info(
        f"market_analyst_input: quotes={len(quotes)} claims={len(claims)} "
        f"positions={len(positions)} watchlist={len(watchlist)} "
        f"esb_available={esb.get('available')} "
        f"analysis_type={analysis_type}"
    )
    has_realtime_data = (
        esb.get("available") or
        (market_snapshot.get("quotes") and len(market_snapshot.get("quotes", [])) > 0)
    )

    # 【修改】实时数据缺失时降级为知识库分析，而非直接拒绝
    # 原因：cron job 在数据源限流时频繁失败，claims 知识库足以支撑基础分析
    if analysis_type in ("market", "portfolio") and not has_realtime_data:
        # 不 return 空结果，而是继续执行，让 LLM 基于 claims 知识库分析
        # 在 prompt 中注入数据缺失说明，由 LLM 自行处理
        state["_data_missing_note"] = (
            "【注意】实时行情数据暂时无法获取（数据源限流或网络问题）。"
            "本次分析将基于 UP 历史观点（claims）和策略框架进行，"
            "缺少实时价格验证，分析结论的时效性可能受限。"
        )
        # 继续执行后续代码，不中断

    # Truncate market_snapshot quotes to keep prompt size reasonable
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

    # 加载匹配的推理模式（Phase 4 新增）
    reasoning_patterns = _load_reasoning_patterns(state)
    if reasoning_patterns:
        print(
            f"[market_analyst] reasoning_patterns={len(reasoning_patterns)}, "
            f"patterns={[p['pattern_id'] for p in reasoning_patterns]}, "
            f"match_themes={[p.get('match_themes') for p in reasoning_patterns]}"
        )

    # 动态加载分析框架片段（不改 framework/ 目录）
    analysis_framework = _load_analysis_framework()
    prompt_template_filled = prompt_template.replace("{analysis_framework}", analysis_framework)

    # ── 【修改】过滤claims，只保留方法论相关 ──
    raw_claims = state.get("claims", [])
    methodology_claims = _filter_methodology_only(raw_claims)
    print(
        f"[market_analyst] claims_total={len(raw_claims)}, "
        f"methodology_only={len(methodology_claims)}, "
        f"filtered={len(raw_claims) - len(methodology_claims)}"
    )

    # ── 【修改】过滤wiki_snippets，只保留framework和方法论相关 ──
    raw_wiki = state.get("wiki_snippets", [])
    methodology_wiki = [
        s for s in raw_wiki
        if s.get("source", "").startswith("framework/") or "投资方法论" in s.get("source", "")
    ]

    # ── 构建watchlist摘要（按优先级分组，Phase 8.1 增强）──
    watchlist_summary = []
    reference_stocks = []  # P4: 非主板（创业板/科创板），仅作情绪锚点
    _PRIORITY_SORT = {"P1": 0, "P1-核心": 0, "P2": 1, "P2-重点": 1, "P3": 2, "P3-观察": 2}

    def _is_mainboard(code: str) -> bool:
        """判断是否为可交易的主板标的（sh6xxxxx / sz0xxxxx，排除300创业板+688科创板）。"""
        pure = code.replace(".SH", "").replace(".SZ", "").strip()
        if not pure:
            return False
        if pure.startswith("688"):
            return False
        if pure.startswith("300"):
            return False
        return True

    for w_item in state.get("watchlist", []) or []:
        entry_info_parts = []
        price_range = w_item.get("entry_price_range") or ""
        if price_range:
            entry_info_parts.append(f"介入区间:{price_range}")
        hs = w_item.get("entry_hard_stop") or ""
        if hs:
            entry_info_parts.append(f"止损:{hs}")
        entry_info = " ".join(entry_info_parts)

        lifecycle = w_item.get("lifecycle_stage") or "观察"
        code = w_item.get("code", "")
        priority = w_item.get("priority", "P3")
        sort_key = _PRIORITY_SORT.get(priority, 99)

        item = {
            "code": code,
            "name": w_item.get("name", ""),
            "priority": priority,
            "sort_key": sort_key,
            "theme": w_item.get("theme", ""),
            "segment": w_item.get("segment", ""),
            "role": w_item.get("role", ""),
            "lifecycle": lifecycle,
            "entry_info": entry_info,
            "latest": w_item.get("latest"),
            "pct_change": w_item.get("pct_change"),
            "watch_reason_short": (w_item.get("watch_reason") or "")[:80],
            "reduce_zone": w_item.get("reduce_zone_desc", ""),
            "risk_zone": w_item.get("risk_zone_desc", ""),
            "up_sentiment": w_item.get("up_sentiment", ""),
        }

        if _is_mainboard(code):
            watchlist_summary.append(item)
        else:
            # 非主板 → 自动归为P4，不入机会扫描
            item["priority"] = "P4-锚点"
            item["sort_key"] = 3
            reference_stocks.append(item)

    watchlist_summary.sort(key=lambda x: x["sort_key"])
    reference_stocks.sort(key=lambda x: x["sort_key"])
    _wl_with_entry = sum(1 for z in watchlist_summary if z["entry_info"])
    _wl_with_lifecycle = sum(1 for z in watchlist_summary if z["lifecycle"] and z["lifecycle"] != "观察")
    logger.info(
        f"watchlist_summary: tradeable={len(watchlist_summary)} "
        f"reference={len(reference_stocks)} "
        f"with_entry_zone={_wl_with_entry} with_lifecycle={_wl_with_lifecycle}"
    )

    # ── 生成多级别MACD分析报告（Step 3 新增）──
    try:
        macd_report = format_multi_tf_macd_report(bars=10)
    except Exception:
        macd_report = "[MACD数据暂不可用]"

    # ── 生成神奇九转报告（Step 3 新增）──
    tf_order_local = ["daily", "120min", "90min", "60min", "30min"]
    td_reports = []
    for code in ["sh000001", "sh000985"]:
        for tf in tf_order_local:
            try:
                r = compute_td_report(code, tf, bars=30)
                if r:
                    td_reports.append(f"[{code} {tf}]\n{r}")
            except Exception:
                pass
    td_report = "\n".join(td_reports) if td_reports else "[九转序列数据暂不可用]"

    # ── 生成斐波那契时间分析报告（Step 3 新增）──
    fib_reports = []
    for code in ["sh000001", "sh000985"]:
        try:
            r = compute_fibonacci_time_report(code)
            if r:
                fib_reports.append(f"[{code}]\n{r}")
        except Exception:
            pass
    fib_report = "\n".join(fib_reports) if fib_reports else "[斐波那契数据暂不可用]"

    context = {
        "claims": methodology_claims,
        "wiki_snippets": methodology_wiki,
        "framework_rules": framework_context,
        "reasoning_patterns": reasoning_patterns,
        "macd_multi_tf_report": macd_report,
        "td_sequential_report": td_report,
        "fibonacci_time_report": fib_report,
        "market_snapshot": market_snapshot,
        "sector_strengths": state.get("sector_strengths", []),
        "external_sector_boards": esb,
        "sector_context": state.get("sector_context", []),
        "memories": state.get("memories", []),
        "stock_contexts": state.get("stock_contexts", []),      # Phase 2 新增
        "direction_signals": state.get("direction_signals", {}),  # Phase 2 新增
        "watchlist_summary": watchlist_summary,  # Phase 8.1 增强：可交易主板标的摘要
        "reference_stocks": reference_stocks,    # Phase 8.1 P4-锚点：非主板（情绪参考，不可操作）
    }
    prompt = f"""{prompt_template_filled}

{state.get("_data_missing_note", "")}

检索到的知识（已过滤，仅保留方法论内容）：
{json.dumps(context, ensure_ascii=False, indent=2)}

当前持仓：
{json.dumps(state.get('positions', []), ensure_ascii=False, indent=2)}

请输出JSON：
"""
    content = _safe_llm_invoke(prompt)
    _t1 = time.time()
    logger.info(f"market_analyst_llm: duration={_t1-_t0:.1f}s prompt_len={len(prompt)}")

    # 成本追踪
    _ct = CostTracker()
    _ct.record_call(provider=(settings.llm_provider or "deepseek"))
    _cost_snapshot = _ct.snapshot()

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
            "opportunity_scan": [],  # Phase 1 新增
            "position_plans": [],
        }

    # 【新增】提取并持久化 daily_state，保证观点上下文连续性
    daily_state_override = _extract_daily_state_block(content)
    source_tag = f"market_analyst:{analysis_type}"
    _persist_daily_state_from_market_context(result, daily_state_override, source_tag)

    return {
        "market_context": result,
        "reasoning_steps": [
            f"市场周期: {result.get('market_phase', 'N/A')}"
        ],
        "cost_tracking": [_cost_snapshot],
    }


def _get_stock_name(stock_code: str, market_snapshot: dict, watchlist: list[dict]) -> str:
    """从行情快照或观察池中提取股票名称。"""
    for q in market_snapshot.get("quotes", []):
        if q.get("code") == stock_code or q.get("secid") == stock_code:
            name = q.get("name") or q.get("label", "")
            if name:
                return name
    for w in watchlist:
        if w.get("code") == stock_code:
            return w.get("name", "")
    return ""


# ── 个股地位关键词（用于从 claims 中提取 UP 标注）──
_POSITION_KEYWORDS = {
    "龙头", "中军", "趋势", "情绪载体", "先锋", "补涨",
    "核心", "跟风", "铲子", "容量票", "大票", "小票",
    "机构票", "游资票", "白马", "黑马",
}


def _extract_up_position_from_claims(stock_code: str, claims: list[dict]) -> tuple[str, str]:
    """从 claims 中提取 UP 对该股的地位标注。

    返回 (position_description, source_hint)。
    如果没有找到，返回 ('', '')。
    """
    pure_code = stock_code.replace("sh", "").replace("sz", "").replace(".", "")
    matches: list[str] = []
    sources: set[str] = set()

    for c in claims:
        stmt = c.get("statement", "")
        subject = c.get("subject", "")
        # 只处理与该股票相关的 claim
        if pure_code not in subject and subject not in stmt:
            # 简单模糊匹配：如果 claim 中既没有股票代码也没有股票名称，跳过
            continue

        # 提取包含地位关键词的句子片段
        for kw in _POSITION_KEYWORDS:
            if kw in stmt:
                # 提取关键词所在句子（简单按句号/分号分割）
                for sentence in stmt.replace("；", "。").split("。"):
                    if kw in sentence and pure_code in sentence:
                        matches.append(sentence.strip())
                        sources.add(c.get("source_path", "") or c.get("id", ""))
                        break

    if not matches:
        return "", ""

    # 去重并拼接
    unique = []
    seen = set()
    for m in matches:
        if m not in seen:
            seen.add(m)
            unique.append(m)

    position = "；".join(unique[:3])
    source = list(sources)[0] if sources else ""
    return position, source


def _fetch_stock_external_info(stock_code: str, stock_name: str) -> list[dict]:
    """通过网络搜索获取个股最新公开信息，用于外部校验。"""
    try:
        from qing_investment.agent.tools.web_search import search_web_simple
    except Exception:
        return []
    query = f"{stock_name} {stock_code.replace('.SH', '').replace('.SZ', '')} 主营业务 最新"
    try:
        results = search_web_simple(query, limit=3)
    except Exception:
        results = []
    return results


def _get_stock_sector_positioning(stock_code: str, up_position: str, up_source: str) -> dict:
    """获取个股板块定位（三层定位法）。"""
    try:
        from qing_investment.agent.tools.stock_sector_mapper import (
            get_stock_positioning,
            to_agent_format,
        )
        result = get_stock_positioning(stock_code, up_position, up_source)
        return to_agent_format(result)
    except Exception as e:
        return {
            "stock_code": stock_code,
            "up_position": up_position,
            "final_position": up_position or "未知",
            "final_reason": f"板块定位获取失败: {e}",
            "sector_details": [],
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

    # 根据 trigger.kind 选择 prompt：买入确认模式 vs 常规个股分析
    trigger = state.get("trigger", {})
    is_buy_signal_mode = trigger.get("kind") == "buy_signal_candidate"
    prompt_template = _load_prompt("stock_analyst")
    market_snapshot = state.get("market_snapshot", {})
    watchlist = state.get("watchlist", [])
    stock_name = _get_stock_name(stock_code, market_snapshot, watchlist)
    external_validation = _fetch_stock_external_info(stock_code, stock_name)

    # ── 三层定位法：注入板块定位数据 ──
    claims = state.get("claims", [])
    up_position, up_source = _extract_up_position_from_claims(stock_code, claims)
    sector_positioning = _get_stock_sector_positioning(stock_code, up_position, up_source)

    # ── Phase 2 新增：从 stock_contexts 中找到当前标的的增强上下文 ──
    stock_contexts = state.get("stock_contexts", [])
    current_stock_ctx = None
    for ctx in stock_contexts:
        if ctx.get("stock_code") == stock_code:
            current_stock_ctx = ctx
            break

    # ── 买入确认模式：注入候选详情 ──
    buy_signal_candidates = state.get("buy_signal_candidates", [])
    current_candidate = None
    for c in buy_signal_candidates:
        if c.get("stock_code") == stock_code:
            current_candidate = c
            break

    context = {
        "stock_code": stock_code,
        "stock_name": stock_name,
        "external_validation": external_validation,
        "positions": state.get("positions", []),
        "watchlist": watchlist,
        "claims": claims,
        "market_context": state.get("market_context", {}),
        "sector_positioning": sector_positioning,
        "stock_context": current_stock_ctx,  # Phase 2 新增
        "direction_signals": state.get("direction_signals", {}),  # Phase 2 新增
        "trigger_kind": trigger.get("kind", ""),
        "buy_signal_candidate": current_candidate if is_buy_signal_mode else None,
    }
    prompt = f"""{prompt_template}

上下文：
{json.dumps(context, ensure_ascii=False, indent=2)}

请输出JSON：
"""
    content = _safe_llm_invoke(prompt)

    # 成本追踪
    _sa_ct = CostTracker()
    _sa_ct.record_call(provider=(settings.llm_provider or "deepseek"))
    _sa_cost = _sa_ct.snapshot()

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
            "odds_analysis": {},  # Phase 1 新增
            "trigger_conditions": "未配置",
            "invalidation_conditions": "未配置",
            "risk_notes": "",
        }

    return {
        "stock_analysis": result,
        "reasoning_steps": [
            f"个股地位: {result.get('stock_role', 'N/A')}"
        ],
        "cost_tracking": [_sa_cost],
    }


def devils_advocate(state: AgentState) -> AgentState:
    """Devil's Advocate 节点 — 强制使用不同模型家族对分析结论进行反向质疑。

    插入在 stock_analyst/market_analyst 之后、synthesize 之前。
    主分析失败不影响此节点正常执行。
    """
    logger = logging.getLogger(__name__)

    market_ctx = state.get("market_context", {})
    stock_analysis = state.get("stock_analysis", {})
    claims_cited = state.get("claims_cited", [])
    da_findings = state.get("devils_advocate_findings", [])

    # 如果没有分析内容，跳过
    if not market_ctx and not stock_analysis:
        logger.info("devils_advocate: skipped (no analysis to challenge)")
        return {"devils_advocate_findings": da_findings}

    try:
        from qing_investment.agent.agents.devils_advocate import DevilsAdvocateAgent
        from qing_investment.agent.tools.llm_client import get_llm_client

        # 强制用 Kimi（不同模型家族）
        llm = get_llm_client(provider="kimi")
        agent = DevilsAdvocateAgent(llm=llm)

        import asyncio
        result = asyncio.run(agent.run(
            market_analysis=_market_ctx_summary(market_ctx),
            stock_analysis=_stock_analysis_summary(stock_analysis),
            claims_cited=claims_cited,
        ))
        logger.info(
            f"devils_advocate: findings={len(result.findings)} "
            f"errors={len(result.errors)} cost={result.cost_usd}"
        )
        return {"devils_advocate_findings": result.findings}
    except Exception as e:
        logger.warning("devils_advocate failed: %s", e)
        return {"devils_advocate_findings": da_findings}


def _market_ctx_summary(ctx: dict) -> str:
    """提取大盘分析的可读摘要。"""
    parts = [
        f"周期: {ctx.get('market_phase', 'N/A')}",
        f"推理: {ctx.get('phase_reasoning', '')}",
    ]
    themes = ctx.get("main_themes", [])
    if themes:
        parts.append(f"主线: {', '.join(themes)}")
    notes = ctx.get("risk_notes", "")
    if notes:
        parts.append(f"风险: {notes}")
    return "\n".join(parts)


def _stock_analysis_summary(analysis: dict) -> str:
    """提取个股分析的可读摘要。"""
    parts = [
        f"地位: {analysis.get('stock_role', 'N/A')}",
    ]
    bullish = analysis.get("bullish_evidence", [])
    bearish = analysis.get("bearish_evidence", [])
    if bullish:
        parts.append(f"利多: {'; '.join(bullish[:3])}")
    if bearish:
        parts.append(f"利空: {'; '.join(bearish[:3])}")
    return "\n".join(parts)


def _format_devils_advocate_block(state: AgentState) -> str:
    """格式化 Devil's Advocate 质疑点段落。"""
    findings = state.get("devils_advocate_findings", [])
    if not findings:
        return ""

    lines = ["", "⚠️ 反向质疑"]
    for f in findings:
        target = f.get("target", "未知")
        concern = f.get("concern", "")
        severity = f.get("severity", "low")
        confidence = f.get("confidence", 0.5)
        sev_icon = {"high": "🔴", "medium": "🟡", "low": "⚪"}.get(severity, "⚪")
        lines.append(f"  {sev_icon} [{target}] {concern} (severity={severity}, confidence={confidence})")
    return "\n".join(lines)


def _format_source_block(state: AgentState) -> str:
    """从检索到的知识构建参考来源段落，强制注入到草稿末尾。

    【修改】只保留framework和wiki方法论引用，移除claim引用。
    """
    sources: list[str] = []
    seen: set[str] = set()

    # Framework rules（方法论来源）
    for f in state.get("framework_rules", []):
        src = f"framework/{f.get('file', '')}"
        if src and src not in seen:
            seen.add(src)
            sources.append(src)

    # Wiki snippets — 只保留framework和投资方法论（方法论来源）
    for s in state.get("wiki_snippets", [])[:5]:
        src = s.get("source", "")
        # 只保留方法论相关的wiki来源
        if src.startswith("framework/") or "投资方法论" in src or "wiki/投资方法论" in src:
            if src and src not in seen:
                seen.add(src)
                sources.append(src)

    # 【移除】Claims不再作为来源引用
    # for c in state.get("claims", [])[:5]:
    #     cid = c.get("id", "")
    #     if cid and cid not in seen:
    #         seen.add(cid)
    #         sources.append(cid)

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
    logger = logging.getLogger(__name__)
    market = state.get("market_context", {})
    stock = state.get("stock_analysis", {})
    positions = state.get("positions", [])

    # Log input data summary
    pos_count = len(positions)
    opp_count = len(market.get("opportunity_scan", []))
    theme_count = len(market.get("themes_in_focus", []))
    has_stock = bool(stock)
    logger.info(
        f"synthesize: has_stock={has_stock} "
        f"positions={pos_count} opportunity_scan={opp_count} themes={theme_count} "
        f"market_phase={market.get('market_phase', 'N/A')}"
    )

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
        draft += _format_devils_advocate_block(state)
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

        # Phase 1 新增：机会扫描展示
        opportunity_scan = market.get("opportunity_scan", [])
        opportunity_lines = []
        if opportunity_scan:
            opportunity_lines.append("【机会扫描】")
            for opp in opportunity_scan:
                opportunity_lines.append(
                    f"  · {opp.get('stock', 'N/A')}({opp.get('code', '')}): "
                    f"{opp.get('pattern', '')} | "
                    f"触发: {opp.get('trigger', '')} | "
                    f"赔率: {opp.get('odds', 'N/A')} | "
                    f"置信: {opp.get('confidence', 'N/A')}"
                )

        position_lines = _build_position_plan_lines(market, positions)

        sector_joined = '\n'.join(sector_lines) if sector_lines else '暂无'
        theme_joined = '\n'.join(theme_lines) if theme_lines else '暂无'
        index_joined = '\n'.join(index_lines) if index_lines else '暂无'
        opportunity_joined = '\n'.join(opportunity_lines) if opportunity_lines else ''
        position_joined = '\n'.join(position_lines) if position_lines else ''

        draft = f"""【盘面】{market.get('market_summary', '暂无')}

【周期定位】{market.get('market_phase', 'N/A')}，{market.get('phase_reasoning', '')}

【主线判断】{', '.join(market.get('main_themes', []))}

【板块结构地图】
{sector_joined}

【题材落地】
{theme_joined}

{opportunity_joined}

【指数纪律】
{index_joined}

【量能观察】{market.get('volume_note', '暂无')}

【情绪信号】{json.dumps(market.get('emotion_signals', {}), ensure_ascii=False)}

【明日跟踪】{'; '.join(market.get('tomorrow_watch', []))}

【风险提示】{market.get('risk_notes', '')}
{position_joined}
"""
        draft += _format_devils_advocate_block(state)
        draft += _format_source_block(state)

    return {

        "draft_analysis": draft,
        "reasoning_steps": ["综合合成完成"],
    }


def style_writer(state: AgentState) -> AgentState:
    logger = logging.getLogger(__name__)
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

    # Log input summary before LLM call
    has_vague_terms = any(w in draft for w in ["等回踩", "等分歧", "逢低关注", "逢低布局"])
    logger.info(
        f"style_writer: draft_len={len(draft)} market_phase={market_phase} "
        f"has_vague_terms={has_vague_terms} review_round={len(review_notes)}"
    )

    content = _safe_llm_invoke(prompt)
    styled = content if content else f"[UP风格化] {draft}"

    logger.info(f"style_writer: output_len={len(styled)} generated={bool(content)}")

    # 成本追踪
    _sw_ct = CostTracker()
    _sw_ct.record_call(provider=(settings.llm_provider or "deepseek"))
    _sw_cost = _sw_ct.snapshot()

    return {
        "styled_output": styled,
        "reasoning_steps": ["风格化生成完成"],
        "cost_tracking": [_sw_cost],
    }


def reviewer(state: AgentState) -> AgentState:
    logger = logging.getLogger(__name__)
    _t0 = time.time()
    prompt_template = _load_prompt("reviewer")
    output = state.get("styled_output", "")
    claims = state.get("claims", [])
    retry_count = state.get("_retry_count", 0)

    prompt = f"""{prompt_template}

待审核输出：
{output}

检索到的 claims：
{json.dumps([c.get('id', 'N/A') for c in claims], ensure_ascii=False)}

请输出JSON：
"""
    content = _safe_llm_invoke(prompt)

    # 成本追踪
    _rv_ct = CostTracker()
    _rv_ct.record_call(provider=(settings.llm_provider or "deepseek"))
    _rv_cost = _rv_ct.snapshot()

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

    _t1 = time.time()
    passed = result.get("passed", False)
    logger.info(
        f"reviewer: passed={passed} retry={retry_count} "
        f"issues={len(raw_issues)} duration={_t1-_t0:.1f}s "
        f"output_len={len(output)}"
    )
    if not passed and raw_issues:
        logger.info(f"reviewer_issues: {' | '.join(str(i)[:80] for i in raw_issues[:3])}")

    return {
        "review_passed": passed,
        "review_notes": review_notes,
        "claims_cited": result.get("verified_claims", []),
        "data_sources": [],
        "confidence": "high" if result.get("passed") else "low",
        "final_output": output,
        "reasoning_steps": [
            f"事实核查: {'通过' if result.get('passed') else '未通过'}"
        ],
        "cost_tracking": [_rv_cost],
    }
