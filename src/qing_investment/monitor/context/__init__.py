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
