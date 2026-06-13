from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import time as time_module
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from qing_investment.paths import repo_root


logger = logging.getLogger(__name__)
CN_TZ = ZoneInfo("Asia/Shanghai")
DEFAULT_CONFIG_DIR = repo_root() / "config" / "stock_monitor"
QUOTE_FIELDS = "f12,f13,f14,f2,f3,f4,f5,f6,f15,f16,f17,f18"
EASTMONEY_QUOTE_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"
QUOTE_CHUNK_SIZE = 15
MARKET_INDEXES = {
    "上证指数": "1.000001",
    "深证成指": "0.399001",
    "创业板指": "0.399006",
    "科创50": "1.000688",
    "全A指数": "1.000985",   # 中证全指，同花顺全A(883657)无公开API，用此替代
}


@dataclass(frozen=True)
class MonitorConfig:
    config_dir: Path
    positions: dict
    watchlist: dict
    strategy_pack: dict
    positions_path: Path


@dataclass(frozen=True)
class RuleAlert:
    action: str
    stock_code: str
    stock_name: str
    price: float
    trigger: str
    severity: str
    summary: str


@dataclass(frozen=True)
class SectorStrength:
    id: str
    name: str
    style: str
    average_pct_change: float
    red_ratio: float
    quote_count: int
    total_amount: float


@dataclass(frozen=True)
class AgentAnalysisTrigger:
    kind: str
    id: str
    title: str
    reason: str
    dedupe_key: str


@dataclass
class BuySignalCandidate:
    """买入信号候选（poll 层输出，不是最终信号）"""
    stock_code: str
    stock_name: str
    price: float
    is_candidate: bool
    matched_conditions: list[str]
    entry_zone: tuple[float, float] | None = None
    stop_loss: float | None = None
    claim_basis: str = ""
    odds_analysis: dict | None = None


DEFAULT_AGENT_ANALYSIS_SCHEDULE = [
    {
        "id": "open_auction",
        "time": "09:26",
        "name": "集合竞价后",
        "focus": "竞价方向（高开/低开/平开），方向强弱对比，建立今天核心假设，更新 daily_state",
        "prompt": "cron_opening",
    },
    {
        "id": "open_confirm",
        "time": "09:45",
        "name": "开盘15分钟确认",
        "focus": "9:30假设是否成立？开盘15分钟内指数和方向是否按预期走？若不成立，修正假设",
        "prompt": "cron_open_confirm",
    },
    {
        "id": "morning_confirm",
        "time": "10:00",
        "name": "10点确认",
        "focus": "30分钟后，今天基调基本确定。是强修复/弱修复/分歧/防御？写出今日机会模式初筛",
        "prompt": "cron_morning_confirm",
    },
    {
        "id": "opportunity_scan",
        "time": "10:30",
        "name": "30分钟确认",
        "focus": "基于早盘走势，7大机会模式逐一检查，给出「今日最有希望触发机会的3-5只标的」",
        "prompt": "cron_opportunity_scan",
    },
    {
        "id": "noon_review",
        "time": "11:20",
        "name": "上午收盘前",
        "focus": "上午定性 + 午后预案。\"如果下午延续上午，该做什么？如果下午反转，该做什么？\"",
        "prompt": "cron_noon_review",
    },
    {
        "id": "afternoon_risk",
        "time": "13:10",
        "name": "午后风险窗口",
        "focus": "验证午后只看不买纪律，检查持仓是否触发风控，识别午后冲高回落风险",
        "prompt": "cron_afternoon_risk",
    },
    {
        "id": "mid_afternoon",
        "time": "14:00",
        "name": "午盘监控",
        "focus": "对比上午预期和下午实际走势，决定是否需要尾盘调整",
        "prompt": "cron_midday",
    },
    {
        "id": "tail_condition",
        "time": "14:55",
        "name": "尾盘条件单",
        "focus": "是否触发尾盘买入/卖出/尾盘杀风险？今日持仓怎么过夜？",
        "prompt": "cron_tail_condition",
    },
    {
        "id": "closing_review",
        "time": "15:20",
        "name": "收盘复盘",
        "focus": "全天观点演进回顾，更新 daily_state + strategy_pack，写复盘报告",
        "prompt": "cron_closing",
    },
]


def parse_price_zone(value: object) -> tuple[float, float] | None:
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
    text = str(code or "").strip().upper()
    match = re.fullmatch(r"(\d{6})(?:\.(?:SH|SZ))?", text)
    return match.group(1) if match else text


def _quotes_by_code(quote_snapshot: dict) -> dict[str, dict]:
    quotes: dict[str, dict] = {}
    for quote in quote_snapshot.get("quotes", []) or []:
        secid = quote.get("secid")
        if secid:
            quotes[str(secid)] = quote
        if quote.get("code"):
            quotes.setdefault(_pure_stock_code(quote.get("code")), quote)
    return quotes


def _quote_for_stock(quotes: dict[str, dict], code: object) -> dict | None:
    secid = stock_code_to_secid(str(code or ""))
    if secid and secid in quotes:
        return quotes[secid]
    return quotes.get(_pure_stock_code(code))


def _quotes_by_label(quote_snapshot: dict) -> dict[str, dict]:
    quotes: dict[str, dict] = {}
    for quote in quote_snapshot.get("quotes", []) or []:
        for key in (quote.get("label"), quote.get("name")):
            if key:
                quotes[str(key)] = quote
    return quotes


def _format_zone(zone: tuple[float, float]) -> str:
    low, high = zone
    if low == high:
        return f"{low:g}"
    return f"{low:g}-{high:g}"


def evaluate_position_alerts(
    config: MonitorConfig,
    quote_snapshot: dict,
) -> list[RuleAlert]:
    quotes = _quotes_by_code(quote_snapshot)
    alerts: list[RuleAlert] = []
    seen: set[tuple[str, str, str]] = set()

    # ── 加载 entry_points 用于丰富提醒消息 ──
    def _norm_code(raw: str) -> str:
        c = raw.lower().strip().replace('.sh', '').replace('.sz', '')
        if c.startswith('sh') or c.startswith('sz'):
            c = c[2:]
        return c

    entry_by_code: dict[str, dict] = {}
    for ep in config.strategy_pack.get("entry_points", []):
        ep_code = _norm_code(str(ep.get("code", "")))
        if ep_code:
            entry_by_code[ep_code] = ep

    def _enrich_summary(action_label: str, row: dict, trigger: str,
                         latest: float, pct_change: str) -> str:
        """Build alert message with entry_points enrichment."""
        code = str(row.get("code", ""))
        name = str(row.get("name", ""))
        norm = _norm_code(code)
        entry = entry_by_code.get(norm)
        risk_zone_raw = row.get("risk_zone") or row.get("risk_line", "")

        parts = [f"【{action_label}】{name}({code}) {latest:g}（{pct_change}%）{trigger}"]

        if entry:
            odds = entry.get("odds_analysis", "")
            cb_id = entry.get("claim_basis", "")
            if odds:
                # Truncate long odds_analysis to fit WeChat messages
                odds_short = odds[:120] + ("…" if len(odds) > 120 else "")
                parts.append(f"赔率：{odds_short}")
            if cb_id:
                parts.append(f"参考：{cb_id}")

        if risk_zone_raw:
            parts.append(f"止损：{risk_zone_raw}")

        return " | ".join(parts)

    for row in position_rows(config):
        code = str(row.get("code", ""))
        quote = _quote_for_stock(quotes, code)
        latest = _to_float((quote or {}).get("latest"))
        if latest is None:
            continue

        name = str(row.get("name") or (quote or {}).get("name") or "")
        pct_change = (quote or {}).get("pct_change", "")

        # ── 减仓观察 ──
        reduce_zone = parse_price_zone(row.get("reduce_zone"))
        if reduce_zone and reduce_zone[0] <= latest <= reduce_zone[1]:
            trigger = f"进入预设减仓区{_format_zone(reduce_zone)}"
            key = (code, "减仓观察", trigger)
            if key in seen:
                continue
            seen.add(key)
            summary = _enrich_summary("减仓观察", row, trigger, latest, pct_change)
            alerts.append(
                RuleAlert(
                    action="减仓观察",
                    stock_code=code,
                    stock_name=name,
                    price=latest,
                    trigger=trigger,
                    severity="observe",
                    summary=summary,
                )
            )

        # ── 风控观察 ──
        risk_zone = parse_price_zone(row.get("risk_zone") or row.get("risk_line"))
        if risk_zone and latest <= risk_zone[1]:
            trigger = f"触及或跌破风险线{_format_zone(risk_zone)}"
            key = (code, "风控观察", trigger)
            if key in seen:
                continue
            seen.add(key)
            summary = _enrich_summary("风控观察", row, trigger, latest, pct_change)
            alerts.append(
                RuleAlert(
                    action="风控观察",
                    stock_code=code,
                    stock_name=name,
                    price=latest,
                    trigger=trigger,
                    severity="risk",
                    summary=summary,
                )
            )

        # ── 加仓观察 ──
        add_zone = parse_price_zone(row.get("add_zone"))
        if add_zone and add_zone[0] <= latest <= add_zone[1]:
            trigger = f"进入预设加仓区{_format_zone(add_zone)}"
            key = (code, "加仓观察", trigger)
            if key in seen:
                continue
            seen.add(key)
            summary = _enrich_summary("机会触发", row, trigger, latest, pct_change)
            alerts.append(
                RuleAlert(
                    action="加仓观察",
                    stock_code=code,
                    stock_name=name,
                    price=latest,
                    trigger=trigger,
                    severity="opportunity",
                    summary=summary,
                )
            )

    return alerts


def evaluate_buy_signal_candidates(
    config: MonitorConfig,
    quote_snapshot: dict,
) -> list[BuySignalCandidate]:
    """基于本地 SQLite K线 + 实时行情做买入信号候选筛选。

    判断"这只票是否值得 LLM 做深度买入确认"。
    不判断"能不能买"，只判断"该不该分析"。
    """
    quotes = _quotes_by_code(quote_snapshot)
    candidates: list[BuySignalCandidate] = []
    seen_codes: set[str] = set()

    # ── 加载 entry_points 和 add_zone 配置 ──
    def _norm_code(raw: str) -> str:
        c = raw.lower().strip().replace(".sh", "").replace(".sz", "")
        if c.startswith("sh") or c.startswith("sz"):
            c = c[2:]
        return c

    entry_by_code: dict[str, dict] = {}
    for ep in config.strategy_pack.get("entry_points", []):
        ep_code = _norm_code(str(ep.get("code", "")))
        if ep_code:
            entry_by_code[ep_code] = ep

    # 从 positions 中提取 add_zone
    for account in config.positions.get("accounts", []):
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

    # 从 watchlist 中提取 entry_zone（如果 entry_points 没有覆盖）
    for theme in config.watchlist.get("themes", []):
        for stock in theme.get("stocks", []):
            stock_code = _norm_code(str(stock.get("code", "")))
            if stock_code and stock_code not in entry_by_code:
                # 从标准字段 entry_zone.price_range 提取介入区间
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

    # ── 遍历所有有介入区间的标的 ──
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
        # 价格偏离度保护：现价 > 区间上限×1.05 时强制判定为"偏离，不触发"
        price_deviated = latest > zone[1] * 1.05
        if price_deviated:
            price_in_zone = False
            logger.info(
                f"buy_signal_deviation: {name}({code_norm}) "
                f"price={latest:.1f} > zone_upper={zone[1]:.1f}×1.05={zone[1]*1.05:.1f} → 偏离不触发"
            )
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
            pass  # K线读取失败，跳过量价条件

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


def evaluate_buy_signal_alerts(
    config: MonitorConfig,
    quote_snapshot: dict,
) -> list[RuleAlert]:
    """将买入信号候选转换为 RuleAlert，供现有 alert 管道处理。"""
    candidates = evaluate_buy_signal_candidates(config, quote_snapshot)
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


def _is_market_closed(value: datetime | None = None) -> bool:
    """Return True if A-share market has closed for the day (after 15:00)."""
    if value is None:
        value = now_cn()
    local = value.astimezone(CN_TZ)
    if not is_a_share_trading_day(local):
        return False
    return local.time() >= time(15, 0)


def _evaluate_generic_index_rule(
    rule: dict, latest: float, index_name: str, quote: dict | None,
    *, current_time: datetime | None = None,
) -> RuleAlert | None:
    """Evaluate a single index rule using the generic trigger_condition format.

    ``close_below`` / ``close_above`` are only evaluated after 15:00.
    ``intraday_below`` / ``intraday_above`` are evaluated during trading hours.
    """
    trigger_condition = rule.get("trigger_condition")
    threshold = _to_float(rule.get("threshold"))

    if not trigger_condition or threshold is None:
        return None

    is_close_rule = trigger_condition in ("close_below", "close_above")
    is_intraday_rule = trigger_condition in ("intraday_below", "intraday_above")

    if is_close_rule and not _is_market_closed(current_time):
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
        summary = (
            f"{action}：{index_name} 当前点位={latest:g}；{trigger}。"
            f"{interpretation}"
        )
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


def _evaluate_legacy_index_rule(
    rule: dict, latest: float, index_name: str, quote: dict | None
) -> RuleAlert | None:
    """Backward-compatible evaluation for legacy trend_defense / weak_close_level format."""
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


def evaluate_market_alerts(
    config: MonitorConfig,
    quote_snapshot: dict,
    *,
    current_time: datetime | None = None,
) -> list[RuleAlert]:
    alerts: list[RuleAlert] = []
    quotes = _quotes_by_label(quote_snapshot)
    index_rules = (
        config.strategy_pack.get("market_framework", {}).get("index_rules", [])
        or []
    )

    for rule in index_rules:
        index_name = str(rule.get("index", ""))
        quote = quotes.get(index_name)
        latest = _to_float((quote or {}).get("latest"))
        if latest is None:
            continue

        # Try generic format first, then fall back to legacy format
        alert = _evaluate_generic_index_rule(rule, latest, index_name, quote, current_time=current_time)
        if alert is None:
            alert = _evaluate_legacy_index_rule(rule, latest, index_name, quote)
        if alert is not None:
            alerts.append(alert)

    return alerts


def compute_sector_strength(
    config: MonitorConfig,
    quote_snapshot: dict,
) -> list[SectorStrength]:
    quotes = _quotes_by_code(quote_snapshot)
    strengths: list[SectorStrength] = []

    for group in config.strategy_pack.get("sector_groups", []) or []:
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


def _aggregate_sector_strength(
    strengths: dict[str, SectorStrength],
    group_ids: list[str],
) -> SectorStrength | None:
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


def evaluate_sector_rotation_alerts(
    config: MonitorConfig,
    quote_snapshot: dict,
) -> list[RuleAlert]:
    strengths = {item.id: item for item in compute_sector_strength(config, quote_snapshot)}
    alerts: list[RuleAlert] = []

    for rule in config.strategy_pack.get("sector_rotation_rules", []) or []:
        offensive = _aggregate_sector_strength(
            strengths, rule.get("offensive_groups", []) or []
        )
        defensive = _aggregate_sector_strength(
            strengths, rule.get("defensive_groups", []) or []
        )
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


def evaluate_monitor_alerts(
    config: MonitorConfig,
    quote_snapshot: dict,
    *,
    current_time: datetime | None = None,
) -> list[RuleAlert]:
    return (
        evaluate_market_alerts(config, quote_snapshot, current_time=current_time)
        + evaluate_sector_rotation_alerts(config, quote_snapshot)
        + evaluate_position_alerts(config, quote_snapshot)
        + evaluate_buy_signal_alerts(config, quote_snapshot)
    )


def format_alerts_message(
    alerts: list[RuleAlert],
    value: datetime,
    quote_snapshot: dict,
) -> str:
    if not alerts:
        return ""

    lines = [
        "[Hermes股票监控提醒]",
        f"时间：{value.astimezone(CN_TZ).strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"数据源：{quote_snapshot.get('source', 'unknown')}",
        f"行情请求耗时：{quote_snapshot.get('elapsed_ms')} ms",
        "",
        "触发信号：",
    ]
    for alert in alerts:
        lines.append(f"- {alert.summary}")

    lines.extend(
        [
            "",
            "处理原则：这是规则触发的观察提醒，不是无条件买卖指令；执行前仍需确认指数、板块扩散和分时承接。",
        ]
    )
    return "\n".join(lines)


def alert_fingerprint(alert: RuleAlert) -> str:
    return "|".join(
        [
            alert.action,
            alert.stock_code,
            alert.stock_name,
            alert.trigger,
        ]
    )


def load_monitor_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save_monitor_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _parse_state_time(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=CN_TZ)
    return parsed.astimezone(CN_TZ)


def _action_to_dedupe_type(action: str) -> str:
    """Map alert action string to a dedupe_by_type key.

    Mapping rules (aligned with yaml-patterns-20260604.md):
        - 风控/风险 → risk_alert
        - 减仓       → reduce_alert
        - 进攻/防御/指数/回流/轮动/板块 → sector_rotation
        - 其他       → default (falls back to global dedupe_minutes)
    """
    if "风控" in action or "风险" in action:
        return "risk_alert"
    if "减仓" in action:
        return "reduce_alert"
    if any(kw in action for kw in ("进攻", "防御", "指数", "回流", "轮动", "板块")):
        return "sector_rotation"
    return "default"


