from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from qing_investment.stock_monitor import (
    collect_quote_targets,
    format_analysis_context,
    format_quote_line,
    format_status_message,
    is_a_share_trading_time,
    load_monitor_config,
    position_rows,
    run_tick,
    stock_code_to_secid,
    watchlist_stock_rows,
)


CN_TZ = ZoneInfo("Asia/Shanghai")


def write_yaml(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def make_config_dir(tmp_path: Path) -> Path:
    config_dir = tmp_path / "stock_monitor"
    config_dir.mkdir()
    write_yaml(
        config_dir / "positions.yaml",
        {
            "accounts": [
                {
                    "name": "acct",
                    "positions": [
                        {"code": "000021.SZ", "name": "深科技", "shares": 100}
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
                    "stocks": [{"code": "000021.SZ", "name": "深科技"}],
                }
            ]
        },
    )
    write_yaml(
        config_dir / "strategy_pack.yaml",
        {"market_framework": {"current_stage": "测试阶段"}},
    )
    return config_dir


def test_a_share_trading_time_windows():
    assert is_a_share_trading_time(datetime(2026, 5, 22, 9, 15, tzinfo=CN_TZ))
    assert is_a_share_trading_time(datetime(2026, 5, 22, 11, 30, tzinfo=CN_TZ))
    assert is_a_share_trading_time(datetime(2026, 5, 22, 13, 0, tzinfo=CN_TZ))
    assert is_a_share_trading_time(datetime(2026, 5, 22, 15, 0, tzinfo=CN_TZ))
    assert not is_a_share_trading_time(datetime(2026, 5, 22, 11, 45, tzinfo=CN_TZ))
    assert not is_a_share_trading_time(datetime(2026, 5, 23, 10, 0, tzinfo=CN_TZ))


def test_load_monitor_config_counts_rows(tmp_path):
    config = load_monitor_config(make_config_dir(tmp_path))

    assert len(position_rows(config)) == 1
    assert position_rows(config)[0]["account"] == "acct"
    assert len(watchlist_stock_rows(config)) == 1
    assert watchlist_stock_rows(config)[0]["theme_id"] == "domestic_compute"


def test_status_message_summarizes_config(tmp_path):
    config = load_monitor_config(make_config_dir(tmp_path))

    message = format_status_message(
        config, datetime(2026, 5, 22, 10, 0, tzinfo=CN_TZ)
    )

    assert "[Hermes股票监控状态]" in message
    assert "持仓条目：1" in message
    assert "观察主题：1" in message
    assert "当前框架：测试阶段" in message


def test_tick_is_silent_outside_trading_time(tmp_path):
    config = load_monitor_config(make_config_dir(tmp_path))

    message = run_tick(
        config,
        datetime(2026, 5, 22, 18, 0, tzinfo=CN_TZ),
        emit_status=True,
        ignore_trading_time=False,
    )

    assert message == ""


def test_tick_can_ignore_trading_time_for_temporary_tests(tmp_path):
    config = load_monitor_config(make_config_dir(tmp_path))

    message = run_tick(
        config,
        datetime(2026, 5, 22, 18, 0, tzinfo=CN_TZ),
        emit_status=True,
        ignore_trading_time=True,
    )

    assert "[Hermes股票监控状态]" in message


def test_analysis_context_contains_positions_and_rules(tmp_path):
    config = load_monitor_config(make_config_dir(tmp_path))

    message = format_analysis_context(
        config, datetime(2026, 5, 22, 18, 0, tzinfo=CN_TZ)
    )

    assert "[Hermes股票监控分析上下文]" in message
    assert "深科技(000021.SZ)" in message
    assert "当前持仓分层" in message


def test_stock_code_to_secid():
    assert stock_code_to_secid("000021.SZ") == "0.000021"
    assert stock_code_to_secid("603650.SH") == "1.603650"
    assert stock_code_to_secid("深科技") is None


def test_collect_quote_targets_includes_indexes_and_stocks(tmp_path):
    config = load_monitor_config(make_config_dir(tmp_path))

    targets = collect_quote_targets(config)

    assert targets["上证指数"] == "1.000001"
    assert targets["深科技(000021.SZ)"] == "0.000021"


def test_format_quote_line():
    line = format_quote_line(
        {
            "label": "深科技(000021.SZ)",
            "latest": 36.5,
            "pct_change": 0.36,
            "change": 0.13,
            "open": 36.1,
            "high": 37.0,
            "low": 35.9,
            "previous_close": 36.37,
            "amount": 4299000000,
        }
    )

    assert "深科技(000021.SZ)" in line
    assert "涨跌幅=0.36%" in line
