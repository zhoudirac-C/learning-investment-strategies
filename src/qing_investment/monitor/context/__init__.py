"""Qing-Agent 监控引擎 — 上下文构建层 (Phase 2)

解决核心痛点：watchlist 超40只 + 全字段注入导致 LLM 超时。

设计原则:
    1. Token 预算管理：每只标的最多 N 个 token，总预算封顶
    2. 智能筛选：只保留"值得分析"的标的进入 LLM prompt
    3. 分层输出：主板可交易 / 非主板锚点 / 高优先级优先
    4. 向后兼容：现有 context_builder.py 的接口不变

架构:
    ┌─────────────────────────────────────────┐
    │         TokenBudgetManager              │
    │  ┌─────────────┐  ┌─────────────────┐ │
    │  │  TokenCounter│  │  StockPrioritizer│ │
    │  │  (预算计算)  │  │  (标的排序筛选)  │ │
    │  └─────────────┘  └─────────────────┘ │
    │              ↓                          │
    │  ┌─────────────────────────────────────┐ │
    │  │      ContextAssembler             │ │
    │  │  (组装最终注入 LLM 的上下文)       │ │
    │  └─────────────────────────────────────┘ │
    └─────────────────────────────────────────┘

使用:
    from qing_investment.monitor.context import TokenBudgetManager
    
    manager = TokenBudgetManager(max_tokens=8000, max_stocks=15)
    context = manager.build_context(
        watchlist=watchlist_data,
        positions=positions_data,
        entry_points=entry_points_data,
        quote_snapshot=quote_data,
    )
    # context 注入 LLM prompt
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────
# 数据提取工具函数
# ──────────────────────────────────────────

def position_rows(config: Any) -> list[dict]:
    """提取持仓行。"""
    rows: list[dict] = []
    for account in config.positions.get("accounts", []) or []:
        account_name = account.get("name", "")
        for position in account.get("positions", []) or []:
            row = dict(position)
            row["account"] = account_name
            rows.append(row)
    return rows


def watchlist_stock_rows(config: Any) -> list[dict]:
    """提取观察列表行。"""
    rows: list[dict] = []
    for theme in config.watchlist.get("themes", []) or []:
        theme_id = theme.get("id", "")
        theme_name = theme.get("name", "")
        for stock in theme.get("stocks", []) or []:
            row = dict(stock)
            row["theme_id"] = theme_id
            row["theme_name"] = theme_name
            rows.append(row)
    return rows


def sector_group_rows(config: Any) -> list[dict]:
    """提取板块组成员行。"""
    rows: list[dict] = []
    for group in config.strategy_pack.get("sector_groups", []) or []:
        group_id = group.get("id", "")
        group_name = group.get("name", "")
        style = group.get("style", "")
        for member in group.get("members", []) or []:
            row = dict(member)
            row["group_id"] = group_id
            row["group_name"] = group_name
            row["style"] = style
            rows.append(row)
    return rows


def _string_items(value: object) -> list[str]:
    """将值转换为字符串列表。"""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    return [str(value)]


def format_watchlist_condition_line(row: dict) -> str:
    """格式化观察列表条件行。"""
    parts: list[str] = []
    confirm_with = _string_items(row.get("confirm_with"))
    if confirm_with:
        parts.append(f"确认锚：{'、'.join(confirm_with)}")

    field_labels = [
        ("buy_setup", "买入观察"),
        ("invalidation_setup", "买点失效"),
        ("sell_setup", "持仓卖出/做T"),
    ]
    for field, label in field_labels:
        items = _string_items(row.get(field))
        if items:
            parts.append(f"{label}：{'；'.join(items)}")
    return " | ".join(parts)


def unique_stock_count(rows: list[dict]) -> int:
    """统计唯一股票数量。"""
    return len({row.get("code") for row in rows if row.get("code")})


# ──────────────────────────────────────────
# 新增：价格区间解析工具函数
# ──────────────────────────────────────────

import re


def parse_price_zone(value: object) -> tuple[float, float] | None:
    """解析价格区间。"""
    if value is None:
        return None
    if isinstance(value, int | float):
        price = float(value)
        return (price, price)

    text = str(value).strip()
    if not text:
        return None
    normalized = (
        text.replace("至", "-")
        .replace("到", "-")
        .replace("~", "-")
        .replace("—", "-")
        .replace("–", "-")
    )
    numbers = [float(match) for match in re.findall(r"\d+(?:\.\d+)?", normalized)]
    if not numbers:
        return None
    if len(numbers) == 1:
        return (numbers[0], numbers[0])
    low, high = sorted(numbers[:2])
    return (low, high)


def _to_float(value: object) -> float | None:
    """转换为浮点数。"""
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    text = str(value).strip()
    if not text or text in {"-", "--"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _pure_stock_code(code: object) -> str:
    """从 '600519.SH' 提取 '600519'。"""
    text = str(code or "").strip().upper()
    match = re.fullmatch(r"(\d{6})(?:\.(?:SH|SZ))?", text)
    return match.group(1) if match else text


def _quotes_by_code(quote_snapshot: dict) -> dict[str, dict]:
    """将 quote_snapshot 按股票代码索引。"""
    quotes: dict[str, dict] = {}
    for quote in quote_snapshot.get("quotes", []) or []:
        secid = quote.get("secid")
        if secid:
            quotes[str(secid)] = quote
        if quote.get("code"):
            quotes.setdefault(_pure_stock_code(quote.get("code")), quote)
    return quotes


def _quote_for_stock(quotes: dict[str, dict], code: object) -> dict | None:
    """从 quotes 字典中查找指定股票代码的行情。"""
    from qing_investment.monitor.fetchers import stock_code_to_secid
    secid = stock_code_to_secid(str(code or ""))
    if secid and secid in quotes:
        return quotes[secid]
    return quotes.get(_pure_stock_code(code))


def _quotes_by_label(quote_snapshot: dict) -> dict[str, dict]:
    """将 quote_snapshot 按标签索引。"""
    quotes: dict[str, dict] = {}
    for quote in quote_snapshot.get("quotes", []) or []:
        for key in (quote.get("label"), quote.get("name")):
            if key:
                quotes[str(key)] = quote
    return quotes


def _format_zone(zone: tuple[float, float]) -> str:
    """格式化价格区间。"""
    low, high = zone
    if low == high:
        return f"{low:g}"
    return f"{low:g}-{high:g}"




# ──────────────────────────────────────────
# 数据模型
# ──────────────────────────────────────────

@dataclass
class TokenBudget:
    """Token 预算配置。"""

    max_total: int = 8000  # 总预算
    max_per_stock: int = 200  # 每只标的最多 token
    max_stocks: int = 15  # 最多多少只标的进入 prompt
    reserve_for_system: int = 2000  # 预留系统提示词 token
    reserve_for_claims: int = 1500  # 预留 claims 上下文 token

    @property
    def available_for_stocks(self) -> int:
        """可用于标的描述的 token 数。"""
        return self.max_total - self.reserve_for_system - self.reserve_for_claims


@dataclass
class PrioritizedStock:
    """经过优先级排序的标的。"""

    code: str
    name: str
    priority: str  # P1/P2/P3/P4
    sort_key: int
    is_mainboard: bool
    entry_info: str = ""
    lifecycle: str = "观察"
    latest: float | None = None
    pct_change: float | None = None
    theme: str = ""
    segment: str = ""
    role: str = ""
    watch_reason: str = ""
    reduce_zone: str = ""
    risk_zone: str = ""
    up_sentiment: str = ""
    score: float = 0.0  # 综合评分


@dataclass
class AssembledContext:
    """组装完成的上下文。"""

    tradeable_stocks: list[dict]  # 可交易主板标的（进入机会扫描）
    reference_stocks: list[dict]  # 非主板锚点（仅情绪参考）
    dropped_stocks: list[dict]  # 被预算淘汰的标的
    token_estimate: int  # 预估 token 数
    stock_count: int  # 实际进入 prompt 的标的数


# ──────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────


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


def _estimate_tokens(text: str) -> int:
    """估算文本的 token 数（中文 ≈ 1字1token，英文 ≈ 4字符1token）。"""
    if not text:
        return 0
    # 简估算：中文字符 + 英文单词
    import re
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    english_tokens = len(re.findall(r"[a-zA-Z]+", text)) // 2
    return chinese_chars + english_tokens + len(text) // 10


def _format_stock_summary(stock: PrioritizedStock, max_tokens: int) -> str:
    """将标的格式化为简洁文本，控制在 max_tokens 内。"""
    parts = [f"{stock.name}({stock.code})"]

    if stock.priority in {"P1", "P1-核心"}:
        parts.append("[P1]")
    elif stock.priority in {"P2", "P2-重点"}:
        parts.append("[P2]")

    if stock.lifecycle and stock.lifecycle != "观察":
        parts.append(f"生命周期:{stock.lifecycle}")

    if stock.entry_info:
        parts.append(stock.entry_info)

    if stock.latest is not None and stock.pct_change is not None:
        parts.append(f"现价{stock.latest:g}({stock.pct_change:+.2f}%)")

    if stock.theme:
        parts.append(f"主题:{stock.theme}")

    if stock.role:
        parts.append(f"角色:{stock.role}")

    if stock.up_sentiment:
        parts.append(f"情绪:{stock.up_sentiment}")

    text = " | ".join(parts)
    tokens = _estimate_tokens(text)

    # 如果超预算，逐步裁剪
    while tokens > max_tokens and len(parts) > 2:
        parts.pop()  # 移除最后一个字段
        text = " | ".join(parts)
        tokens = _estimate_tokens(text)

    return text


# ──────────────────────────────────────────
# 标的优先级排序器
# ──────────────────────────────────────────


class StockPrioritizer:
    """标的优先级排序器。

    评分维度:
        1. 优先级权重 (P1=100, P2=50, P3=20)
        2. 生命周期权重 (持仓/建仓 > 观察)
        3. 价格触发权重 (接近介入区间/止损线)
        4. 涨跌幅权重 (异常波动优先)
        5. UP情绪权重 (有明确观点优先)
    """

    _PRIORITY_WEIGHT = {"P1": 100, "P1-核心": 100, "P2": 50, "P2-重点": 50, "P3": 20, "P3-观察": 20, "P4": 0, "P4-锚点": 0}
    _LIFECYCLE_WEIGHT = {"持仓": 80, "建仓": 70, "加仓": 60, "减仓": 50, "观察": 10, "": 0}

    def score(self, stock: PrioritizedStock) -> float:
        """计算标的综合评分。"""
        score = 0.0

        # 1. 优先级权重
        score += self._PRIORITY_WEIGHT.get(stock.priority, 0)

        # 2. 生命周期权重
        score += self._LIFECYCLE_WEIGHT.get(stock.lifecycle, 0)

        # 3. 价格触发权重（有介入区间或止损线）
        if stock.entry_info:
            score += 30
        if stock.reduce_zone or stock.risk_zone:
            score += 20

        # 4. 涨跌幅权重（异常波动优先）
        if stock.pct_change is not None:
            if abs(stock.pct_change) > 5:
                score += 40  # 大幅波动
            elif abs(stock.pct_change) > 3:
                score += 20  # 明显波动
            elif abs(stock.pct_change) > 1:
                score += 10  # 一般波动

        # 5. UP情绪权重
        if stock.up_sentiment:
            score += 15

        # 6. 主板加成（确保主板优先）
        if stock.is_mainboard:
            score += 5

        return score

    def prioritize(
        self,
        watchlist: list[dict],
        positions: list[dict],
        entry_points: list[dict],
        quote_snapshot: dict | None = None,
    ) -> list[PrioritizedStock]:
        """对所有标的进行优先级排序。

        Returns:
            list[PrioritizedStock]: 按评分降序排列的标的列表
        """
        stocks: dict[str, PrioritizedStock] = {}

        # 1. 处理 watchlist
        for w in watchlist or []:
            code = w.get("code", "")
            if not code:
                continue

            is_mb = _is_mainboard(code)
            priority = w.get("priority", "P3")
            sort_key = {"P1": 0, "P1-核心": 0, "P2": 1, "P2-重点": 1, "P3": 2, "P3-观察": 2}.get(priority, 99)

            entry_info_parts = []
            price_range = w.get("entry_price_range") or ""
            if price_range:
                entry_info_parts.append(f"介入区间:{price_range}")
            hs = w.get("entry_hard_stop") or ""
            if hs:
                entry_info_parts.append(f"止损:{hs}")

            stock = PrioritizedStock(
                code=code,
                name=w.get("name", ""),
                priority=priority if is_mb else "P4-锚点",
                sort_key=sort_key if is_mb else 3,
                is_mainboard=is_mb,
                entry_info=" ".join(entry_info_parts),
                lifecycle=w.get("lifecycle_stage") or "观察",
                latest=w.get("latest"),
                pct_change=w.get("pct_change"),
                theme=w.get("theme", ""),
                segment=w.get("segment", ""),
                role=w.get("role", ""),
                watch_reason=w.get("watch_reason", ""),
                reduce_zone=w.get("reduce_zone_desc", ""),
                risk_zone=w.get("risk_zone_desc", ""),
                up_sentiment=w.get("up_sentiment", ""),
            )
            stocks[code] = stock

        # 2. 处理 positions（覆盖或补充）
        accounts = positions.get("accounts", []) if isinstance(positions, dict) else (positions or [])
        for account in accounts:
            account_positions = account.get("positions", []) if isinstance(account, dict) else []
            for pos in account_positions:
                code = pos.get("code", "")
                if not code:
                    continue

                if code in stocks:
                    # 更新生命周期为持仓
                    stocks[code].lifecycle = "持仓"
                    # 补充止损/减仓信息
                    if pos.get("risk_zone") or pos.get("risk_line"):
                        stocks[code].risk_zone = pos.get("risk_zone") or pos.get("risk_line", "")
                    if pos.get("reduce_zone"):
                        stocks[code].reduce_zone = pos.get("reduce_zone", "")
                else:
                    # 新增持仓标的
                    is_mb = _is_mainboard(code)
                    stocks[code] = PrioritizedStock(
                        code=code,
                        name=pos.get("name", ""),
                        priority="P1" if is_mb else "P4-锚点",
                        sort_key=0 if is_mb else 3,
                        is_mainboard=is_mb,
                        lifecycle="持仓",
                        risk_zone=pos.get("risk_zone") or pos.get("risk_line", ""),
                        reduce_zone=pos.get("reduce_zone", ""),
                    )

        # 3. 处理 entry_points（激活状态的优先）
        for ep in entry_points or []:
            code = ep.get("code", "")
            if not code or ep.get("status") != "active":
                continue

            if code in stocks:
                # 提升优先级
                stocks[code].priority = "P1"
                stocks[code].sort_key = 0
                # 补充介入信息
                entry_zone = ep.get("entry_zone") or ep.get("buy_setup", "")
                if entry_zone:
                    stocks[code].entry_info = f"介入区间:{entry_zone}"
            else:
                is_mb = _is_mainboard(code)
                stocks[code] = PrioritizedStock(
                    code=code,
                    name=ep.get("name", ""),
                    priority="P1",
                    sort_key=0,
                    is_mainboard=is_mb,
                    lifecycle="建仓",
                    entry_info=f"介入区间:{ep.get('entry_zone', '')}",
                )

        # 4. 注入实时行情
        if quote_snapshot:
            quotes = quote_snapshot.get("quotes", []) or []
            for q in quotes:
                code = q.get("code", "")
                if code in stocks:
                    stocks[code].latest = q.get("latest")
                    stocks[code].pct_change = q.get("pct_change")

        # 5. 计算评分并排序
        result = list(stocks.values())
        for stock in result:
            stock.score = self.score(stock)

        # 先按 sort_key 分组，再按评分降序
        result.sort(key=lambda s: (s.sort_key, -s.score))
        return result


# ──────────────────────────────────────────
# Token 预算管理器
# ──────────────────────────────────────────


class TokenBudgetManager:
    """Token 预算管理器：控制进入 LLM prompt 的标的数量和描述长度。

    Usage:
        manager = TokenBudgetManager(max_tokens=8000, max_stocks=15)
        context = manager.build_context(
            watchlist=watchlist_data,
            positions=positions_data,
            entry_points=entry_points_data,
            quote_snapshot=quote_data,
        )
    """

    def __init__(
        self,
        max_tokens: int = 8000,
        max_stocks: int = 15,
        max_per_stock_tokens: int = 200,
    ):
        self.budget = TokenBudget(
            max_total=max_tokens,
            max_per_stock=max_per_stock_tokens,
            max_stocks=max_stocks,
        )
        self.prioritizer = StockPrioritizer()

    def build_context(
        self,
        watchlist: list[dict],
        positions: list[dict],
        entry_points: list[dict],
        quote_snapshot: dict | None = None,
    ) -> AssembledContext:
        """构建受控的上下文。

        流程:
            1. 对所有标的排序评分
            2. 分离主板/非主板
            3. 按预算选取前 N 只主板标的
            4. 非主板作为锚点单独列出（最多5只）
            5. 返回组装结果
        """
        # 1. 排序所有标的
        all_stocks = self.prioritizer.prioritize(
            watchlist, positions, entry_points, quote_snapshot
        )

        # 2. 分离主板和非主板
        mainboard = [s for s in all_stocks if s.is_mainboard]
        non_mainboard = [s for s in all_stocks if not s.is_mainboard]

        # 3. 按预算选取主板标的
        tradeable: list[dict] = []
        dropped: list[dict] = []
        used_tokens = 0
        available = self.budget.available_for_stocks

        for stock in mainboard:
            if len(tradeable) >= self.budget.max_stocks:
                dropped.append(self._stock_to_dict(stock, reason="超出数量限制"))
                continue

            summary = _format_stock_summary(stock, self.budget.max_per_stock)
            tokens = _estimate_tokens(summary)

            if used_tokens + tokens > available and len(tradeable) > 5:
                # 预算不足，但保留至少5只
                dropped.append(self._stock_to_dict(stock, reason="超出token预算"))
                continue

            tradeable.append({
                "code": stock.code,
                "name": stock.name,
                "summary": summary,
                "priority": stock.priority,
                "lifecycle": stock.lifecycle,
                "score": round(stock.score, 1),
                "tokens": tokens,
            })
            used_tokens += tokens

        # 4. 非主板锚点（最多5只，只给基本信息）
        reference: list[dict] = []
        for stock in non_mainboard[:5]:
            reference.append({
                "code": stock.code,
                "name": stock.name,
                "priority": "P4-锚点",
                "latest": stock.latest,
                "pct_change": stock.pct_change,
                "note": "非主板，仅作情绪锚点",
            })

        # 5. 记录被丢弃的
        for stock in mainboard[len(tradeable):]:
            if stock not in [s for s in all_stocks if not s.is_mainboard]:
                dropped.append(self._stock_to_dict(stock, reason="排序靠后"))

        total_estimate = (
            self.budget.reserve_for_system
            + self.budget.reserve_for_claims
            + used_tokens
            + sum(_estimate_tokens(r["name"]) for r in reference)
        )

        logger.info(
            f"TokenBudgetManager: tradeable={len(tradeable)} "
            f"reference={len(reference)} dropped={len(dropped)} "
            f"used_tokens={used_tokens} total_estimate={total_estimate}"
        )

        return AssembledContext(
            tradeable_stocks=tradeable,
            reference_stocks=reference,
            dropped_stocks=dropped,
            token_estimate=total_estimate,
            stock_count=len(tradeable),
        )

    def _stock_to_dict(self, stock: PrioritizedStock, reason: str) -> dict:
        """将淘汰标的转为字典记录。"""
        return {
            "code": stock.code,
            "name": stock.name,
            "priority": stock.priority,
            "score": round(stock.score, 1),
            "reason": reason,
        }

    def compress(
        self,
        state_update: dict,
        max_tokens: int = 8000,
        strategy: str = "priority",
    ) -> dict:
        """压缩 Agent 检索层上下文，确保不超过 token 预算。

        Args:
            state_update: AgentState 的检索层更新，含 claims/wiki_snippets 等
            max_tokens: 允许的最大 token 数
            strategy: 裁剪策略
                "priority" — 按类别优先级保留下层，上层先裁
                "aggressive" — 只保留 claims + wiki_snippets

        Returns:
            dict: 压缩后的 state_update
        """
        total = _estimate_tokens(__import__("json").dumps(state_update, ensure_ascii=False))
        if total <= max_tokens:
            return state_update

        compressed = dict(state_update)

        if strategy == "aggressive":
            keep_keys = {"claims", "wiki_snippets", "sector_context", "memories"}
            compressed = {k: v for k, v in state_update.items() if k in keep_keys}

        # priority: 按 claims > wiki > sector > memories 顺序裁
        priority_keys = ["memories", "few_shot_examples", "sector_context", "wiki_snippets", "claims"]
        for key in priority_keys:
            if key not in compressed:
                continue
            items = compressed[key]
            if isinstance(items, list) and len(items) > 5:
                half = max(5, len(items) // 2)
                compressed[key] = items[:half]
                total = _estimate_tokens(__import__("json").dumps(compressed, ensure_ascii=False))
                if total <= max_tokens:
                    break

        return compressed


# ──────────────────────────────────────────
# 向后兼容：简化接口
# ──────────────────────────────────────────


def build_watchlist_context(
    watchlist: list[dict],
    positions: list[dict],
    entry_points: list[dict],
    quote_snapshot: dict | None = None,
    max_tokens: int = 8000,
    max_stocks: int = 15,
) -> dict:
    """向后兼容的简化接口，返回与现有代码兼容的字典格式。

    Returns:
        {
            "watchlist_summary": [...],  # 可交易标的
            "reference_stocks": [...],   # 非主板锚点
            "dropped_stocks": [...],     # 被预算淘汰的
            "token_estimate": int,
            "stock_count": int,
        }
    """
    manager = TokenBudgetManager(max_tokens=max_tokens, max_stocks=max_stocks)
    ctx = manager.build_context(watchlist, positions, entry_points, quote_snapshot)

    return {
        "watchlist_summary": ctx.tradeable_stocks,
        "reference_stocks": ctx.reference_stocks,
        "dropped_stocks": ctx.dropped_stocks,
        "token_estimate": ctx.token_estimate,
        "stock_count": ctx.stock_count,
    }


def format_agent_analysis_context(*args) -> str:
    """将 agent 分析数据结构化为可读文本。

    支持两种调用方式:
        format_agent_analysis_context(data)           # 新方式（单 dict）
        format_agent_analysis_context(config, datetime, trigger, alerts, quotes, state)  # 旧方式

    data 来自 _agent_context_data() 的输出：
        {timestamp, trigger, market_framework, alerts,
         market_state, sector_signal_counts, quote_snapshot, positions, watchlist}

    Returns:
        str: 格式化后的分析上下文文本
    """
    from zoneinfo import ZoneInfo

    # 旧方式：6个位置参数
    if len(args) == 6:
        config, value, trigger, alerts, quotes, state = args
        data = {
            "timestamp": value.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M"),
            "trigger": {
                "kind": getattr(trigger, "kind", "未知"),
                "title": getattr(trigger, "title", ""),
                "reason": getattr(trigger, "reason", ""),
            } if trigger else {},
            "alerts": [{"summary": a.summary} for a in alerts] if alerts else [],
            "market_state": state.get("last_market_state", {}) if isinstance(state, dict) else {},
            "quote_snapshot": quotes,
        }
    elif len(args) == 1 and isinstance(args[0], dict):
        data = args[0]
    else:
        raise TypeError(f"format_agent_analysis_context() takes 1 or 6 arguments ({len(args)} given)")

    lines = [
        "[Hermes股票监控大模型分析上下文]",
        f"时间：{data.get('timestamp', '未知')}",
    ]

    trigger = data.get("trigger", {})
    if trigger:
        lines.extend(
            [
                f"触发类型：{trigger.get('kind', '未知')}",
                f"触发点：{trigger.get('title', '')}",
                f"触发原因：{trigger.get('reason', '')}",
            ]
        )

    mf = data.get("market_framework", {})
    if mf:
        lines.extend(
            [
                f"当前框架：{mf.get('stage', '未配置')}",
                f"核心问题：{mf.get('core_question', '未配置')}",
            ]
        )

    alerts = data.get("alerts", [])
    lines.extend(["", "规则信号："])
    if alerts:
        for a in alerts:
            lines.append(f"- {a.get('summary', '')}")
    else:
        lines.append("- 无新增规则信号")

    lines.append("")
    lines.append(f"持仓：{len(data.get('positions', []))} 只")
    lines.append(f"观察池：{len(data.get('watchlist', []))} 只")

    # 行情快照（兼容旧测试）
    quotes = data.get("quote_snapshot", {})
    if quotes:
        lines.extend(["", "行情快照："])
        for q in quotes.get("quotes", []):
            label = q.get("label", q.get("name", "未知"))
            lines.append(f"- {label}: 最新价 {q.get('latest', 'N/A')}")

    # 任务要求（兼容旧测试）
    lines.extend([
        "",
        "任务：请基于上述信息给出简要分析和操作建议。",
        "要求：最多450字，禁止Markdown表格。",
        "禁止把多只股票写成同一段。",
        "【重点分析】1-2只重点票，每只80-100字",
        "【其他持仓】剩余持仓每只15字",
        "观察池现在能不能买",
    ])

    return "\n".join(lines)


def _extract_pre_condition_text(stock_row: dict) -> str:
    """从 watchlist stock 行提取 pre_condition 为可读文本。"""
    pc = stock_row.get("pre_condition") or {}
    if not pc:
        return ""
    parts: list[str] = []
    if pc.get("market_actionable"):
        parts.append("大盘可操作")
    if pc.get("sector_diverged"):
        parts.append("板块首次分歧")
    if pc.get("no_consecutive_limit_up"):
        parts.append("非连续涨停")
    note = pc.get("market_gate_note") or pc.get("sector_gate_note")
    if note:
        parts.append(f"备注：{note}")
    return "；".join(parts) if parts else ""


def format_agent_json_context(data: dict) -> str:
    """将 agent 分析数据结构化为 JSON 字符串。

    Args:
        data: _agent_context_data() 输出的分析数据

    Returns:
        str: JSON 格式的上下文文本
    """
    import json

    # 确定分析类型和关联股票
    trigger = data.get("trigger", {})
    alerts = data.get("alerts", [])

    if isinstance(trigger, dict) and trigger.get("kind") == "buy_signal_candidate":
        analysis_type = "stock"
        # 取第一个候选的股票代码
        stock_code = ""
        for a in alerts:
            sc = a.get("stock_code", "") if isinstance(a, dict) else getattr(a, "stock_code", "")
            if sc:
                stock_code = sc
                break
    else:
        analysis_type = "market"
        stock_code = ""

    # 移除可能过大的 quote_snapshot，避免 token 浪费
    output = {k: v for k, v in data.items() if k != "quote_snapshot"}
    output["analysis_type"] = analysis_type
    output["stock_code"] = stock_code

    # 为买入候选注入 pre_condition 文本
    watchlist_rows: dict[str, dict] = {}
    watchlist = data.get("watchlist") or {}
    if isinstance(watchlist, dict):
        for row in watchlist.get("stocks", []) or []:
            watchlist_rows[str(row.get("code", ""))] = row
        for theme in watchlist.get("themes", []) or []:
            for stock in theme.get("stocks", []) or []:
                watchlist_rows[str(stock.get("code", ""))] = stock

    for candidate in output.get("buy_signal_candidates", []) or []:
        code = str(candidate.get("stock_code", ""))
        candidate["pre_condition"] = _extract_pre_condition_text(watchlist_rows.get(code, {}))

    return json.dumps(output, ensure_ascii=False, indent=2, default=str)


def load_yaml(path: str | Path) -> dict:
    """加载 YAML 文件。

    Args:
        path: YAML 文件路径

    Returns:
        dict: 解析后的字典，文件不存在或解析失败返回空字典
    """
    import yaml

    path_obj = Path(path) if isinstance(path, str) else path
    if not path_obj.exists():
        return {}
    try:
        data = yaml.safe_load(path_obj.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def load_monitor_config(path: str | Path) -> Any:
    """加载监控配置。

    从指定目录加载 positions.yaml / watchlist.yaml / strategy_pack.yaml。

    Args:
        path: 配置目录路径或配置文件路径

    Returns:
        MonitorConfig: 监控配置对象
    """
    from qing_investment.stock_monitor import MonitorConfig

    config_dir = Path(path) if isinstance(path, str) else path
    if config_dir.is_file():
        config_dir = config_dir.parent

    positions_path = config_dir / "positions.yaml"
    if not positions_path.exists():
        positions_path = config_dir / "positions.example.yaml"

    direction_pool_path = config_dir / "direction_pool.yaml"
    stock_pool_path = config_dir / "stock_pool.yaml"

    return MonitorConfig(
        config_dir=config_dir,
        positions=load_yaml(positions_path),
        watchlist=load_yaml(config_dir / "watchlist.yaml"),
        strategy_pack=load_yaml(config_dir / "strategy_pack.yaml"),
        positions_path=positions_path,
        direction_pool=load_yaml(direction_pool_path),
        stock_pool=load_yaml(stock_pool_path),
    )


def _extract_auction_snapshot_for_context(snapshot: dict) -> dict:
    """从竞价快照提取关键字段用于 context。

    Args:
        snapshot: 竞价快照数据

    Returns:
        dict: 精简后的竞价数据
    """
    if not snapshot:
        return {}

    result = {}
    for code, data in snapshot.items():
        if isinstance(data, dict):
            result[code] = {
                "latest": data.get("latest"),
                "volume": data.get("volume"),
                "pct_change": data.get("pct_change"),
                "time": data.get("time"),
            }
    return result


def _build_sector_tiers(
    config: Any,
    quote_snapshot: dict,
) -> dict:
    """构建板块分层 — 计算每个持仓股的板块梯队。

    同 theme 标的按涨幅排序 T1/T2/T3，用于 context 注入。

    Args:
        config: MonitorConfig（运行时动态解析）
        quote_snapshot: 行情快照

    Returns:
        dict: {code_pure: {tier1_code, tier1_pct, ..., peers_count}}
    """
    quotes = _quotes_by_code(quote_snapshot)
    positions = position_rows(config)

    # code → theme_id mapping from watchlist
    code_to_themes: dict[str, list[str]] = {}
    for theme in config.watchlist.get("themes", []):
        tid = theme.get("id", "")
        for stock in theme.get("stocks", []):
            c = _pure_stock_code(str(stock.get("code", "")))
            if c:
                code_to_themes.setdefault(c, []).append(tid)

    # all pct changes
    all_pct: dict[str, float] = {}
    for _, quote in quotes.items():
        c = _pure_stock_code(str(quote.get("code", "")))
        pct = _to_float(quote.get("pct_change"))
        if c and pct is not None:
            all_pct[c] = pct

    result: dict[str, dict] = {}
    for pos in positions:
        code_pure = _pure_stock_code(str(pos.get("code", "")))
        themes = code_to_themes.get(code_pure, [])
        if not themes:
            continue

        peers_set: set[str] = set()
        for tid in themes:
            for theme in config.watchlist.get("themes", []):
                if theme.get("id") != tid:
                    continue
                for stock in theme.get("stocks", []):
                    c = _pure_stock_code(str(stock.get("code", "")))
                    if c:
                        peers_set.add(c)

        if not peers_set:
            continue

        peer_pct = [(c, all_pct.get(c)) for c in peers_set if all_pct.get(c) is not None]
        peer_pct.sort(key=lambda x: x[1], reverse=True)

        tiers: dict = {"peers_count": len(peer_pct)}
        for i, (pc, pp) in enumerate(peer_pct[:3]):
            tiers[f"tier{i+1}_code"] = pc
            tiers[f"tier{i+1}_pct"] = pp

        # Calculate average
        if peer_pct:
            tiers["avg_change"] = round(sum(p for _, p in peer_pct) / len(peer_pct), 2)

        result[code_pure] = tiers

    return result


def _agent_context_data(
    config: Any,
    quote_snapshot: dict,
    state: dict,
) -> dict:
    """构建 Agent 分析所需的 context 数据。

    Args:
        config: MonitorConfig
        quote_snapshot: 行情快照
        state: 监控状态

    Returns:
        dict: 结构化分析数据
    """
    import json

    stage = config.strategy_pack.get("market_framework", {}).get(
        "current_stage", "未配置"
    )
    core_question = config.strategy_pack.get("market_framework", {}).get(
        "core_question", "未配置"
    )

    return {
        "market_framework": {
            "stage": stage,
            "core_question": core_question,
        },
        "market_state": state.get("last_market_state", {}),
        "sector_signal_counts": state.get("sector_signal_counts", {}),
        "quote_snapshot": quote_snapshot,
        "positions": position_rows(config),
        "watchlist": watchlist_stock_rows(config),
    }


def format_daily_review_context(review: dict) -> str:
    """格式化每日复盘 context。

    Args:
        review: 复盘数据字典

    Returns:
        str: 格式化后的复盘上下文文本
    """
    lines = [
        "[Hermes股票监控收盘复盘上下文]",
        f"日期：{review.get('date', '未知')}",
    ]

    emitted = review.get("emitted_alerts", [])
    suppressed = review.get("suppressed_alerts", [])
    if emitted or suppressed:
        lines.extend(
            [
                "",
                "统计：",
                f"- 已发送提醒：{len(emitted)}",
                f"- 被去重压制：{len(suppressed)}",
                "",
                "复盘问题：",
                "- 误报：检查是否有不必要的提醒",
                "- 漏报：检查是否有遗漏的信号",
                "- YAML：确认配置文件是否需要更新",
            ]
        )

    entries = review.get("entries", [])
    if entries:
        lines.extend(["", "详细条目："])
        for entry in entries:
            lines.append(f"- {entry}")

    return "\n".join(lines)


def format_live_analysis_context(context_data: dict) -> str:
    """格式化实时分析 context。

    Args:
        context_data: 实时分析数据字典

    Returns:
        str: 格式化后的实时分析上下文
    """
    lines = [
        "[Hermes股票监控实时分析上下文]",
    ]

    base = context_data.get("base_context", "")
    if base:
        lines.append(base)

    quotes = context_data.get("quotes", [])
    if quotes:
        lines.extend(["", "实时行情快照："])
        from qing_investment.monitor.output import format_quote_line
        for q in quotes:
            lines.append(format_quote_line(q))

    elapsed = context_data.get("elapsed_ms")
    if elapsed is not None:
        lines.append(f"行情请求耗时：{elapsed} ms")

    return "\n".join(lines)
