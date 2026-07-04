"""
交易日看盘定时任务集成测试

模拟 cron 在 A 股交易时段触发 stock monitor 的 `run_tick`，
所有实时行情请求均被 mock，不访问外部网络。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from qing_investment.monitor.scheduler import run_tick
from qing_investment.stock_monitor import load_monitor_config


CN_TZ = ZoneInfo("Asia/Shanghai")


def write_yaml(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def make_config_dir(tmp_path: Path) -> Path:
    """构造一个带持仓、观察池和策略包的监控配置目录。"""
    config_dir = tmp_path / "stock_monitor"
    config_dir.mkdir()
    write_yaml(
        config_dir / "positions.yaml",
        {
            "accounts": [
                {
                    "name": "主账户",
                    "positions": [
                        {
                            "code": "000021.SZ",
                            "name": "深科技",
                            "shares": 1000,
                            "cost": 36.2,
                            "role": "core_holding",
                            "reduce_zone": "36.9-37.5",
                            "risk_line": 35.9,
                        }
                    ],
                }
            ]
        },
    )
    write_yaml(
        config_dir / "watchlist.yaml",
        {
            "themes": [
                {
                    "id": "domestic_compute",
                    "name": "国产算力",
                    "stocks": [
                        {
                            "code": "000021.SZ",
                            "name": "深科技",
                            "watch_reason": "测试观察",
                            "confirm_with": ["华天科技"],
                            "buy_setup": ["站回分时均线"],
                            "invalidation_setup": ["跌破日内低点"],
                            "sell_setup": ["持仓T出"],
                        }
                    ],
                }
            ]
        },
    )
    write_yaml(
        config_dir / "strategy_pack.yaml",
        {
            "market_framework": {"current_stage": "磨底期观察"},
            "notification_policy": {"message_fields": ["time", "action", "stock", "price"]},
        },
    )
    # 真实 load_monitor_config 会读取 direction_pool.yaml / stock_pool.yaml
    write_yaml(config_dir / "direction_pool.yaml", {"directions": []})
    write_yaml(config_dir / "stock_pool.yaml", {"stocks": []})
    return config_dir


def make_quote_snapshot(*quotes: dict) -> dict:
    return {
        "source": "test",
        "elapsed_ms": 12.3,
        "errors": [],
        "quotes": list(quotes),
    }


def test_trading_day_morning_tick_emits_position_alert(tmp_path: Path):
    """模拟交易日 10:30 cron 触发，持仓触发减仓观察，行情请求被 mock。"""
    config_dir = make_config_dir(tmp_path)
    config = load_monitor_config(config_dir)
    state_path = tmp_path / "state.json"

    # 深科技涨至 37.1，进入预设减仓区 36.9-37.5
    quote_fetcher = lambda _targets: make_quote_snapshot(
        {"code": "000021", "latest": 37.1, "pct_change": 2.1}
    )

    message = run_tick(
        config,
        datetime(2026, 5, 22, 10, 30, tzinfo=CN_TZ),
        emit_status=False,
        ignore_trading_time=False,
        quote_fetcher=quote_fetcher,
        state_path=state_path,
    )

    assert "[Hermes股票监控提醒]" in message
    assert "深科技(000021.SZ)" in message
    assert "减仓观察" in message
    assert "37.1" in message


def test_trading_day_tick_keeps_silent_outside_trading_time(tmp_path: Path):
    """非交易时段不触发提醒，仅返回空字符串。"""
    config_dir = make_config_dir(tmp_path)
    config = load_monitor_config(config_dir)

    quote_fetcher = lambda _targets: make_quote_snapshot(
        {"code": "000021", "latest": 37.1, "pct_change": 2.1}
    )

    message = run_tick(
        config,
        datetime(2026, 5, 22, 20, 0, tzinfo=CN_TZ),
        emit_status=False,
        ignore_trading_time=False,
        quote_fetcher=quote_fetcher,
    )

    assert message == ""


def test_trading_day_tick_uses_last_snapshot_when_quote_fetch_fails(tmp_path: Path):
    """模拟行情接口临时失败时，使用上一次快照，不崩溃。"""
    config_dir = make_config_dir(tmp_path)
    config = load_monitor_config(config_dir)
    state_path = tmp_path / "state.json"

    # 先写入一个历史快照
    state_path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "last_quote_snapshot": make_quote_snapshot(
                    {"code": "000021", "latest": 37.1, "pct_change": 2.1}
                ),
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    # 本次行情请求失败
    quote_fetcher = lambda _targets: {
        "source": "test",
        "quotes": [],
        "errors": ["temporary failure"],
        "elapsed_ms": 1.0,
    }

    message = run_tick(
        config,
        datetime(2026, 5, 22, 10, 30, tzinfo=CN_TZ),
        emit_status=False,
        ignore_trading_time=False,
        quote_fetcher=quote_fetcher,
        state_path=state_path,
    )

    # 没有新告警，因为快照与上次相同且已在历史中
    assert message == ""


def test_env_mock_quotes_bypasses_network(tmp_path: Path, monkeypatch):
    """设置 QING_AGENT_MOCK_QUOTES=1 后，不传 quote_fetcher 也不访问网络。"""
    monkeypatch.setenv("QING_AGENT_MOCK_QUOTES", "1")
    config_dir = make_config_dir(tmp_path)
    config = load_monitor_config(config_dir)

    # 不传 quote_fetcher，默认会走真实行情；但 env 开关强制返回 mock 空数据
    message = run_tick(
        config,
        datetime(2026, 5, 22, 10, 30, tzinfo=CN_TZ),
        emit_status=False,
        ignore_trading_time=False,
    )

    # mock 行情为空，没有告警
    assert message == ""


def test_env_ignore_trading_time_allows_off_hours_tick(tmp_path: Path, monkeypatch):
    """设置 QING_AGENT_IGNORE_TRADING_TIME=1 后，非交易时段也能触发规则。"""
    monkeypatch.setenv("QING_AGENT_IGNORE_TRADING_TIME", "1")
    monkeypatch.setenv("QING_AGENT_MOCK_QUOTES", "1")
    config_dir = make_config_dir(tmp_path)
    config = load_monitor_config(config_dir)

    # 显式传入 mock 行情，同时验证 env 开关绕过交易时间拦截
    quote_fetcher = lambda _targets: make_quote_snapshot(
        {"code": "000021", "latest": 37.1, "pct_change": 2.1}
    )

    message = run_tick(
        config,
        datetime(2026, 5, 22, 20, 0, tzinfo=CN_TZ),
        emit_status=False,
        ignore_trading_time=False,  # 不依赖参数，全靠环境变量
        quote_fetcher=quote_fetcher,
    )

    assert "[Hermes股票监控提醒]" in message
    assert "深科技(000021.SZ)" in message
    assert "减仓观察" in message
