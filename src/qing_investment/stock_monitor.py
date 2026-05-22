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
QUOTE_FIELDS = "f12,f14,f2,f3,f4,f5,f6,f15,f16,f17,f18"
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
    for row in position_rows(config) + watchlist_stock_rows(config):
        code = str(row.get("code", ""))
        secid = stock_code_to_secid(code)
        if secid:
            label = f"{row.get('name', '')}({code})"
            targets[label] = secid
    return targets


def fetch_eastmoney_quotes(targets: dict[str, str], timeout: float = 8.0) -> dict:
    if not targets:
        return {"source": "eastmoney_push2", "quotes": [], "errors": ["empty targets"]}

    reverse = {secid: label for label, secid in targets.items()}
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
    quotes = []
    for item in rows:
        secid = f"{item.get('f13', '')}.{item.get('f12', '')}"
        # ulist may omit f13 depending on endpoint response; reconstruct by lookup.
        label = reverse.get(secid) or next(
            (name for name, target in targets.items() if target.endswith(f".{item.get('f12')}")),
            item.get("f14", ""),
        )
        latest = item.get("f2")
        previous_close = item.get("f18")
        quotes.append(
            {
                "label": label,
                "code": item.get("f12"),
                "name": item.get("f14"),
                "latest": latest,
                "pct_change": item.get("f3"),
                "change": item.get("f4"),
                "volume": item.get("f5"),
                "amount": item.get("f6"),
                "high": item.get("f15"),
                "low": item.get("f16"),
                "open": item.get("f17"),
                "previous_close": previous_close,
            }
        )

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
) -> str:
    if not ignore_trading_time and not is_a_share_trading_time(value):
        return ""
    if emit_status:
        return format_status_message(config, value)
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