def filter_new_alerts(
    alerts: list[RuleAlert],
    state: dict,
    value: datetime,
    *,
    dedupe_minutes: int,
    dedupe_by_type: dict | None = None,
) -> list[RuleAlert]:
    if dedupe_minutes <= 0:
        return alerts

    history = state.get("alert_history", {})
    if not isinstance(history, dict):
        history = {}
    current = value.astimezone(CN_TZ)
    # Same-day dedupe: {date: {code_action: price}}
    daily_emitted = state.get("daily_emitted", {})
    today_str = current.strftime("%Y-%m-%d")

    fresh: list[RuleAlert] = []
    for alert in alerts:
        fp = alert_fingerprint(alert)
        last_entry = history.get(fp)

        # Determine per-type dedupe minutes (used by both same-day and history dedupe)
        dedupe_type = _action_to_dedupe_type(alert.action)
        type_config = (dedupe_by_type or {}).get(dedupe_type, {})
        effective_minutes = type_config.get("dedupe_minutes", dedupe_minutes)
        breakthrough_pct = type_config.get("breakthrough_if_price_change_pct", 0)

        # Same-day dedupe for reduce/risk alerts on same stock
        # 只在时间间隔 < effective_minutes 时生效（避免与 history-based dedupe 冲突）
        code_action_key = f"{alert.stock_code}_{alert.action}"
        daily_key = (daily_emitted.get(today_str, {}) if isinstance(daily_emitted, dict) else {})
        same_day_price = daily_key.get(code_action_key)

        if same_day_price is not None and alert.action in ("减仓观察", "风控观察"):
            # 检查 history 中的上次时间，确认是否仍在 dedupe 窗口内
            if isinstance(last_entry, dict):
                last_time = _parse_state_time(last_entry.get("time"))
                if last_time is not None:
                    elapsed_minutes = (current - last_time).total_seconds() / 60
                    if elapsed_minutes < effective_minutes:
                        pct_change = abs((alert.price - same_day_price) / same_day_price) * 100 if same_day_price > 0 else 0
                        if pct_change < 2.0:
                            # Same stock + same action already fired today within dedupe window, and price barely moved → suppress
                            continue

        if last_entry is None:
            fresh.append(alert)
            continue

        # Backward compat: old format was plain ISO string, new format is dict
        if isinstance(last_entry, str):
            last_time = _parse_state_time(last_entry)
            last_price = None
        else:
            last_time = _parse_state_time(last_entry.get("time"))
            last_price = last_entry.get("price")

        if last_time is None:
            fresh.append(alert)
            continue

        elapsed_minutes = (current - last_time).total_seconds() / 60
        if elapsed_minutes >= effective_minutes:
            fresh.append(alert)
            continue

        # Breakthrough: price changed significantly since last alert
        if breakthrough_pct > 0 and last_price is not None and last_price > 0:
            pct_change = abs((alert.price - last_price) / last_price) * 100
            if pct_change >= breakthrough_pct:
                fresh.append(alert)
                continue

    return fresh


def record_emitted_alerts(
    state: dict,
    alerts: list[RuleAlert],
    value: datetime,
) -> None:
    history = state.setdefault("alert_history", {})
    daily = state.setdefault("daily_emitted", {})
    current = value.astimezone(CN_TZ).isoformat()
    today_str = value.astimezone(CN_TZ).strftime("%Y-%m-%d")
    today_entry = daily.setdefault(today_str, {})
    for alert in alerts:
        history[alert_fingerprint(alert)] = {
            "time": current,
            "price": alert.price,
        }
        # Record for same-day dedupe
        code_action_key = f"{alert.stock_code}_{alert.action}"
        today_entry[code_action_key] = alert.price


def alert_to_log_entry(
    alert: RuleAlert,
    value: datetime,
    *,
    status: str,
) -> dict:
    local = value.astimezone(CN_TZ)
    return {
        "date": local.strftime("%Y-%m-%d"),
        "time": local.isoformat(),
        "status": status,
        "fingerprint": alert_fingerprint(alert),
        "action": alert.action,
        "stock_code": alert.stock_code,
        "stock_name": alert.stock_name,
        "price": alert.price,
        "severity": alert.severity,
        "trigger": alert.trigger,
        "summary": alert.summary,
    }


def record_alert_decision_log(
    state: dict,
    alerts: list[RuleAlert],
    emitted_alerts: list[RuleAlert],
    value: datetime,
) -> None:
    emitted_keys = {alert_fingerprint(alert) for alert in emitted_alerts}
    log = state.setdefault("alert_decision_log", [])
    for alert in alerts:
        status = "emitted" if alert_fingerprint(alert) in emitted_keys else "suppressed"
        log.append(alert_to_log_entry(alert, value, status=status))


def update_sector_signal_counts(
    state: dict,
    alerts: list[RuleAlert],
    value: datetime,
) -> None:
    sector_alerts = [alert for alert in alerts if alert.stock_name == "板块强弱"]
    if not sector_alerts:
        state["sector_signal_counts"] = {}
        return

    previous = state.get("sector_signal_counts", {})
    if not isinstance(previous, dict):
        previous = {}
    current_counts: dict[str, dict] = {}
    current_time = value.astimezone(CN_TZ).isoformat()
    for alert in sector_alerts:
        key = alert_fingerprint(alert)
        prior = previous.get(key, {})
        count = int(prior.get("count", 0)) + 1 if isinstance(prior, dict) else 1
        current_counts[key] = {
            "action": alert.action,
            "count": count,
            "last_seen_at": current_time,
        }
    state["sector_signal_counts"] = current_counts


def update_market_state(
    state: dict,
    alerts: list[RuleAlert],
    quote_snapshot: dict,
    value: datetime,
) -> None:
    state["last_market_state"] = {
        "time": value.astimezone(CN_TZ).isoformat(),
        "quote_count": len(quote_snapshot.get("quotes", []) or []),
        "alert_count": len(alerts),
        "risk_count": sum(1 for alert in alerts if alert.severity == "risk"),
        "observe_count": sum(1 for alert in alerts if alert.severity == "observe"),
        "sector_actions": [
            alert.action for alert in alerts if alert.stock_name == "板块强弱"
        ],
    }


def agent_analysis_schedule_rows(config: MonitorConfig) -> list[dict]:
    rows = config.strategy_pack.get("agent_analysis_schedule")
    if not rows:
        rows = DEFAULT_AGENT_ANALYSIS_SCHEDULE
    return [dict(row) for row in rows if isinstance(row, dict)]


def _hhmm(value: datetime) -> str:
    return value.astimezone(CN_TZ).strftime("%H:%M")


def _agent_history(state: dict) -> dict:
    history = state.get("agent_analysis_history", {})
    return history if isinstance(history, dict) else {}


def _agent_dedupe_key_for_schedule(row: dict, value: datetime) -> str:
    date_text = value.astimezone(CN_TZ).strftime("%Y-%m-%d")
    return f"scheduled:{row.get('id', row.get('time', 'unknown'))}:{date_text}"


def find_agent_analysis_trigger(
    config: MonitorConfig,
    state: dict,
    value: datetime,
    alerts: list[RuleAlert],
) -> AgentAnalysisTrigger | None:
    history = _agent_history(state)

    # ── 买入信号候选优先 ──
    buy_candidates = [a for a in alerts if a.action == "机会候选"]
    if buy_candidates:
        # 价格分桶 + 4小时冷却窗口去重（Phase 4）
        try:
            from qing_investment.agent.tools.daily_state import (
                load_daily_state,
                should_trigger_agent_for_candidate,
            )
            daily_state = load_daily_state()
            # 只允许至少有一个候选通过去重检查时才触发
            triggerable = []
            for alert in buy_candidates:
                if should_trigger_agent_for_candidate(
                    daily_state, alert.stock_code, alert.price or 0, now=value
                ):
                    triggerable.append(alert)
            if triggerable:
                codes = ",".join(dict.fromkeys(a.stock_code for a in triggerable))
                dedupe_key = f"buy_candidate:{value.astimezone(CN_TZ).strftime('%Y-%m-%d')}:{codes}"
                if dedupe_key not in history:
                    names = "、".join(dict.fromkeys(a.stock_name for a in triggerable))
                    return AgentAnalysisTrigger(
                        kind="buy_signal_candidate",
                        id="buy_signal_candidate",
                        title="买入信号候选触发",
                        reason=f"{names}({codes}) 满足买入条件，需要深度确认",
                        dedupe_key=dedupe_key,
                    )
            # 所有买入候选都已被去重 → 不再 fallback 到 event trigger
            return None
        except Exception:
            # daily_state 去重失败时 fallback 到原有逻辑
            codes = ",".join(dict.fromkeys(a.stock_code for a in buy_candidates))
            dedupe_key = f"buy_candidate:{value.astimezone(CN_TZ).strftime('%Y-%m-%d')}:{codes}"
            if dedupe_key not in history:
                names = "、".join(dict.fromkeys(a.stock_name for a in buy_candidates))
                return AgentAnalysisTrigger(
                    kind="buy_signal_candidate",
                    id="buy_signal_candidate",
                    title="买入信号候选触发",
                    reason=f"{names}({codes}) 满足买入条件，需要深度确认",
                    dedupe_key=dedupe_key,
                )
            # 买入候选已去重 → 不再 fallback 到 event trigger
            return None

    if alerts:
        actions = "、".join(dict.fromkeys(alert.action for alert in alerts))
        fingerprints = ",".join(alert_fingerprint(alert) for alert in alerts)
        dedupe_key = (
            f"event:{value.astimezone(CN_TZ).strftime('%Y-%m-%d')}:{fingerprints}"
        )
        if dedupe_key not in history:
            return AgentAnalysisTrigger(
                kind="event",
                id="rule_alert",
                title="规则触发",
                reason=f"出现新的规则信号：{actions}",
                dedupe_key=dedupe_key,
            )

    current_hhmm = _hhmm(value)
    for row in agent_analysis_schedule_rows(config):
        if str(row.get("time", "")) != current_hhmm:
            continue
        dedupe_key = _agent_dedupe_key_for_schedule(row, value)
        if dedupe_key in history:
            return None
        return AgentAnalysisTrigger(
            kind="scheduled",
            id=str(row.get("id", current_hhmm)),
            title=str(row.get("name", current_hhmm)),
            reason=str(row.get("focus", "")),
            dedupe_key=dedupe_key,
        )
    return None


def find_any_agent_analysis_trigger(
    config: MonitorConfig,
    state: dict,
    value: datetime,
    alerts: list[RuleAlert],
) -> AgentAnalysisTrigger | None:
    """Always return a scheduled trigger if one exists for current time,
    regardless of whether it's in agent_analysis_schedule.

    This bypasses the time-restriction so cron jobs can run at any time.
    """
    history = _agent_history(state)

    # ── 买入信号候选优先 ──
    buy_candidates = [a for a in alerts if a.action == "机会候选"]
    if buy_candidates:
        # 价格分桶 + 4小时冷却窗口去重（Phase 4）
        try:
            from qing_investment.agent.tools.daily_state import (
                load_daily_state,
                should_trigger_agent_for_candidate,
            )
            daily_state = load_daily_state()
            triggerable = []
            for alert in buy_candidates:
                if should_trigger_agent_for_candidate(
                    daily_state, alert.stock_code, alert.price or 0, now=value
                ):
                    triggerable.append(alert)
            if triggerable:
                codes = ",".join(dict.fromkeys(a.stock_code for a in triggerable))
                dedupe_key = f"buy_candidate:{value.astimezone(CN_TZ).strftime('%Y-%m-%d')}:{codes}"
                if dedupe_key not in history:
                    names = "、".join(dict.fromkeys(a.stock_name for a in triggerable))
                    return AgentAnalysisTrigger(
                        kind="buy_signal_candidate",
                        id="buy_signal_candidate",
                        title="买入信号候选触发",
                        reason=f"{names}({codes}) 满足买入条件，需要深度确认",
                        dedupe_key=dedupe_key,
                    )
            # 所有买入候选都已被去重 → 不再 fallback 到 event trigger
            return None
        except Exception:
            codes = ",".join(dict.fromkeys(a.stock_code for a in buy_candidates))
            dedupe_key = f"buy_candidate:{value.astimezone(CN_TZ).strftime('%Y-%m-%d')}:{codes}"
            if dedupe_key not in history:
                names = "、".join(dict.fromkeys(a.stock_name for a in buy_candidates))
                return AgentAnalysisTrigger(
                    kind="buy_signal_candidate",
                    id="buy_signal_candidate",
                    title="买入信号候选触发",
                    reason=f"{names}({codes}) 满足买入条件，需要深度确认",
                    dedupe_key=dedupe_key,
                )
            # 买入候选已去重 → 不再 fallback 到 event trigger
            return None

    # First check event-driven triggers (alerts)
    if alerts:
        actions = "、".join(dict.fromkeys(alert.action for alert in alerts))
        fingerprints = ",".join(alert_fingerprint(alert) for alert in alerts)
        dedupe_key = (
            f"event:{value.astimezone(CN_TZ).strftime('%Y-%m-%d')}:{fingerprints}"
        )
        if dedupe_key not in history:
            return AgentAnalysisTrigger(
                kind="event",
                id="rule_alert",
                title="规则触发",
                reason=f"出现新的规则信号：{actions}",
                dedupe_key=dedupe_key,
            )

    # Build trigger from current time — no schedule restriction
    current_hhmm = _hhmm(value)

    # Try to find matching row in schedule for metadata
    schedule_rows = agent_analysis_schedule_rows(config)
    current_row = None
    for row in schedule_rows:
        if str(row.get("time", "")) == current_hhmm:
            current_row = row
            break

    # If matched scheduled row, use its metadata
    if current_row:
        dedupe_key = _agent_dedupe_key_for_schedule(current_row, value)
        if dedupe_key in history:
            return None
        return AgentAnalysisTrigger(
            kind="scheduled",
            id=str(current_row.get("id", current_hhmm)),
            title=str(current_row.get("name", current_hhmm)),
            reason=str(current_row.get("focus", "")),
            dedupe_key=dedupe_key,
        )

    # No scheduled row for this time — create a generic trigger
    dedupe_key = f"scheduled:any:{value.astimezone(CN_TZ).strftime('%Y-%m-%d')}:{current_hhmm}"
    if dedupe_key in history:
        return None
    return AgentAnalysisTrigger(
        kind="scheduled",
        id=f"any_{current_hhmm}",
        title=f"{current_hhmm} 定时分析",
        reason="定时触发分析",
        dedupe_key=dedupe_key,
    )


def record_agent_analysis_trigger(
    state: dict,
    trigger: AgentAnalysisTrigger,
    value: datetime,
) -> None:
    history = state.setdefault("agent_analysis_history", {})
    history[trigger.dedupe_key] = {
        "time": value.astimezone(CN_TZ).isoformat(),
        "kind": trigger.kind,
        "id": trigger.id,
        "title": trigger.title,
        "reason": trigger.reason,
    }


def is_scheduled_agent_analysis_time(config: MonitorConfig, value: datetime) -> bool:
    current_hhmm = _hhmm(value)
    return any(str(row.get("time", "")) == current_hhmm for row in agent_analysis_schedule_rows(config))


# ──────────────────────────────────────────────
# Phase 1: 昨日特征摘要系统
# ──────────────────────────────────────────────

SUMMARY_CONFIG_DIR = DEFAULT_CONFIG_DIR
SUMMARY_FILENAME = "daily_review_summary.json"

# 字段清单（设计文档 §1.1）
SUMMARY_FIELDS_BASIC = ["close", "open", "high", "low", "change_pct", "volume", "amount"]
SUMMARY_FIELDS_BOARD = ["is_limit_up", "consecutive_limit_ups", "weak_board",
                        "board_open_count", "first_board_time", "board_seal_ratio",
                        "board_quality"]
SUMMARY_FIELDS_TECH = ["turnover_rate", "amplitude", "volume_ratio",
                       "vs_ma5", "vs_ma10", "near5d_return"]
SUMMARY_FIELDS_DETAIL = ["intraday_pattern", "sector_avg_change",
                         "dragon_tiger_net", "entry_zone_distance", "entry_zone_range",
                         "dt_seat_type", "dt_top_buy_behavior", "dt_is_pure_hot_money"]
SUMMARY_FIELDS_COST = ["avg_cost", "unrealized_pct", "cost_protection_line"]
ALL_SUMMARY_FIELDS = (SUMMARY_FIELDS_BASIC + SUMMARY_FIELDS_BOARD + SUMMARY_FIELDS_TECH
                      + SUMMARY_FIELDS_DETAIL + SUMMARY_FIELDS_COST)

# 涨停判定阈值（主板10%，创业板/科创板20% — 但用户仅主板可交易）
LIMIT_UP_THRESHOLD = 9.5  # 涨停临界%

# 通用计算函数
# 为兼容性，不在模块最外层定义，放在函数内部


def _summary_file_path(config_dir: Path | None = None) -> Path:
    """返回 summary 文件路径。"""
    return (config_dir or SUMMARY_CONFIG_DIR) / SUMMARY_FILENAME


def _compute_vs_ma(close: float, klines: list[dict], ma_days: int) -> float | None:
    """计算收盘价相对 MA 的位置百分比。"""
    closes = [d.get("close", 0) for d in klines[-ma_days:] if d.get("close")]
    if len(closes) < ma_days:
        return None
    ma = sum(closes) / len(closes)
    return round((close - ma) / ma * 100, 1) if ma else None


