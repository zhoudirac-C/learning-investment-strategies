from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import re
import time
from datetime import datetime, timezone, timedelta

from langgraph.types import Send
from pathlib import Path

import numpy as np

from qing_investment.agent.tools.daily_state import (
    load_daily_state,
    save_daily_state,
    archive_daily_state,
    update_market_stage,
    update_direction_priority,
    update_position_stance,
    add_opportunity,
    add_intraday_narrative,
    update_field,
    normalize_code,
)
from qing_investment.agent.tools.llm_client import (
    format_provider_usage_summary,
    get_llm_client,
    get_provider_usage_records,
    record_provider_usage,
)
from qing_investment.agent.tools.mem0_client import Mem0ClientWrapper
from qing_investment.agent.tools.neo4j_client import Neo4jClient
from qing_investment.agent.tools.qdrant_client import QdrantClientWrapper
from qing_investment.agent.tools.cost_tracker import CostTracker
from qing_investment.agent.tools.external_market_fetcher import fetch_pre_market_brief
from qing_investment.agent.config import settings
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
    if mindset_path.exists() and name in ("stock_analyst", "market_summary", "stock_scanner", "cron_closing"):
        mindset = mindset_path.read_text(encoding="utf-8")
        content = f"{mindset}\n\n---\n\n{content}"
    return content


def _load_prompt_for_trigger(trigger_id: str | None, default_name: str) -> str:
    """根据 trigger.id 选择对应 prompt；未匹配时回退到 default prompt。"""
    prompt_map = {
        "pre_market": "cron_pre_market",
        "open_auction": "cron_opening",
        "open_confirm": "cron_opening",
        "morning_confirm": "cron_morning_confirm",
        "closing_review": "cron_closing",
    }
    if trigger_id in prompt_map:
        return _load_prompt(prompt_map[trigger_id])
    return _load_prompt(default_name)


def _load_analysis_framework() -> str:
    """加载市场分析框架 prompt 片段（独立于主 prompt，方便修改）。"""
    path = _PROMPT_DIR / "market_analysis_framework.txt"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return "[market_analysis_framework.txt not found]"


def shard_router(state: AgentState) -> list[Send]:
    """根据 watchlist 生成分片，并 fan-out 到多个 stock_scanner_shard 节点。

    当 shard_size <= 0 或 watchlist 很小时，返回单个 shard（复用现有逻辑，不走外部分片）。
    """
    from qing_investment.agent.tools.watchlist_sharder import (
        shard_watchlist,
        shard_to_context,
    )

    watchlist = _normalize_watchlist(state.get("watchlist"))
    positions = _normalize_positions(state.get("positions"))

    # 兼容旧的外部分片请求：如果调用方已经传了 watchlist_shard，直接用它
    existing_shard = state.get("watchlist_shard")
    if existing_shard:
        return [Send("stock_scanner_shard", {"watchlist_shard": existing_shard})]

    # analyze_trigger 已经解析好 shard_size / core_only，这里直接复用，避免再次读取环境变量覆盖请求值
    shard_size = state.get("shard_size")
    if shard_size is None:
        shard_size = int(os.environ.get("WATCHLIST_SHARD_SIZE", "8"))
    core_only = state.get("core_only")
    if core_only is None:
        core_only = False

    # shard_size <= 0 表示不分片：直接扫描全部 watchlist
    if shard_size <= 0:
        return [Send("stock_scanner_shard", {"watchlist_shard": {"name": "全部标的", "items": watchlist, "is_priority": False}})]

    shards = shard_watchlist(
        watchlist,
        positions,
        max_items=shard_size,
        core_only=core_only,
    )

    if not shards:
        # 没有可分析标的时仍跑一个空 shard，保证下游节点有 market_context
        return [Send("stock_scanner_shard", {"watchlist_shard": None})]

    return [
        Send("stock_scanner_shard", {"watchlist_shard": shard_to_context(s)})
        for s in shards
    ]


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


def _build_daily_state_summary_for_closing(daily_state: dict) -> str:
    """构建收盘复盘使用的 daily_state 摘要，包含历史变更记录。

    输出格式面向 LLM，便于做预判 vs 实际对比。
    """
    lines: list[str] = []

    stage = daily_state.get("market_stage", {})
    if stage.get("phase") and stage["phase"] != "未判断":
        lines.append(f"当前市场阶段：{stage['phase']} | {stage.get('detail', '')}")
        lines.append(f"阶段最后更新：{stage.get('updated_by', '')} @ {stage.get('updated_at', '')}")

    directions = daily_state.get("direction_priority", [])
    if directions:
        lines.append("当前方向优先级：")
        for d in directions[:3]:
            lines.append(f"  - {d.get('direction', '')} ({d.get('intensity', '')})")

    stance = daily_state.get("position_stance", "")
    if stance and stance != "未判断":
        lines.append(f"当前持仓态度：{stance}")

    opportunities = daily_state.get("active_opportunities", [])
    if opportunities:
        lines.append("当前活跃机会：")
        for o in opportunities[:5]:
            lines.append(f"  - {o.get('stock', '')}({o.get('code', '')}): {o.get('pattern', '')} | {o.get('status', '')}")

    history = daily_state.get("history", [])
    if history:
        lines.append("今日关键判断演进：")
        for h in history[-10:]:
            stage_phase = (h.get("market_stage") or {}).get("phase", "")
            dirs = [d.get("direction", "") for d in h.get("direction_priority", [])[:3]]
            lines.append(
                f"  [{h.get('source', '')}] {h.get('timestamp', '')[:16]} "
                f"阶段={stage_phase} 方向={' > '.join(dirs)} 机会数={h.get('opportunity_count', 0)}"
            )

    narrative = daily_state.get("intraday_narrative", [])
    if narrative:
        lines.append("今日节点叙事：")
        for n in narrative[-5:]:
            lines.append(f"  - {n.get('time', '')}: {n.get('summary', '')}")

    return "\n".join(lines) if lines else "今日尚未建立市场判断。"


def _refresh_active_opportunity_statuses(
    daily_state: dict,
    positions: list[dict],
    quotes: list[dict],
) -> None:
    """收盘复盘前根据收盘价自动刷新机会状态。

    - 收盘价在 entry_zone 内 → "候选"
    - 收盘价跌破 stop_loss → "失效"
    - 已出现在持仓中 → "已触发"
    """
    opportunities = daily_state.get("active_opportunities", [])
    if not opportunities:
        return

    quote_lookup: dict[str, dict] = {}
    for q in quotes or []:
        code = _pure_stock_code(q.get("code") or q.get("secid"))
        if code:
            quote_lookup[code] = q

    position_codes = {_pure_stock_code(p.get("code", "")) for p in positions or []}

    for opp in opportunities:
        code = _pure_stock_code(opp.get("code", ""))
        if not code:
            continue
        quote = quote_lookup.get(code)
        if not quote:
            continue

        price = quote.get("latest") or quote.get("price")
        if price is None:
            continue
        try:
            price = float(price)
        except (ValueError, TypeError):
            continue

        if code in position_codes:
            opp["status"] = "已触发"
            continue

        stop_loss = opp.get("stop_loss")
        if stop_loss is not None:
            try:
                if price < float(stop_loss):
                    opp["status"] = "失效"
                    continue
            except (ValueError, TypeError):
                pass

        entry_zone = opp.get("entry_zone")
        if entry_zone and len(entry_zone) >= 2:
            try:
                low, high = float(entry_zone[0]), float(entry_zone[1])
                if low <= price <= high:
                    opp["status"] = "候选"
            except (ValueError, TypeError):
                pass


