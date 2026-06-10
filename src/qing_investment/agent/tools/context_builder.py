"""Context Builder — 在每次 LLM 调用前自动构建增强上下文。

Phase 2 核心组件：
- 从 Neo4j 检索标的相关的 claims（ABOUT 边 + 同主题 claims）
- 从 Qdrant 语义召回补充 claims
- 提取关键信息：语言强度、角色定义、介入建议、时效性
- 控制浓度：每只标的最多 3 条 claims 摘要（每条 50 字以内）

Refs: docs/config-cron-architecture-review.md v2.0 Phase 2
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


def _to_date_str(val: Any) -> str:
    """Normalize source_date to string format 'YYYY-MM-DD'.
    
    Neo4j returns Date objects; Qdrant returns strings. This handles both.
    """
    if isinstance(val, str):
        return val
    if hasattr(val, "strftime"):
        return val.strftime("%Y-%m-%d")
    return str(val)


def _parse_date(val: Any) -> datetime | None:
    """Parse a Date object or string into datetime for age calculation.
    
    Neo4j may return neotime.Date; Qdrant returns strings. Both are
    normalized to string first, then parsed.
    """
    date_str = _to_date_str(val)
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None

# ── 语言强度映射 ──
_INTENSITY_MAP = {
    "high": "🔥🔥🔥",
    "medium": "🔥🔥",
    "low": "🔥",
}

# ── 介入建议关键词提取 ──
_ENTRY_KEYWORDS = {
    "买入", "加仓", "建仓", "试探", "介入", "买点", "回调买", "回踩买",
    "可以参与", "值得参与", "赔率很高", "错了亏小钱",
}

_AVOID_KEYWORDS = {
    "不追高", "追高是韭菜", "只观察", "不参与", "回避", "减仓", "清仓",
    "观望", "等分歧", "等回踩",
}


def _extract_entry_signal(statement: str) -> str | None:
    """从 claim statement 中提取介入/回避信号。"""
    stmt = statement.lower()
    for kw in _ENTRY_KEYWORDS:
        if kw in stmt:
            return "建议介入"
    for kw in _AVOID_KEYWORDS:
        if kw in stmt:
            return "建议回避"
    return None


def _extract_role_definition(statement: str) -> str | None:
    """从 claim 中提取 UP 对标的的角色定义。"""
    role_keywords = {
        "龙头", "中军", "趋势", "情绪载体", "先锋", "补涨",
        "核心", "跟风", "铲子", "容量票", "大票", "小票",
        "机构票", "游资票", "白马", "黑马", "弹性",
    }
    for kw in role_keywords:
        if kw in statement:
            # 提取包含关键词的短句
            for sent in statement.replace("；", "。").split("。"):
                if kw in sent:
                    return sent.strip()[:50]
    return None


def _summarize_claim(claim: dict, max_len: int = 50) -> dict:
    """将 claim 浓缩为结构化摘要。"""
    stmt = claim.get("statement", "")
    intensity = claim.get("intensity", "medium")
    source_date = claim.get("source_date", "")

    # 计算时效性标签
    freshness = "历史"
    if source_date:
        dt = _parse_date(source_date)
        if dt:
            days_ago = (datetime.now() - dt).days
            if days_ago <= 7:
                freshness = "最新"
            elif days_ago <= 30:
                freshness = "近期"
        # 非 str 则不做 `strftime`，因为后面还要用 source_date

    # 提取关键信号
    entry_signal = _extract_entry_signal(stmt)
    role_def = _extract_role_definition(stmt)

    # 浓缩 statement
    summary = stmt[:max_len] + "..." if len(stmt) > max_len else stmt

    return {
        "id": claim.get("id", ""),
        "summary": summary,
        "intensity": _INTENSITY_MAP.get(intensity, "🔥🔥"),
        "freshness": freshness,
        "entry_signal": entry_signal,
        "role_definition": role_def,
        "source_date": _to_date_str(source_date),  # 统一为字符串
    }


def _score_claim_relevance(
    claim: dict,
    stock_code: str,
    stock_name: str,
    active_patterns: list[dict] | None = None,
) -> float:
    """评分 claim 与标的的相关性（越高越相关）。

    Args:
        claim: claim 字典
        stock_code: 股票代码
        stock_name: 股票名称
        active_patterns: 当前激活的 reasoning patterns（可选），
                        匹配到 pattern applicable_themes 的 claim 获得额外加分
    """
    score = 0.0
    stmt = claim.get("statement", "")
    subject = claim.get("subject", "")
    claim_type = claim.get("claim_type", "")

    # 直接提到股票代码或名称
    pure_code = stock_code.replace("sh", "").replace("sz", "").replace(".", "")
    if pure_code in stmt or pure_code in subject:
        score += 10.0
    if stock_name and stock_name in stmt:
        score += 8.0

    # 有介入建议信号
    if _extract_entry_signal(stmt):
        score += 5.0

    # 有角色定义
    if _extract_role_definition(stmt):
        score += 3.0

    # 时效性加分
    intensity = claim.get("intensity", "medium")
    if intensity == "high":
        score += 2.0

    source_date = claim.get("source_date", "")
    if source_date:
        dt = _parse_date(source_date)
        if dt:
            days_ago = (datetime.now() - dt).days
            if days_ago <= 3:
                score += 3.0
            elif days_ago <= 7:
                score += 2.0
            elif days_ago <= 14:
                score += 1.0

    # Phase 6: reasoning pattern 匹配加分
    if active_patterns:
        # 从 claim 的 subject 和 statement 中提取主题关键词
        claim_text = f"{subject} {stmt}".lower()
        for pattern in active_patterns:
            applicable_themes = pattern.get("applicable_themes", [])
            for theme in applicable_themes:
                if theme.lower() in claim_text:
                    # 匹配到 active pattern 的主题，额外加分
                    score += 4.0
                    break  # 每个 pattern 只加一次分

    return score


def build_stock_context(
    stock_code: str,
    stock_name: str,
    neo4j_claims: list[dict],
    qdrant_claims: list[dict] | None = None,
    max_claims: int = 3,
    active_patterns: list[dict] | None = None,
) -> dict:
    """为单只标的构建增强上下文。

    Args:
        stock_code: 股票代码（如 "000534.SZ"）
        stock_name: 股票名称
        neo4j_claims: 从 Neo4j 检索到的 claims（ABOUT 边）
        qdrant_claims: 从 Qdrant 语义召回的 claims（可选）
        max_claims: 最多注入几条 claims 摘要（防止上下文溢出）
        active_patterns: 当前激活的 reasoning patterns（可选），用于 claims 排序

    Returns:
        {
            "stock_code": "...",
            "stock_name": "...",
            "claim_count": 5,
            "claim_summary": [
                {"id": "...", "summary": "...", "intensity": "🔥🔥🔥", "freshness": "最新", "entry_signal": "建议介入", "role_definition": "..."}
            ],
            "overall_signal": "UP近期看好，建议回调介入",
            "latest_date": "2026-06-04",
        }
    """
    # 合并并去重
    all_claims: list[dict] = []
    seen_ids: set[str] = set()

    for c in neo4j_claims:
        cid = c.get("id", "")
        if cid and cid not in seen_ids:
            seen_ids.add(cid)
            all_claims.append(c)

    if qdrant_claims:
        for c in qdrant_claims:
            cid = c.get("id", "")
            if cid and cid not in seen_ids:
                seen_ids.add(cid)
                all_claims.append(c)

    # 按相关性评分排序（传入 active_patterns）
    scored = [
        (c, _score_claim_relevance(c, stock_code, stock_name, active_patterns))
        for c in all_claims
    ]
    scored.sort(key=lambda x: -x[1])

    # 取 Top N 并浓缩
    top_claims = scored[:max_claims]
    summaries = [_summarize_claim(c) for c, _ in top_claims]

    # 生成整体信号判断
    entry_signals = [s for s in summaries if s["entry_signal"] == "建议介入"]
    avoid_signals = [s for s in summaries if s["entry_signal"] == "建议回避"]

    if entry_signals and not avoid_signals:
        overall = f"UP{len(entry_signals)}次提及看好，建议关注介入机会"
    elif avoid_signals and not entry_signals:
        overall = f"UP{len(avoid_signals)}次提示回避，当前不建议介入"
    elif entry_signals and avoid_signals:
        overall = "UP观点存在分歧，需结合实时数据判断"
    else:
        overall = "UP近期未明确表态，以实时数据为准"

    # 最新提及日期
    dates = [_to_date_str(c.get("source_date", "")) for c in all_claims if c.get("source_date")]
    latest_date = max(dates) if dates else ""

    return {
        "stock_code": stock_code,
        "stock_name": stock_name,
        "claim_count": len(all_claims),
        "claim_summary": summaries,
        "overall_signal": overall,
        "latest_date": latest_date,
    }


def build_market_context(
    positions: list[dict],
    watchlist: list[dict],
    entry_points: list[dict],
    neo4j_client: Any,
    qdrant_client: Any | None = None,
    embedding_model: Any | None = None,
    active_patterns: list[dict] | None = None,
) -> dict:
    """为市场分析构建完整的增强上下文。

    识别需要分析的标的（持仓 + entry_points 中接近触发条件的票），
    对每只标的调用 build_stock_context 构建 claims 摘要。

    Args:
        active_patterns: 当前激活的 reasoning patterns（来自 _load_reasoning_patterns），
                         用于指导 claims 排序优先级

    Returns:
        {
            "target_stocks": ["000534.SZ", "600246.SH"],
            "stock_contexts": [
                {"stock_code": "...", "stock_name": "...", "claim_summary": [...], ...}
            ],
            "direction_signals": {
                "燃气轮机": {"intensity": "🔥🔥🔥", "latest_claim": "..."},
            }
        }
    """
    from qing_investment.agent.tools.neo4j_client import Neo4jClient

    # 收集需要分析的标的
    target_codes: set[str] = set()
    code_to_name: dict[str, str] = {}

    # 1. 持仓票
    for account in positions:
        for pos in account.get("positions", []):
            code = pos.get("code", "")
            if code:
                target_codes.add(code)
                code_to_name[code] = pos.get("name", "")

    # 2. entry_points 中 active 的票
    for ep in entry_points:
        code = ep.get("code", "")
        if code and ep.get("status") == "active":
            target_codes.add(code)
            code_to_name[code] = ep.get("name", "")

    # 3. watchlist 中 priority=high 的票（Top 10）
    high_priority = [
        w for w in watchlist
        if w.get("priority") == "high"
    ][:10]
    for w in high_priority:
        code = w.get("code", "")
        if code:
            target_codes.add(code)
            code_to_name[code] = w.get("name", "")

    # 为每只标的构建上下文
    stock_contexts = []
    # 收集方向信号（用于方向优先级判断）
    # Phase 2.1: 从 Neo4j 动态查询 sector-theme 方向（替代硬编码列表）
    direction_claims: dict[str, list[dict]] = {}
    try:
        if isinstance(neo4j_client, Neo4jClient):
            sector_themes = neo4j_client.get_sector_themes(days=30, limit=100)
            dynamic_directions = [st["direction"] for st in sector_themes]
        else:
            dynamic_directions = []
    except Exception as e:
        logger.warning("Failed to get dynamic sector themes: %s", e)
        dynamic_directions = []

    for code in target_codes:
        name = code_to_name.get(code, "")

        # Neo4j 检索
        neo4j_claims = []
        try:
            if isinstance(neo4j_client, Neo4jClient):
                neo4j_claims = neo4j_client.get_claims_about_stock(code, limit=10)
        except Exception as e:
            logger.warning("Neo4j claims retrieval failed for %s: %s", code, e)

        # Qdrant 语义召回（Phase 3: 动态 query 生成）
        qdrant_claims = None
        if qdrant_client and embedding_model:
            try:
                # Phase 3: 构建动态语义 query
                # 结合标的名称 + entry_points 触发条件 + 方向信息
                query_parts = [name, code.replace(".SZ", "").replace(".SH", "")]

                # 从 entry_points 找该标的的触发条件
                ep_trigger = ""
                for ep in entry_points:
                    if ep.get("code") == code and ep.get("status") == "active":
                        trigger = ep.get("trigger", "")
                        setup = ep.get("buy_setup", "")
                        if trigger:
                            ep_trigger = trigger
                        elif setup:
                            ep_trigger = setup
                        break

                if ep_trigger:
                    query_parts.append(ep_trigger)
                else:
                    # fallback: 从 claims 中提取技术面关键词
                    tech_keywords = []
                    for c in neo4j_claims[:3]:
                        stmt = c.get("statement", "")
                        # 提取常见技术信号
                        for kw in ["回踩", "突破", "企稳", "放量", "缩量", "分歧", "加速", "回调"]:
                            if kw in stmt and kw not in tech_keywords:
                                tech_keywords.append(kw)
                    if tech_keywords:
                        query_parts.extend(tech_keywords)
                    else:
                        query_parts.extend(["技术分析", "介入建议"])

                query_text = " ".join(query_parts)
                logger.debug("Qdrant query for %s: %s", code, query_text)

                query_vec = embedding_model.encode(query_text).tolist()[0]
                results = qdrant_client.search(query_vec, collection="qing_claims", limit=5)
                qdrant_claims = []
                for r in results:
                    payload = r.get("payload", {})
                    qdrant_claims.append({
                        "id": payload.get("claim_id", ""),
                        "statement": payload.get("statement", ""),
                        "subject": payload.get("subject", ""),
                        "source_date": payload.get("source_date", ""),
                        "intensity": payload.get("intensity", "medium"),
                        "claim_type": payload.get("claim_type", ""),
                    })
            except Exception as e:
                logger.warning("Qdrant claims retrieval failed for %s: %s", code, e)

        # 构建上下文（传入 active_patterns）
        ctx = build_stock_context(code, name, neo4j_claims, qdrant_claims, active_patterns=active_patterns)
        stock_contexts.append(ctx)

        # 收集方向信号（使用动态方向列表）
        for c in neo4j_claims:
            stmt = c.get("statement", "")
            for direction in dynamic_directions:
                if direction in stmt:
                    direction_claims.setdefault(direction, []).append(c)

    # 方向信号汇总
    direction_signals = {}
    for direction, claims in direction_claims.items():
        if not claims:
            continue
        # 找最新且强度最高的
        latest = max(claims, key=lambda c: _to_date_str(c.get("source_date", "")))
        intensity = latest.get("intensity", "medium")
        direction_signals[direction] = {
            "intensity": _INTENSITY_MAP.get(intensity, "🔥🔥"),
            "latest_claim": latest.get("statement", "")[:60] + "...",
            "claim_count": len(claims),
        }

    return {
        "target_stocks": list(target_codes),
        "stock_contexts": stock_contexts,
        "direction_signals": direction_signals,
    }
