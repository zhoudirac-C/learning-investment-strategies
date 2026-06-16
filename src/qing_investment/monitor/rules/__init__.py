"""Qing-Agent 监控引擎 — 规则引擎层 (Phase 1)

将 stock_monitor.py 中的规则判断逻辑拆分为独立的 RuleEngine 模块。

职责边界:
    - 只负责"判断规则是否触发"，不负责数据获取和消息发送
    - 输入: 行情快照 + 配置
    - 输出: RuleAlert 列表

规则类型:
    1. 持仓规则: 减仓观察/风控观察/加仓观察
    2. 买入信号: 介入区间 + 6项条件筛选
    3. 指数规则: 趋势防线/弱修复阈值
    4. 板块轮动: 进攻/防御切换

向后兼容:
    evaluate_monitor_alerts() 委托给本模块，行为完全一致。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import Any

from pydantic import BaseModel, Field

from qing_investment.monitor.chain_scanner import ChainAwareScanner
from qing_investment.monitor.gates import GateResult


# ──────────────────────────────────────────
# 数据模型 (从 stock_monitor.py 迁移)
# ──────────────────────────────────────────

class RuleAlert(BaseModel):
    """规则触发告警。"""

    action: str = Field(description="动作类型，如 减仓观察/风控观察/机会候选")
    stock_code: str = Field(description="股票代码")
    stock_name: str = Field(description="股票名称")
    price: float = Field(description="触发价格")
    trigger: str = Field(description="触发条件描述")
    severity: str = Field(description="严重程度: observe/risk/opportunity")
    summary: str = Field(description="完整告警消息")


class SectorStrength(BaseModel):
    """板块强度统计。"""

    id: str
    name: str
    style: str
    average_pct_change: float
    red_ratio: float
    quote_count: int
    total_amount: float


class BuySignalCandidate(BaseModel):
    """买入信号候选（poll 层输出，不是最终信号）。"""

    stock_code: str
    stock_name: str
    price: float
    is_candidate: bool
    matched_conditions: list[str]
    entry_zone: tuple[float, float] | None = None
    stop_loss: float | None = None
    claim_basis: str = ""
    odds_analysis: Any = None


# ──────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────

def _to_float(val: Any) -> float | None:
    """安全转换为 float。"""
    try:
        return float(val) if val is not None and val != "" else None
    except (ValueError, TypeError):
        return None


def _norm_code(raw: str) -> str:
    """标准化股票代码。"""
    c = raw.lower().strip().replace(".sh", "").replace(".sz", "")
    if c.startswith("sh") or c.startswith("sz"):
        c = c[2:]
    return c


def parse_price_zone(value: object) -> tuple[float, float] | None:
    """解析价格区间文本，如 '73-76' 或 '73~76'；也支持单个数值。"""
    if value is None:
        return None
    if isinstance(value, int | float):
        price = float(value)
        return (price, price)

    text = str(value).strip()
    if not text:
        return None
    # 支持 - 或 ~ 分隔
    for sep in ["-", "~", "—", "到"]:
        if sep in text:
            parts = text.split(sep)
            if len(parts) == 2:
                low = _to_float(parts[0].strip())
                high = _to_float(parts[1].strip())
                if low is not None and high is not None and low <= high:
                    return (low, high)
    return None


def _format_zone(zone: tuple[float, float]) -> str:
    """格式化价格区间。"""
    return f"{zone[0]:g}-{zone[1]:g}"


def _quotes_by_code(quote_snapshot: dict) -> dict[str, dict]:
    """按代码索引行情数据（优先使用 secid，回退到 code）。"""
    quotes: dict[str, dict] = {}
    for q in quote_snapshot.get("quotes", []) or []:
        # 优先使用 secid（含市场信息，如 0.000001 / 1.000001）
        secid = str(q.get("secid", ""))
        if secid:
            quotes[secid] = q
        # 同时用 code 索引（用于无 secid 的兼容场景）
        code = str(q.get("code", ""))
        if code and code not in quotes:
            quotes[code] = q
    return quotes


def _quotes_by_label(quote_snapshot: dict) -> dict[str, dict]:
    """按标签索引行情数据。"""
    quotes: dict[str, dict] = {}
    for q in quote_snapshot.get("quotes", []) or []:
        label = str(q.get("label", ""))
        if label:
            quotes[label] = q
    return quotes


def _quote_for_stock(quotes: dict[str, dict], code: str) -> dict | None:
    """根据代码查找行情。"""
    if not code:
        return None
    # 先尝试精确匹配
    if code in quotes:
        return quotes[code]
    # 尝试 secid 匹配（如 0.000001.SZ -> 0.000001）
    norm = _norm_code(code)
    for k, v in quotes.items():
        # 直接匹配标准化后的 code
        if _norm_code(k) == norm:
            return v
        # 尝试 secid 匹配（secid 格式: 市场.代码，如 0.000001）
        secid = str(v.get("secid", ""))
        if secid:
            # secid 格式: 0.000001，标准化后: 000001
            secid_norm = secid.split(".", 1)[1] if "." in secid else secid
            if secid_norm == norm:
                return v
    return None


# ──────────────────────────────────────────
# 规则引擎基类
# ──────────────────────────────────────────

class BaseRuleEngine:
    """规则引擎基类。"""

    name: str = "base"

    def evaluate(self, config: dict, quote_snapshot: dict, **kwargs) -> list[RuleAlert]:
        """评估规则，返回告警列表。"""
        return []


# ──────────────────────────────────────────
# 1. 持仓规则引擎
# ──────────────────────────────────────────

class PositionRuleEngine(BaseRuleEngine):
    """持仓规则引擎: 减仓观察/风控观察/加仓观察。"""

    name = "position"

    def evaluate(self, config: dict, quote_snapshot: dict, **kwargs) -> list[RuleAlert]:
        quotes = _quotes_by_code(quote_snapshot)
        alerts: list[RuleAlert] = []
        seen: set[tuple[str, str, str]] = set()

        # 加载 entry_points 用于丰富提醒消息
        entry_by_code: dict[str, dict] = {}
        for ep in config.get("entry_points", []) or []:
            ep_code = _norm_code(str(ep.get("code", "")))
            if ep_code:
                entry_by_code[ep_code] = ep

        # 遍历持仓
        for account in config.get("positions", {}).get("accounts", []) or []:
            for pos in account.get("positions", []) or []:
                code = str(pos.get("code", ""))
                quote = _quote_for_stock(quotes, code)
                latest = _to_float((quote or {}).get("latest"))
                if latest is None:
                    continue

                name = str(pos.get("name") or (quote or {}).get("name") or "")
                pct_change = str((quote or {}).get("pct_change", ""))

                # ── 减仓观察 ──
                reduce_zone = parse_price_zone(pos.get("reduce_zone"))
                if reduce_zone and reduce_zone[0] <= latest <= reduce_zone[1]:
                    trigger = f"进入预设减仓区{_format_zone(reduce_zone)}"
                    key = (code, "减仓观察", trigger)
                    if key in seen:
                        continue
                    seen.add(key)
                    alerts.append(
                        RuleAlert(
                            action="减仓观察",
                            stock_code=code,
                            stock_name=name,
                            price=latest,
                            trigger=trigger,
                            severity="observe",
                            summary=self._build_summary(
                                "减仓观察", name, code, latest, pct_change, trigger, pos, entry_by_code
                            ),
                        )
                    )

                # ── 风控观察 ──
                risk_zone = parse_price_zone(pos.get("risk_zone") or pos.get("risk_line"))
                if risk_zone and latest <= risk_zone[1]:
                    trigger = f"触及或跌破风险线{_format_zone(risk_zone)}"
                    key = (code, "风控观察", trigger)
                    if key in seen:
                        continue
                    seen.add(key)
                    alerts.append(
                        RuleAlert(
                            action="风控观察",
                            stock_code=code,
                            stock_name=name,
                            price=latest,
                            trigger=trigger,
                            severity="risk",
                            summary=self._build_summary(
                                "风控观察", name, code, latest, pct_change, trigger, pos, entry_by_code
                            ),
                        )
                    )

                # ── 加仓观察 ──
                add_zone = parse_price_zone(pos.get("add_zone"))
                if add_zone and add_zone[0] <= latest <= add_zone[1]:
                    trigger = f"进入预设加仓区{_format_zone(add_zone)}"
                    key = (code, "加仓观察", trigger)
                    if key in seen:
                        continue
                    seen.add(key)
                    alerts.append(
                        RuleAlert(
                            action="加仓观察",
                            stock_code=code,
                            stock_name=name,
                            price=latest,
                            trigger=trigger,
                            severity="opportunity",
                            summary=self._build_summary(
                                "机会触发", name, code, latest, pct_change, trigger, pos, entry_by_code
                            ),
                        )
                    )

        return alerts

    def _build_summary(
        self,
        action_label: str,
        name: str,
        code: str,
        latest: float,
        pct_change: str,
        trigger: str,
        pos: dict,
        entry_by_code: dict[str, dict],
    ) -> str:
        """构建告警消息。"""
        norm = _norm_code(code)
        entry = entry_by_code.get(norm)
        risk_zone_raw = pos.get("risk_zone") or pos.get("risk_line", "")

        parts = [f"【{action_label}】{name}({code}) {latest:g}（{pct_change}%）{trigger}"]

        if entry:
            odds = entry.get("odds_analysis", "")
            cb_id = entry.get("claim_basis", "")
            if odds:
                odds_short = str(odds)[:120] + ("…" if len(str(odds)) > 120 else "")
                parts.append(f"赔率：{odds_short}")
            if cb_id:
                parts.append(f"参考：{cb_id}")

        if risk_zone_raw:
            parts.append(f"止损：{risk_zone_raw}")

        return " | ".join(parts)


# ──────────────────────────────────────────
# 2. 买入信号规则引擎
# ──────────────────────────────────────────

class BuySignalRuleEngine(BaseRuleEngine):
    """买入信号规则引擎: 介入区间 + 6项条件筛选。"""

    name = "buy_signal"

    def evaluate(
        self,
        config: dict,
        quote_snapshot: dict,
        *,
        current_time: datetime | None = None,
        market_gate_result: "GateResult" | None = None,
        sector_gate_results: dict[str, "GateResult"] | None = None,
        **kwargs,
    ) -> list[RuleAlert]:
        candidates = self._evaluate_with_gates(
            config,
            quote_snapshot,
            market_gate_result=market_gate_result,
            sector_gate_results=sector_gate_results,
        )
        alerts: list[RuleAlert] = []

        for candidate in candidates:
            if not candidate.is_candidate:
                continue

            zone_str = (
                f"{candidate.entry_zone[0]:g}-{candidate.entry_zone[1]:g}"
                if candidate.entry_zone
                else "未知"
            )
            summary = (
                f"【机会候选】{candidate.stock_name}({candidate.stock_code}) "
                f"现价{candidate.price:g} 进入介入区间{zone_str} "
                f"满足{len(candidate.matched_conditions)}/6条件："
                f"{', '.join(candidate.matched_conditions)}"
            )

            alerts.append(
                RuleAlert(
                    action="机会候选",
                    stock_code=candidate.stock_code,
                    stock_name=candidate.stock_name,
                    price=candidate.price,
                    trigger=f"进入介入区间{zone_str}",
                    severity="opportunity",
                    summary=summary,
                )
            )

        return alerts

    def _evaluate_with_gates(
        self,
        config: dict,
        quote_snapshot: dict,
        *,
        market_gate_result: "GateResult" | None = None,
        sector_gate_results: dict[str, "GateResult"] | None = None,
    ) -> list[BuySignalCandidate]:
        """四层架构：前置门控已由上层计算，本层只做标的条件检查。"""
        sector_gate_results = sector_gate_results or {}
        candidates = self._evaluate_candidates(config, quote_snapshot)

        filtered: list[BuySignalCandidate] = []
        for candidate in candidates:
            # 前置门控：市场
            if market_gate_result is not None and not market_gate_result.passed:
                candidate.is_candidate = False
                filtered.append(candidate)
                continue

            # 前置门控：板块（通过 direction_id 查找）
            direction_id = self._stock_direction_id(config, candidate.stock_code)
            sector_result = sector_gate_results.get(direction_id)
            if sector_result is not None and not sector_result.passed:
                candidate.is_candidate = False
                filtered.append(candidate)
                continue

            filtered.append(candidate)
        return filtered

    def _stock_direction_id(self, config: dict, code: str) -> str:
        """从 stock_pool 查找标的所属 direction_id。"""
        code_norm = _norm_code(code)
        for stock in config.get("stock_pool", {}).get("stocks", []) or []:
            if _norm_code(str(stock.get("code", ""))) == code_norm:
                return stock.get("direction", "")
        return ""

    def _evaluate_candidates(
        self, config: dict, quote_snapshot: dict
    ) -> list[BuySignalCandidate]:
        """评估买入信号候选。"""
        quotes = _quotes_by_code(quote_snapshot)
        candidates: list[BuySignalCandidate] = []

        # 加载 entry_points
        entry_by_code: dict[str, dict] = {}
        for ep in config.get("entry_points", []) or []:
            ep_code = _norm_code(str(ep.get("code", "")))
            if ep_code:
                entry_by_code[ep_code] = ep

        # 从 positions 提取 add_zone
        for account in config.get("positions", {}).get("accounts", []) or []:
            for pos in account.get("positions", []) or []:
                pos_code = _norm_code(str(pos.get("code", "")))
                if pos_code and pos_code not in entry_by_code:
                    add_zone = parse_price_zone(pos.get("add_zone"))
                    if add_zone:
                        entry_by_code[pos_code] = {
                            "code": pos.get("code", ""),
                            "name": pos.get("name", ""),
                            "entry_zone": f"{add_zone[0]}-{add_zone[1]}",
                            "stop_loss": pos.get("risk_zone") or pos.get("risk_line"),
                            "claim_basis": "",
                            "odds_analysis": {},
                        }

        # 从 watchlist 提取 entry_zone
        for theme in config.get("watchlist", {}).get("themes", []) or []:
            for stock in theme.get("stocks", []) or []:
                stock_code = _norm_code(str(stock.get("code", "")))
                if stock_code and stock_code not in entry_by_code:
                    ez = stock.get("entry_zone", {}) or {}
                    price_range_text = ez.get("price_range", "")
                    zone = parse_price_zone(price_range_text)
                    if zone:
                        entry_by_code[stock_code] = {
                            "code": stock.get("code", ""),
                            "name": stock.get("name", ""),
                            "entry_zone": f"{zone[0]}-{zone[1]}",
                            "stop_loss": stock.get("invalidation_setup", ""),
                            "claim_basis": "",
                            "odds_analysis": {},
                        }

        # 遍历所有有介入区间的标的
        for code_norm, entry in entry_by_code.items():
            quote = _quote_for_stock(quotes, entry.get("code", code_norm))
            if not quote:
                continue

            latest = _to_float(quote.get("latest"))
            if latest is None:
                continue

            name = str(quote.get("name") or entry.get("name", ""))
            pct_change = _to_float(quote.get("pct_change", 0)) or 0.0

            zone = parse_price_zone(entry.get("entry_zone"))
            if not zone:
                continue

            # 六项条件
            price_in_zone = zone[0] <= latest <= zone[1]
            price_deviated = latest > zone[1] * 1.05
            if price_deviated:
                price_in_zone = False

            not_crashing = pct_change > -3.0
            no_limit_up = pct_change < 7.0
            has_claim_support = bool(entry.get("claim_basis"))

            # 本地 K线条件（SQLite 读取，零网络延迟）
            volume_shrinking = False
            above_key_ma = False
            try:
                from qing_investment.kline_cache import get_klines, get_ma

                klines = get_klines(entry.get("code", code_norm), days=5)
                if len(klines) >= 4:
                    vols = [d.get("volume", 0) for d in klines[-3:]]
                    if all(vols):
                        volume_shrinking = vols[0] < vols[1] < vols[2]
                ma20 = get_ma(entry.get("code", code_norm), days=20)
                if ma20 and klines:
                    above_key_ma = klines[-1].get("close", 0) > ma20
            except Exception:
                pass

            conditions = {
                "价格进入区间": price_in_zone,
                "非系统性大跌": not_crashing,
                "未涨停": no_limit_up,
                "UP明确看好": has_claim_support,
                "近3日缩量": volume_shrinking,
                "MA20上方": above_key_ma,
            }
            matched = [k for k, v in conditions.items() if v]
            is_candidate = len(matched) >= 4

            candidates.append(
                BuySignalCandidate(
                    stock_code=entry.get("code", code_norm),
                    stock_name=name,
                    price=latest,
                    is_candidate=is_candidate,
                    matched_conditions=matched,
                    entry_zone=zone,
                    stop_loss=_to_float(entry.get("stop_loss")),
                    claim_basis=entry.get("claim_basis", ""),
                    odds_analysis=entry.get("odds_analysis") or {},
                )
            )

        return candidates


# ──────────────────────────────────────────
# 3. 指数规则引擎
# ──────────────────────────────────────────

class IndexRuleEngine(BaseRuleEngine):
    """指数规则引擎: 趋势防线/弱修复阈值。"""

    name = "index"

    def evaluate(
        self, config: dict, quote_snapshot: dict, *, current_time: datetime | None = None, **kwargs
    ) -> list[RuleAlert]:
        alerts: list[RuleAlert] = []
        quotes = _quotes_by_label(quote_snapshot)
        index_rules = (
            config.get("market_framework", {}).get("index_rules", []) or []
        )

        for rule in index_rules:
            index_name = str(rule.get("index", ""))
            quote = quotes.get(index_name)
            latest = _to_float((quote or {}).get("latest"))
            if latest is None:
                continue

            # 先尝试通用格式，再回退到旧格式
            alert = self._evaluate_generic(rule, latest, index_name, quote, current_time=current_time)
            if alert is None:
                alert = self._evaluate_legacy(rule, latest, index_name, quote)
            if alert is not None:
                alerts.append(alert)

        return alerts

    def _evaluate_generic(
        self,
        rule: dict,
        latest: float,
        index_name: str,
        quote: dict | None,
        *,
        current_time: datetime | None = None,
    ) -> RuleAlert | None:
        """通用格式: trigger_condition + threshold。"""
        trigger_condition = rule.get("trigger_condition")
        threshold = _to_float(rule.get("threshold"))

        if not trigger_condition or threshold is None:
            return None

        is_close_rule = trigger_condition in ("close_below", "close_above")

        # close规则只在收盘后评估（15:00后）
        if is_close_rule and current_time is not None:
            from zoneinfo import ZoneInfo
            cn_tz = ZoneInfo("Asia/Shanghai")
            local = current_time.astimezone(cn_tz)
            if local.time() < time(15, 0):
                return None

        if trigger_condition in ("close_below", "intraday_below"):
            if not (latest <= threshold):
                return None
        elif trigger_condition in ("close_above", "intraday_above"):
            if not (latest >= threshold):
                return None
        else:
            return None

        severity = rule.get("severity", "observe")
        action = rule.get("action") or "指数规则触发"

        trigger_template = rule.get("trigger_template", "")
        if trigger_template:
            trigger = trigger_template.format(threshold=threshold)
        else:
            direction = "跌破" if "below" in trigger_condition else "突破"
            trigger = f"{direction}{threshold:g}"

        interpretation = rule.get("interpretation", "")
        if interpretation:
            summary = f"{action}：{index_name} 当前点位={latest:g}；{trigger}。{interpretation}"
        else:
            summary = (
                f"{action}：{index_name} 当前点位={latest:g}；{trigger}。"
                "需要降低进攻预期，观察科技主线是否继续承接。"
            )

        return RuleAlert(
            action=action,
            stock_code=str((quote or {}).get("code", "")),
            stock_name=index_name,
            price=latest,
            trigger=trigger,
            severity=severity,
            summary=summary,
        )

    def _evaluate_legacy(
        self, rule: dict, latest: float, index_name: str, quote: dict | None
    ) -> RuleAlert | None:
        """旧格式: trend_defense / weak_close_level。"""
        trend_defense = _to_float(rule.get("trend_defense"))
        weak_close_level = _to_float(rule.get("weak_close_level"))

        if trend_defense is not None and latest <= trend_defense:
            action = "指数趋势防线观察"
            trigger = f"跌至趋势防线{trend_defense:g}附近或下方"
            severity = "risk"
        elif weak_close_level is not None and latest < weak_close_level:
            action = "指数弱修复观察"
            trigger = f"低于弱修复阈值{weak_close_level:g}"
            severity = "observe"
        else:
            return None

        return RuleAlert(
            action=action,
            stock_code=str((quote or {}).get("code", "")),
            stock_name=index_name,
            price=latest,
            trigger=trigger,
            severity=severity,
            summary=(
                f"{action}：{index_name} 当前点位={latest:g}；{trigger}。"
                "需要降低进攻预期，观察科技主线是否继续承接。"
            ),
        )


# ──────────────────────────────────────────
# 4. 板块轮动规则引擎
# ──────────────────────────────────────────

class SectorRotationRuleEngine(BaseRuleEngine):
    """板块轮动规则引擎: 进攻/防御切换观察。"""

    name = "sector_rotation"

    def evaluate(self, config: dict, quote_snapshot: dict, **kwargs) -> list[RuleAlert]:
        strengths = {
            item.id: item for item in self._compute_sector_strength(config, quote_snapshot)
        }
        alerts: list[RuleAlert] = []

        for rule in config.get("sector_rotation_rules", []) or []:
            offensive = self._aggregate(strengths, rule.get("offensive_groups", []) or [])
            defensive = self._aggregate(strengths, rule.get("defensive_groups", []) or [])
            if offensive is None or defensive is None:
                continue

            min_spread = _to_float(rule.get("min_spread_pct")) or 1.0
            min_red_ratio_spread = _to_float(rule.get("min_red_ratio_spread")) or 0.0
            pct_spread = round(offensive.average_pct_change - defensive.average_pct_change, 3)
            red_ratio_spread = round(offensive.red_ratio - defensive.red_ratio, 3)

            if pct_spread >= min_spread and red_ratio_spread >= min_red_ratio_spread:
                action = "进攻回流观察"
                trigger = (
                    f"{offensive.name} 均涨幅{offensive.average_pct_change:g}%、"
                    f"红盘率{offensive.red_ratio:g}，强于 {defensive.name}"
                )
                severity = "observe"
            elif -pct_spread >= min_spread and -red_ratio_spread >= min_red_ratio_spread:
                action = "防御切换观察"
                trigger = (
                    f"{defensive.name} 均涨幅{defensive.average_pct_change:g}%、"
                    f"红盘率{defensive.red_ratio:g}，强于 {offensive.name}"
                )
                severity = "risk"
            else:
                continue

            alerts.append(
                RuleAlert(
                    action=action,
                    stock_code=str(rule.get("id", "")),
                    stock_name="板块强弱",
                    price=abs(pct_spread),
                    trigger=trigger,
                    severity=severity,
                    summary=(
                        f"{action}：{trigger}。当前强弱差={abs(pct_spread):g}pct，"
                        "需要结合指数关键位和持仓分时承接确认。"
                    ),
                )
            )

        return alerts

    def _compute_sector_strength(self, config: dict, quote_snapshot: dict) -> list[SectorStrength]:
        """计算板块强度。"""
        quotes = _quotes_by_code(quote_snapshot)
        strengths: list[SectorStrength] = []

        for group in config.get("sector_groups", []) or []:
            pct_changes: list[float] = []
            red_count = 0
            total_amount = 0.0
            for member in group.get("members", []) or []:
                quote = _quote_for_stock(quotes, member.get("code"))
                pct_change = _to_float((quote or {}).get("pct_change"))
                if pct_change is None:
                    continue
                pct_changes.append(pct_change)
                if pct_change > 0:
                    red_count += 1
                amount = _to_float((quote or {}).get("amount"))
                if amount is not None:
                    total_amount += amount

            quote_count = len(pct_changes)
            if quote_count == 0:
                continue
            strengths.append(
                SectorStrength(
                    id=str(group.get("id", "")),
                    name=str(group.get("name", "")),
                    style=str(group.get("style", "")),
                    average_pct_change=round(sum(pct_changes) / quote_count, 3),
                    red_ratio=round(red_count / quote_count, 3),
                    quote_count=quote_count,
                    total_amount=round(total_amount, 2),
                )
            )

        return strengths

    def _aggregate(
        self, strengths: dict[str, SectorStrength], group_ids: list[str]
    ) -> SectorStrength | None:
        """聚合多个板块组的强度。"""
        selected = [strengths[group_id] for group_id in group_ids if group_id in strengths]
        if not selected:
            return None

        quote_count = sum(item.quote_count for item in selected)
        if quote_count == 0:
            return None

        average_pct_change = sum(
            item.average_pct_change * item.quote_count for item in selected
        ) / quote_count
        red_ratio = sum(item.red_ratio * item.quote_count for item in selected) / quote_count
        total_amount = sum(item.total_amount for item in selected)
        return SectorStrength(
            id=",".join(group_ids),
            name="、".join(item.name for item in selected),
            style="aggregate",
            average_pct_change=round(average_pct_change, 3),
            red_ratio=round(red_ratio, 3),
            quote_count=quote_count,
            total_amount=round(total_amount, 2),
        )


# ──────────────────────────────────────────
# 统一入口: RuleEngine
# ──────────────────────────────────────────

class RuleEngine:
    """统一规则引擎，管理所有子引擎的注册和执行。

    Usage:
        engine = RuleEngine()
        alerts = engine.evaluate(config_dict, quote_snapshot)
    """

    def __init__(self):
        self._engines: list[BaseRuleEngine] = [
            PositionRuleEngine(),
            BuySignalRuleEngine(),
            IndexRuleEngine(),
            SectorRotationRuleEngine(),
        ]

    def evaluate(
        self, config: dict, quote_snapshot: dict, *, current_time: datetime | None = None
    ) -> list[RuleAlert]:
        """执行所有规则引擎，合并告警。"""
        all_alerts: list[RuleAlert] = []
        for engine in self._engines:
            try:
                alerts = engine.evaluate(config, quote_snapshot, current_time=current_time)
                all_alerts.extend(alerts)
            except Exception as exc:
                # 单个引擎失败不影响其他引擎
                import logging
                logging.getLogger(__name__).warning(
                    f"RuleEngine {engine.name} failed: {exc}", exc_info=True
                )
        return all_alerts

    def evaluate_by_type(
        self,
        rule_type: str,
        config: dict,
        quote_snapshot: dict,
        *,
        current_time: datetime | None = None,
    ) -> list[RuleAlert]:
        """按类型执行单个规则引擎。"""
        type_map = {
            "position": PositionRuleEngine,
            "buy_signal": BuySignalRuleEngine,
            "index": IndexRuleEngine,
            "sector_rotation": SectorRotationRuleEngine,
        }
        engine_class = type_map.get(rule_type)
        if not engine_class:
            return []
        engine = engine_class()
        return engine.evaluate(config, quote_snapshot, current_time=current_time)


# ──────────────────────────────────────────
# 向后兼容: 委托函数
# ──────────────────────────────────────────

_rule_engine: RuleEngine | None = None


def _get_engine() -> RuleEngine:
    """获取全局 RuleEngine 单例。"""
    global _rule_engine
    if _rule_engine is None:
        _rule_engine = RuleEngine()
    return _rule_engine


def evaluate_monitor_alerts(
    config: dict, quote_snapshot: dict, *, current_time: datetime | None = None
) -> list[RuleAlert]:
    """向后兼容的委托函数，行为与 stock_monitor.evaluate_monitor_alerts 一致。

    Returns:
        list[RuleAlert]: 所有触发的告警
    """
    return _get_engine().evaluate(config, quote_snapshot, current_time=current_time)


def validate_position_price_zones(
    config: MonitorConfig,
) -> list[str]:
    """验证持仓价格区间是否合理（防失真）。

    规则：
    - reduce_zone 上限距现价 > 12% → 向上失真
    - risk_zone 缺失 → 高危漏报

    Returns:
        list[str]: 告警信息列表，空列表表示全部正常
    """
    from qing_investment.monitor.context import (
        _pure_stock_code,
        parse_price_zone,
        position_rows,
    )

    warnings: list[str] = []

    for row in position_rows(config):
        code = str(row.get("code", ""))
        name = str(row.get("name", ""))

        reduce_zone = parse_price_zone(row.get("reduce_zone"))
        risk_zone = parse_price_zone(
            row.get("risk_zone") or row.get("risk_line")
        )

        if reduce_zone is None and risk_zone is None:
            warnings.append(
                f"[{name}({code})] 缺少 reduce_zone 和 risk_zone，跌停将无提醒"
            )
            continue

    return warnings