def _persist_daily_state_from_market_context(
    market_context: dict,
    daily_state_override: dict | None,
    source_tag: str,
    trigger_id: str | None = None,
) -> None:
    """根据 market_summary / stock_scanner 输出更新 daily_state.json。

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
                        entry_zone=opp.get("entry_zone"),
                        stop_loss=opp.get("stop_loss"),
                        source_node=source_tag,
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
                        upside=opp.get("upside", opp.get("upside_pct", "")),
                        downside=opp.get("downside", opp.get("downside_pct", "")),
                        ratio=opp.get("ratio", opp.get("odds", "")),
                        status=opp.get("status", "未触发"),
                        entry_zone=opp.get("entry_zone"),
                        stop_loss=opp.get("stop_loss"),
                        source_node=f"{source_tag}:derived",
                    )

        # 4) 添加本节点综合叙事
        market_summary = market_context.get("market_summary", "")
        if market_summary:
            label_map = {
                "open_auction": "09:26 剧本验证",
                "open_confirm": "09:45 假设验证",
                "morning_confirm": "10:00 结论固化",
            }
            label = label_map.get(trigger_id, f"{now_time} 节点分析")
            state = add_intraday_narrative(
                state, label, str(market_summary)[:200]
            )

        # Phase 1.4: 记录关键字段的最后更新来源
        update_field(state, source_tag, "market_stage", state.get("market_stage", {}))
        update_field(state, source_tag, "direction_priority", state.get("direction_priority", []))
        update_field(state, source_tag, "position_stance", state.get("position_stance", "未判断"))
        update_field(state, source_tag, "active_opportunities", state.get("active_opportunities", []))

        # 写入元数据与版本化记录（Phase 1）
        state.setdefault("_meta", {})
        state["_meta"]["last_persisted_by"] = source_tag
        state["_meta"]["last_persisted_at"] = now_iso

        # 版本号与历史变更记录：只在 market_summary 节点递增，避免 stock_scanner 重复填充 history
        is_market_summary_node = source_tag.startswith("market_summary:")
        if is_market_summary_node:
            current_version = state.get("version", 1)
            state["version"] = current_version + 1

            # 追加关键字段变更历史，便于收盘复盘做预判 vs 实际对比
            state.setdefault("history", [])
            state["history"].append({
                "version": current_version,
                "source": source_tag,
                "timestamp": now_iso,
                "market_stage": copy.deepcopy(state.get("market_stage", {})),
                "direction_priority": copy.deepcopy(state.get("direction_priority", [])),
                "position_stance": state.get("position_stance", ""),
                "opportunity_count": len(state.get("active_opportunities", [])),
                "narrative_count": len(state.get("intraday_narrative", [])),
            })
            # 保留最近 50 条历史记录，防止文件无限增长
            if len(state["history"]) > 50:
                state["history"] = state["history"][-50:]
            logger.info("Persisted daily_state from %s (version=%d)", source_tag, state["version"])
        else:
            logger.info("Persisted daily_state from %s (version=%d)", source_tag, state.get("version", 1))

        save_daily_state(state)
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


def _safe_llm_invoke(
    prompt: str,
    min_length: int = 0,
    use_acp_first: bool | None = None,
) -> str:
    """安全调用 LLM，默认走配置 provider。

    通过环境变量控制本地调用优先级：
    - KIMI_CODE_ACP_FIRST=1 / true：优先本地 Kimi Code ACP（stdio JSON-RPC）
    - KIMI_CODE_CLI_FIRST=1 / true：[已废弃] 优先本地 Kimi Code CLI（kimi -p，受 argv 限制）
    - 否则：直接走 settings.llm_provider

    Args:
        prompt: 发送给 LLM 的提示。
        min_length: 本地调用返回内容的最小可接受长度（字符数）。
            若返回内容长度低于此值，视为失败并 fallback 到配置 provider。
        use_acp_first: 是否优先本地 ACP。None 时从环境变量读取；
            False 时强制走配置 provider（用于 style_writer / reviewer 等 retry 节点，避免本地 ACP 拖慢）。
    """
    import os

    if use_acp_first is None:
        # 默认不优先本地 ACP（2026-08-03 起：监控链路全面走远端 deepseek，
        # 避免每次 LLM 调用都 spawn `kimi acp` 子进程产生僵尸/反复重启）。
        acp_first = os.environ.get("KIMI_CODE_ACP_FIRST", "0").lower() not in ("0", "false", "no")
    else:
        acp_first = use_acp_first
    # [DEPRECATED] kimi -p 方式已废弃，不再加入本地优先列表。
    # cli_first = os.environ.get("KIMI_CODE_CLI_FIRST", "0").lower() not in ("0", "false", "no")

    local_providers = []
    if acp_first:
        local_providers.append("kimi-code-acp")
    # if cli_first:
    #     local_providers.append("kimi-code-cli")

    for local_provider in local_providers:
        logger.info("[_safe_llm_invoke] 优先尝试 %s", local_provider)
        record_provider_usage(local_provider, "attempt", "local-first enabled")
        local_llm = get_llm_client(provider=local_provider)
        try:
            content = local_llm.invoke(prompt).content
            record_provider_usage(local_provider, "success", f"content_len={len(content)}")
            logger.info(
                "[_safe_llm_invoke] %s 成功, content_len=%d, tracker=%s",
                local_provider,
                len(content),
                format_provider_usage_summary(get_provider_usage_records()),
            )
            if min_length > 0 and len(content) < min_length:
                raise RuntimeError(
                    f"{local_provider} returned too short output ({len(content)} chars, min={min_length})"
                )
            return content
        except Exception as e:
            record_provider_usage(local_provider, "failed", str(e)[:120])
            logger.warning(
                "[_safe_llm_invoke] %s 失败: %s, 将 fallback 到 %s",
                local_provider, e, settings.llm_provider,
            )
        finally:
            try:
                local_llm.stop()
            except Exception:
                pass

    # fallback / 直接走配置 provider
    logger.info("[_safe_llm_invoke] 调用配置 provider: %s", settings.llm_provider)
    record_provider_usage(settings.llm_provider, "fallback" if local_providers else "attempt")
    try:
        llm = get_llm_client()
        content = llm.invoke(prompt).content
        record_provider_usage(settings.llm_provider, "success", f"content_len={len(content)}")
        logger.info(
            "[_safe_llm_invoke] provider %s 成功, content_len=%d, tracker=%s",
            settings.llm_provider,
            len(content),
            format_provider_usage_summary(get_provider_usage_records()),
        )
        return content
    except Exception as e:
        record_provider_usage(settings.llm_provider, "failed", str(e)[:120])
        logger.warning(
            "[_safe_llm_invoke] provider %s 失败: %s, tracker=%s",
            settings.llm_provider,
            e,
            format_provider_usage_summary(get_provider_usage_records()),
        )
        return ""


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
        # 而非 market_summary / stock_scanner 中的完整 Embedding+LLM rerank
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


def _pure_index_code(raw: str | None) -> str:
    """从 secid/code 中提取纯指数代码，复用个股代码归一化逻辑。"""
    return _pure_stock_code(raw)


def _slim_market_snapshot_for_summary(market_snapshot: dict) -> dict:
    """为 market_summary 保留指数+关键市场数据，去掉个股明细。"""
    if not market_snapshot:
        return {}
    quotes = market_snapshot.get("quotes", []) or []
    market_indexes = {"000001", "399001", "399006", "000688", "000985", "000016", "000300", "000905", "000852", "399303"}
    slim_quotes = [
        q for q in quotes
        if _pure_index_code(q.get("secid")) in market_indexes
        or _pure_index_code(q.get("code")) in market_indexes
        or "指数" in (q.get("label") or "")
    ]
    return {
        **market_snapshot,
        "quotes": slim_quotes,
        "_slim_from": len(quotes),
    }


_MAX_MARKET_SUMMARY_PROMPT_BYTES = 128000
_MAX_STOCK_SCANNER_PROMPT_BYTES = 64000


def _truncate_context_for_prompt(
    context: dict,
    non_context_bytes: int,
    max_bytes: int = _MAX_MARKET_SUMMARY_PROMPT_BYTES,
    truncatable_fields: list[str] | None = None,
) -> tuple[dict, bool]:
    """迭代压缩/丢弃低优先级上下文字段，直到 prompt 低于 max_bytes。

    策略：优先截断列表型字段（每次取前一半），必要时清空单个字段；
    按字段当前序列化大小从大到小处理，直到总 prompt 字节数合规。
    返回 (context, was_truncated)。
    """
    truncated = dict(context)
    was_truncated = False
    # 低优先级在前：优先截断/丢弃
    if truncatable_fields is None:
        truncatable_fields = [
            "memories",
            "wiki_snippets",
            "claims",
            "sector_context",
            "reasoning_patterns",
            "framework_rules",
        ]

    for _ in range(100):
        context_json = json.dumps(truncated, ensure_ascii=False, indent=2, default=str)
        total_bytes = non_context_bytes + len(context_json.encode("utf-8"))
        if total_bytes <= max_bytes:
            return truncated, was_truncated

        was_truncated = True
        sizes = []
        for field in truncatable_fields:
            value = truncated.get(field)
            if value:
                field_bytes = len(
                    json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")
                )
                sizes.append((field_bytes, field))

        if not sizes:
            return truncated, was_truncated

        sizes.sort(reverse=True)
        field = sizes[0][1]
        value = truncated[field]

        if isinstance(value, list):
            if len(value) > 1:
                truncated[field] = value[: max(1, len(value) // 2)]
            else:
                truncated[field] = []
        elif isinstance(value, dict):
            keys = list(value.keys())
            if len(keys) > 1:
                truncated[field] = {k: value[k] for k in keys[: max(1, len(keys) // 2)]}
            else:
                truncated[field] = {}
        else:
            # 其他类型无法继续截断，跳过防止死循环
            break

    return truncated, was_truncated


def _build_degraded_digest(market_snapshot: dict, esb: dict) -> dict:
    """market_summary LLM 失败时的规则拼装降级摘要（纯原始数据，无 LLM 加工）。

    只读 market_snapshot.quotes / market_snapshot.sentiment / external_sector_boards，
    产出盘面概述文本 + 结构化情绪信号，供下游合成保底使用——不编造任何判断。
    """
    snapshot = market_snapshot or {}
    quotes = snapshot.get("quotes") or []
    sentiment = snapshot.get("sentiment") or {}
    if not isinstance(sentiment, dict):
        sentiment = {}
    parts: list[str] = ["【未加工原始数据】"]

    def _pct(q: dict) -> float | None:
        try:
            return float(q.get("pct_change"))
        except (TypeError, ValueError):
            return None

    index_keywords = ("上证指数", "深证成指", "创业板指", "科创50", "中证全指", "全A")
    idx_parts = []
    for q in quotes:
        label = q.get("label") or q.get("name") or ""
        pct = _pct(q)
        if pct is not None and any(k in label for k in index_keywords):
            idx_parts.append(f"{label}{pct:+.2f}%")
    if idx_parts:
        parts.append("指数：" + " ".join(idx_parts[:6]))

    # 量能：沪深成交额合计（quotes 的 amount 单位为万元）
    def _amount_of(keyword: str) -> float | None:
        for q in quotes:
            label = q.get("label") or q.get("name") or ""
            if keyword in label:
                try:
                    return float(q.get("amount") or 0)
                except (TypeError, ValueError):
                    return None
        return None

    sh_amt, sz_amt = _amount_of("上证指数"), _amount_of("深证成指")
    if sh_amt is not None and sz_amt is not None and (sh_amt + sz_amt) > 0:
        parts.append(f"量能：沪深合计约{(sh_amt + sz_amt) / 10000.0:.0f}亿（截至快照时间）")

    if sentiment:
        emo: list[str] = []
        if sentiment.get("limit_up_count") is not None:
            emo.append(f"涨停{sentiment['limit_up_count']}")
        if sentiment.get("limit_down_count") is not None:
            emo.append(f"跌停{sentiment['limit_down_count']}")
        if sentiment.get("consecutive_height") is not None:
            emo.append(f"连板高度{sentiment['consecutive_height']}板")
        if sentiment.get("broken_board_rate") is not None:
            try:
                emo.append(f"炸板率{float(sentiment['broken_board_rate']) * 100:.1f}%")
            except (TypeError, ValueError):
                pass
        if sentiment.get("up_count") is not None and sentiment.get("down_count") is not None:
            emo.append(f"涨{sentiment['up_count']}/跌{sentiment['down_count']}家")
        if emo:
            parts.append("情绪：" + " ".join(emo))

    boards = esb or {}
    for key, board_label in (("concept", "概念"), ("industry", "行业")):
        leaders = ((boards.get(key) or {}).get("leaders") or [])[:5]
        tops = []
        for b in leaders:
            name = b.get("name")
            try:
                pct = float(b.get("pct_change") or 0)
            except (TypeError, ValueError):
                continue
            if name:
                tops.append(f"{name}{pct:+.1f}%")
        if tops:
            parts.append(f"板块榜（{board_label}，按涨幅）：" + " ".join(tops))

    return {"summary_text": "；".join(parts), "emotion_signals": sentiment}


def market_summary(state: AgentState) -> AgentState:
    """市场/板块分析节点：只输出精简市场背景，不处理个股。"""
    logger = logging.getLogger(__name__)
    _t0 = time.time()
    trigger_id = (state.get("trigger") or {}).get("id")
    prompt_template = _load_prompt_for_trigger(trigger_id, "market_summary")
    is_closing_review = trigger_id == "closing_review"
    analysis_type = (state.get("parsed_intent") or {}).get("analysis_type", "stock")

    market_snapshot = _slim_market_snapshot_for_summary(state.get("market_snapshot") or {})
    claims = state.get("claims", []) or []
    methodology_claims = _filter_methodology_only(claims)
    wiki_snippets = [
        s for s in (state.get("wiki_snippets", []) or [])
        if s.get("source", "").startswith("framework/") or "投资方法论" in s.get("source", "")
    ]
    framework_context = _load_framework_files(analysis_type)
    reasoning_patterns = _load_reasoning_patterns(state)
    esb = state.get("external_sector_boards", {})

    # 实时数据可用性守卫：market/portfolio 分析缺失实时数据时注入降级说明
    has_realtime_data = bool(
        esb.get("available") or market_snapshot.get("quotes")
    )
    _data_missing_note = ""
    if analysis_type in ("market", "portfolio") and not has_realtime_data:
        _data_missing_note = (
            "【注意】实时行情数据暂时无法获取（数据源限流或网络问题）。"
            "本次分析将基于 UP 历史观点（claims）和策略框架进行，"
            "缺少实时价格验证，分析结论的时效性可能受限。"
        )

    logger.info(
        "market_summary_input: quotes=%d claims=%d wiki=%d framework=%d patterns=%d esb_available=%s",
        len(market_snapshot.get("quotes", [])),
        len(methodology_claims),
        len(wiki_snippets),
        len(framework_context),
        len(reasoning_patterns),
        esb.get("available"),
    )

    analysis_framework = _load_analysis_framework()
    prompt_template_filled = prompt_template.replace("{analysis_framework}", analysis_framework)

    # Phase 1: 收盘复盘节点加载当天 daily_state 摘要，注入到检索知识中
    daily_state_summary = ""
    if is_closing_review:
        try:
            ds = load_daily_state()
            daily_state_summary = _build_daily_state_summary_for_closing(ds)
            logger.info(
                "market_summary closing_review: loaded daily_state summary with %d history entries, %d narrative entries",
                len(ds.get("history", [])), len(ds.get("intraday_narrative", []))
            )
        except Exception as e:
            logger.warning("market_summary closing_review: failed to load daily_state summary: %s", e)

    # Phase 4/5: 早盘节点注入前置信息占位符
    pre_market_brief = ""
    core_assumption_0926 = ""
    if trigger_id == "pre_market":
        try:
            pmb = asyncio.run(fetch_pre_market_brief())
            pre_market_brief = json.dumps(pmb, ensure_ascii=False, indent=2, default=str)
        except Exception as e:
            logger.warning("market_summary pre_market: failed to fetch pre_market_brief: %s", e)
            pre_market_brief = "外部数据不可用"
    elif trigger_id == "open_auction":
        try:
            ds = load_daily_state()
            pmb = ds.get("pre_market_brief")
            if isinstance(pmb, dict) and pmb.get("available") is not False and pmb:
                pre_market_brief = json.dumps(pmb, ensure_ascii=False, indent=2, default=str)
            else:
                pre_market_brief = "外部数据不可用，仅基于知识库分析"
        except Exception as e:
            logger.warning("market_summary open_auction: failed to load pre_market_brief: %s", e)
            pre_market_brief = "外部数据不可用"
    elif trigger_id == "morning_confirm":
        try:
            ds = load_daily_state()
            core_assumption_0926 = ds.get("market_stage", {}).get("detail", "")
            if not core_assumption_0926:
                for n in reversed(ds.get("intraday_narrative", [])):
                    if "09:26" in n.get("time", ""):
                        core_assumption_0926 = n.get("summary", "")
                        break
        except Exception as e:
            logger.warning("market_summary morning_confirm: failed to load 09:26 assumption: %s", e)

    prompt_template_filled = prompt_template_filled.replace("{pre_market_brief}", pre_market_brief)
    prompt_template_filled = prompt_template_filled.replace("{core_assumption_0926}", core_assumption_0926)

    # Phase 6: 收盘复盘前自动刷新机会状态
    refreshed_opportunities: list[dict] = []
    if is_closing_review:
        try:
            ds = load_daily_state()
            _refresh_active_opportunity_statuses(
                ds,
                state.get("positions", []),
                market_snapshot.get("quotes", []),
            )
            refreshed_opportunities = ds.get("active_opportunities", [])
            logger.info(
                "market_summary closing_review: refreshed %d opportunities",
                len(refreshed_opportunities),
            )
        except Exception as e:
            logger.warning("market_summary closing_review: failed to refresh opportunities: %s", e)

    context = {
        "today": _now_cn_str("%Y-%m-%d") + " 周" + "一二三四五六日"[datetime.now(_CN_TZ).weekday()],
        "market_snapshot": market_snapshot,
        "macd_multi_tf_report": market_snapshot.get("macd_multi_tf_report", ""),
        "td_sequential_report": market_snapshot.get("td_sequential_report", ""),
        "fibonacci_time_report": market_snapshot.get("fibonacci_time_report", ""),
        "sector_strengths": state.get("sector_strengths", []),
        "external_sector_boards": esb,
        "sector_context": state.get("sector_context", []),
        "claims": methodology_claims,
        "wiki_snippets": wiki_snippets,
        "framework_rules": framework_context,
        "reasoning_patterns": reasoning_patterns,
        "direction_signals": state.get("direction_signals", {}),
        "memories": state.get("memories", []),
        "daily_state_summary": daily_state_summary,
        "pre_market_brief": pre_market_brief if trigger_id == "pre_market" else "",
        "active_opportunities": refreshed_opportunities,
    }

    fallback = {
        "market_summary": "",
        "market_phase": "未配置",
        "phase_reasoning": "LLM未返回结果或API未配置",
        "main_themes": [],
        "sector_map": {},
        "themes_in_focus": [],
        "index_discipline": {},
        "volume_note": "",
        "emotion_signals": {},
        "risk_notes": "",
        "citations": [],
    }

    context_json = json.dumps(context, ensure_ascii=False, indent=2, default=str)
    prompt = f"""{prompt_template_filled}