def _compute_near5d_return(klines: list[dict]) -> float | None:
    """计算近5个交易日的累计涨跌幅。"""
    if len(klines) < 2:
        return None
    # 取最近5个有收盘价的交易日
    closes = [d.get("close") for d in klines[-6:] if d.get("close") is not None]
    if len(closes) < 2:
        return None
    return round((closes[-1] - closes[0]) / closes[0] * 100, 1)


def _compute_volume_ratio(today_volume: float, klines: list[dict]) -> float | None:
    """计算今日量/近5日均量的比值。"""
    vols = [d.get("volume", 0) for d in klines[-6:-1] if d.get("volume")]
    if not vols:
        return None
    avg_5d = sum(vols) / len(vols)
    return round(today_volume / avg_5d, 2) if avg_5d else None


def _check_entry_zone_distance(code: str, close: float, config: MonitorConfig) -> dict:
    """判断收盘价距 entry_zone 的距离。"""
    result = {"entry_zone_distance": None, "entry_zone_range": None}

    # 从 strategy_pack entry_points 查找
    for ep in config.strategy_pack.get("entry_points", []):
        ep_code = _pure_stock_code(str(ep.get("code", "")))
        if ep_code == _pure_stock_code(code):
            zone_raw = ep.get("entry_zone") or ""
            zone = parse_price_zone(zone_raw)
            if zone:
                result["entry_zone_range"] = _format_zone(zone)
                if close < zone[0]:
                    result["entry_zone_distance"] = "below"
                elif close <= zone[1]:
                    result["entry_zone_distance"] = "in"
                else:
                    result["entry_zone_distance"] = "above"
            return result

    # 从 watchlist 查找
    for theme in config.watchlist.get("themes", []):
        for stock in theme.get("stocks", []):
            if _pure_stock_code(str(stock.get("code", ""))) == _pure_stock_code(code):
                ez = stock.get("entry_zone", {}) or {}
                zone = parse_price_zone(ez.get("price_range", ""))
                if zone:
                    result["entry_zone_range"] = _format_zone(zone)
                    if close < zone[0]:
                        result["entry_zone_distance"] = "below"
                    elif close <= zone[1]:
                        result["entry_zone_distance"] = "in"
                    else:
                        result["entry_zone_distance"] = "above"
                return result

    return result


# ── 龙虎榜数据采集（akshare 东方财富接口）──

_SEAT_TYPE_KEYWORDS = {
    "深股通专用": "外资",
    "沪股通专用": "外资",
    "机构专用": "机构",
    "中信证券股份有限公司": "游资",
    "中国国际金融股份有限公司": "量化",
    "量化": "量化",
}


def _classify_seat_type(name: str) -> str:
    """根据营业部名称判断席位性质。"""
    for keyword, seat_type in _SEAT_TYPE_KEYWORDS.items():
        if keyword in name:
            return seat_type
    # 默认游资（非机构/外资席位）
    return "游资"


def _classify_top_buy_behavior(
    df_buy: "pd.DataFrame",
    df_sell: "pd.DataFrame",
) -> str:
    """判断买一席位的次日行为倾向。

    买一的行为：
    - 锁仓：买一金额 >> 卖一金额，且净额大额为正
    - 做T：买一出现在卖出榜（买卖双向操作）
    - 出局：卖一金额大，且买一不在买入榜前5
    - 加仓：买一金额远超其他席位的卖出
    """
    try:
        top_buy_name = df_buy.iloc[0]["交易营业部名称"]
        top_buy_net = float(df_buy.iloc[0]["净额"])
        top_sell_net = float(df_sell.iloc[0]["净额"]) if not df_sell.empty else 0

        # 检查买一是否也出现在卖出榜（做T）
        buy_names = set(df_buy["交易营业部名称"].tolist())
        sell_names = set(df_sell["交易营业部名称"].tolist())
        overlap = buy_names & sell_names

        if top_buy_name in overlap:
            # 买一同时买卖 → 做T
            return "做T"
        elif top_buy_net > abs(top_sell_net) * 3:
            # 买一净额是卖一净额的3倍以上 → 抢筹锁仓
            return "锁仓"
        elif top_buy_net > abs(top_sell_net) * 1.5:
            return "加仓"
        elif top_buy_net < abs(top_sell_net) * 0.5:
            return "出局"
        else:
            return "混合"
    except Exception:
        return "unknown"


def _assess_board_quality(df_buy: "pd.DataFrame", df_sell: "pd.DataFrame") -> str:
    """评估封板质量。"""
    try:
        # 净买入总额
        total_buy = float(df_buy["净额"].sum()) if "净额" in df_buy.columns else 0
        total_sell = float(df_sell["净额"].sum()) if "净额" in df_sell.columns else 0
        net = total_buy  # 买入榜净额之和

        if net > 0 and net > abs(total_sell) * 2:
            return "strong"
        elif net > 0:
            return "medium"
        else:
            return "weak"
    except Exception:
        return "NA"


def _fetch_dragon_tiger_data(
    code: str,
    date_str: str,
    timeout: int = 10,
) -> dict:
    """获取个股龙虎榜数据（akshare 东方财富接口）。

    Args:
        code: 6位股票代码
        date_str: 日期 "2026-06-11" 或 "20260611"
        timeout: 超时秒数

    Returns:
        dict: {
            "dragon_tiger_net": str,        # 净买入额字符串 "+1.56亿"
            "dt_seat_type": str,            # "机构+游资" | "机构" | "游资" | "量化" | "混合"
            "dt_top_buy_behavior": str,     # "锁仓" | "加仓" | "做T" | "出局" | "混合"
            "dt_is_pure_hot_money": bool,   # 是否纯游资
            "board_quality": str,           # "strong" | "medium" | "weak" | "NA"
            "_error": str,                  # 错误信息（如有）
        }
    """
    result = {
        "dragon_tiger_net": None,
        "dt_seat_type": None,
        "dt_top_buy_behavior": None,
        "dt_is_pure_hot_money": None,
        "board_quality": None,
    }

    try:
        date_compact = date_str.replace("-", "")
        import akshare as ak

        df_buy = ak.stock_lhb_stock_detail_em(symbol=code, date=date_compact, flag="买入")
        df_sell = ak.stock_lhb_stock_detail_em(symbol=code, date=date_compact, flag="卖出")

        if df_buy is None:
            result["_error"] = "当日未上榜"
            return result
        try:
            if df_buy.empty:
                result["_error"] = "当日未上榜"
                return result
        except Exception:
            pass  # 不是 DataFrame 也能接受

        # ── 净额 ──
        total_net = float(df_buy["净额"].sum())
        if abs(total_net) >= 100_000_000:
            net_str = f"{'+' if total_net >= 0 else ''}{total_net / 100_000_000:.2f}亿"
        elif abs(total_net) >= 10_000:
            net_str = f"{'+' if total_net >= 0 else ''}{total_net / 10_000:.0f}万"
        else:
            net_str = f"{total_net:.0f}"
        result["dragon_tiger_net"] = net_str

        # ── 席位类型分布 ──
        seat_types = set()
        for _, row in df_buy.iterrows():
            seat_types.add(_classify_seat_type(str(row.get("交易营业部名称", ""))))
        for _, row in df_sell.iterrows():
            seat_types.add(_classify_seat_type(str(row.get("交易营业部名称", ""))))

        seat_types.discard("游资")  # 游资是默认值，不特别标注
        if not seat_types:
            result["dt_seat_type"] = "游资"
            result["dt_is_pure_hot_money"] = True
        elif len(seat_types) == 1:
            result["dt_seat_type"] = list(seat_types)[0]
            result["dt_is_pure_hot_money"] = list(seat_types)[0] == "游资"
        else:
            result["dt_seat_type"] = "+".join(sorted(seat_types))
            result["dt_is_pure_hot_money"] = False

        # ── 买一行为 ──
        result["dt_top_buy_behavior"] = _classify_top_buy_behavior(df_buy, df_sell)

        # ── 封板质量 ──
        result["board_quality"] = _assess_board_quality(df_buy, df_sell)

    except ImportError:
        result["_error"] = "akshare not installed"
    except Exception as e:
        result["_error"] = str(e)

    return result


def _fetch_daily_dragon_tiger_board(
    date_str: str,
    timeout: int = 15,
) -> dict:
    """获取当日全市场龙虎榜总榜（akshare 东方财富接口）。

    数据源：stock_lhb_detail_em
    通常16:00-17:00发布当日数据，因此仅在 >= 16:00 时尝试获取。

    Returns:
        {
            "available": bool,
            "board": [{"code","name","net_buy","reason","pct_change","turnover_rate"}, ...],
            "fetched_at": str,
            "_error": str | None,
        }
    """
    result: dict = {
        "available": False,
        "board": [],
        "fetched_at": datetime.now(tz=CN_TZ).isoformat(),
        "_error": None,
    }

    try:
        import akshare as ak

        date_compact = date_str.replace("-", "")
        df = ak.stock_lhb_detail_em(start_date=date_compact, end_date=date_compact)

        if df is None or df.empty:
            result["_error"] = "当日龙虎榜数据未发布或为空"
            return result

        board = []
        for _, row in df.iterrows():
            net_raw = str(row.get("龙虎榜净买额", "0"))
            entry = {
                "code": str(row.get("代码", "")).strip(),
                "name": str(row.get("名称", "")),
                "net_buy": _format_net_buy_str(net_raw),
                "reason": str(row.get("上榜原因", "")),
                "pct_change": _to_float(row.get("涨跌幅")),
                "turnover_rate": _to_float(row.get("换手率")),
            }
            board.append(entry)

        result["board"] = board
        result["available"] = True
        result["_error"] = None

    except ImportError:
        result["_error"] = "akshare not installed"
    except Exception as e:
        result["_error"] = str(e)

    return result


def _filter_dragon_tiger_board(
    board: list[dict],
    config: MonitorConfig,
) -> dict:
    """对全市场龙虎榜总榜做三层交叉过滤。

    Args:
        board: _fetch_daily_dragon_tiger_board() 返回的 board list
        config: MonitorConfig

    Returns:
        {
            "watch_dt_items": [str],    # 持仓/观察池上榜标记
            "dt_nettop5": [dict],       # 全市场净买入TOP5
            "dt_sector_summary": {str: dict},  # theme_id → {total_net, stocks}
        }
    """
    result = {
        "watch_dt_items": [],
        "dt_nettop5": [],
        "dt_sector_summary": {},
    }

    if not board:
        return result

    # ── 构建持仓+观察池的 code 集合 ──
    watch_codes: set[str] = set()
    for pos in position_rows(config):
        watch_codes.add(_pure_stock_code(str(pos.get("code", ""))))
    for theme in config.watchlist.get("themes", []):
        for stock in theme.get("stocks", []):
            watch_codes.add(_pure_stock_code(str(stock.get("code", ""))))

    # ── 构建 code→theme_ids 映射 ──
    code_to_themes: dict[str, list[str]] = {}
    for theme in config.watchlist.get("themes", []):
        tid = theme.get("id", "")
        for stock in theme.get("stocks", []):
            c = _pure_stock_code(str(stock.get("code", "")))
            if c:
                code_to_themes.setdefault(c, []).append(tid)

    # ── 过滤1: 持仓/观察池上榜（按 code 去重，取净额绝对值最大的）──
    best_dt_per_code: dict[str, dict] = {}
    for entry in board:
        code = _pure_stock_code(entry.get("code", ""))
        if code not in watch_codes:
            continue
        net_abs = abs(_parse_net_buy_float(entry.get("net_buy", "0")))
        if code not in best_dt_per_code or net_abs > best_dt_per_code[code]["_net_abs"]:
            best_dt_per_code[code] = {"entry": entry, "_net_abs": net_abs}

    for code, data in best_dt_per_code.items():
        entry = data["entry"]
        result["watch_dt_items"].append(
            f"{entry.get('name','')}({code}) 净买{entry.get('net_buy','0')}"
        )

    # ── 过滤2: 全市场净买入TOP5 ──
    sorted_board = sorted(
        board,
        key=lambda x: _parse_net_buy_float(x.get("net_buy", "0")),
        reverse=True,
    )
    result["dt_nettop5"] = [
        {"code": e.get("code"), "name": e.get("name"), "net_buy": e.get("net_buy")}
        for e in sorted_board[:5]
    ]

    # ── 过滤3: 按持仓 theme 汇总 ──
    for entry in board:
        code = _pure_stock_code(entry.get("code", ""))
        themes = code_to_themes.get(code, [])
        net_float = _parse_net_buy_float(entry.get("net_buy", "0"))
        for tid in themes:
            if tid not in result["dt_sector_summary"]:
                result["dt_sector_summary"][tid] = {"total_net": 0.0, "stocks": []}
            result["dt_sector_summary"][tid]["total_net"] += net_float
            if code not in result["dt_sector_summary"][tid]["stocks"]:
                result["dt_sector_summary"][tid]["stocks"].append(code)

    # 格式化 net 为可读字符串
    for tid in result["dt_sector_summary"]:
        net = result["dt_sector_summary"][tid]["total_net"]
        if abs(net) >= 100_000_000:
            net_str = f"{'+' if net >= 0 else ''}{net / 100_000_000:.2f}亿"
        elif abs(net) >= 10_000:
            net_str = f"{'+' if net >= 0 else ''}{net / 10_000:.0f}万"
        else:
            net_str = f"{net:.0f}"
        result["dt_sector_summary"][tid]["total_net_str"] = net_str
        del result["dt_sector_summary"][tid]["total_net"]

    return result


def _parse_net_buy_float(net_str: str) -> float:
    """将龙虎榜净买额字符串转为浮动数值。"""
    try:
        text = str(net_str).strip()
        if not text or text in ("-", "--"):
            return 0.0
        sign = -1.0 if text.startswith("-") else 1.0
        text = text.lstrip("+-").strip()
        if "亿" in text:
            return sign * float(text.replace("亿", "")) * 100_000_000
        elif "万" in text:
            return sign * float(text.replace("万", "")) * 10_000
        else:
            return sign * float(text)
    except (ValueError, TypeError):
        return 0.0


def _format_net_buy_str(net_raw: str) -> str:
    """将龙虎榜净买额原始字符串格式化为 '+X.XX亿' 或 '+XXXX万' 格式。"""
    try:
        net_float = float(str(net_raw).strip().replace(",", ""))
        if abs(net_float) >= 100_000_000:
            return f"{'+' if net_float >= 0 else ''}{net_float / 100_000_000:.2f}亿"
        elif abs(net_float) >= 10_000:
            return f"{'+' if net_float >= 0 else ''}{net_float / 10_000:.0f}万"
        else:
            return f"{net_float:.0f}"
    except (ValueError, TypeError):
        return str(net_raw)


