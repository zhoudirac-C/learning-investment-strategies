from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from qing_investment.stock_monitor import (
    collect_quote_targets,
    compute_sector_strength,
    evaluate_market_alerts,
    evaluate_position_alerts,
    evaluate_sector_rotation_alerts,
    format_analysis_context,
    format_alerts_message,
    format_quote_line,
    format_status_message,
    is_a_share_trading_time,
    load_monitor_config,
    parse_eastmoney_quote_rows,
    parse_price_zone,
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


def make_rule_config_dir(tmp_path: Path) -> Path:
    config_dir = tmp_path / "rule_stock_monitor"
    config_dir.mkdir()
    write_yaml(
        config_dir / "positions.yaml",
        {
            "accounts": [
                {
                    "name": "acct",
                    "positions": [
                        {
                            "code": "000021.SZ",
                            "name": "深科技",
                            "shares": 1000,
                            "cost": 36.2,
                            "role": "core_holding",
                            "reduce_zone": "36.9-37.5",
                            "risk_line": 35.9,
                        },
                        {
                            "code": "002636.SZ",
                            "name": "金安国纪",
                            "shares": 1000,
                            "cost": 45.3,
                            "role": "strong_repair_holding",
                            "risk_line": 43.0,
                        },
                    ],
                }
            ]
        },
    )
    write_yaml(config_dir / "watchlist.yaml", {"themes": []})
    write_yaml(
        config_dir / "strategy_pack.yaml",
        {
            "market_framework": {
                "current_stage": "测试阶段",
                "index_rules": [
                    {
                        "name": "short_repair_observation",
                        "index": "上证指数",
                        "valid_close_level": 4080,
                        "weak_close_level": 4070,
                        "trend_defense": 4027,
                    }
                ],
            },
            "notification_policy": {
                "message_fields": ["time", "action", "stock", "price"]
            },
            "sector_groups": [
                {
                    "id": "offensive_tech",
                    "name": "科技进攻线",
                    "style": "offensive",
                    "members": [
                        {"code": "000021.SZ", "name": "深科技"},
                        {"code": "002636.SZ", "name": "金安国纪"},
                    ],
                },
                {
                    "id": "defensive",
                    "name": "防御稳定线",
                    "style": "defensive",
                    "members": [
                        {"code": "600036.SH", "name": "招商银行"},
                        {"code": "600519.SH", "name": "贵州茅台"},
                    ],
                },
            ],
            "sector_rotation_rules": [
                {
                    "id": "offense_vs_defense",
                    "offensive_groups": ["offensive_tech"],
                    "defensive_groups": ["defensive"],
                    "min_spread_pct": 1.0,
                    "min_red_ratio_spread": 0.25,
                }
            ],
        },
    )
    return config_dir


def quote_snapshot(*quotes: dict) -> dict:
    return {
        "source": "test",
        "elapsed_ms": 12.3,
        "errors": [],
        "quotes": list(quotes),
    }


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


def test_collect_quote_targets_includes_sector_group_members(tmp_path):
    config = load_monitor_config(make_rule_config_dir(tmp_path))

    targets = collect_quote_targets(config)

    assert targets["防御稳定线/招商银行(600036.SH)"] == "1.600036"


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


def test_parse_eastmoney_quote_rows_disambiguates_same_six_digit_code():
    rows = [
        {
            "f13": 1,
            "f12": "000001",
            "f14": "上证指数",
            "f2": 4065.0,
            "f3": -0.2,
        },
        {
            "f13": 0,
            "f12": "000001",
            "f14": "平安银行",
            "f2": 10.68,
            "f3": 1.1,
        },
    ]

    quotes = parse_eastmoney_quote_rows(
        rows,
        {
            "上证指数": "1.000001",
            "防御稳定线/平安银行(000001.SZ)": "0.000001",
        },
    )

    by_name = {quote["name"]: quote for quote in quotes}
    assert by_name["上证指数"]["label"] == "上证指数"
    assert by_name["平安银行"]["label"] == "防御稳定线/平安银行(000001.SZ)"


def test_parse_price_zone_normalizes_ranges():
    assert parse_price_zone("36.9-37.5") == (36.9, 37.5)
    assert parse_price_zone("44.5-43") == (43.0, 44.5)
    assert parse_price_zone(35.9) == (35.9, 35.9)
    assert parse_price_zone("") is None


def test_position_alerts_trigger_reduce_zone_and_risk_line(tmp_path):
    config = load_monitor_config(make_rule_config_dir(tmp_path))

    alerts = evaluate_position_alerts(
        config,
        quote_snapshot(
            {"code": "000021", "latest": 37.1, "pct_change": 2.1},
            {"code": "002636", "latest": 42.8, "pct_change": -1.4},
        ),
    )

    alert_text = "\n".join(alert.summary for alert in alerts)
    assert "深科技" in alert_text
    assert "减仓观察" in alert_text
    assert "金安国纪" in alert_text
    assert "风控观察" in alert_text


def test_alert_message_includes_action_price_and_context(tmp_path):
    config = load_monitor_config(make_rule_config_dir(tmp_path))
    alerts = evaluate_position_alerts(
        config,
        quote_snapshot({"code": "000021", "latest": 37.1, "pct_change": 2.1}),
    )

    message = format_alerts_message(
        alerts,
        datetime(2026, 5, 22, 10, 0, tzinfo=CN_TZ),
        quote_snapshot({"code": "000021", "latest": 37.1, "pct_change": 2.1}),
    )

    assert "[Hermes股票监控提醒]" in message
    assert "深科技(000021.SZ)" in message
    assert "当前价=37.1" in message
    assert "减仓观察" in message


def test_tick_emits_alert_message_when_rules_trigger(tmp_path):
    config = load_monitor_config(make_rule_config_dir(tmp_path))

    message = run_tick(
        config,
        datetime(2026, 5, 22, 10, 0, tzinfo=CN_TZ),
        emit_status=False,
        ignore_trading_time=False,
        quote_fetcher=lambda _targets: quote_snapshot(
            {"code": "000021", "latest": 37.1, "pct_change": 2.1}
        ),
    )

    assert "[Hermes股票监控提醒]" in message
    assert "深科技(000021.SZ)" in message


def test_market_alerts_use_configured_index_levels(tmp_path):
    config = load_monitor_config(make_rule_config_dir(tmp_path))

    alerts = evaluate_market_alerts(
        config,
        quote_snapshot({"label": "上证指数", "code": "000001", "latest": 4065}),
    )

    assert len(alerts) == 1
    assert alerts[0].action == "指数弱修复观察"
    assert "上证指数" in alerts[0].summary
    assert "4070" in alerts[0].summary


def test_sector_strength_computes_average_gain_and_red_ratio(tmp_path):
    config = load_monitor_config(make_rule_config_dir(tmp_path))

    strengths = compute_sector_strength(
        config,
        quote_snapshot(
            {"code": "000021", "latest": 37.1, "pct_change": 2.0},
            {"code": "002636", "latest": 42.8, "pct_change": -1.0},
            {"code": "600036", "latest": 40.0, "pct_change": 0.2},
            {"code": "600519", "latest": 1500.0, "pct_change": 0.4},
        ),
    )

    tech = next(item for item in strengths if item.id == "offensive_tech")
    defensive = next(item for item in strengths if item.id == "defensive")
    assert tech.average_pct_change == 0.5
    assert tech.red_ratio == 0.5
    assert defensive.average_pct_change == 0.3
    assert defensive.red_ratio == 1.0


def test_sector_strength_uses_market_specific_codes_when_index_code_collides(tmp_path):
    config = load_monitor_config(make_rule_config_dir(tmp_path))
    config.strategy_pack["sector_groups"] = [
        {
            "id": "bank",
            "name": "银行",
            "style": "defensive",
            "members": [{"code": "000001.SZ", "name": "平安银行"}],
        }
    ]

    strengths = compute_sector_strength(
        config,
        quote_snapshot(
            {
                "secid": "0.000001",
                "code": "000001",
                "name": "平安银行",
                "latest": 10.68,
                "pct_change": 1.1,
            },
            {
                "secid": "1.000001",
                "code": "000001",
                "name": "上证指数",
                "latest": 4065.0,
                "pct_change": -0.2,
            },
        ),
    )

    assert strengths[0].average_pct_change == 1.1


def test_sector_rotation_alerts_detect_defensive_switch(tmp_path):
    config = load_monitor_config(make_rule_config_dir(tmp_path))

    alerts = evaluate_sector_rotation_alerts(
        config,
        quote_snapshot(
            {"code": "000021", "latest": 37.1, "pct_change": -1.5},
            {"code": "002636", "latest": 42.8, "pct_change": -0.5},
            {"code": "600036", "latest": 40.0, "pct_change": 1.0},
            {"code": "600519", "latest": 1500.0, "pct_change": 1.2},
        ),
    )

    assert len(alerts) == 1
    assert alerts[0].action == "防御切换观察"
    assert "防御稳定线" in alerts[0].summary
    assert "科技进攻线" in alerts[0].summary