{_data_missing_note}

检索到的知识：
{context_json}

请输出JSON：
"""
    prompt_bytes = len(prompt.encode("utf-8"))
    was_truncated = False
    if prompt_bytes > _MAX_MARKET_SUMMARY_PROMPT_BYTES:
        logger.warning(
            "market_summary prompt exceeds %d bytes (%d bytes), truncating context fields",
            _MAX_MARKET_SUMMARY_PROMPT_BYTES, prompt_bytes,
        )
        non_context_bytes = prompt_bytes - len(context_json.encode("utf-8"))
        context, was_truncated = _truncate_context_for_prompt(
            context, non_context_bytes, _MAX_MARKET_SUMMARY_PROMPT_BYTES
        )
        context["_truncated"] = True
        context_json = json.dumps(context, ensure_ascii=False, indent=2, default=str)
        prompt = f"""{prompt_template_filled}

{_data_missing_note}

检索到的知识：
{context_json}

请输出JSON：
"""
        prompt_bytes = len(prompt.encode("utf-8"))
        logger.warning(
            "market_summary prompt after truncation: %d bytes (truncated=%s)",
            prompt_bytes, was_truncated,
        )

    # Hard ceiling: never send an oversized prompt to the LLM.
    if prompt_bytes > _MAX_MARKET_SUMMARY_PROMPT_BYTES:
        logger.error(
            "market_summary prompt still exceeds %d bytes (%d bytes) after truncation; returning fallback without LLM call",
            _MAX_MARKET_SUMMARY_PROMPT_BYTES, prompt_bytes,
        )
        result = dict(fallback)
        result["_truncated"] = True
        result["_fallback_reason"] = "prompt_too_large"
        degraded = _build_degraded_digest(market_snapshot, esb)
        result["market_summary"] = degraded["summary_text"]
        result["emotion_signals"] = degraded["emotion_signals"]
        _fallback_ct = CostTracker()
        return {
            "market_summary_context": result,
            "reasoning_steps": [f"市场总结: {result.get('market_phase', 'N/A')} (fallback: prompt_too_large)"],
            "cost_tracking": [_fallback_ct.snapshot()],
            **({"_data_missing_note": _data_missing_note} if _data_missing_note else {}),
        }

    content = _safe_llm_invoke(prompt)
    if not content:
        # 空返回（超时/限流等瞬时失败）重试一次
        logger.warning("market_summary_llm: empty content, retrying once")
        content = _safe_llm_invoke(prompt)
    _t1 = time.time()
    logger.info(
        "market_summary_llm: duration=%.1fs prompt_len=%d content_len=%d",
        _t1 - _t0, len(prompt), len(content) if content else 0
    )

    cleaned_content = re.sub(r"```daily_state\s*[\s\S]*?```", "", content or "").strip() if content else ""
    _json_parse_failed = False
    try:
        result = json.loads(cleaned_content) if cleaned_content else {}
    except json.JSONDecodeError:
        result = {}
        _json_parse_failed = True

    if not result or not isinstance(result, dict):
        # fallback：区分真实失败原因 + 规则拼装原始数据降级摘要（不编造判断）
        _fb_reason = "json_parse_error" if (content and _json_parse_failed) else "llm_empty"
        result = dict(fallback)
        result["_fallback_reason"] = _fb_reason
        degraded = _build_degraded_digest(market_snapshot, esb)
        result["market_summary"] = degraded["summary_text"]
        result["emotion_signals"] = degraded["emotion_signals"]
        result["phase_reasoning"] = (
            f"market_summary LLM 子节点失败（{_fb_reason}）；"
            "盘面概述为系统按规则拼装的原始数据，未经 LLM 加工"
        )
    else:
        for key, value in fallback.items():
            if key not in result:
                result[key] = value

    if was_truncated:
        result["_truncated"] = True

    # 保持旧版 market_analyst 的 sector_strength 键向后兼容
    if "sector_map" in result and "sector_strength" not in result:
        result["sector_strength"] = result["sector_map"]
    elif "sector_strength" in result and "sector_map" not in result:
        result["sector_map"] = result["sector_strength"]

    # 成本追踪
    _ms_ct = CostTracker()
    _ms_ct.record_call(provider=(settings.llm_provider or "deepseek"))
    _ms_cost = _ms_ct.snapshot()

    # 提取并持久化 daily_state；同时把 override 传给下游 stock_scanner 用于合并
    daily_state_override = _extract_daily_state_block(content)
    source_tag = f"market_summary:{analysis_type}"

    # Phase 2: 分片请求时，只让 priority shard 持久化市场阶段/历史，避免 theme shard 重复写入 daily_state
    shard = state.get("watchlist_shard")
    should_persist_market_stage = not shard or bool(shard.get("is_priority"))
    if should_persist_market_stage:
        _persist_daily_state_from_market_context(result, daily_state_override, source_tag, trigger_id)
    else:
        logger.info("market_summary skipped daily_state persistence for non-priority shard %s", shard.get("name") if isinstance(shard, dict) else "unknown")
    if daily_state_override:
        result["_daily_state_override"] = daily_state_override

    # Phase 1: 收盘复盘节点执行后归档当日 daily_state
    if trigger_id == "closing_review":
        try:
            archive_path = archive_daily_state()
            if archive_path:
                logger.info("market_summary closing_review: archived daily_state to %s", archive_path)
            else:
                logger.info("market_summary closing_review: no daily_state file to archive")
        except Exception as e:
            logger.warning("market_summary closing_review: failed to archive daily_state: %s", e)

    reasoning = f"市场总结: {result.get('market_phase', 'N/A')}"
    if result.get("_fallback_reason"):
        reasoning += f" (fallback: {result['_fallback_reason']})"
    elif was_truncated:
        reasoning += " (prompt truncated)"
    return {
        "market_summary_context": result,
        "reasoning_steps": [reasoning],
        "cost_tracking": [_ms_cost],
        **({"_data_missing_note": _data_missing_note} if _data_missing_note else {}),
    }


def _pure_stock_code(code: str | None) -> str:
    """Normalize a stock identifier to a pure numeric code.

    Handles ``000001.SH`` / ``sh600000`` / ``SZ000001`` and East Money ``secid``
    like ``0.002594`` / ``1.600000``. Returns an empty string if the input is
    not parseable as a numeric code.
    """
    if not code:
        return ""
    s = str(code).strip()
    # Strip exchange suffixes (case-insensitive).
    for marker in (".SH", ".SZ", ".BJ"):
        s = s.replace(marker, "").replace(marker.lower(), "")
    # Strip exchange prefixes (case-insensitive).
    s = s.lower()
    for prefix in ("sh", "sz", "bj"):
        s = s.replace(prefix, "")
    # East Money secid: ``market.code`` -> keep the numeric code part.
    if "." in s:
        s = s.split(".")[-1]
    s = s.strip()
    return s if s.isdigit() else ""


def _build_watchlist_summary(
    watchlist_raw: list[dict],
    positions: list[dict],
    market_snapshot: dict,
) -> tuple[list[dict], list[dict]]:
    """构建观察池摘要，区分可交易主板标的与仅作参考的非主板标的。

    positions 和 market_snapshot 为保留参数，用于未来扩展（例如将持仓与观察池交叉校验），
    当前仅保留以匹配调用签名。

    返回 (watchlist_summary, reference_stocks)。
    """
    watchlist_summary: list[dict] = []
    reference_stocks: list[dict] = []
    _PRIORITY_SORT = {"P1": 0, "P1-核心": 0, "P2": 1, "P2-重点": 1, "P3": 2, "P3-观察": 2}

    def _is_mainboard(code: str) -> bool:
        """判断是否为可交易标的（仅排除仅作参考的 300 创业板与 688 科创板）。

        实现上不过度限制交易所前缀，因此北京所（8xx/4xx）、可转债代码等也会被保留；
        这些非主板标的后续会在投资组合层面由交易规则过滤，此处只负责把 300/688
        标为 reference_stocks。
        """
        pure = _pure_stock_code(code)
        if not pure:
            return False
        if pure.startswith("688"):
            return False
        if pure.startswith("300"):
            return False
        return True

    for w_item in watchlist_raw or []:
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
            item["priority"] = "P4-锚点"
            item["sort_key"] = 3
            reference_stocks.append(item)

    watchlist_summary.sort(key=lambda x: x["sort_key"])
    reference_stocks.sort(key=lambda x: x["sort_key"])
    return watchlist_summary, reference_stocks


def _normalize_positions(positions):
    """兼容 positions 为 {accounts: [...]} 或列表两种形态。"""
    if isinstance(positions, dict):
        flat: list[dict] = []
        for acc in positions.get("accounts", []) or []:
            flat.extend(acc.get("positions", []) or [])
        return flat
    if isinstance(positions, list):
        return positions
    return []


def _normalize_watchlist(watchlist):
    """Normalize watchlist from multiple shapes into a flat list of stock dicts.

    Supported shapes:
    - list of stock dicts (each has ``code``): returned as-is.
    - dict with ``"themes"``: flatten ``theme["stocks"]`` and inherit ``theme`` name.
    - dict with ``"stocks"``: return that list directly.
    - list of themes or mixed themes/stocks: flatten theme stocks and keep standalone stocks.
    - empty/unsupported inputs: return ``[]``.
    """
    if not watchlist:
        return []

    if isinstance(watchlist, dict):
        if "themes" in watchlist:
            stocks: list[dict] = []
            for theme in watchlist.get("themes") or []:
                if not isinstance(theme, dict):
                    continue
                theme_name = theme.get("name", "")
                for s in theme.get("stocks") or []:
                    if not isinstance(s, dict):
                        continue
                    item = dict(s)
                    if not item.get("theme"):
                        item["theme"] = theme_name
                    stocks.append(item)
            return stocks
        if "stocks" in watchlist:
            return list(watchlist.get("stocks") or [])
        return []

    if isinstance(watchlist, list):
        # If every element already looks like a stock, keep the list unchanged.
        if all(isinstance(w, dict) and "code" in w for w in watchlist):
            return watchlist
        # Otherwise treat it as a list of themes, a mixed list, or a malformed list.
        stocks: list[dict] = []
        for item in watchlist:
            if not isinstance(item, dict):
                continue
            if "stocks" in item:
                theme_name = item.get("name", "")
                for s in item.get("stocks") or []:
                    if not isinstance(s, dict):
                        continue
                    stock_item = dict(s)
                    if not stock_item.get("theme"):
                        stock_item["theme"] = theme_name
                    stocks.append(stock_item)
            elif "code" in item:
                stocks.append(dict(item))
        return stocks

    return []


def _render_market_summary_text(ctx: dict) -> str:
    """把 market_summary_context 渲染为一段简短的市场背景文字。"""
    phase = ctx.get("market_phase") or "未配置"
    reasoning = ctx.get("phase_reasoning") or ""
    summary = ctx.get("market_summary") or ""
    themes = ctx.get("main_themes") or []
    focus = ctx.get("themes_in_focus") or []
    risks = ctx.get("risk_notes") or ""
    parts = [f"市场阶段：{phase}"]
    if reasoning:
        parts.append(f"阶段判断依据：{reasoning[:120]}")
    if summary:
        parts.append(f"盘面概述：{summary[:500]}")
    if themes:
        parts.append(f"主线/主题：{', '.join(str(t) for t in themes[:5])}")
    if focus:
        parts.append(f"当前重点：{', '.join(str(t) for t in focus[:5])}")
    if risks:
        parts.append(f"关键风险：{risks[:120]}")
    return "；".join(parts)


def stock_scanner_shard(state: AgentState) -> AgentState:
    """个股扫描节点（分片版）：基于市场背景扫描单个 watchlist shard。"""
    logger = logging.getLogger(__name__)
    _t0 = time.time()
    prompt_template = _load_prompt("stock_scanner")
    analysis_type = (state.get("parsed_intent") or {}).get("analysis_type", "stock")
    trigger_id = (state.get("trigger") or {}).get("id")

    market_summary_ctx = state.get("market_summary_context") or {}
    market_snapshot = dict(state.get("market_snapshot") or {})
    positions = _normalize_positions(state.get("positions") or [])
    watchlist = _normalize_watchlist(state.get("watchlist") or [])

    # 精简行情快照：保留指数 + 持仓 + 高优先级 watchlist
    all_quotes = market_snapshot.get("quotes", []) or []
    codes_to_keep: set[str] = set()
    for p in positions:
        code = _pure_stock_code(p.get("code"))
        if code:
            codes_to_keep.add(code)
    for w in watchlist:
        code = _pure_stock_code(w.get("code"))
        if code:
            codes_to_keep.add(code)
    filtered = [
        q for q in all_quotes
        if (_pure_stock_code(q.get("code")) in codes_to_keep)
        or (_pure_stock_code(q.get("secid")) in codes_to_keep)
    ]
    market_snapshot["quotes"] = filtered
    market_snapshot["_filtered_from"] = len(all_quotes)

    watchlist_summary, reference_stocks = _build_watchlist_summary(
        watchlist, positions, market_snapshot
    )

    # ── Phase 2 新增：若存在 watchlist_shard，则只分析该分片内的标的 ──
    shard = state.get("watchlist_shard")
    shard_name = "全部标的"
    shard_items_text = "（未分片，分析全部持仓与观察池）"
    stock_contexts = state.get("stock_contexts", [])
    if shard:
        shard_items = shard.get("items", []) if isinstance(shard, dict) else []
        shard_codes = {
            _pure_stock_code(item.get("code", ""))
            for item in shard_items
            if _pure_stock_code(item.get("code", ""))
        }
        shard_name = shard.get("name", "未命名批次") if isinstance(shard, dict) else "未命名批次"
        shard_items_text = "\n".join(
            f"- {item.get('code', '')} {item.get('name', '')}"
            for item in shard_items
        ) or "（本批次无有效标的）"

        watchlist_summary = [
            w for w in watchlist_summary
            if _pure_stock_code(w.get("code", "")) in shard_codes
        ]
        reference_stocks = [
            r for r in reference_stocks
            if _pure_stock_code(r.get("code", "")) in shard_codes
        ]
        positions = [
            p for p in positions
            if _pure_stock_code(p.get("code", "")) in shard_codes
        ]
        stock_contexts = [
            s for s in stock_contexts
            if _pure_stock_code(s.get("stock_code", "")) in shard_codes
        ]

        all_quotes = market_snapshot.get("quotes", []) or []
        filtered_quotes = [
            q for q in all_quotes
            if _pure_stock_code(q.get("code")) in shard_codes
            or _pure_stock_code(q.get("secid")) in shard_codes
        ]
        market_snapshot["quotes"] = filtered_quotes
        market_snapshot["_filtered_from"] = len(all_quotes)

        logger.info(
            "stock_scanner_shard: name=%s codes=%s watchlist=%d reference=%d positions=%d contexts=%d",
            shard_name,
            sorted(shard_codes),
            len(watchlist_summary),
            len(reference_stocks),
            len(positions),
            len(stock_contexts),
        )

    logger.info(
        "stock_scanner_input: market_summary_len=%d stock_contexts=%d watchlist_summary=%d reference=%d positions=%d",
        len(json.dumps(market_summary_ctx, ensure_ascii=False, default=str)),
        len(stock_contexts),
        len(watchlist_summary),
        len(reference_stocks),
        len(positions),
    )

    context = {
        "market_summary_context": _render_market_summary_text(market_summary_ctx),
        "market_snapshot": market_snapshot,
        "positions": positions,
        "watchlist_summary": watchlist_summary,
        "reference_stocks": reference_stocks,
        "stock_contexts": stock_contexts,
        "direction_signals": state.get("direction_signals", {}),
    }

    prompt_template_filled = prompt_template.replace("{shard_name}", shard_name).replace(
        "{shard_items}", shard_items_text
    )

    context_json = json.dumps(context, ensure_ascii=False, indent=2, default=str)
    prompt = f"""{prompt_template_filled}