def _build_yesterday_summary(
    config: MonitorConfig,
    quote_snapshot: dict,
    state: dict,
    daily_state: dict | None = None,
) -> dict:
    """构建昨日特征摘要：从 state.json + daily_state.json + K线缓存 提取。

    产出物结构（设计文档 §1.1）：
    {
        "date": "2026-06-11",
        "market": {...},
        "positions": {
            "002409": { 18+ 字段 },
            "000636": { 18+ 字段 }
        },
        "tomorrow_scenarios": null,  # 由收盘复盘 LLM 填充
    }
    """
    date_str = datetime.now(tz=CN_TZ).strftime("%Y-%m-%d")
    quotes = _quotes_by_code(quote_snapshot)

    # ── 市场层面数据（来自 daily_state + strategy_pack）──
    market_info = {
        "stage": (daily_state or {}).get("market_stage", {}).get("phase", ""),
        "stage_detail": (daily_state or {}).get("market_stage", {}).get("detail", ""),
        "direction_priority": (daily_state or {}).get("direction_priority", []),
        "position_stance": (daily_state or {}).get("position_stance", ""),
        "key_levels": config.strategy_pack.get("key_levels", {}),
    }

    # ── 逐个持仓计算 ──
    positions_summary: dict[str, dict] = {}
    for pos in position_rows(config):
        code_raw = str(pos.get("code", ""))
        code_pure = _pure_stock_code(code_raw)
        quote = _quote_for_stock(quotes, code_pure) or _quote_for_stock(quotes, code_raw) or {}

        # ── A. 基础行情（7个字段）──
        close = _to_float(quote.get("latest"))
        open_ = _to_float(quote.get("open"))
        high = _to_float(quote.get("high"))
        low = _to_float(quote.get("low"))
        change_pct = _to_float(quote.get("pct_change"))
        volume = _to_float(quote.get("volume"))
        amount = quote.get("amount", "")

        if close is None:
            continue  # 无有效行情，跳过

        entry: dict = {
            "close": close,
            "open": open_,
            "high": high,
            "low": low,
            "change_pct": change_pct,
            "volume": volume,
            "amount": amount,
            # 默认 null 占位
            **{k: None for k in SUMMARY_FIELDS_BOARD},
            **{k: None for k in SUMMARY_FIELDS_TECH},
            **{k: None for k in SUMMARY_FIELDS_DETAIL},
            **{k: None for k in SUMMARY_FIELDS_COST},
        }

        # ── is_limit_up 从 change_pct 推导 ──
        if change_pct is not None and change_pct >= LIMIT_UP_THRESHOLD:
            entry["is_limit_up"] = True
        elif change_pct is not None:
            entry["is_limit_up"] = False

        # ── C. 技术/量价特征（从 K线缓存）──
        try:
            from qing_investment.kline_cache import get_klines
            klines = get_klines(code_pure, days=30)
            if len(klines) >= 2:
                last_kline = klines[-1]
                # turnover: 换手率（从 K线直接取）
                entry["turnover_rate"] = _to_float(last_kline.get("turnover"))
                # amplitude: 振幅 = (high - low) / pre_close * 100
                if all(v is not None for v in [high, low, close]):
                    # 用当日最高最低算振幅
                    pass  # 下面单独算
                # 从 K线 amplitude 字段（如果存在）
                entry["amplitude"] = _to_float(last_kline.get("amplitude"))

            # 量比 (今日量/近5日均量)
            if volume is not None:
                entry["volume_ratio"] = _compute_volume_ratio(volume, klines)

            # vs_ma5, vs_ma10
            if close:
                entry["vs_ma5"] = _compute_vs_ma(close, klines, 5)
                entry["vs_ma10"] = _compute_vs_ma(close, klines, 10)

            # 近5日涨幅
            entry["near5d_return"] = _compute_near5d_return(klines)

            # 若 K线缓存有振幅而上面没取到，补充
            if entry["amplitude"] is None and all(v is not None for v in [high, low]):
                entry["amplitude"] = round((high - low) / close * 100, 2)
        except Exception as e:
            logger.warning("K线缓存计算失败 %s: %s", code_pure, e)

        # ── D. entry_zone 距离 ──
        zone_info = _check_entry_zone_distance(code_pure, close, config)
        entry["entry_zone_distance"] = zone_info["entry_zone_distance"]
        entry["entry_zone_range"] = zone_info["entry_zone_range"]

        # ── 持仓成本 ──
        cost = _to_float(pos.get("cost"))
        shares = pos.get("shares", 0)
        if cost is not None and cost > 0:
            entry["avg_cost"] = cost
            if close:
                unrealized = round((close - cost) / cost * 100, 2)
                entry["unrealized_pct"] = unrealized
                # 成本保护线：浮盈>10% → 成本+5%；浮盈5-10% → 成本+3%；浮盈<5% → 成本
                if unrealized > 10:
                    entry["cost_protection_line"] = round(cost * 1.05, 2)
                elif unrealized > 5:
                    entry["cost_protection_line"] = round(cost * 1.03, 2)
                else:
                    entry["cost_protection_line"] = round(cost * 1.00, 2)

        # ── E. 龙虎榜数据（akshare 东方财富接口）──
        # 仅对涨停/连板持仓采集（非涨停不用费 API 调用）
        if entry.get("is_limit_up"):
            try:
                dt_data = _fetch_dragon_tiger_data(code_pure, date_str)
                if dt_data.get("_error") and "未上榜" in dt_data["_error"]:
                    pass  # 当日未上榜，保留 null
                else:
                    for key in ["dragon_tiger_net", "dt_seat_type",
                                "dt_top_buy_behavior", "dt_is_pure_hot_money",
                                "board_quality"]:
                        if dt_data.get(key) is not None:
                            entry[key] = dt_data[key]
            except Exception as e:
                logger.warning("龙虎榜数据获取失败 %s: %s", code_pure, e)

        positions_summary[code_pure] = entry

    return {
        "date": date_str,
        "built_at": datetime.now(tz=CN_TZ).isoformat(),
        "market": market_info,
        "positions": positions_summary,
        "tomorrow_scenarios": None,  # 由收盘复盘 LLM 填充
    }


def _save_yesterday_summary(summary: dict, config_dir: Path | None = None) -> bool:
    """持久化昨日特征摘要到 daily_review_summary.json。

    格式：按日期键存储，如 {"2026-06-11": {...}, "2026-06-12": {...}}
    """
    try:
        file_path = _summary_file_path(config_dir)
        existing: dict = {}
        if file_path.exists():
            existing = json.loads(file_path.read_text(encoding="utf-8"))

        date_str = summary.get("date", datetime.now(tz=CN_TZ).strftime("%Y-%m-%d"))
        existing[date_str] = summary

        file_path.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("昨日特征摘要已保存: %s (%s 条持仓)", file_path,
                     len(summary.get("positions", {})))
        return True
    except Exception as e:
        logger.error("保存昨日特征摘要失败: %s", e)
        return False


def _update_summary_tomorrow_scenarios(
    tomorrow_scenarios: dict,
    config_dir: Path | None = None,
    date_str: str | None = None,
) -> bool:
    """更新已持久化的 summary 中的 tomorrow_scenarios（由收盘复盘 cron 在 LLM 输出后调用）。

    Args:
        tomorrow_scenarios: {"strong_repair": {...}, "weak_consolidation": {...}, ...}
        config_dir: 配置目录
        date_str: 目标日期（默认今天）

    Returns:
        True 更新成功，False 失败
    """
    try:
        file_path = _summary_file_path(config_dir)
        if not file_path.exists():
            logger.warning("summary 文件不存在，无法更新 tomorrow_scenarios")
            return False

        existing = json.loads(file_path.read_text(encoding="utf-8"))
        if date_str is None:
            date_str = datetime.now(tz=CN_TZ).strftime("%Y-%m-%d")

        if date_str not in existing:
            logger.warning("summary 无 %s 日数据，无法更新 tomorrow_scenarios", date_str)
            return False

        existing[date_str]["tomorrow_scenarios"] = tomorrow_scenarios
        file_path.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("tomorrow_scenarios 已更新到 %s: %s", date_str,
                     list(tomorrow_scenarios.keys()) if isinstance(tomorrow_scenarios, dict) else "N/A")
        return True
    except Exception as e:
        logger.error("更新 tomorrow_scenarios 失败: %s", e)
        return False


def _load_yesterday_summary(
    config_dir: Path | None = None,
    date_str: str | None = None,
) -> dict | None:
    """读取昨日特征摘要，优先级：文件 > state.json 快照 > 无数据。

    Args:
        config_dir: 配置目录（默认 stock_monitor）
        date_str: 目标日期（默认昨天）

    Returns:
        summary dict 或 None（完全无数据）
    """
    config_dir = config_dir or DEFAULT_CONFIG_DIR
    if date_str is None:
        from datetime import timedelta
        date_str = (datetime.now(tz=CN_TZ) - timedelta(days=1)).strftime("%Y-%m-%d")

    # ── 优先：从 daily_review_summary.json 读取 ──
    file_path = _summary_file_path(config_dir)
    if file_path.exists():
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                # 如果直接是日期键结构
                if date_str in data:
                    logger.info("读取昨日特征摘要: 文件命中 %s", date_str)
                    return data[date_str]
                # 如果文件里只有一个键且是日期格式，可能是新格式
                # 也尝试按日期匹配
                for key in data:
                    if isinstance(data[key], dict) and "positions" in data.get(key, {}):
                        if key == date_str:
                            logger.info("读取昨日特征摘要: 文件命中 %s", date_str)
                            return data[key]

            # 如果整个文件就是这个日期的 summary（单记录格式）
            if isinstance(data, dict) and "positions" in data and "date" in data:
                if data.get("date") == date_str:
                    return data

            logger.info("读取昨日特征摘要: 文件存在但未命中日期 %s", date_str)
        except Exception as e:
            logger.warning("读取 daily_review_summary.json 失败: %s", e)

    # ── Fallback: 从 state.json 的 last_quote_snapshot 提取 ──
    try:
        state_path = config_dir / "state.json"
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8"))
            qs = state.get("last_quote_snapshot", {})
            if qs and qs.get("quotes"):
                logger.info("读取昨日特征摘要: fallback → state.json last_quote_snapshot")
                summary = {
                    "date": date_str,
                    "built_at": datetime.now(tz=CN_TZ).isoformat(),
                    "source": "fallback_state_json",
                    "market": {},
                    "positions": {},
                    "tomorrow_scenarios": None,
                }
                for q in qs.get("quotes", []):
                    code = _pure_stock_code(str(q.get("code", "")))
                    summary["positions"][code] = {
                        "close": _to_float(q.get("previous_close")),
                        "open": _to_float(q.get("open")),
                        "high": _to_float(q.get("high")),
                        "low": _to_float(q.get("low")),
                        "change_pct": _to_float(q.get("pct_change")),
                        "volume": _to_float(q.get("volume")),
                        "amount": q.get("amount", ""),
                        **{k: None for k in SUMMARY_FIELDS_BOARD},
                        **{k: None for k in SUMMARY_FIELDS_TECH},
                        **{k: None for k in SUMMARY_FIELDS_DETAIL},
                        **{k: None for k in SUMMARY_FIELDS_COST},
                    }
                return summary
    except Exception as e:
        logger.warning("Fallback state.json 读取失败: %s", e)

    logger.warning("昨日特征摘要完全不可用: %s", date_str)
    return None


# ──────────────────────────────────────────────
# Phase 2: 竞价快照系统
# ──────────────────────────────────────────────

AUCTION_CACHE_FILENAME = "auction_volume_cache.json"
AUCTION_CACHE_MAX_DAYS = 10  # keep 10 days, use last 5 for avg


def _auction_cache_path(config_dir: Path | None = None) -> Path:
    """返回竞价量缓存文件路径。"""
    return (config_dir or DEFAULT_CONFIG_DIR) / AUCTION_CACHE_FILENAME


def _load_auction_cache(config_dir: Path | None = None) -> dict:
    """读取竞价量缓存。"""
    path = _auction_cache_path(config_dir)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("读取竞价量缓存失败: %s", e)
    return {}


def _save_auction_cache(cache: dict, config_dir: Path | None = None) -> bool:
    """保存竞价量缓存。"""
    try:
        path = _auction_cache_path(config_dir)
        path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.debug("竞价量缓存已保存: %s (%d 只股票)", path, len(cache))
        return True
    except Exception as e:
        logger.error("保存竞价量缓存失败: %s", e)
        return False


def _update_auction_cache(
    auction_data: dict[str, dict],  # {code_pure: {volume, price, date}}
    config_dir: Path | None = None,
) -> None:
    """更新竞价量缓存，追加当日数据，保留最近 AUCTION_CACHE_MAX_DAYS 天。"""
    cache = _load_auction_cache(config_dir)
    today = datetime.now(tz=CN_TZ).strftime("%Y-%m-%d")

    for code, data in auction_data.items():
        if code not in cache:
            cache[code] = []
        # 如果今天已有记录，覆盖
        existing_entries = [e for e in cache[code] if e.get("date") != today]
        existing_entries.append({
            "date": today,
            "volume": data.get("volume"),
            "price": data.get("price"),
            "change_pct": data.get("change_pct"),
        })
        # 保留最近 N 天
        existing_entries.sort(key=lambda e: e.get("date", ""), reverse=True)
        cache[code] = existing_entries[:AUCTION_CACHE_MAX_DAYS]

    _save_auction_cache(cache, config_dir)


def _compute_auction_volume_ratio(
    code: str,
    today_volume: float | None,
    config_dir: Path | None = None,
) -> float | None:
    """计算今日竞价量 / 近5日竞价量均值。

    不足5天的缓存时自动从 K线缓存回填（日K volume 作为竞价量近似值）。
    回填数据写入 cache 后复用，随着真实竞价数据积累逐渐替换。

    Args:
        code: 股票代码（6位纯数字）
        today_volume: 今日竞价量
        config_dir: 配置目录

    Returns:
        量比，或 None（数据不足）
    """
    if today_volume is None or today_volume <= 0:
        return None

    cache = _load_auction_cache(config_dir)
    entries = cache.get(code, [])
    today = datetime.now(tz=CN_TZ).strftime("%Y-%m-%d")

    # ── 从 cache 取历史竞价量（排除今天）──
    past_entries = sorted(
        [e for e in entries if e.get("date") != today and e.get("volume") is not None],
        key=lambda x: x.get("date", ""),
        reverse=True,
    )
    past_volumes = [e["volume"] for e in past_entries[:5]]

    # ── 如果不足5条，从 K线缓存回填日K volume ──
    cache_updated = False
    if len(past_volumes) < 5:
        try:
            from qing_investment.kline_cache import get_klines
            klines = get_klines(code, days=10)
            if klines:
                # 已有的 cache 日期集合，避免重复
                cached_dates = {e.get("date") for e in past_entries if e.get("date")}

                # 从 K线取最后5个交易日（排除今天），作为竞价量近似值回填
                for k in reversed(klines[-8:]):  # 取稍多些以确保有足够近5日
                    k_date = str(k.get("date", ""))
                    if k_date in cached_dates or k_date == today:
                        continue
                    k_volume = _to_float(k.get("volume"))
                    if k_volume and k_volume > 0:
                        # 用日K volume 作为竞价量近似值
                        if code not in cache:
                            cache[code] = []
                        cache[code].append({
                            "date": k_date,
                            "volume": k_volume * 0.5,  # 日K volume 远大于竞价量，但相对比较仍有效
                            "price": None,
                            "change_pct": None,
                            "source": "kline_backfill",
                        })
                        cached_dates.add(k_date)
                        cache_updated = True

                # 重新排序 + 去重 + 计数
                if cache_updated and code in cache:
                    cache[code] = sorted(
                        cache[code],
                        key=lambda e: e.get("date", ""),
                        reverse=True,
                    )[:AUCTION_CACHE_MAX_DAYS]

                    # 重新计算 past_volumes（含回填数据）
                    past_entries = [
                        e for e in cache[code]
                        if e.get("date") != today and e.get("volume") is not None
                    ][:5]
                    past_volumes = [e["volume"] for e in past_entries]

        except Exception:
            pass

    # ── 保存 cache（如有更新）──
    if cache_updated:
        _save_auction_cache(cache, config_dir)

    if len(past_volumes) < 2:
        return None  # 数据不足

    avg_volume = sum(past_volumes) / len(past_volumes)
    if avg_volume <= 0:
        return None

    return round(today_volume / avg_volume, 2)


def _compute_auction_vs_yesterday_volume(
    code: str,
    today_auction_volume: float | None,
    config: MonitorConfig,
    quote_snapshot: dict,
) -> float | None:
    """计算竞价量 / 昨日全天成交量。"""
    if today_auction_volume is None or today_auction_volume <= 0:
        return None

    # 从 quote_snapshot 中找该股票的昨日成交量
    quotes = _quotes_by_code(quote_snapshot)
    quote = _quote_for_stock(quotes, code) or {}
    yesterday_volume = _to_float(quote.get("volume"))

    if yesterday_volume is None or yesterday_volume <= 0:
        return None

    return round(today_auction_volume / yesterday_volume, 4)


def _auction_snapshot(
    config: MonitorConfig,
    quote_snapshot: dict,
    *,
    auto_cache: bool = True,
    config_dir: Path | None = None,
) -> dict:
    """采集竞价快照。

    从实时行情快照的 quote 字段提取竞价数据。
    需要在 09:25-09:26 之间调用（此时 f2/latest = 竞价撮合价）。

    Args:
        config: MonitorConfig
        quote_snapshot: 实时行情快照（东财API返回）
        auto_cache: 是否自动更新竞价量缓存
        config_dir: 配置目录

    Returns:
        auction_data: dict, keyed by 6-digit code
    """
    quotes = _quotes_by_code(quote_snapshot)
    config_dir = config_dir or config.config_dir

    # 要采集的标的：持仓 + 观察池
    all_stocks: list[dict] = position_rows(config) + watchlist_stock_rows(config)
    seen_codes: set[str] = set()
    result: dict[str, dict] = {}
    cache_data: dict[str, dict] = {}  # 用于缓存更新

    for stock in all_stocks:
        code_raw = str(stock.get("code", ""))
        code_pure = _pure_stock_code(code_raw)
        if code_pure in seen_codes:
            continue
        seen_codes.add(code_pure)

        quote = _quote_for_stock(quotes, code_pure) or _quote_for_stock(quotes, code_raw) or {}
        if not quote:
            continue

        # ── 基础字段（来自东财API f2/f3/f5/f15/f17/f18）──
        auction_price = _to_float(quote.get("latest"))
        auction_change_pct = _to_float(quote.get("pct_change"))
        auction_open = _to_float(quote.get("open"))
        previous_close = _to_float(quote.get("previous_close"))
        low_price = _to_float(quote.get("low"))
        high_price = _to_float(quote.get("high"))

        # 竞价量 = 截至09:26的累计成交量（此时仅有竞价撮合量）
        auction_volume = _to_float(quote.get("volume"))

        if auction_price is None:
            continue

        # 如果 open 和 latest 不一致，说明已有盘中交易
        # 此时 open 仍是竞价价，latest 是盘中价
        effective_auction_price = auction_open if auction_open is not None else auction_price
        effective_auction_pct = (
            round((effective_auction_price - previous_close) / previous_close * 100, 2)
            if previous_close and previous_close > 0 and effective_auction_price
            else None
        )

        # 计算竞价振幅（open vs 竞价阶段的 low/high）
        auction_amplitude = None
        if all(v is not None for v in [high_price, low_price, previous_close]) and previous_close > 0:
            if low_price and high_price:
                auction_amplitude = round((high_price - low_price) / previous_close * 100, 2)

        # 竞价量与昨日成交量对比
        auction_vs_yesterday = _compute_auction_vs_yesterday_volume(
            code_pure, auction_volume, config, quote_snapshot
        )

        entry = {
            # 基础6字段
            "auction_price": effective_auction_price,
            "auction_change_pct": effective_auction_pct,
            "auction_volume": auction_volume,
            "previous_close": previous_close,
            "auction_open": effective_auction_price,
            "auction_amplitude": auction_amplitude,
            # 评审补充字段（无数据源）
            "auction_volume_ratio": None,  # 等缓存更新后重新计算
            "auction_vs_yesterday_volume": auction_vs_yesterday,
            "last5min_high_pct": None,
            "last5min_low_pct": None,
            "auction_trend_920_925": "unknown",
            "unmatched_buy_ratio": None,
            # 元数据
            "data_source": "eastmoney_push2_open_price",
            "note": "9:20-9:25轨迹竞价不可用（需Level-2数据），标记为unknown",
        }
        result[code_pure] = entry

        # 收集缓存数据
        if auction_volume is not None:
            cache_data[code_pure] = {
                "volume": auction_volume,
                "price": effective_auction_price,
                "change_pct": effective_auction_pct,
            }

    # ── 更新竞价量缓存 ──
    if auto_cache and cache_data:
        _update_auction_cache(cache_data, config_dir)

    # ── 使用更新后的缓存重新计算量比 ──
    for code_pure, entry in result.items():
        cache_vol = cache_data.get(code_pure, {}).get("volume")
        entry["auction_volume_ratio"] = _compute_auction_volume_ratio(
            code_pure, cache_vol, config_dir
        )

    return result


