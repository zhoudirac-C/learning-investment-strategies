"""发现引擎纯逻辑（T17 触发过滤 / T18 发现 prompt / T19 提议去重）。

Prompt 按 docs/tasks/m0-chain-industry-tracking.md §3.3 的发现模式：
已有产业链清单作为 prompt 输入避免重复提议；4 条判断标准
（驱动因素 / 传导路径 / A股标的 / 不重复）；输出 {"proposals": [...]}（0..3 条）。

与任务书差异（见 docs/tasks/m0-chain-phase3-plan.md）：批量一次调用输出列表
（相关新闻聚类成一条提议）；阶段枚举对齐 schema.STAGE_LEVELS（任务书 §3.3
写的是旧版阶段名）。
"""
from __future__ import annotations

import json
import re

from investment_engine.industry_chain.schema import CONFIDENCE_LEVELS, STAGE_LEVELS

# 触发关键词（任务书 §3.3）：标题命中其一且不匹配已有链 → 发现候选
TRIGGER_KEYWORDS = ("涨价", "扩产", "缺货", "供需", "产业链", "深度", "专题")

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")  # 与 industry_chain.schema 同口径

_REQUIRED_FIELDS = ("chain_id", "name", "driver", "thesis")

_SYSTEM = (
    "你是产业链研究分析师，负责从每日新信息中发现【新的】产业链逻辑。"
    "只输出 JSON，不要输出任何其他内容。"
)

_USER_TMPL = """以下是今日的新信息，请判断是否存在"新的产业链逻辑"。

【已有产业链清单】（避免重复提议）：
{existing_chains}

【待确认提议清单】（已提议待人工确认，不要重复）：
{pending_proposals}

【新信息】（{n_items} 条）
{items_text}

判断标准（4 条全部满足才提议）：
1. 是否有一个清晰的"驱动因素"（涨价/技术升级/政策催化/供需缺口）？
2. 是否有一个可拆解的"传导路径"（上游→中游→下游）？
3. 是否有明确的"A股标的"可以承接这个逻辑？
4. 是否与已有产业链、待确认提议都不重复？

注意：
- 已有产业链的增量信息（如已有煤炭链时的"煤炭进口数据拆解"）不是新产业链。
- 单家公司事件（无产业链传导）不是新产业链逻辑。单家公司的财报点评/公告
  本身不构成产业链逻辑，除非文中给出产业链级证据（行业价格/产能/供需数据、
  上下游传导）。
- confidence=高 仅当 ≥2 条独立来源同向；单一来源最高给 中。
- 宁可不提议，不要重复或硬凑。每日 0-2 条提议是正常水平。

如果满足，输出新产业链提议（最多 3 条）：
{{
  "proposals": [
    {{
      "chain_id": "简短英文ID（小写字母/数字/连字符）",
      "name": "产业链名称",
      "driver": "驱动因素（≤50字）",
      "thesis": "产业逻辑（≤100字）",
      "chain": {{
        "upstream": {{"materials": [...], "key_nodes": [...], "stocks": [...]}},
        "midstream": {{"materials": [...], "key_nodes": [...], "stocks": [...]}},
        "downstream": {{"materials": [...], "key_nodes": [...], "stocks": [...]}}
      }},
      "current_stage": "阶段0-观察/阶段1-启动期/阶段2-加速期/阶段3-分歧期/阶段4-见顶期",
      "timing": "当前建议（做哪个环节/观察/回避）",
      "confidence": "高/中/低",
      "source": "信息来源（研报标题/公告）",
      "source_info_ids": ["支撑该提议的信息 info_id"]
    }}
  ]
}}

如果没有满足条件的新产业链逻辑，输出 {{"proposals": []}}。
"""


def is_discovery_candidate(item: dict) -> bool:
    """标题命中触发关键词即为候选（是否已有链的增量信息由匹配层排除）。

    板块异动（source=sector）直接候选——它本身就是"涨幅>3%"的筛选结果，
    标题不含关键词也不影响（任务书 §3.3：板块涨幅>3% 且无产业链归属）。
    """
    if item.get("source") == "sector":
        return True
    title = item.get("title") or ""
    return any(kw in title for kw in TRIGGER_KEYWORDS)


def _fmt_chain_line(chain: dict) -> str:
    driver = str(chain.get("driver") or "").strip()
    suffix = f"：{driver}" if driver else ""
    return f"- {chain.get('chain_id')} | {chain.get('name')}{suffix}"