上下文：
{context_json}

请输出JSON：
"""
    prompt_bytes = len(prompt.encode("utf-8"))
    was_truncated = False
    if prompt_bytes > _MAX_STOCK_SCANNER_PROMPT_BYTES:
        logger.warning(
            "stock_scanner_shard prompt exceeds %d bytes (%d bytes), truncating context fields",
            _MAX_STOCK_SCANNER_PROMPT_BYTES, prompt_bytes,
        )
        non_context_bytes = prompt_bytes - len(context_json.encode("utf-8"))
        context, was_truncated = _truncate_context_for_prompt(
            context,
            non_context_bytes,
            _MAX_STOCK_SCANNER_PROMPT_BYTES,
            truncatable_fields=[
                "stock_contexts",
                "market_snapshot",
                "watchlist_summary",
                "reference_stocks",
                "positions",
                "direction_signals",
            ],
        )
        context["_truncated"] = True
        context_json = json.dumps(context, ensure_ascii=False, indent=2, default=str)
        prompt = f"""{prompt_template_filled}

上下文：
{context_json}

请输出JSON：
"""
        prompt_bytes = len(prompt.encode("utf-8"))
        logger.warning(
            "stock_scanner_shard prompt after truncation: %d bytes (truncated=%s)",
            prompt_bytes, was_truncated,
        )

    if prompt_bytes > _MAX_STOCK_SCANNER_PROMPT_BYTES:
        logger.error(
            "stock_scanner_shard prompt still exceeds %d bytes (%d bytes) after truncation; returning degraded context without LLM call",
            _MAX_STOCK_SCANNER_PROMPT_BYTES, prompt_bytes,
        )
        full_market_context = dict(market_summary_ctx)
        full_market_context.setdefault("opportunity_scan", [])
        full_market_context.setdefault("position_plans", [])
        full_market_context["_truncated"] = True
        full_market_context["_scan_failed"] = True
        full_market_context["_fallback_reason"] = "prompt_too_large"
        return {
            "stock_scanner_results": [
                {
                    "market_context": full_market_context,
                    "reasoning_steps": ["个股扫描: prompt过大，返回降级结果"],
                    "cost_tracking": [{"llm_calls": 0, "total_cost_usd": "0"}],
                    "daily_state_override": None,
                }
            ],
        }

    content = _safe_llm_invoke(prompt)
    _t1 = time.time()
    logger.info(
        "stock_scanner_shard_llm: duration=%.1fs prompt_len=%d content_len=%d",
        _t1 - _t0, len(prompt), len(content) if content else 0
    )

    cleaned_content = re.sub(r"```daily_state\s*[\s\S]*?```", "", content or "").strip() if content else ""
    scan_failed = False
    try:
        scan_result = json.loads(cleaned_content) if cleaned_content else {}
    except json.JSONDecodeError:
        logger.warning(
            "stock_scanner_shard failed to parse LLM output as JSON (content_len=%d): %s...",
            len(cleaned_content) if cleaned_content else 0,
            cleaned_content[:200] if cleaned_content else "",
        )
        scan_result = {}
        scan_failed = True

    if not scan_result:
        logger.warning(
            "stock_scanner_shard received empty scan_result; returning degraded market_context"
        )
        scan_failed = True

    # 合并 market_summary 的输出；保留全部 market_summary_context 键并补齐个股相关键
    full_market_context = dict(market_summary_ctx)
    full_market_context.setdefault("opportunity_scan", scan_result.get("opportunity_scan", []))
    full_market_context.setdefault("position_plans", scan_result.get("position_plans", []))

    if not scan_result:
        full_market_context["opportunity_scan"] = []
        full_market_context["position_plans"] = []

    if scan_failed:
        full_market_context["_scan_failed"] = True

    if was_truncated:
        full_market_context["_truncated"] = True

    # 保持 sector_map / sector_strength 向后兼容（alias）
    if "sector_map" in full_market_context and "sector_strength" not in full_market_context:
        full_market_context["sector_strength"] = full_market_context["sector_map"]
    elif "sector_strength" in full_market_context and "sector_map" not in full_market_context:
        full_market_context["sector_map"] = full_market_context["sector_strength"]

    # 成本追踪
    _ss_ct = CostTracker()
    _ss_ct.record_call(provider=(settings.llm_provider or "deepseek"))
    _ss_cost = _ss_ct.snapshot()

    # 提取 daily_state 代码块，留给 merge_scanner_results 统一持久化
    scanner_override = _extract_daily_state_block(content)
    # 注意：不要在分片节点单独持久化，避免多个并行节点写 daily_state 冲突
    # （market_stage 类字段以上游 market_summary 为准，机会类字段由 merge_scanner_results 合并）

    return {
        "stock_scanner_results": [
            {
                "market_context": full_market_context,
                "reasoning_steps": [
                    f"个股扫描({shard_name}): opportunities={len(full_market_context.get('opportunity_scan', []))} positions={len(full_market_context.get('position_plans', []))}"
                ],
                "cost_tracking": [_ss_cost],
                "daily_state_override": scanner_override,
            }
        ],
    }


def merge_scanner_results(state: AgentState) -> AgentState:
    """合并多个 stock_scanner_shard 的输出，统一生成 market_context 并持久化 daily_state。"""
    logger = logging.getLogger(__name__)
    results = state.get("stock_scanner_results", []) or []
    market_summary_ctx = state.get("market_summary_context") or {}
    trigger_id = (state.get("trigger") or {}).get("id")
    analysis_type = (state.get("parsed_intent") or {}).get("analysis_type", "stock")

    merged = dict(market_summary_ctx)
    merged.setdefault("opportunity_scan", [])
    merged.setdefault("position_plans", [])

    reasoning_steps: list[str] = []
    total_cost: list[dict] = []
    any_truncated = False
    any_failed = False

    daily_state_overrides: list[dict] = []

    for idx, r in enumerate(results):
        mc = r.get("market_context", {}) if isinstance(r, dict) else {}
        reasoning_steps.extend(r.get("reasoning_steps", []) if isinstance(r, dict) else [])
        total_cost.extend(r.get("cost_tracking", []) if isinstance(r, dict) else [])
        any_truncated = any_truncated or bool(mc.get("_truncated"))
        any_failed = any_failed or bool(mc.get("_scan_failed"))

        override = r.get("daily_state_override") if isinstance(r, dict) else None
        if override:
            daily_state_overrides.append(override)

        for opp in mc.get("opportunity_scan", []):
            merged["opportunity_scan"].append(opp)
        for plan in mc.get("position_plans", []):
            merged["position_plans"].append(plan)

    if any_truncated:
        merged["_truncated"] = True
    if any_failed:
        merged["_scan_failed"] = True

    # 透传降级原因（如 prompt 过大导致的 fallback）
    fallback_reasons = [
        mc.get("_fallback_reason")
        for r in results
        if isinstance(r, dict)
        for mc in [r.get("market_context", {})]
        if isinstance(mc, dict) and mc.get("_fallback_reason")
    ]
    if fallback_reasons:
        merged["_fallback_reason"] = fallback_reasons[0]

    # 合并各分片的 daily_state 覆盖块
    merged_override: dict | None = None
    if daily_state_overrides:
        merged_override = {}
        for override in daily_state_overrides:
            for key, value in override.items():
                if key == "active_opportunities" and isinstance(value, list):
                    merged_override.setdefault(key, []).extend(value)
                else:
                    merged_override[key] = value

    # 统一持久化 daily_state（一次触发只写一次）
    source_tag = f"stock_scanner:{analysis_type}"
    _persist_daily_state_from_market_context(merged, merged_override, source_tag, trigger_id)

    logger.info(
        "merge_scanner_results: shards=%d opportunities=%d position_plans=%d",
        len(results),
        len(merged.get("opportunity_scan", [])),
        len(merged.get("position_plans", [])),
    )

    return {
        "market_context": merged,
        "reasoning_steps": [
            f"个股扫描合并: {len(results)} 个分片, opportunities={len(merged.get('opportunity_scan', []))}, position_plans={len(merged.get('position_plans', []))}"
        ] + reasoning_steps,
        "cost_tracking": total_cost,
        # 分片结果已合并到 market_context，不再返回累加器；
        # 由于 state 使用 Annotated[list, operator.add]，返回 [] 即可让该字段保持为空。
        "stock_scanner_results": [],
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
    # 防御性处理：stock_code 可能为列表或空
    if isinstance(stock_code, list):
        stock_code = next((c for c in stock_code if c), "")
    if not stock_code or not isinstance(stock_code, str):
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

    # 兼容 LLM 把 stock_code 解析成列表的情况，取第一个有效元素
    if isinstance(stock_code, list):
        stock_code = next((c for c in stock_code if c), None)

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
{json.dumps(context, ensure_ascii=False, indent=2, default=str)}

请输出JSON：
"""
    content = _safe_llm_invoke(prompt)

    # 成本追踪
    _sa_ct = CostTracker()
    _sa_ct.record_call(provider=(settings.llm_provider or "deepseek"))
    _sa_cost = _sa_ct.snapshot()

    # 清洗可能的 ```daily_state 代码块，避免 JSON 解析失败
    import re as _re_sa
    cleaned_content = _re_sa.sub(r"```daily_state\s*[\s\S]*?```", "", content or "").strip() if content else ""
    try:
        result = json.loads(cleaned_content) if cleaned_content else {}
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

    插入在 stock_analyst / stock_scanner 之后、synthesize 之前。
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
        from qing_investment.agent.tools.llm_client import record_provider_usage

        # Devil's Advocate 内部已配置优先走 deepseek（与主分析不同模型家族），
        # 不注入固定 provider，让它使用自己的 fallback 链：deepseek → kimi-coding → zhipu。
        logger.info("[devils_advocate] 调用远端 deepseek")
        record_provider_usage("deepseek", "attempt", "devils_advocate fixed provider")
        agent = DevilsAdvocateAgent()

        import asyncio
        result = asyncio.run(agent.run(
            market_analysis=_market_ctx_summary(market_ctx),
            stock_analysis=_stock_analysis_summary(stock_analysis),
            claims_cited=claims_cited,
        ))
        actual_provider = agent.used_provider or "deepseek"
        record_provider_usage(actual_provider, "success", f"findings={len(result.findings)}")
        logger.info(
            f"devils_advocate: findings={len(result.findings)} "
            f"errors={len(result.errors)} cost={result.cost_usd} "
            f"provider={actual_provider}"
        )
        return {"devils_advocate_findings": result.findings}
    except Exception as e:
        record_provider_usage("deepseek", "failed", str(e)[:120])
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
        logger = logging.getLogger(__name__)
        logger.debug("[_format_devils_advocate_block] no findings, skipping")
        return ""
    logger = logging.getLogger(__name__)
    logger.info("[_format_devils_advocate_block] formatting %d findings for output", len(findings))

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
            if not items:
                continue
            sector_lines.append(f"{layer}：")
            for item in items:
                if isinstance(item, str):
                    sector_lines.append(f"  - {item}")
                    continue
                if not isinstance(item, dict):
                    continue
                stocks = "、".join(item.get("key_stocks", []))
                sector_lines.append(f"  - {item.get('name', '')}（{item.get('status', '')}）→ {item.get('logic', '')}；标的：{stocks}")

        themes = market.get("themes_in_focus", [])
        theme_lines = []
        for t in themes:
            if isinstance(t, str):
                theme_lines.append(f"【{t}】")
                continue
            if not isinstance(t, dict):
                continue
            theme_lines.append(f"【{t.get('theme', '')}】")
            theme_lines.append(f"催化：{t.get('catalyst', '')}")
            theme_lines.append(f"风险：{t.get('risk', '')}")
            theme_lines.append(f"相关：{'、'.join(t.get('key_stocks', []))}")

        idx = market.get("index_discipline", {})
        index_lines = []
        if isinstance(idx, dict) and idx:
            index_lines.append(f"支撑{idx.get('support', 'N/A')} / 压力{idx.get('resistance', 'N/A')}")
            index_lines.append(f"跌破→{idx.get('action_below', 'N/A')}；突破→{idx.get('action_above', 'N/A')}；中间→{idx.get('middle_zone', 'N/A')}")

        # Phase 1 新增：机会扫描展示
        opportunity_scan = market.get("opportunity_scan", [])
        opportunity_lines = []
        if opportunity_scan:
            opportunity_lines.append("【机会扫描】")
            for opp in opportunity_scan:
                if isinstance(opp, str):
                    opportunity_lines.append(f"  · {opp}")
                    continue
                if not isinstance(opp, dict):
                    continue
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
        today=_now_cn_str("%Y-%m-%d") + " 周" + "一二三四五六日"[datetime.now(_CN_TZ).weekday()],
    )

    # Log input summary before LLM call
    has_vague_terms = any(w in draft for w in ["等回踩", "等分歧", "逢低关注", "逢低布局"])
    logger.info(
        f"style_writer: draft_len={len(draft)} market_phase={market_phase} "
        f"has_vague_terms={has_vague_terms} review_round={len(review_notes)}"
    )

    # style_writer 会被 reviewer 多次调用，优先走远端 deepseek 以避免本地 ACP 拖慢整体耗时
    content = _safe_llm_invoke(prompt, min_length=150, use_acp_first=False)
    styled = content if content else f"[UP风格化] {draft}"

    logger.info(f"style_writer: output_len={len(styled)} generated={bool(content)} content_len={len(content) if content else 0}")

    # 成本追踪
    _sw_ct = CostTracker()
    _sw_ct.record_call(provider=(settings.llm_provider or "deepseek"))
    _sw_cost = _sw_ct.snapshot()
    logger.info("[style_writer] cost_tracking: calls=%s cost=%s", _sw_cost["llm_calls"], _sw_cost["total_cost_usd"])

    return {
        "styled_output": styled,
        "reasoning_steps": ["风格化生成完成"],
        "cost_tracking": [_sw_cost],
    }