def _extract_auction_snapshot_for_context(
    auction_data: dict[str, dict],
    config: MonitorConfig,
) -> dict:
    """将竞价快照转换为 agent context 可注入的格式。

    仅保留持仓+关键观察池标的，方便 LLM 使用。
    """
    # 确定哪些标的要注入：持仓 + 有 claims 支撑的观察池标的
    core_codes: set[str] = set()
    for pos in position_rows(config):
        core_codes.add(_pure_stock_code(str(pos.get("code", ""))))

    for theme in config.watchlist.get("themes", []):
        for stock in theme.get("stocks", []):
            code_pure = _pure_stock_code(str(stock.get("code", "")))
            linked = stock.get("linked_claims") or stock.get("claim_basis")
            if linked:
                core_codes.add(code_pure)

    filtered = {
        code: entry for code, entry in auction_data.items()
        if code in core_codes
    }
    return filtered


def _build_sector_tiers(
    config: MonitorConfig,
    enriched_positions: list[dict],
    quotes_by_code: dict[str, dict],
) -> dict[str, dict]:
    """计算每个持仓股的板块梯队（同theme标的按涨幅排序 T1/T2/T3）。

    Returns:
        {code_pure: {tier1_code, tier1_pct, tier2_code, tier2_pct,
                      tier3_code, tier3_pct, avg_change, peers_count}}
    """
    # ── 1. 构建 code→[theme_id] 映射（从 watchlist）──
    code_to_themes: dict[str, list[str]] = {}
    for theme in config.watchlist.get("themes", []):
        tid = theme.get("id", "")
        for stock in theme.get("stocks", []):
            c = _pure_stock_code(str(stock.get("code", "")))
            if c:
                code_to_themes.setdefault(c, []).append(tid)

    # ── 2. 构建同 theme 的 code→pct_change 一览（持仓+观察池）──
    # 先收集所有标的的实时涨跌
    all_pct: dict[str, float] = {}
    for _, quote in quotes_by_code.items():
        c = _pure_stock_code(str(quote.get("code", "")))
        pct = _to_float(quote.get("pct_change"))
        if c and pct is not None:
            all_pct[c] = pct

    # 再从 positions 补充（可能不在 quotes 中）
    for pos in enriched_positions:
        c = _pure_stock_code(str(pos.get("code", "")))
        pct = _to_float(pos.get("pct_change"))
        if c and pct is not None and c not in all_pct:
            all_pct[c] = pct

    # ── 3. 对每个持仓，查它的 theme → 找同 theme 标的 → 排序 ──
    result: dict[str, dict] = {}
    for pos in enriched_positions:
        code_pure = _pure_stock_code(str(pos.get("code", "")))
        themes = code_to_themes.get(code_pure, [])
        if not themes:
            continue

        # 收集所有同 theme 的标的（去重）
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

        # 按涨幅排序
        peer_pct = [(c, all_pct.get(c)) for c in peers_set if all_pct.get(c) is not None]
        peer_pct.sort(key=lambda x: x[1], reverse=True)

        if not peer_pct:
            continue

        pct_values = [p for _, p in peer_pct]
        avg_change = round(sum(pct_values) / len(pct_values), 2) if pct_values else None

        tier = {
            "avg_change": avg_change,
            "peers_count": len(peer_pct),
        }
        # Tier 1/2/3（最多3个）
        for i, (c, p) in enumerate(peer_pct[:3]):
            tier[f"tier{i+1}_code"] = c
            tier[f"tier{i+1}_pct"] = p
            # 标记是否持仓
            tier[f"tier{i+1}_is_position"] = any(
                _pure_stock_code(str(p2.get("code", ""))) == c
                for p2 in enriched_positions
            )

        # 标记自身的排名
        for i, (c, _) in enumerate(peer_pct):
            if c == code_pure:
                tier["self_rank"] = i + 1
                tier["self_rank_label"] = f"T{i+1}" if i < 3 else f"T{i+1}+"
                break

        result[code_pure] = tier

    return result


def _agent_context_data(
    config: MonitorConfig,
    value: datetime,
    trigger: AgentAnalysisTrigger,
    alerts: list[RuleAlert],
    quote_snapshot: dict,
    state: dict,
) -> dict:
    """Build the structured data dict used by both text and JSON formatters."""
    stage = config.strategy_pack.get("market_framework", {}).get(
        "current_stage", "未配置"
    )
    core_question = config.strategy_pack.get("market_framework", {}).get(
        "core_question", "未配置"
    )

    alert_dicts = [
        {
            "action": a.action,
            "stock_code": a.stock_code,
            "stock_name": a.stock_name,
            "price": a.price,
            "trigger": a.trigger,
            "severity": a.severity,
            "summary": a.summary,
        }
        for a in alerts
    ]

    positions = position_rows(config)
    watch_stocks = watchlist_stock_rows(config)

    # Enrich positions with live quote data
    quotes_by_code = _quotes_by_code(quote_snapshot)
    enriched_positions: list[dict] = []
    for p in positions:
        code = p.get("code", "")
        quote = _quote_for_stock(quotes_by_code, code) or {}
        enriched = dict(p)
        latest = _to_float(quote.get("latest"))
        pct = _to_float(quote.get("pct_change"))
        if latest is not None:
            enriched["latest"] = latest
        if pct is not None:
            enriched["pct_change"] = pct

        # ── Phase 3: 实时持仓成本注入 ──
        cost = _to_float(p.get("cost"))
        if cost is not None and cost > 0 and latest is not None:
            unrealized_pct = round((latest - cost) / cost * 100, 2)
            enriched["avg_cost"] = cost
            enriched["unrealized_pct"] = unrealized_pct
            # 成本保护线：浮盈>10%→成本+5%; 5-10%→成本+3%; <5%→成本
            if unrealized_pct > 10:
                enriched["cost_protection_line"] = round(cost * 1.05, 2)
            elif unrealized_pct > 5:
                enriched["cost_protection_line"] = round(cost * 1.03, 2)
            elif unrealized_pct > 0:
                enriched["cost_protection_line"] = round(cost * 1.00, 2)
            else:
                # 浮亏：保护线 = 成本价（-3%以内守成本，-3%以上守95%成本）
                enriched["cost_protection_line"] = round(
                    cost * (1.0 if unrealized_pct >= -3 else 0.95), 2
                )
        enriched_positions.append(enriched)
    sector_strengths = [
        {
            "id": s.id,
            "name": s.name,
            "style": s.style,
            "average_pct_change": s.average_pct_change,
            "red_ratio": s.red_ratio,
            "quote_count": s.quote_count,
        }
        for s in compute_sector_strength(config, quote_snapshot)
    ]

    external_sector_boards: dict
    try:
        from qing_investment.agent.tools.sector_data import get_sector_strength_snapshot

        external_sector_boards = get_sector_strength_snapshot(top_n=30)
        external_sector_boards["available"] = True
    except Exception as e:
        external_sector_boards = {
            "available": False,
            "error": f"外部板块数据获取失败: {e}",
            "concept": {"leaders": [], "laggards": [], "count": 0, "source": "none"},
            "industry": {"leaders": [], "laggards": [], "count": 0, "source": "none"},
        }

    # 买入信号候选详情（仅在 trigger.kind == "buy_signal_candidate" 时填充）
    buy_signal_candidates: list[dict] = []
    if trigger.kind == "buy_signal_candidate":
        try:
            candidates = evaluate_buy_signal_candidates(config, quote_snapshot)
            for c in candidates:
                if c.is_candidate:
                    buy_signal_candidates.append({
                        "stock_code": c.stock_code,
                        "stock_name": c.stock_name,
                        "price": c.price,
                        "entry_zone": list(c.entry_zone) if c.entry_zone else None,
                        "stop_loss": c.stop_loss,
                        "matched_conditions": c.matched_conditions,
                        "claim_basis": c.claim_basis,
                        "odds_analysis": c.odds_analysis,
                    })
        except Exception:
            pass  # 候选提取失败不影响主流程

    # 确定 analysis_type
    analysis_type = "market"
    primary_stock_code = ""
    if trigger.kind == "buy_signal_candidate":
        analysis_type = "stock"
        if buy_signal_candidates:
            primary_stock_code = buy_signal_candidates[0]["stock_code"]

    # ── Phase 2: 竞价快照注入 ──
    # 从当前 quote_snapshot 提取竞价数据（仅 09:20-09:30 有效）
    auction_snapshot_data: dict = {}
    current_time = value.astimezone(CN_TZ).time()
    if time(9, 20) <= current_time <= time(9, 31):
        try:
            raw_auction = _auction_snapshot(
                config, quote_snapshot,
                auto_cache=True, config_dir=config.config_dir,
            )
            auction_snapshot_data = _extract_auction_snapshot_for_context(raw_auction, config)
        except Exception as e:
            logger.warning("竞价快照提取失败: %s", e)
            auction_snapshot_data = {"_error": str(e)}

    # ── Phase 4.2: 板块梯队对比 ──
    sector_tier_data = _build_sector_tiers(config, enriched_positions, quotes_by_code)

    # ── 将板块梯队注入每个持仓的 enriched dict ──
    for pos in enriched_positions:
        code = _pure_stock_code(str(pos.get("code", "")))
        if code in sector_tier_data:
            pos["sector_tier"] = sector_tier_data[code]

    # ── Phase 6.2: 持仓类型标记 ──
    # 为每个持仓自动分类：limit_up / weak_board / floating_loss / trend
    _ys_for_ptype = _load_yesterday_summary(config_dir=config.config_dir)
    yesterday_positions = (_ys_for_ptype or {}).get("positions", {})
    for pos in enriched_positions:
        code = _pure_stock_code(str(pos.get("code", "")))
        yp = yesterday_positions.get(code, {})
        is_limit_up = yp.get("is_limit_up", False) or pos.get("pct_change", 0) >= 9.0
        unrealized = pos.get("unrealized_pct", 0) or 0
        board_quality = yp.get("board_quality", "")
        change_pct = yp.get("change_pct", 0) or 0
        amplitude = yp.get("amplitude", 0) or 0

        if is_limit_up and (board_quality == "weak" or amplitude > 6.0):
            pos["position_type"] = "weak_board"
        elif is_limit_up:
            pos["position_type"] = "limit_up"
        elif unrealized < -5:
            pos["position_type"] = "floating_loss"
        else:
            pos["position_type"] = "trend"

    # ── Phase 4.1b: 龙虎榜全市场总榜交叉校验 ──
    # 仅收盘后（>= 16:00）执行，龙虎榜数据一般16:00-17:00发布
    dt_board_data: dict = {}
    if current_time >= time(16, 0):
        try:
            date_today = _state_date(value)
            raw_board = _fetch_daily_dragon_tiger_board(date_today)
            if raw_board.get("available") and raw_board.get("board"):
                dt_board_data = _filter_dragon_tiger_board(
                    raw_board["board"], config
                )
                dt_board_data["_board_count"] = len(raw_board["board"])
                dt_board_data["_fetched_at"] = raw_board.get("fetched_at")
        except Exception as e:
            logger.warning("龙虎榜总榜获取失败: %s", e)
            dt_board_data = {"_error": str(e)}

    # Phase 8.1 日志：watchlist序列化统计
    _wl_with_entry = sum(1 for row in watch_stocks if row.get("entry_zone", {}).get("price_range"))
    _wl_with_stop = sum(1 for row in watch_stocks if row.get("entry_zone", {}).get("hard_stop"))
    _wl_with_lifecycle = sum(1 for row in watch_stocks if row.get("lifecycle", {}).get("stage"))
    logger.info(
        f"watchlist_serialized: total={len(watch_stocks)} "
        f"with_entry_zone={_wl_with_entry} with_stop={_wl_with_stop} "
        f"with_lifecycle={_wl_with_lifecycle}"
    )

    return {
        "timestamp": value.astimezone(CN_TZ).isoformat(),
        "analysis_type": analysis_type,
        "stock_code": primary_stock_code,
        "trigger": {
            "kind": trigger.kind,
            "id": trigger.id,
            "title": trigger.title,
            "reason": trigger.reason,
        },
        "market_framework": {
            "stage": stage,
            "core_question": core_question,
        },
        "alerts": alert_dicts,
        "buy_signal_candidates": buy_signal_candidates,
        "market_state": state.get("last_market_state", {}),
        "sector_signal_counts": state.get("sector_signal_counts", {}),
        "sector_strengths": sector_strengths,
        "external_sector_boards": external_sector_boards,
        "quote_snapshot": quote_snapshot,
        "market_snapshot": {
            "quotes": quote_snapshot.get("quotes", []),
            "source": quote_snapshot.get("source", "unknown"),
            "elapsed_ms": quote_snapshot.get("elapsed_ms", 0),
        },
        "positions": enriched_positions,
        "watchlist": [
            {
                "theme": row.get("theme_name", ""),
                "role": row.get("role", ""),
                "name": row.get("name", ""),
                "code": row.get("code", ""),
                "priority": row.get("priority", ""),
                "latest": _to_float((_quote_for_stock(quotes_by_code, row.get("code", "")) or {}).get("latest")),
                "pct_change": _to_float((_quote_for_stock(quotes_by_code, row.get("code", "")) or {}).get("pct_change")),
                "watch_reason": row.get("watch_reason", ""),
                "note": row.get("note", ""),
                "buy_setup": _string_items(row.get("buy_setup")),
                "invalidation_setup": _string_items(row.get("invalidation_setup")),
                "sell_setup": _string_items(row.get("sell_setup")),
                "confirm_with": _string_items(row.get("confirm_with")),
                # Phase 8.1 新增：决策关键字段
                "segment": row.get("segment", ""),
                "entry_price_range": row.get("entry_zone", {}).get("price_range"),
                "entry_method": row.get("entry_zone", {}).get("method"),
                "entry_confirm_signal": row.get("entry_zone", {}).get("confirm_signal"),
                "entry_hard_stop": row.get("entry_zone", {}).get("hard_stop"),
                "entry_position_ratio": row.get("entry_zone", {}).get("position_ratio"),
                "lifecycle_stage": row.get("lifecycle", {}).get("stage"),
                "reduce_zone_desc": row.get("reduce_zone", {}).get("description"),
                "reduce_zone_price": _to_float(row.get("reduce_zone", {}).get("price")),
                "reduce_zone_action": row.get("reduce_zone", {}).get("action"),
                "risk_zone_desc": row.get("risk_zone", {}).get("description"),
                "risk_zone_price": _to_float(row.get("risk_zone", {}).get("price")),
                "risk_zone_action": row.get("risk_zone", {}).get("action"),
                "last_mentioned_date": row.get("up_mention_status", {}).get("last_mentioned_date"),
                "up_sentiment": row.get("up_mention_status", {}).get("sentiment"),
                "mention_context": (row.get("up_mention_status", {}) or {}).get("mention_context", ""),
            }
            for row in watch_stocks
        ],
        "yesterday_summary": _load_yesterday_summary(config_dir=config.config_dir),
        "auction_snapshot": auction_snapshot_data,
        "dragon_tiger_board": dt_board_data,
    }