def build_discovery_messages(chains: list[dict], pending: list[dict],
                             items: list[dict], *,
                             max_items: int = 40) -> list[dict]:
    from investment_engine.chain_tracker.analysis import format_items

    user = _USER_TMPL.format(
        existing_chains="\n".join(_fmt_chain_line(c) for c in chains) or "（无）",
        pending_proposals="\n".join(_fmt_chain_line(p) for p in pending) or "（无）",
        n_items=len(items),
        items_text=format_items(items, max_items),
    )
    return [{"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user}]


def _normalize_proposal(p: dict) -> dict | None:
    """字段校验 + 枚举归一；不合格返回 None（丢弃该条，不阻断其他提议）。"""
    for field in _REQUIRED_FIELDS:
        if not isinstance(p.get(field), str) or not p[field].strip():
            return None
    if not _SLUG_RE.match(p["chain_id"]):
        return None
    out = dict(p)
    if out.get("current_stage") not in STAGE_LEVELS:
        out["current_stage"] = "阶段0-观察"
    if out.get("confidence") not in CONFIDENCE_LEVELS:
        out["confidence"] = "中"
    # 来源分层：momentum=资金异动驱动（引擎 B），report=研报驱动（引擎 A）；
    # 事后按层统计命中率。非法值回落 report。
    if out.get("source_type") not in ("report", "momentum"):
        out["source_type"] = "report"
    if not isinstance(out.get("chain"), dict):
        out["chain"] = {}
    ids = out.get("source_info_ids")
    out["source_info_ids"] = ([str(i) for i in ids if i]
                              if isinstance(ids, list) else [])
    return out


def parse_discovery(raw: str) -> list[dict]:
    """解析 LLM 输出；fence 容忍；接受 {"proposals": [...]} / 裸列表 / 单个对象。"""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"输出非 JSON: {raw[:80]!r}") from e

    if isinstance(data, dict):
        if "proposals" in data:
            proposals = data["proposals"]
        elif "chain_id" in data:  # 单个提议对象兜底
            proposals = [data]
        else:
            proposals = []
    elif isinstance(data, list):
        proposals = data
    else:
        raise ValueError(f"输出非 JSON object/list: {raw[:80]!r}")
    if isinstance(proposals, dict):
        proposals = [proposals]
    if not isinstance(proposals, list):
        raise ValueError(f"proposals 字段非列表: {raw[:80]!r}")

    out = []
    for p in proposals:
        if not isinstance(p, dict):
            continue
        normalized = _normalize_proposal(p)
        if normalized is not None:
            out.append(normalized)
    return out


def filter_duplicate_proposals(
    proposals: list[dict], chains: list[dict], pending: list[dict],
) -> tuple[list[dict], list[dict]]:
    """后置去重：chain_id/name 撞已有链、撞 pending、批内重复 → 跳过。"""
    existing_ids = {c.get("chain_id") for c in chains}
    existing_names = {c.get("name") for c in chains}
    pending_ids = {p.get("chain_id") for p in pending}
    pending_names = {p.get("name") for p in pending}

    kept: list[dict] = []
    skipped: list[dict] = []
    seen_ids: set[str] = set()
    for p in proposals:
        cid, name = p.get("chain_id"), p.get("name")
        if (cid in existing_ids or cid in pending_ids or cid in seen_ids
                or name in existing_names or name in pending_names):
            skipped.append(p)
            continue
        seen_ids.add(cid)
        kept.append(p)
    return kept, skipped


# ---------- 引擎 B：异动驱动拆链（设计文档 §4.4） ----------

_MOMENTUM_SYSTEM = (
    "你是产业链拆解分析师。输入是一个已被资金行为确认的题材异动，"
    "你的任务是拆解它的产业链图谱，为后续补涨环节挖掘提供地图。"
    "只输出 JSON，不要输出任何其他内容。"
)

_MOMENTUM_USER_TMPL = """【题材异动卡】（资金行为已确认，无需再判断是否值得关注）：
题材：{theme} | 涨停 {zt_count} 家（首板 {first_board_count}）| 最高 {max_lbc} 板
封单资金合计 {seal_fund_text} | 最早首封 {earliest_seal} | 连续上榜 {streak_days} 天
板块涨幅 {sector_pct_text} | 触发：{trigger_text} | 领涨：{leaders_text}

【板块内涨停个股明细】（标的优先从这里选，这些是资金认的票）：
{stocks_text}

【当日相关信息】（研报/公告，作为拆链素材而非触发依据）：
{related_text}

【已有产业链清单】（避免重复提议）：
{existing_chains}

【待确认提议清单】（已提议待人工确认，不要重复）：
{pending_proposals}

规则层阶段初判：{stage}（由涨停/连板/炸板数据得出，直接采用，不要修改）。

任务：判断该题材是否有可拆解的产业链传导路径（上游→中游→下游）。
- 纯情绪题材（次新股/壳资源/无产业逻辑的情绪炒作）或无法拆解传导路径的，
  输出空列表。
- 有产业链逻辑则输出 1 条提议；chain 的 upstream/midstream/downstream 各段
  除 materials/key_nodes/stocks 外，加 "benefit_level": "核心/间接/联动"
  （核心=直接受益业绩弹性最大，间接=供需传导受益，联动=仅情绪带动）。
- stocks 优先从涨停明细中选取；单一来源 confidence 最高给 中。

输出格式（0 或 1 条）：
{{
  "proposals": [
    {{
      "chain_id": "简短英文ID（小写字母/数字/连字符）",
      "name": "产业链名称",
      "driver": "驱动因素（≤50字）",
      "thesis": "产业逻辑（≤100字）",
      "chain": {{
        "upstream": {{"materials": [...], "key_nodes": [...], "stocks": [...], "benefit_level": "..."}},
        "midstream": {{"materials": [...], "key_nodes": [...], "stocks": [...], "benefit_level": "..."}},
        "downstream": {{"materials": [...], "key_nodes": [...], "stocks": [...], "benefit_level": "..."}}
      }},
      "current_stage": "{stage}",
      "timing": "当前建议（做哪个环节/观察/回避）",
      "confidence": "高/中/低",
      "source": "资金异动（{theme}）+ 素材来源",
      "source_info_ids": []
    }}
  ]
}}
"""


def _fmt_yi(v: float | int | None) -> str:
    try:
        return f"{float(v) / 1e8:.1f}亿"
    except (TypeError, ValueError):
        return "-"


def build_momentum_messages(card: dict, chains: list[dict], pending: list[dict],
                            related_items: list[dict], *,
                            stage: str) -> list[dict]:
    """异动拆链 prompt：题材热度卡 + 涨停明细 + 相关素材 + 已有链/pending。

    card 来自 momentum.aggregate_theme_cards + trigger_themes（含 trigger_reasons）；
    stage 来自 momentum.judge_stage（规则初判，prompt 中锁定不让 LLM 改）。
    """
    stocks_text = "\n".join(
        f"- {s.get('name')}（{s.get('code')}）：{s.get('lbc')}板，"
        f"封单{_fmt_yi(s.get('fund'))}，首封{s.get('fbt') or '-'}"
        for s in card.get("stocks") or []) or "（无）"
    related_text = "\n".join(
        f"- [{i.get('info_id')}] {i.get('title')}" for i in related_items) or "（无）"
    sector_pct = card.get("sector_pct")
    user = _MOMENTUM_USER_TMPL.format(
        theme=card.get("theme"),
        zt_count=card.get("zt_count"),
        first_board_count=card.get("first_board_count"),
        max_lbc=card.get("max_lbc"),
        seal_fund_text=_fmt_yi(card.get("seal_fund")),
        earliest_seal=card.get("earliest_seal") or "-",
        streak_days=card.get("streak_days"),
        sector_pct_text=(f"{sector_pct:+.1f}%" if sector_pct is not None else "-"),
        trigger_text="/".join(card.get("trigger_reasons") or []),
        leaders_text="、".join(card.get("leaders") or []) or "-",
        stocks_text=stocks_text,
        related_text=related_text,
        existing_chains="\n".join(_fmt_chain_line(c) for c in chains) or "（无）",
        pending_proposals="\n".join(_fmt_chain_line(p) for p in pending) or "（无）",
        stage=stage,
    )
    return [{"role": "system", "content": _MOMENTUM_SYSTEM},
            {"role": "user", "content": user}]


def build_pending_index(pending: list[dict]) -> dict[str, dict]:
    """待确认提议 → 匹配信号（复用 matching.extract_chain_signals）。

    提议里的 stocks/key_nodes 多为名称字符串（LLM 不保证给代码），
    统一转成 chain.yaml 形状后走同一套关键词提取。
    """
    from investment_engine.chain_tracker.matching import extract_chain_signals

    index: dict[str, dict] = {}
    for p in pending:
        if not p.get("chain_id"):
            continue
        chain_spec = p.get("chain") if isinstance(p.get("chain"), dict) else {}
        mappings: list[dict] = []
        metrics: list[dict] = []
        segments: list[dict] = []
        for key in ("upstream", "midstream", "downstream"):
            seg = chain_spec.get(key) or {}
            if not isinstance(seg, dict):
                continue
            segments.append({"materials": seg.get("materials") or []})
            for s in seg.get("stocks") or []:
                if isinstance(s, dict):
                    mappings.append({"code": s.get("code"), "name": s.get("name")})
                elif s:
                    mappings.append({"name": str(s)})
            for kn in seg.get("key_nodes") or []:
                if isinstance(kn, dict):
                    if kn.get("node"):
                        metrics.append({"metric": str(kn["node"])})
                elif kn:
                    metrics.append({"metric": str(kn)})
        pseudo = {"chain_id": p.get("chain_id"), "name": p.get("name"),
                  "driver": p.get("driver"), "mappings": mappings,
                  "tracking_metrics": metrics, "segments": segments}
        index[str(p["chain_id"])] = extract_chain_signals(pseudo)
    return index