def citation_validator(state: AgentState) -> AgentState:
    """引用校验节点 — 在 style_writer 输出后、reviewer 语义检查前执行纯规则校验.

    职责：
    1. 从 styled_output 中提取数字 claim（价格、百分比、成交量等）
    2. 检查每个 claim 是否有来源标注
    3. 输出校验报告（覆盖率、问题列表）
    4. 非阻断：即使校验不通过，也不阻止流程（reviewer 仍会执行语义检查）
    """
    logger = logging.getLogger(__name__)
    _t0 = time.time()
    output = state.get("styled_output", "")

    if not output:
        return {
            "citation_report": {
                "valid": True,
                "coverage": 1.0,
                "total_claims": 0,
                "cited_claims": 0,
                "issues": [],
                "summary": "无输出内容，跳过引用校验",
            },
            "reasoning_steps": ["引用校验: 跳过（无输出）"],
        }

    # 硬检验：输出过短通常意味着生成失败，直接标记为不通过
    _MIN_OUTPUT_LENGTH = 100
    if len(output) < _MIN_OUTPUT_LENGTH:
        logger.warning(
            "[citation_validator] output too short (%d chars < %d), forcing invalid",
            len(output), _MIN_OUTPUT_LENGTH,
        )
        _short_ct = CostTracker()
        _short_ct.record_call(provider="rules")
        return {
            "citation_report": {
                "valid": False,
                "coverage": 0.0,
                "total_claims": 0,
                "cited_claims": 0,
                "issues": [
                    {
                        "section": "全局",
                        "claim_text": output,
                        "issue_type": "output_too_short",
                        "suggestion": f"输出过短（{len(output)} 字符），疑似生成失败，请重新生成",
                    }
                ],
                "summary": f"输出过短（{len(output)} 字符），疑似生成失败",
            },
            "reasoning_steps": ["引用校验: 输出过短，生成失败"],
            "cost_tracking": [_short_ct.snapshot()],
        }

    from qing_investment.agent.validators.citation_validator import CitationValidator

    validator = CitationValidator()
    report = validator.validate(output)
    report_dict = {
        "valid": report.valid,
        "coverage": round(report.coverage, 3),
        "total_claims": report.total_claims,
        "cited_claims": report.cited_claims,
        "issues": [
            {"section": i.section, "claim_text": i.claim_text,
             "issue_type": i.issue_type, "suggestion": i.suggestion}
            for i in report.issues
        ],
        "summary": f"总数={report.total_claims}, 有引用={report.cited_claims}, "
                   f"覆盖率={report.coverage:.1%}, 状态={'通过' if report.valid else '⚠️ 低于阈值'}",
    }

    _t1 = time.time()
    logger.info(
        f"citation_validator: total={report.total_claims} cited={report.cited_claims} "
        f"coverage={report.coverage:.1%} valid={report.valid} duration={_t1-_t0:.1f}s"
    )
    if report.issues:
        logger.info(f"citation_issues ({len(report.issues)}): "
                     f"{' | '.join(f'[{i.issue_type}] {i.claim_text[:40]}' for i in report.issues[:3])}")

    # 成本追踪（规则校验，无 LLM 调用）
    _ct = CostTracker()
    _ct.record_call(provider="rules")  # 规则引擎，记为 0 成本
    _ct_cost = _ct.snapshot()

    return {
        "citation_report": report_dict,
        "reasoning_steps": [f"引用校验: {report_dict['summary']}"],
        "cost_tracking": [_ct_cost],
    }