def format_agent_analysis_context(
    config: MonitorConfig,
    value: datetime,
    trigger: AgentAnalysisTrigger,
    alerts: list[RuleAlert],
    quote_snapshot: dict,
    state: dict,
) -> str:
    data = _agent_context_data(config, value, trigger, alerts, quote_snapshot, state)
    stage = data["market_framework"]["stage"]
    core_question = data["market_framework"]["core_question"]

    # ── Phase 3 新增：加载 daily_state ──
    from qing_investment.agent.tools.daily_state import load_daily_state, get_state_summary
    daily_state = load_daily_state()
    state_summary = get_state_summary(daily_state)

    # ── Phase 3 新增：加载差异化 prompt ──
    cron_prompt = ""
    schedule_rows = agent_analysis_schedule_rows(config)
    current_row = None
    for row in schedule_rows:
        row_time = str(row.get("time", ""))
        current_hhmm = value.astimezone(CN_TZ).strftime("%H:%M")
        if row_time == current_hhmm:
            current_row = row
            break

    if current_row:
        prompt_name = current_row.get("prompt", "")
        if prompt_name:
            prompt_path = repo_root() / "src" / "qing_investment" / "agent" / "prompts" / "system" / f"{prompt_name}.txt"
            if prompt_path.exists():
                cron_prompt = prompt_path.read_text(encoding="utf-8")

    # ── Phase 4 新增：加载观察池热度排行 ──
    hot_score_summary = ""
    try:
        from qing_investment.agent.tools.hot_score import format_hot_score_summary
        hot_score_summary = format_hot_score_summary(limit=10)
    except Exception as e:
        logger.warning("Failed to load hot scores: %s", e)

    lines = [
        "[Hermes股票监控大模型分析上下文]",
        f"时间：{data['timestamp']}",
        f"触发类型：{data['trigger']['kind']}",
        f"触发点：{data['trigger']['title']}",
        f"触发原因：{data['trigger']['reason']}",
        f"当前框架：{stage}",
        f"核心问题：{core_question}",
        "",
        "=== daily_state 当前状态 ===",
        state_summary,
        "",
        "=== 观察池热度排行 ===",
        hot_score_summary if hot_score_summary else "热度分尚未计算",
        "",
        "=== 节点专属指令 ===",
        cron_prompt if cron_prompt else "（使用默认分析模板）",
        "",
        "规则信号：",
    ]
    if data["alerts"]:
        for alert in data["alerts"]:
            lines.append(f"- {alert['summary']}")
    else:
        lines.append("- 无新增规则信号；这是固定关键时间点分析。")

    market_state = data["market_state"]
    if market_state:
        lines.extend(
            [
                "",
                "状态摘要：",
                f"- alert_count={market_state.get('alert_count')}",
                f"- risk_count={market_state.get('risk_count')}",
                f"- sector_actions={market_state.get('sector_actions')}",
            ]
        )

    sector_counts = data["sector_signal_counts"]
    if sector_counts:
        lines.extend(["", "板块连续信号："])
        for key, value_dict in sector_counts.items():
            lines.append(
                "- {key}: {action} 连续{count}次".format(
                    key=key,
                    action=value_dict.get("action", ""),
                    count=value_dict.get("count", 0),
                )
            )

    lines.extend(
        [
            "",
            "实时行情快照：",
            f"数据源：{quote_snapshot.get('source', 'unknown')}",
            f"行情请求耗时：{quote_snapshot.get('elapsed_ms')} ms",
            f"行情条数：{len(quote_snapshot.get('quotes', []) or [])}",
        ]
    )
    if quote_snapshot.get("errors"):
        lines.append(f"行情错误：{'; '.join(quote_snapshot.get('errors', []))}")
    for quote in quote_snapshot.get("quotes", [])[:30]:
        lines.append(format_quote_line(quote))

    # ── Phase 1+2: 注入昨日特征摘要 + 竞价快照 ──
    yesterday = data.get("yesterday_summary")
    if yesterday and yesterday.get("positions"):
        lines.extend(["", "=== 昨日特征摘要 ==="])
        lines.append(f"市场阶段: {yesterday.get('market', {}).get('stage', '')}")
        for code, pos in yesterday.get("positions", {}).items():
            up_flag = "🔒" if pos.get("is_limit_up") else ""
            parts = [
                f"{pos.get('avg_cost', '?')}",  # 成本
                f"浮盈{pos.get('unrealized_pct', '?')}%",
            ]
            if pos.get("vs_ma5") is not None:
                parts.append(f"vsMA5={pos.get('vs_ma5')}%")
            if pos.get("entry_zone_distance"):
                parts.append(f"区间{pos.get('entry_zone_range')}({pos.get('entry_zone_distance')})")
            lines.append(f"- {code}{up_flag}: close={pos.get('close')} {'|'.join(parts)}")

    auction = data.get("auction_snapshot")
    if auction:
        lines.extend(["", "=== 竞价快照 ==="])
        for code, entry in auction.items():
            trend = entry.get("auction_trend_920_925", "unknown")
            vol_ratio = entry.get("auction_volume_ratio")
            vs_yest = entry.get("auction_vs_yesterday_volume")
            parts = [f"价={entry.get('auction_price')} ({entry.get('auction_change_pct')}%)"]
            if entry.get("auction_volume") is not None:
                parts.append(f"量={entry.get('auction_volume')}")
            if vol_ratio is not None:
                parts.append(f"量比={vol_ratio}")
            if vs_yest is not None:
                parts.append(f"vs昨={vs_yest}")
            lines.append(f"- {code}: {' '.join(parts)}")

    # ── Phase 3: 持仓成本信息注入 ──
    if data.get("positions"):
        lines.extend(["", "=== 持仓成本 ==="])
        for pos in data["positions"]:
            code = _pure_stock_code(str(pos.get("code", "")))
            cost = pos.get("avg_cost")
            unrealized = pos.get("unrealized_pct")
            prot_line = pos.get("cost_protection_line")
            tier = pos.get("sector_tier")
            tier_str = ""
            if tier:
                rank = tier.get("self_rank_label", "")
                avg = tier.get("avg_change", "")
                tier_str = f" T{rank}/板块{avg}%"
            ptype = pos.get("position_type", "")
            ptype_str = f" [{ptype}]" if ptype else ""
            if cost is not None:
                lines.append(
                    f"- {code}:{ptype_str} 成本{cost} 浮盈{unrealized}% 保护线{prot_line}{tier_str}"
                )

    # ── Phase 4.1b: 龙虎榜总榜摘要 ──
    dt_board = data.get("dragon_tiger_board", {})
    if dt_board and not dt_board.get("_error"):
        watch_items = dt_board.get("watch_dt_items", [])
        nettops = dt_board.get("dt_nettop5", [])
        sector_summary = dt_board.get("dt_sector_summary", {})
        lines.extend(["", "=== 龙虎榜总榜 ==="])
        if watch_items:
            lines.append(f"你的池子上榜: {'; '.join(watch_items[:3])}")
        if nettops:
            top_items = [f"{e.get('name','')}({e.get('net_buy','')})" for e in nettops[:3]]
            lines.append(f"全市场净买TOP: {'; '.join(top_items)}")
        if sector_summary:
            sector_lines = [
                f"{tid}: {info['total_net_str']} ({len(info['stocks'])}只)"
                for tid, info in sector_summary.items()
            ]
            lines.append(f"板块龙虎汇总: {'; '.join(sector_lines)}")
        lines.append(f"上榜总数: {dt_board.get('_board_count', 0)}只")

    lines.extend(
        [
            "",
            "【⚠️ 数据优先级】实时行情快照（上方的实际价格和涨跌幅）优先于下方 config 配置文件中的参考价。如果实时行情快照中有标的的最新价/涨跌幅，请以实时行情为准，不要用配置文件中的陈旧参考价(current_ref)。",
            "",
            "请按本项目 AGENTS.md 与 qing-stock-analysis 框架输出极简微信提醒：",
            "输出必须覆盖三件事：全A指数涨跌方向（强/弱修复定性）+ 观察池现在能不能买 + 持仓池现在怎么操作。",
            "【盘面】必须以全A指数（中证全指000985）的涨跌幅为锚做一句话定性（如'全A+0.8%强修复，上游材料领涨'或'全A-0.3%弱修复，继续观望'）。",
            "格式固定，最多450字，禁止Markdown表格、分级标题、长篇数据罗列和研报式分析。",
            "必须按下面换行模板输出，禁止把多只股票写成同一段：",
            "【盘面】一句话定性（必须含全A涨跌幅+强/弱修复判断+领涨方向）。全A锚合并至此，不再另起一行。",
            "【重点分析】1-2只重点票，每只80-100字。按持仓类型（limit_up/weak_board/floating_loss/trend）套用对应分析框架，说明动作+触发+证伪。",
            "【其他持仓】剩余持仓每只15字（动作+触发+证伪）。",
            "【观察池】最多3只，每只15字。可买说明买点，不买说明原因。",
            "【参考来源】列出依据的UP观点/框架/实时数据。",
        ]
    )

    return "\n".join(lines)

def format_agent_json_context(
    config: MonitorConfig,
    value: datetime,
    trigger: AgentAnalysisTrigger,
    alerts: list[RuleAlert],
    quote_snapshot: dict,
    state: dict,
    max_quotes: int = 40,
) -> str:
    """Return the agent context as a JSON string for qing-agent HTTP API.

    Quotes are truncated to ``max_quotes`` to keep the payload small enough
    for LLM prompt limits and reasonable HTTP latency.
    """
    data = _agent_context_data(config, value, trigger, alerts, quote_snapshot, state)
    qs = data.get("quote_snapshot", {})
    all_quotes = qs.get("quotes", []) or []
    if len(all_quotes) > max_quotes:
        qs["quotes"] = all_quotes[:max_quotes]
        qs["_total_quotes"] = len(all_quotes)
    return json.dumps(data, ensure_ascii=False, indent=2)


def _state_date(value: datetime) -> str:
    return value.astimezone(CN_TZ).strftime("%Y-%m-%d")


def summarize_daily_review(state: dict, date_text: str) -> dict:
    decision_log = state.get("alert_decision_log", [])
    if not isinstance(decision_log, list):
        decision_log = []
    today_entries = [
        entry
        for entry in decision_log
        if isinstance(entry, dict) and entry.get("date") == date_text
    ]

    agent_history = state.get("agent_analysis_history", {})
    if not isinstance(agent_history, dict):
        agent_history = {}
    agent_runs = [
        value
        for value in agent_history.values()
        if isinstance(value, dict) and str(value.get("time", "")).startswith(date_text)
    ]

    return {
        "date": date_text,
        "emitted_alerts": [
            entry for entry in today_entries if entry.get("status") == "emitted"
        ],
        "suppressed_alerts": [
            entry for entry in today_entries if entry.get("status") == "suppressed"
        ],
        "agent_runs": agent_runs,
        "last_market_state": state.get("last_market_state", {}),
        "sector_signal_counts": state.get("sector_signal_counts", {}),
        "last_fetch_error": state.get("last_fetch_error", {}),
    }


def _append_review_entries(lines: list[str], entries: list[dict], limit: int = 12) -> None:
    if not entries:
        lines.append("- 无")
        return
    for entry in entries[:limit]:
        lines.append(
            "- {time} {action} {stock}: {summary}".format(
                time=str(entry.get("time", ""))[11:19],
                action=entry.get("action", ""),
                stock=entry.get("stock_name") or entry.get("stock_code", ""),
                summary=entry.get("summary", ""),
            )
        )
    if len(entries) > limit:
        lines.append(f"- 另有 {len(entries) - limit} 条未展开")


def format_daily_review_context(
    config: MonitorConfig,
    value: datetime,
    state: dict,
) -> str:
    date_text = _state_date(value)
    summary = summarize_daily_review(state, date_text)
    stage = config.strategy_pack.get("market_framework", {}).get(
        "current_stage", "未配置"
    )
    core_question = config.strategy_pack.get("market_framework", {}).get(
        "core_question", "未配置"
    )

    lines = [
        "[Hermes股票监控收盘复盘上下文]",
        f"日期：{date_text}",
        f"生成时间：{value.astimezone(CN_TZ).strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"当前框架：{stage}",
        f"核心问题：{core_question}",
        "",
        "统计：",
        f"- 已发送提醒：{len(summary['emitted_alerts'])}",
        f"- 被去重压制：{len(summary['suppressed_alerts'])}",
        f"- 大模型关键点分析次数：{len(summary['agent_runs'])}",
        "",
        "已发送提醒：",
    ]
    _append_review_entries(lines, summary["emitted_alerts"])

    lines.extend(["", "被去重压制："])
    _append_review_entries(lines, summary["suppressed_alerts"])

    lines.extend(
        [
            "",
            "最后市场状态：",
            json.dumps(summary["last_market_state"], ensure_ascii=False, sort_keys=True),
            "",
            "板块连续信号：",
            json.dumps(
                summary["sector_signal_counts"], ensure_ascii=False, sort_keys=True
            ),
        ]
    )
    if summary["last_fetch_error"]:
        lines.extend(
            [
                "",
                "最后行情错误：",
                json.dumps(
                    summary["last_fetch_error"], ensure_ascii=False, sort_keys=True
                ),
            ]
        )

    # ── 收盘复盘新增：MACD/九转/斐波那契大盘分析数据 ──
    try:
        from qing_investment.kline_cache import (
            format_multi_tf_macd_report,
            compute_td_report,
            compute_fibonacci_time_report,
        )
        import sqlite3
        macd = format_multi_tf_macd_report()
        td_sh = compute_td_report("sh000001", "daily")
        td_ci = compute_td_report("sh000985", "daily")
        fib_sh = compute_fibonacci_time_report("sh000001")
        fib_ci = compute_fibonacci_time_report("sh000985")
        if macd:
            lines.extend(["", "📊 大盘多级别MACD：", macd])
        if td_sh or td_ci:
            lines.extend(["", "🔢 神奇九转：", td_sh, td_ci])
        if fib_sh or fib_ci:
            lines.extend(["", "📅 斐波那契时间窗口：", fib_sh, fib_ci])
    except Exception as e:
        lines.extend(["", f"⚠️ MACD数据获取失败: {e}"])

    stale_warnings = state.get("stale_zone_warnings")
    if stale_warnings:
        lines.extend(
            [
                "",
                "⚠️ 持仓价格区间失真警告：",
                json.dumps(stale_warnings, ensure_ascii=False),
            ]
        )

    lines.extend(
        [
            "",
            "请按本项目 AGENTS.md 与 qing-stock-analysis 框架输出收盘监控复盘：",
            "1. 判断今天提醒质量：哪些是有效提醒，哪些可能是误报",
            "2. 检查可能漏报的条件：指数、板块、持仓、观察池是否有该提醒而未提醒",
            "3. 总结被去重压制的信号是否合理",
            "4. 给出需要调整的 YAML 配置建议，明确文件和字段，例如 strategy_pack.yaml 的阈值或 watchlist.yaml 的观察池",
            "5. 给出下一交易日最重要的 3 条观察条件",
        ]
    )
    return "\n".join(lines)


def load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def load_monitor_config(config_dir: Path = DEFAULT_CONFIG_DIR) -> MonitorConfig:
    positions_path = config_dir / "positions.yaml"
    if not positions_path.exists():
        positions_path = config_dir / "positions.example.yaml"

    return MonitorConfig(
        config_dir=config_dir,
        positions=load_yaml(positions_path),
        watchlist=load_yaml(config_dir / "watchlist.yaml"),
        strategy_pack=load_yaml(config_dir / "strategy_pack.yaml"),
        positions_path=positions_path,
    )


def now_cn() -> datetime:
    return datetime.now(tz=CN_TZ)


def is_a_share_trading_day(value: datetime) -> bool:
    return value.astimezone(CN_TZ).weekday() < 5


def is_a_share_trading_time(value: datetime) -> bool:
    local = value.astimezone(CN_TZ)
    if not is_a_share_trading_day(local):
        return False
    current = local.time()
    return (
        time(9, 15) <= current <= time(11, 30)
        or time(13, 0) <= current <= time(15, 0)
    )


def position_rows(config: MonitorConfig) -> list[dict]:
    rows: list[dict] = []
    for account in config.positions.get("accounts", []) or []:
        account_name = account.get("name", "")
        for position in account.get("positions", []) or []:
            row = dict(position)
            row["account"] = account_name
            rows.append(row)
    return rows


def watchlist_stock_rows(config: MonitorConfig) -> list[dict]:
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


