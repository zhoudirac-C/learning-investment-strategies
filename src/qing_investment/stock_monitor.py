from __future__ import annotations

import argparse
import json
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


DEFAULT_AGENT_ANALYSIS_SCHEDULE = [
    {
        "id": "open_auction",
        "time": "09:26",
        "name": "集合竞价后",
        "focus": "核心持仓和观察池是否超预期高开低开",
    },
    {
        "id": "open_confirm",
        "time": "09:45",
        "name": "开盘15分钟确认",
        "focus": "指数是否失守关键位，科技/CPO/PCB/半导体谁主动",
    },
    {
        "id": "morning_confirm",
        "time": "10:30",
        "name": "30分钟确认",
        "focus": "底部钝化和主线修复质量是否成立",
    },
    {
        "id": "noon_review",
        "time": "11:25",
        "name": "上午收盘前",
        "focus": "上午定性为强修复、弱修复、防御切换还是继续分歧",
    },
    {
        "id": "afternoon_risk",
        "time": "13:30",
        "name": "午后风险窗口",
        "focus": "冲高无扩散时是否需要兑现或减亏",
    },
    {
        "id": "tail_condition",
        "time": "14:55",
        "name": "尾盘条件单",
        "focus": "是否符合尾盘低吸、减仓或规避尾盘杀的条件",
    },
    {
        "id": "close_review",
        "time": "15:05",
        "name": "收盘复盘",
        "focus": "当天监控小结和次日观察重点",
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

    for row in position_rows(config):
        code = str(row.get("code", ""))
        quote = _quote_for_stock(quotes, code)
        latest = _to_float((quote or {}).get("latest"))
        if latest is None:
            continue

        name = str(row.get("name") or (quote or {}).get("name") or "")
        pct_change = (quote or {}).get("pct_change", "")
        reduce_zone = parse_price_zone(row.get("reduce_zone"))
        if reduce_zone and reduce_zone[0] <= latest <= reduce_zone[1]:
            trigger = f"进入预设减仓区{_format_zone(reduce_zone)}"
            summary = (
                f"减仓观察：{name}({code}) 当前价={latest:g} 涨跌幅={pct_change}%；"
                f"{trigger}。只作为降低集中度/做T候选，需再确认板块扩散与分时承接。"
            )
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

        risk_zone = parse_price_zone(row.get("risk_zone") or row.get("risk_line"))
        if risk_zone and latest <= risk_zone[1]:
            trigger = f"触及或跌破风险线{_format_zone(risk_zone)}"
            summary = (
                f"风控观察：{name}({code}) 当前价={latest:g} 涨跌幅={pct_change}%；"
                f"{trigger}。若不能快速收回，需要按仓位纪律降级处理。"
            )
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

    return alerts


def evaluate_market_alerts(
    config: MonitorConfig,
    quote_snapshot: dict,
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
            continue

        alerts.append(
            RuleAlert(
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
        )

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
) -> list[RuleAlert]:
    return (
        evaluate_market_alerts(config, quote_snapshot)
        + evaluate_sector_rotation_alerts(config, quote_snapshot)
        + evaluate_position_alerts(config, quote_snapshot)
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


def filter_new_alerts(
    alerts: list[RuleAlert],
    state: dict,
    value: datetime,
    *,
    dedupe_minutes: int,
) -> list[RuleAlert]:
    if dedupe_minutes <= 0:
        return alerts

    history = state.get("alert_history", {})
    if not isinstance(history, dict):
        history = {}
    current = value.astimezone(CN_TZ)
    fresh: list[RuleAlert] = []
    for alert in alerts:
        last_sent = _parse_state_time(history.get(alert_fingerprint(alert)))
        if last_sent is None:
            fresh.append(alert)
            continue
        elapsed_minutes = (current - last_sent).total_seconds() / 60
        if elapsed_minutes >= dedupe_minutes:
            fresh.append(alert)
    return fresh


def record_emitted_alerts(
    state: dict,
    alerts: list[RuleAlert],
    value: datetime,
) -> None:
    history = state.setdefault("alert_history", {})
    current = value.astimezone(CN_TZ).isoformat()
    for alert in alerts:
        history[alert_fingerprint(alert)] = current


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


def format_agent_analysis_context(
    config: MonitorConfig,
    value: datetime,
    trigger: AgentAnalysisTrigger,
    alerts: list[RuleAlert],
    quote_snapshot: dict,
    state: dict,
) -> str:
    stage = config.strategy_pack.get("market_framework", {}).get(
        "current_stage", "未配置"
    )
    core_question = config.strategy_pack.get("market_framework", {}).get(
        "core_question", "未配置"
    )
    lines = [
        "[Hermes股票监控大模型分析上下文]",
        f"时间：{value.astimezone(CN_TZ).strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"触发类型：{trigger.kind}",
        f"触发点：{trigger.title}",
        f"触发原因：{trigger.reason}",
        f"当前框架：{stage}",
        f"核心问题：{core_question}",
        "",
        "规则信号：",
    ]
    if alerts:
        for alert in alerts:
            lines.append(f"- {alert.summary}")
    else:
        lines.append("- 无新增规则信号；这是固定关键时间点分析。")

    market_state = state.get("last_market_state", {})
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

    sector_counts = state.get("sector_signal_counts", {})
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

    lines.extend(
        [
            "",
            "请按本项目 AGENTS.md 与 qing-stock-analysis 框架输出微信提醒：",
            "1. 用一句话给出当前盘面定性",
            "2. 分持仓说明继续持有、做T观察、减仓观察或风控观察的触发条件",
            "3. 标明证伪条件和下一次观察时间",
            "4. 不要给无条件买卖指令；必须基于触发条件和盘面证据",
        ]
    )
    return "\n".join(lines)


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
        "持仓：",
    ]
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

    lines.extend(["", "观察池："])
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
    quote_snapshot = fetch_eastmoney_quotes(targets)
    base_context = format_analysis_context(config, value)

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
            "请把上述实时行情作为盘面证据，结合持仓成本、观察池和策略包做简短分析。",
            "请特别说明：行情请求耗时、整体判断、持仓分层、触发微信提醒的条件。",
        ]
    )
    return "\n".join(lines)


def run_tick(
    config: MonitorConfig,
    value: datetime,
    *,
    emit_status: bool,
    ignore_trading_time: bool,
    quote_fetcher=fetch_eastmoney_quotes,
    state_path: Path | None = None,
    dedupe_minutes: int = 30,
    agent_context_on_trigger: bool = False,
) -> str:
    scheduled_agent_time = agent_context_on_trigger and is_scheduled_agent_analysis_time(
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
    alerts = evaluate_monitor_alerts(config, quote_snapshot)
    resolved_state_path = state_path or config.config_dir / "state.json"
    state = load_monitor_state(resolved_state_path)
    state["version"] = 1
    state["last_updated"] = value.astimezone(CN_TZ).isoformat()
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
    new_alerts = filter_new_alerts(
        alerts, state, value, dedupe_minutes=dedupe_minutes
    )
    update_sector_signal_counts(state, alerts, value)
    update_market_state(state, alerts, quote_snapshot, value)
    record_alert_decision_log(state, alerts, new_alerts, value)
    agent_trigger = None
    if agent_context_on_trigger:
        agent_trigger = find_agent_analysis_trigger(config, state, value, new_alerts)
    if new_alerts:
        record_emitted_alerts(state, new_alerts, value)
    save_monitor_state(resolved_state_path, state)
    if agent_trigger:
        record_agent_analysis_trigger(state, agent_trigger, value)
        save_monitor_state(resolved_state_path, state)
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
        "--daily-review-context",
        action="store_true",
        help="Print an end-of-day monitoring review context from the state file.",
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
        print(format_daily_review_context(config, current, load_monitor_state(state_path)))
        return 0

    message = run_tick(
        config,
        current,
        emit_status=args.emit_status_on_tick,
        ignore_trading_time=args.ignore_trading_time,
        state_path=Path(args.state_file) if args.state_file else None,
        dedupe_minutes=args.dedupe_minutes,
        agent_context_on_trigger=args.agent_context_on_trigger,
    )
    if message:
        print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