def reviewer(state: AgentState) -> AgentState:
    logger = logging.getLogger(__name__)
    _t0 = time.time()
    prompt_template = _load_prompt("reviewer")
    output = state.get("styled_output", "")
    claims = state.get("claims", [])
    retry_count = state.get("_retry_count", 0)

    prompt = f"""{prompt_template}

今日日期：{_now_cn_str("%Y-%m-%d") + " 周" + "一二三四五六日"[datetime.now(_CN_TZ).weekday()]}

待审核输出：
{output}

检索到的 claims：
{json.dumps([c.get('id', 'N/A') for c in claims], ensure_ascii=False)}

请输出JSON：
"""
    # reviewer 每次 retry 都调 LLM，优先走远端 deepseek 以避免本地 ACP 拖慢整体耗时
    content = _safe_llm_invoke(prompt, use_acp_first=False)

    # 成本追踪
    _rv_ct = CostTracker()
    _rv_ct.record_call(provider=(settings.llm_provider or "deepseek"))
    _rv_cost = _rv_ct.snapshot()
    logger.info("[reviewer] cost_tracking: calls=%s cost=%s", _rv_cost["llm_calls"], _rv_cost["total_cost_usd"])

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
    # 输出过短通常意味着生成失败（如 Kimi Code CLI 清洗后只剩几个字符），直接打回
    if passed and len(output) < 100:
        passed = False
        review_notes.append(f"输出过短（{len(output)} 字符），疑似生成失败")
        logger.warning("[reviewer] output too short (%d chars), forcing fail", len(output))
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
        "_retry_count": retry_count + 1 if not passed else retry_count,
    }
