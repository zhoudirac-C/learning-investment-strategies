from __future__ import annotations

import argparse
import json
import re
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


def fetch_eastmoney_quotes(targets: dict[str, str], timeout: float = 8.0) -> dict:
    if not targets:
        return {"source": "eastmoney_push2", "quotes": [], "errors": ["empty targets"]}

    params = urllib.parse.urlencode(
        {
            "fltt": "2",
            "invt": "2",
            "fields": QUOTE_FIELDS,
            "secids": ",".join(targets.values()),
        }
    )
    request = urllib.request.Request(
        f"{EASTMONEY_QUOTE_URL}?{params}",
        headers={"User-Agent": "Mozilla/5.0"},
    )

    started = time_module.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # pragma: no cover - network dependent
        return {
            "source": "eastmoney_push2",
            "quotes": [],
            "errors": [str(exc)],
            "elapsed_ms": round((time_module.perf_counter() - started) * 1000, 1),
        }

    rows = (payload.get("data") or {}).get("diff") or []
    quotes = parse_eastmoney_quote_rows(rows, targets)

    return {
        "source": "eastmoney_push2",
        "quotes": quotes,
        "errors": [],
        "elapsed_ms": round((time_module.perf_counter() - started) * 1000, 1),
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
) -> str:
    if not ignore_trading_time and not is_a_share_trading_time(value):
        return ""
    if emit_status:
        return format_status_message(config, value)
    quote_snapshot = quote_fetcher(collect_quote_targets(config))
    alerts = evaluate_monitor_alerts(config, quote_snapshot)
    if alerts:
        return format_alerts_message(alerts, value, quote_snapshot)
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

    message = run_tick(
        config,
        current,
        emit_status=args.emit_status_on_tick,
        ignore_trading_time=args.ignore_trading_time,
    )
    if message:
        print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