def _string_items(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    return [str(value)]


def format_watchlist_condition_line(row: dict) -> str:
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


def sector_group_rows(config: MonitorConfig) -> list[dict]:
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


def unique_stock_count(rows: list[dict]) -> int:
    return len({row.get("code") for row in rows if row.get("code")})


def stock_code_to_secid(code: str) -> str | None:
    match = re.fullmatch(r"(\d{6})\.(SH|SZ)", code.strip().upper())
    if not match:
        return None
    pure, market = match.groups()
    return f"{'1' if market == 'SH' else '0'}.{pure}"


def collect_quote_targets(config: MonitorConfig) -> dict[str, str]:
    targets = dict(MARKET_INDEXES)
    seen_secids = set(targets.values())
    for row in position_rows(config) + watchlist_stock_rows(config):
        code = str(row.get("code", ""))
        secid = stock_code_to_secid(code)
        if secid and secid not in seen_secids:
            label = f"{row.get('name', '')}({code})"
            targets[label] = secid
            seen_secids.add(secid)
    for row in sector_group_rows(config):
        code = str(row.get("code", ""))
        secid = stock_code_to_secid(code)
        if secid and secid not in seen_secids:
            label = f"{row.get('group_name', '')}/{row.get('name', '')}({code})"
            targets[label] = secid
            seen_secids.add(secid)
    return targets


def parse_eastmoney_quote_rows(rows: list[dict], targets: dict[str, str]) -> list[dict]:
    reverse = {secid: label for label, secid in targets.items()}
    quotes = []
    for item in rows:
        code = item.get("f12")
        market = item.get("f13")
        secid = f"{market}.{code}" if market not in (None, "") and code else None
        label = reverse.get(secid or "")
        if not label:
            matches = [
                name for name, target in targets.items() if target.endswith(f".{code}")
            ]
            label = matches[0] if len(matches) == 1 else item.get("f14", "")

        quotes.append(
            {
                "secid": secid,
                "label": label,
                "code": code,
                "name": item.get("f14"),
                "latest": item.get("f2"),
                "pct_change": item.get("f3"),
                "change": item.get("f4"),
                "volume": item.get("f5"),
                "amount": item.get("f6"),
                "high": item.get("f15"),
                "low": item.get("f16"),
                "open": item.get("f17"),
                "previous_close": item.get("f18"),
            }
        )
    return quotes


def chunk_quote_targets(
    targets: dict[str, str],
    *,
    chunk_size: int = QUOTE_CHUNK_SIZE,
) -> list[dict[str, str]]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    items = list(targets.items())
    return [
        dict(items[index : index + chunk_size])
        for index in range(0, len(items), chunk_size)
    ]


def fetch_eastmoney_quotes(targets: dict[str, str], timeout: float = 8.0) -> dict:
    if not targets:
        return {"source": "eastmoney_push2", "quotes": [], "errors": ["empty targets"]}

    started = time_module.perf_counter()
    quotes: list[dict] = []
    errors: list[str] = []
    for chunk in chunk_quote_targets(targets):
        chunk_result = _fetch_eastmoney_quote_chunk_adaptive(chunk, timeout=timeout)
        quotes.extend(chunk_result.get("quotes", []) or [])
        errors.extend(chunk_result.get("errors", []) or [])

    return {
        "source": "eastmoney_push2",
        "quotes": quotes,
        "errors": errors,
        "elapsed_ms": round((time_module.perf_counter() - started) * 1000, 1),
    }


def _fetch_eastmoney_quote_chunk_adaptive(
    targets: dict[str, str],
    timeout: float = 8.0,
    depth: int = 1,
) -> dict:
    result = _fetch_eastmoney_quote_chunk(targets, timeout=timeout)
    if not result.get("errors") or len(targets) <= 1 or depth <= 0:
        return result

    split_results = [
        _fetch_eastmoney_quote_chunk_adaptive(chunk, timeout=timeout, depth=depth - 1)
        for chunk in chunk_quote_targets(targets, chunk_size=max(1, len(targets) // 2))
    ]
    quotes = [
        quote
        for split_result in split_results
        for quote in split_result.get("quotes", []) or []
    ]
    errors = [
        error
        for split_result in split_results
        for error in split_result.get("errors", []) or []
    ]
    if quotes:
        return {"source": "eastmoney_push2", "quotes": quotes, "errors": errors}
    return result


def _fetch_eastmoney_quote_chunk(targets: dict[str, str], timeout: float = 8.0) -> dict:
    params = urllib.parse.urlencode(
        {
            "fltt": "2",
            "invt": "2",
            "fields": QUOTE_FIELDS,
            "secids": ",".join(targets.values()),
        },
        safe=",",
    )
    url = f"{EASTMONEY_QUOTE_URL}?{params}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"},
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # pragma: no cover - network dependent
        curl_payload = _fetch_eastmoney_quote_chunk_with_curl(
            url, targets, timeout=timeout
        )
        if not curl_payload.get("errors"):
            return curl_payload
        return {
            "source": "eastmoney_push2",
            "quotes": [],
            "errors": [str(exc), *curl_payload.get("errors", [])],
        }

    rows = (payload.get("data") or {}).get("diff") or []
    quotes = parse_eastmoney_quote_rows(rows, targets)

    return {
        "source": "eastmoney_push2",
        "quotes": quotes,
        "errors": [],
    }


def _fetch_eastmoney_quote_chunk_with_curl(
    url: str,
    targets: dict[str, str],
    timeout: float = 8.0,
) -> dict:
    try:
        result = subprocess.run(
            [
                "curl",
                "-fsSL",
                "--max-time",
                str(int(timeout)),
                "-H",
                "User-Agent: Mozilla/5.0",
                url,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
    except Exception as exc:  # pragma: no cover - subprocess/network dependent
        return {"source": "eastmoney_push2", "quotes": [], "errors": [str(exc)]}

    rows = (payload.get("data") or {}).get("diff") or []
    return {
        "source": "eastmoney_push2",
        "quotes": parse_eastmoney_quote_rows(rows, targets),
        "errors": [],
    }




def fetch_tencent_quotes(targets: dict[str, str]) -> dict:
    """腾讯财经备用接口，当东方财富不可用时调用。"""
    if not targets:
        return {"source": "tencent_gtimg", "quotes": [], "errors": ["empty targets"]}

    import urllib.request
    import re

    def to_tencent_code(code_str: str) -> str | None:
        code = str(code_str).strip().upper()
        # 处理 secid 格式: "1.000001" (1=SH, 0=SZ)
        match = __import__('re').match(r'([10])\.(\d{6})', code)
        if match:
            mkt, num = match.groups()
            return f"{'sh' if mkt == '1' else 'sz'}{num}"
        # 处理 "000001.SZ" 格式
        match = __import__('re').match(r'(\d{6})\.(SH|SZ)', code)
        if match:
            num, mkt = match.groups()
            return f"{'sh' if mkt == 'SH' else 'sz'}{num}"
        # 处理纯数字
        if __import__('re').match(r'\d{6}$', code):
            if code.startswith(('600', '601', '603', '605', '688', '689')):
                return f"sh{code}"
            else:
                return f"sz{code}"
        return None

    # 构建腾讯格式代码映射
    tencent_map: dict[str, str] = {}  # tencent_code -> original secid
    name_map: dict[str, str] = {}  # tencent_code -> label
    for label, secid in targets.items():
        tc = to_tencent_code(secid)
        if tc:
            tencent_map[tc] = secid
            name_map[tc] = label

    if not tencent_map:
        return {"source": "tencent_gtimg", "quotes": [], "errors": ["no valid codes"]}

    started = __import__('time').perf_counter()
    all_quotes: list[dict] = []
    tencent_codes = list(tencent_map.keys())
    chunk_size = 60

    for i in range(0, len(tencent_codes), chunk_size):
        chunk = tencent_codes[i:i + chunk_size]
        url = f"https://qt.gtimg.cn/q={','.join(chunk)}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read().decode('gbk')
            for line in data.strip().split(';'):
                line = line.strip()
                if not line or not line.startswith('v_'):
                    continue
                match = __import__('re').match(r'v_(\w+)="(.+)"', line)
                if not match:
                    continue
                tc_code, content = match.groups()
                parts = content.split('~')
                if len(parts) < 35:
                    continue
                latest = _to_float(parts[3])
                prev = _to_float(parts[4])
                open_price = _to_float(parts[5])
                high = _to_float(parts[33])
                low = _to_float(parts[34])
                volume = _to_float(parts[6])
                amount = _to_float(parts[37]) if len(parts) > 37 else None
                pct_change = None
                change = None
                if latest is not None and prev is not None and prev > 0:
                    pct_change = round((latest - prev) / prev * 100, 2)
                    change = round(latest - prev, 2)

                all_quotes.append({
                    "secid": tencent_map.get(tc_code, tc_code),
                    "label": name_map.get(tc_code, parts[1]),
                    "code": parts[2],
                    "name": parts[1],
                    "latest": parts[3],
                    "previous_close": parts[4],
                    "open": parts[5],
                    "high": parts[33] if high is not None else None,
                    "low": parts[34] if low is not None else None,
                    "volume": parts[6],
                    "amount": parts[37] if len(parts) > 37 else None,
                    "pct_change": pct_change,
                    "change": change,
                })
        except Exception as exc:
            return {
                "source": "tencent_gtimg",
                "quotes": all_quotes,
                "errors": [str(exc)],
                "elapsed_ms": round((__import__('time').perf_counter() - started) * 1000, 1),
            }

    return {
        "source": "tencent_gtimg",
        "quotes": all_quotes,
        "errors": [],
        "elapsed_ms": round((__import__('time').perf_counter() - started) * 1000, 1),
    }


def fetch_sina_quotes(targets: dict[str, str]) -> dict:
    """新浪财经备用接口，当腾讯不可用时调用。

    新浪接口支持批量查询，格式: https://hq.sinajs.cn/list=sh600519,sz000001
    返回格式: var hq_str_sh600519="贵州茅台,1740.00,...";
    """
    if not targets:
        return {"source": "sina_hq", "quotes": [], "errors": ["empty targets"]}

    def to_sina_code(secid: str) -> str | None:
        code = str(secid).strip().upper()
        match = __import__('re').match(r'([10])\.(\d{6})', code)
        if match:
            mkt, num = match.groups()
            return f"{'sh' if mkt == '1' else 'sz'}{num}"
        match = __import__('re').match(r'(\d{6})\.(SH|SZ)', code)
        if match:
            num, mkt = match.groups()
            return f"{'sh' if mkt == 'SH' else 'sz'}{num}"
        if __import__('re').match(r'\d{6}$', code):
            if code.startswith(('600', '601', '603', '605', '688', '689')):
                return f"sh{code}"
            else:
                return f"sz{code}"
        return None

    # 构建映射: sina_code -> (original_secid, label)
    sina_map: dict[str, tuple[str, str]] = {}
    for label, secid in targets.items():
        sc = to_sina_code(secid)
        if sc:
            sina_map[sc] = (secid, label)

    if not sina_map:
        return {"source": "sina_hq", "quotes": [], "errors": ["no valid codes"]}

    started = __import__('time').perf_counter()
    all_quotes: list[dict] = []
    sina_codes = list(sina_map.keys())
    chunk_size = 80  # 新浪接口批量限制

    for i in range(0, len(sina_codes), chunk_size):
        chunk = sina_codes[i:i + chunk_size]
        url = f"https://hq.sinajs.cn/list={','.join(chunk)}"
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Referer": "https://finance.sina.com.cn",
                },
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read().decode('gbk')

            for line in data.strip().split('\n'):
                line = line.strip()
                if not line.startswith('var hq_str_'):
                    continue
                match = __import__('re').match(r'var hq_str_(\w+)="(.+)";', line)
                if not match:
                    continue
                sina_code, content = match.groups()
                if not content or content == '""':
                    continue
                parts = content.split(',')
                if len(parts) < 5:
                    continue

                secid, label = sina_map.get(sina_code, (sina_code, sina_code))
                name = parts[0]
                # 指数格式: 名称,今开,昨收,最新,最高,最低
                # 股票格式: 名称,今开,昨收,最新,最高,最低,买入价,卖出价,成交量,成交额...
                open_price = _to_float(parts[1])
                prev = _to_float(parts[2])
                latest = _to_float(parts[3])
                high = _to_float(parts[4])
                low = _to_float(parts[5]) if len(parts) > 5 else None
                volume = _to_float(parts[8]) if len(parts) > 8 else None
                amount = _to_float(parts[9]) if len(parts) > 9 else None

                pct_change = None
                change = None
                if latest is not None and prev is not None and prev > 0:
                    pct_change = round((latest - prev) / prev * 100, 2)
                    change = round(latest - prev, 2)

                all_quotes.append({
                    "secid": secid,
                    "label": label,
                    "code": sina_code[2:],  # 去掉 sh/sz 前缀
                    "name": name,
                    "latest": latest,
                    "previous_close": prev,
                    "open": open_price,
                    "high": high,
                    "low": low,
                    "volume": volume,
                    "amount": amount,
                    "pct_change": pct_change,
                    "change": change,
                })
        except Exception as exc:
            return {
                "source": "sina_hq",
                "quotes": all_quotes,
                "errors": [str(exc)],
                "elapsed_ms": round((__import__('time').perf_counter() - started) * 1000, 1),
            }

    return {
        "source": "sina_hq",
        "quotes": all_quotes,
        "errors": [],
        "elapsed_ms": round((__import__('time').perf_counter() - started) * 1000, 1),
    }


def fetch_quotes_with_fallback(targets: dict[str, str]) -> dict:
    """多数据源降级获取行情：腾讯优先 → 新浪 → 东财兜底 → 缓存。

    降级策略（基于服务器IP限流经验）：
    1. 腾讯(gtimg): 最稳定，对服务器IP友好，优先尝试
    2. 新浪(hq.sinajs.cn): 备用，覆盖大部分A股
    3. 东财(push2.eastmoney.com): 数据最全但限流严格，最后尝试
    4. 都失败: 返回缓存数据 + 警告
    """
    # 尝试1: 腾讯（最稳定）
    tencent_result = fetch_tencent_quotes(targets)
    tencent_quotes = tencent_result.get("quotes", []) or []
    tencent_errors = tencent_result.get("errors", []) or []
    if len(tencent_quotes) >= len(targets) * 0.8 and not tencent_errors:
        return tencent_result

    # 尝试2: 新浪（备用）
    sina_result = fetch_sina_quotes(targets)
    sina_quotes = sina_result.get("quotes", []) or []
    sina_errors = sina_result.get("errors", []) or []
    if sina_quotes and not sina_errors:
        # 合并腾讯已获取的数据 + 新浪补充
        if tencent_quotes:
            merged = _merge_quotes(tencent_quotes, sina_quotes)
            return {
                "source": "tencent_gtimg+sina_hq",
                "quotes": merged,
                "errors": [],
                "elapsed_ms": (
                    tencent_result.get("elapsed_ms", 0) + sina_result.get("elapsed_ms", 0)
                ),
            }
        return sina_result

    # 尝试3: 东财（数据最全但限流严格）
    em_result = fetch_eastmoney_quotes(targets)
    em_quotes = em_result.get("quotes", []) or []
    em_errors = em_result.get("errors", []) or []
    if em_quotes and not em_errors:
        return em_result

    # 兜底: 返回任何可用的数据 + 合并警告
    best_result = tencent_result if tencent_quotes else (sina_result if sina_quotes else em_result)
    best_quotes = best_result.get("quotes", []) or []

    if best_quotes:
        # 合并所有可用数据源
        merged = best_quotes
        if tencent_quotes and best_result is not tencent_result:
            merged = _merge_quotes(merged, tencent_quotes)
        if sina_quotes and best_result is not sina_result:
            merged = _merge_quotes(merged, sina_quotes)
        if em_quotes and best_result is not em_result:
            merged = _merge_quotes(merged, em_quotes)

        all_errors = []
        if tencent_errors:
            all_errors.append(f"腾讯: {tencent_errors[0][:80]}")
        if sina_errors:
            all_errors.append(f"新浪: {sina_errors[0][:80]}")
        if em_errors:
            all_errors.append(f"东财: {em_errors[0][:80]}")

        return {
            "source": "fallback_merged",
            "quotes": merged,
            "errors": all_errors,
            "elapsed_ms": best_result.get("elapsed_ms", 0),
        }

    # 完全失败
    return {
        "source": "all_failed",
        "quotes": [],
        "errors": [
            f"所有数据源失败。腾讯: {tencent_errors[:1]}; 新浪: {sina_errors[:1]}; 东财: {em_errors[:1]}"
        ],
    }


def _merge_quotes(base: list[dict], extra: list[dict]) -> list[dict]:
    """合并两个quote列表，以base为主，extra补充缺失的secid。"""
    seen = {q.get("secid"): q for q in base if q.get("secid")}
    for q in extra:
        secid = q.get("secid")
        if secid and secid not in seen:
            seen[secid] = q
    return list(seen.values())


def format_quote_line(quote: dict) -> str:
    return (
        "- {label}: 最新={latest} 涨跌幅={pct}% 涨跌={change} "
        "开={open} 高={high} 低={low} 昨收={prev} 成交额={amount}"
    ).format(
        label=quote.get("label") or quote.get("name") or quote.get("code"),
        latest=quote.get("latest"),
        pct=quote.get("pct_change"),
        change=quote.get("change"),
        open=quote.get("open"),
        high=quote.get("high"),
        low=quote.get("low"),
        prev=quote.get("previous_close"),
        amount=quote.get("amount"),
    )


def format_status_message(config: MonitorConfig, value: datetime) -> str:
    positions = position_rows(config)
    watch_stocks = watchlist_stock_rows(config)
    theme_count = len(config.watchlist.get("themes", []) or [])
    buy_setup_count = sum(1 for row in watch_stocks if row.get("buy_setup"))
    invalidation_setup_count = sum(
        1 for row in watch_stocks if row.get("invalidation_setup")
    )
    sell_setup_count = sum(1 for row in watch_stocks if row.get("sell_setup"))
    stage = (
        config.strategy_pack.get("market_framework", {})
        .get("current_stage", "未配置")
    )
    trading_state = "交易时段内" if is_a_share_trading_time(value) else "非交易时段"
    path_note = "private" if config.positions_path.name == "positions.yaml" else "example"

    return "\n".join(
        [
            "[Hermes股票监控状态]",
            f"时间：{value.astimezone(CN_TZ).strftime('%Y-%m-%d %H:%M:%S %Z')}",
            f"交易状态：{trading_state}",
            f"持仓配置：{config.positions_path} ({path_note})",
            f"持仓条目：{len(positions)}",
            f"观察主题：{theme_count}",
            f"观察标的：{unique_stock_count(watch_stocks)}",
            f"观察池买入条件：{buy_setup_count}",
            f"观察池买点失效条件：{invalidation_setup_count}",
            f"持仓卖出/做T条件：{sell_setup_count}",
            f"当前框架：{stage}",
            "提醒策略：默认只在触发条件时输出；空输出表示静默。",
        ]
    )


def format_smoke_message(config: MonitorConfig, value: datetime) -> str:
    return "\n".join(
        [
            "[Hermes股票监控测试]",
            "这是一条手动 smoke test，不代表买卖建议。",
            format_status_message(config, value),
            "下一步：接入实时行情后，cron tick 将只在触发买入/卖出/风控条件时输出。",
        ]
    )


def format_analysis_context(config: MonitorConfig, value: datetime) -> str:
    positions = position_rows(config)
    watch_stocks = watchlist_stock_rows(config)
    stage = config.strategy_pack.get("market_framework", {}).get(
        "current_stage", "未配置"
    )
    core_question = config.strategy_pack.get("market_framework", {}).get(
        "core_question", "未配置"
    )
    rules = config.strategy_pack.get("position_rules", []) or []

    lines = [
        "[Hermes股票监控分析上下文]",
        f"时间：{value.astimezone(CN_TZ).strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"交易状态：{'交易时段内' if is_a_share_trading_time(value) else '非交易时段'}",
        f"当前框架：{stage}",
        f"核心问题：{core_question}",
        "",
        "=== 持仓池（positions.yaml）===",
        f"状态：{'【空仓】当前无持仓' if not positions else f'共 {len(positions)} 只持仓'}",
        "",
        "重要区分：",
        "- 持仓池 = 你当前实际持有的股票（来自 positions.yaml）",
        "- 观察池 = 你关注但尚未买入的股票（来自 watchlist.yaml）",
        "- 严禁将观察池标的当作持仓分析！",
        "",
        "持仓明细：",
    ]
    if not positions:
        lines.append("  （无持仓）")
    for row in positions:
        lines.append(
            "- {account} {name}({code}) 股数={shares} 成本={cost} 策略={strategy} 风险线={risk}".format(
                account=row.get("account", ""),
                name=row.get("name", ""),
                code=row.get("code", ""),
                shares=row.get("shares", ""),
                cost=row.get("cost", ""),
                strategy=row.get("strategy", ""),
                risk=row.get("risk_line") or row.get("risk_zone", ""),
            )
        )

    lines.extend(["", "=== 观察池（watchlist.yaml）===", "这些标的尚未买入，仅作观察："])
    for row in watch_stocks:
        lines.append(
            "- {theme} / {role}: {name}({code}) {reason}".format(
                theme=row.get("theme_name", ""),
                role=row.get("role", ""),
                name=row.get("name", ""),
                code=row.get("code", ""),
                reason=row.get("watch_reason", ""),
            )
        )
        condition_line = format_watchlist_condition_line(row)
        if condition_line:
            lines.append(f"  条件：{condition_line}")

    lines.extend(["", "核心规则："])
    for rule in rules:
        lines.append(
            "- {name}: {action}".format(
                name=rule.get("name", ""),
                action=rule.get("action", ""),
            )
        )

    lines.extend(
        [
            "",
            "请基于本项目 AGENTS.md 和 qing-stock-analysis 框架输出：",
            "1. 当前持仓分层",
            "2. 下一次交易时段最重要的观察信号",
            "3. 哪些情况需要微信提醒",
            "4. 不要给无条件买卖指令；必须写触发条件和证伪条件",
        ]
    )
    return "\n".join(lines)


def format_live_analysis_context(config: MonitorConfig, value: datetime) -> str:
    targets = collect_quote_targets(config)
    quote_snapshot = fetch_quotes_with_fallback(targets)
    base_context = format_analysis_context(config, value)
    positions = position_rows(config)
    position_status = "空仓" if not positions else f"持仓{len(positions)}只"

    lines = [
        base_context,
        "",
        "实时行情快照：",
        f"数据源：{quote_snapshot.get('source')}",
        f"行情请求耗时：{quote_snapshot.get('elapsed_ms')} ms",
        f"请求标的数：{len(targets)}",
    ]
    errors = quote_snapshot.get("errors") or []
    if errors:
        lines.append(f"行情错误：{'; '.join(errors)}")
    else:
        for quote in quote_snapshot.get("quotes", []):
            lines.append(format_quote_line(quote))

    lines.extend(
        [
            "",
            "【⚠️ 数据优先级】实时行情快照（上方的实际价格和涨跌幅）优先于下方 config 配置文件中的参考价。如果实时行情快照中有标的的最新价/涨跌幅，请以实时行情为准，不要用配置文件中的陈旧参考价(current_ref)。",
            "",
            "请把上述实时行情作为盘面证据，输出极简微信提醒。",
            "只回答：观察池现在能不能买、持仓池现在怎么操作。",
            "【重要】当前持仓状态：" + position_status,
            "【重要】观察池标的 ≠ 持仓，严禁混淆！",
            "最多450字，禁止Markdown表格、分级标题、长篇数据罗列和研报式分析。",
            "必须按下面换行模板输出，禁止把多只股票写成同一段：",
            "【盘面】一句话定性（含全A涨跌幅+强/弱修复+明日预期）。",
            "【重点分析】1-2只重点票，每只80-100字。",
            "【其他持仓】每只15字。",
            "【观察池】最多3只，每只15字。",
            "【脚注】数据源=...；时间=...；异常=...",
            "不要给无条件买卖指令。",
        ]
    )
    return "\n".join(lines)


def validate_position_price_zones(
    config: MonitorConfig,
    quote_snapshot: dict,
) -> list[dict]:
    """检查持仓的 risk_zone / reduce_zone 是否与当前价格距离过大（防失真）。

    返回 stale_warnings 列表，每个条目包含 position 信息和警告原因。
    规则：
    - reduce_zone 上限距现价 > 12% → 向上失真（提醒下调）
    - risk_zone 下限 > 现价（已被跌破）→ 向下失真（提醒已触发但未更新）
    - reduce_zone / risk_zone 缺失 → 高危漏报
    """
    quotes = _quotes_by_code(quote_snapshot)
    warnings: list[dict] = []

    for row in position_rows(config):
        code = str(row.get("code", ""))
        name = str(row.get("name", ""))
        quote = _quote_for_stock(quotes, code)
        latest = _to_float((quote or {}).get("latest"))
        if latest is None:
            continue

        reduce_zone = parse_price_zone(row.get("reduce_zone"))
        risk_zone = parse_price_zone(row.get("risk_zone") or row.get("risk_line"))

        # 高危：两个区间都缺失
        if reduce_zone is None and risk_zone is None:
            warnings.append({
                "code": code,
                "name": name,
                "issue": "missing_all_zones",
                "detail": f"缺少 reduce_zone 和 risk_zone，跌停/大跌将无提醒",
                "latest": latest,
            })
            continue

        # 检查 reduce_zone 是否过高（向上失真）
        if reduce_zone:
            gap_pct = round((reduce_zone[0] - latest) / latest * 100, 1)
            if gap_pct > 12:
                warnings.append({
                    "code": code,
                    "name": name,
                    "issue": "reduce_zone_stale_high",
                    "detail": f"reduce_zone={_format_zone(reduce_zone)}，距现价{latest}+{gap_pct}%，已失真，建议下调",
                    "latest": latest,
                    "gap_pct": gap_pct,
                })

        # 检查 risk_zone 是否已被跌破（向下失真）
        if risk_zone:
            if latest < risk_zone[0]:
                gap_pct = round((risk_zone[0] - latest) / latest * 100, 1)
                warnings.append({
                    "code": code,
                    "name": name,
                    "issue": "risk_zone_breached",
                    "detail": f"risk_zone={_format_zone(risk_zone)}，现价{latest}已跌破下限+{gap_pct}%，风险线已失效",
                    "latest": latest,
                    "gap_pct": gap_pct,
                })

    return warnings


def run_tick(
    config: MonitorConfig,
    value: datetime,
    *,
    emit_status: bool,
    ignore_trading_time: bool,
    quote_fetcher=fetch_quotes_with_fallback,
    state_path: Path | None = None,
    dedupe_minutes: int = 30,
    agent_context_on_trigger: bool = False,
    agent_json_context: bool = False,
    agent_any_time: bool = False,
) -> str:
    """Run one monitor tick.

    If agent_any_time=True, bypass the agent_analysis_schedule time restriction
    and always produce an agent trigger when --agent-json-context or
    --agent-context-on-trigger is used. This lets cron jobs run at arbitrary
    times without needing the time to be listed in strategy_pack.yaml.
    """
    scheduled_agent_time = (agent_context_on_trigger or agent_json_context) and is_scheduled_agent_analysis_time(
        config, value
    )
    if (
        not ignore_trading_time
        and not is_a_share_trading_time(value)
        and not scheduled_agent_time
    ):
        return ""
    if emit_status:
        return format_status_message(config, value)
    quote_snapshot = quote_fetcher(collect_quote_targets(config))
    # 防失真检查：验证持仓价格区间是否与当前行情匹配
    stale_warnings = validate_position_price_zones(config, quote_snapshot)
    alerts = evaluate_monitor_alerts(config, quote_snapshot, current_time=value)
    resolved_state_path = state_path or config.config_dir / "state.json"
    state = load_monitor_state(resolved_state_path)
    state["version"] = 1
    state["last_updated"] = value.astimezone(CN_TZ).isoformat()
    if stale_warnings:
        state["stale_zone_warnings"] = stale_warnings
    if quote_snapshot.get("quotes"):
        state["last_quote_snapshot"] = quote_snapshot
        state.pop("last_fetch_error", None)
    elif quote_snapshot.get("errors"):
        state["last_fetch_error"] = {
            "time": value.astimezone(CN_TZ).isoformat(),
            "source": quote_snapshot.get("source", "unknown"),
            "errors": quote_snapshot.get("errors", []),
            "elapsed_ms": quote_snapshot.get("elapsed_ms"),
        }

    # ── Phase 4: 同步买入候选到 daily_state ──
    try:
        from qing_investment.agent.tools.daily_state import (
            load_daily_state,
            save_daily_state,
            sync_buy_candidates,
        )
        daily_state = load_daily_state()
        candidates = evaluate_buy_signal_candidates(config, quote_snapshot)
        candidate_dicts = [
            {
                "stock_code": c.stock_code,
                "stock_name": c.stock_name,
                "price": c.price,
                "entry_zone": list(c.entry_zone) if c.entry_zone else None,
                "stop_loss": c.stop_loss,
                "matched_conditions": c.matched_conditions,
                "odds_analysis": c.odds_analysis,
            }
            for c in candidates if c.is_candidate
        ]
        if candidate_dicts:
            daily_state = sync_buy_candidates(daily_state, candidate_dicts, now=value)
            save_daily_state(daily_state)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Sync buy candidates to daily_state failed: %s", e)

    notification_policy = config.strategy_pack.get("notification_policy", {}) or {}
    dedupe_by_type = notification_policy.get("dedupe_by_type", {}) or {}
    new_alerts = filter_new_alerts(
        alerts, state, value, dedupe_minutes=dedupe_minutes, dedupe_by_type=dedupe_by_type
    )
    update_sector_signal_counts(state, alerts, value)
    update_market_state(state, alerts, quote_snapshot, value)
    record_alert_decision_log(state, alerts, new_alerts, value)
    agent_trigger = None
    if agent_context_on_trigger or agent_json_context:
        if agent_any_time:
            agent_trigger = find_any_agent_analysis_trigger(config, state, value, new_alerts)
        else:
            agent_trigger = find_agent_analysis_trigger(config, state, value, new_alerts)
    if new_alerts:
        record_emitted_alerts(state, new_alerts, value)
    save_monitor_state(resolved_state_path, state)
    if agent_trigger:
        record_agent_analysis_trigger(state, agent_trigger, value)
        save_monitor_state(resolved_state_path, state)
        if agent_json_context:
            return format_agent_json_context(
                config,
                value,
                agent_trigger,
                new_alerts,
                quote_snapshot,
                state,
            )
        return format_agent_analysis_context(
            config,
            value,
            agent_trigger,
            new_alerts,
            quote_snapshot,
            state,
        )
    if new_alerts:
        return format_alerts_message(new_alerts, value, quote_snapshot)
    return ""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Hermes-friendly A-share stock monitor entrypoint."
    )
    parser.add_argument(
        "--config-dir",
        default=str(DEFAULT_CONFIG_DIR),
        help="Path to config/stock_monitor.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print monitor configuration status and exit.",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Print a test notification body and exit.",
    )
    parser.add_argument(
        "--emit-status-on-tick",
        action="store_true",
        help="During trading time, emit status even without market triggers.",
    )
    parser.add_argument(
        "--ignore-trading-time",
        action="store_true",
        help="Bypass A-share trading time guard for temporary tests.",
    )
    parser.add_argument(
        "--analysis-context",
        action="store_true",
        help="Print a Hermes-friendly analysis context and exit.",
    )
    parser.add_argument(
        "--live-analysis-context",
        action="store_true",
        help="Fetch live Eastmoney quotes, print an analysis context, and exit.",
    )
    parser.add_argument(
        "--state-file",
        default=None,
        help="JSON state file for quote snapshots and alert de-duplication.",
    )
    parser.add_argument(
        "--dedupe-minutes",
        type=int,
        default=30,
        help="Suppress the same alert for this many minutes. Use 0 to disable.",
    )
    parser.add_argument(
        "--agent-context-on-trigger",
        action="store_true",
        help=(
            "Emit Hermes model analysis context at configured key times or when "
            "new rule alerts trigger."
        ),
    )
    parser.add_argument(
        "--agent-json-context",
        action="store_true",
        help=(
            "Emit structured JSON context for qing-agent HTTP API at configured "
            "key times or when new rule alerts trigger."
        ),
    )
    parser.add_argument(
        "--agent-any-time",
        action="store_true",
        help=(
            "Bypass agent_analysis_schedule time restriction. "
            "Always produce agent context when --agent-json-context is used, "
            "regardless of whether current time is in the schedule."
        ),
    )
    parser.add_argument(
        "--daily-review-context",
        action="store_true",
        help="Print an end-of-day monitoring review context from the state file.",
    )
    parser.add_argument(
        "--freshness-check",
        action="store_true",
        help="Run knowledge-base freshness check (unprocessed raw docs, stale claims).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_monitor_config(Path(args.config_dir))
    current = now_cn()

    if args.smoke:
        print(format_smoke_message(config, current))
        return 0
    if args.status:
        print(format_status_message(config, current))
        return 0
    if args.analysis_context:
        print(format_analysis_context(config, current))
        return 0
    if args.live_analysis_context:
        print(format_live_analysis_context(config, current))
        return 0
    if args.daily_review_context:
        state_path = Path(args.state_file) if args.state_file else config.config_dir / "state.json"
        state = load_monitor_state(state_path)
        print(format_daily_review_context(config, current, state))

        # ── Phase 1.4: 收盘复盘自动提取昨日特征摘要 ──
        # 从 state.json 的 last_quote_snapshot 提取并保存
        qs = state.get("last_quote_snapshot", {})
        if qs and qs.get("quotes"):
            try:
                daily_state = json.loads(
                    (config.config_dir / "daily_state.json").read_text(encoding="utf-8")
                ) if (config.config_dir / "daily_state.json").exists() else None
            except Exception:
                daily_state = None

            summary = _build_yesterday_summary(config, qs, state, daily_state)
            _save_yesterday_summary(summary, config.config_dir)
            logger.info("收盘复盘: 昨日特征摘要已自动构建并保存 (%s 条持仓)",
                         len(summary.get("positions", {})))

            # ── 龙虎榜全市场总榜（17:00 数据已就绪）──
            try:
                date_today = _state_date(current)
                raw_board = _fetch_daily_dragon_tiger_board(date_today)
                if raw_board.get("available") and raw_board.get("board"):
                    board_filtered = _filter_dragon_tiger_board(raw_board["board"], config)
                    # 将龙虎榜数据保存到 summary 的 market 字段中
                    summary["dragon_tiger_board"] = {
                        "board_count": len(raw_board["board"]),
                        "watch_dt_items": board_filtered.get("watch_dt_items", []),
                        "dt_nettop5": board_filtered.get("dt_nettop5", []),
                        "dt_sector_summary": board_filtered.get("dt_sector_summary", {}),
                        "fetched_at": raw_board.get("fetched_at"),
                    }
                    _save_yesterday_summary(summary, config.config_dir)
                    logger.info("龙虎榜总榜已采集: %d 只上榜, %d 只持仓/观察池命中",
                                 len(raw_board["board"]),
                                 len(board_filtered.get("watch_dt_items", [])))
            except Exception as e:
                logger.warning("龙虎榜总榜采集失败（不影响主流程）: %s", e)
        else:
            logger.warning("收盘复盘: last_quote_snapshot 无数据，skip 特征摘要保存")
        return 0

    if args.freshness_check:
        import subprocess
        repo_root = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            [sys.executable, str(repo_root / "scripts" / "freshness_check.py")],
            capture_output=True,
            text=True,
        )
        print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        return result.returncode

    message = run_tick(
        config,
        current,
        emit_status=args.emit_status_on_tick,
        ignore_trading_time=args.ignore_trading_time,
        state_path=Path(args.state_file) if args.state_file else None,
        dedupe_minutes=args.dedupe_minutes,
        agent_context_on_trigger=args.agent_context_on_trigger,
        agent_json_context=args.agent_json_context,
        agent_any_time=args.agent_any_time,
    )
    if message:
        print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
