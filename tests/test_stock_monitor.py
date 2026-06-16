from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from qing_investment.stock_monitor import (
    AgentAnalysisTrigger,
    RuleAlert,
    alert_fingerprint,
    agent_analysis_schedule_rows,
    collect_quote_targets,
    compute_sector_strength,
    evaluate_market_alerts,
    evaluate_position_alerts,
    evaluate_sector_rotation_alerts,
    fetch_eastmoney_quotes,
    fetch_tencent_quotes,
    filter_new_alerts,
    format_alert_decision_log,
    format_alerts_message,
    format_analysis_context,
    format_daily_review_context,
    format_status_message,
    load_monitor_config,
    load_monitor_state,
    parse_price_zone,
    record_agent_analysis_trigger,
    record_emitted_alerts,
    run_tick,
    save_monitor_state,
    stock_code_to_secid,
    summarize_daily_review,
    update_market_state,
    update_sector_signal_counts,
)

# 已从 stock_monitor 迁移到子模块的函数
from qing_investment.monitor.fetchers import (
    chunk_quote_targets,
    fetch_quotes_with_fallback,
    parse_eastmoney_quote_rows,
)
from qing_investment.monitor.output import alert_to_log_entry, format_quote_line
from qing_investment.monitor.scheduler import (
    find_agent_analysis_trigger,
    is_a_share_trading_time,
    record_alert_decision_log,
)
from qing_investment.monitor.context import (
    format_agent_analysis_context,
    position_rows,
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
            "agent_analysis_schedule": [
                {
                    "id": "open_auction",
                    "time": "09:26",
                    "name": "集合竞价后",
                    "focus": "核心持仓和观察池是否超预期高开低开",
                },
                {
                    "id": "morning_confirm",
                    "time": "10:30",
                    "name": "30分钟确认",
                    "focus": "底部钝化和主线修复质量是否成立",
                },
                {
                    "id": "close_review",
                    "time": "15:05",
                    "name": "收盘复盘",
                    "focus": "当天监控小结和次日观察重点",
                },
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
    # 9:15 集合竞价，新实现从 9:30 开始算交易时间
    assert not is_a_share_trading_time(datetime(2026, 5, 22, 9, 15, tzinfo=CN_TZ))
    assert is_a_share_trading_time(datetime(2026, 5, 22, 9, 30, tzinfo=CN_TZ))
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


def test_watchlist_key_candidates_have_pre_condition():
    """P0-1: key entry candidates expose pre_condition for rule engine."""
    repo_root = Path(__file__).resolve().parents[1]
    config = load_monitor_config(repo_root / "config" / "stock_monitor")

    stocks_by_code: dict[str, dict] = {}
    for theme in config.watchlist.get("themes", []):
        for stock in theme.get("stocks", []):
            code = stock.get("code")
            if code:
                stocks_by_code[code] = stock

    for code in ["000636.SZ", "600110.SH", "002384.SZ"]:
        assert code in stocks_by_code, f"{code} not found in watchlist"
        pre = stocks_by_code[code].get("pre_condition")
        assert pre is not None, f"{code} missing pre_condition"
        assert pre.get("market_actionable") is True
        assert pre.get("sector_diverged") is True
        assert pre.get("no_consecutive_limit_up") is True
        assert "market_gate_note" in pre
        assert "sector_gate_note" in pre


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
    assert "买入观察：站回分时均线" in message
    assert "买点失效：跌破日内低点" in message
    assert "持仓卖出/做T：持仓T出" in message
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


def test_chunk_quote_targets_preserves_all_targets_in_order():
    targets = {f"stock{i}": f"0.{i:06d}" for i in range(5)}

    chunks = chunk_quote_targets(targets, chunk_size=2)

    assert chunks == [
        {"stock0": "0.000000", "stock1": "0.000001"},
        {"stock2": "0.000002", "stock3": "0.000003"},
        {"stock4": "0.000004"},
    ]


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


def test_fetch_quotes_falls_back_to_curl_when_urllib_disconnects(monkeypatch):
    def fail_urlopen(*_args, **_kwargs):
        raise OSError("Remote end closed connection without response")

    class CurlResult:
        stdout = (
            '{"data":{"diff":[{"f13":1,"f12":"000001","f14":"上证指数",'
            '"f2":4112.9,"f3":0.87}]}}'
        )

    def fake_run(*_args, **_kwargs):
        return CurlResult()

    monkeypatch.setattr(
        "qing_investment.stock_monitor.urllib.request.urlopen", fail_urlopen
    )
    monkeypatch.setattr("qing_investment.stock_monitor.subprocess.run", fake_run)

    snapshot = fetch_eastmoney_quotes({"上证指数": "1.000001"})

    assert snapshot["errors"] == []
    assert snapshot["quotes"][0]["name"] == "上证指数"
    assert snapshot["quotes"][0]["latest"] == 4112.9


def test_fetch_quotes_keeps_commas_unescaped_for_curl_fallback(monkeypatch):
    def fail_urlopen(*_args, **_kwargs):
        raise OSError("Remote end closed connection without response")

    class CurlResult:
        stdout = '{"data":{"diff":[]}}'

    def fake_run(args, **_kwargs):
        url = args[-1]
        assert "secids=1.000001,0.399001" in url
        assert "%2C" not in url
        return CurlResult()

    monkeypatch.setattr(
        "qing_investment.stock_monitor.urllib.request.urlopen", fail_urlopen
    )
    monkeypatch.setattr("qing_investment.stock_monitor.subprocess.run", fake_run)

    snapshot = fetch_eastmoney_quotes(
        {"上证指数": "1.000001", "深证成指": "0.399001"}
    )

    assert snapshot["errors"] == []


def test_fetch_quotes_splits_failed_chunks_into_smaller_requests(monkeypatch):
    def fail_urlopen(*_args, **_kwargs):
        raise OSError("Remote end closed connection without response")

    class CurlResult:
        def __init__(self, stdout: str):
            self.stdout = stdout

    requested_urls = []

    def fake_run(args, **_kwargs):
        url = args[-1]
        requested_urls.append(url)
        secids = url.split("secids=", 1)[1]
        if "," in secids:
            raise OSError("chunk too large")
        code = secids.split(".")[1]
        return CurlResult(
            '{"data":{"diff":[{"f13":1,"f12":"%s","f14":"name%s",'
            '"f2":1.0,"f3":0.1}]}}' % (code, code)
        )

    monkeypatch.setattr(
        "qing_investment.stock_monitor.urllib.request.urlopen", fail_urlopen
    )
    monkeypatch.setattr("qing_investment.stock_monitor.subprocess.run", fake_run)

    snapshot = fetch_eastmoney_quotes(
        {"a": "1.000001", "b": "1.000002"},
    )

    assert len(snapshot["quotes"]) == 2
    assert any("secids=1.000001,1.000002" in url for url in requested_urls)
    assert snapshot["errors"] == []


def test_fetch_quotes_with_fallback_uses_tencent_when_eastmoney_partial_errors(
    monkeypatch,
):
    targets = {"上证指数": "1.000001", "深科技(000021.SZ)": "0.000021"}

    def fake_eastmoney(_targets):
        return {
            "source": "eastmoney_push2",
            "quotes": [{"secid": "1.000001", "name": "上证指数"}],
            "errors": ["chunk failed"],
        }

    def fake_tencent(_targets):
        return {
            "source": "tencent_gtimg",
            "quotes": [
                {"secid": "1.000001", "name": "上证指数"},
                {"secid": "0.000021", "name": "深科技"},
            ],
            "errors": [],
        }

    monkeypatch.setattr(
        "qing_investment.stock_monitor.fetch_eastmoney_quotes", fake_eastmoney
    )
    monkeypatch.setattr(
        "qing_investment.stock_monitor.fetch_tencent_quotes", fake_tencent
    )

    snapshot = fetch_quotes_with_fallback(targets)

    assert snapshot["source"] == "tencent_gtimg"
    assert len(snapshot["quotes"]) == 2


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
    assert "37.1（2.1%）" in message or "37.1（2.10%）" in message
    assert "减仓观察" in message or "【减仓观察】" in message


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


def test_alert_fingerprint_is_stable_for_same_signal(tmp_path):
    config = load_monitor_config(make_rule_config_dir(tmp_path))
    alert = evaluate_position_alerts(
        config,
        quote_snapshot({"code": "000021", "latest": 37.1, "pct_change": 2.1}),
    )[0]

    assert alert_fingerprint(alert) == alert_fingerprint(alert)
    assert "000021.SZ" in alert_fingerprint(alert)
    assert "减仓观察" in alert_fingerprint(alert)


def test_filter_new_alerts_suppresses_same_signal_within_dedupe_window(tmp_path):
    config = load_monitor_config(make_rule_config_dir(tmp_path))
    alert = evaluate_position_alerts(
        config,
        quote_snapshot({"code": "000021", "latest": 37.1, "pct_change": 2.1}),
    )[0]
    state = {}
    first_time = datetime(2026, 5, 22, 10, 0, tzinfo=CN_TZ)
    second_time = datetime(2026, 5, 22, 10, 10, tzinfo=CN_TZ)
    third_time = datetime(2026, 5, 22, 10, 31, tzinfo=CN_TZ)

    first_alerts = filter_new_alerts([alert], state, first_time, dedupe_minutes=30)
    record_emitted_alerts(state, first_alerts, first_time)
    second_alerts = filter_new_alerts([alert], state, second_time, dedupe_minutes=30)
    third_alerts = filter_new_alerts([alert], state, third_time, dedupe_minutes=30)

    assert first_alerts == [alert]
    assert second_alerts == []
    assert third_alerts == [alert]


def test_monitor_state_round_trips_json(tmp_path):
    path = tmp_path / "state.json"
    state = {
        "version": 1,
        "alert_history": {"signal": "2026-05-22T10:00:00+08:00"},
    }

    save_monitor_state(path, state)

    loaded = load_monitor_state(path)
    assert loaded["version"] == state["version"]
    assert loaded["alert_history"] == state["alert_history"]


def test_tick_persists_snapshot_and_suppresses_duplicate_alerts(tmp_path):
    config = load_monitor_config(make_rule_config_dir(tmp_path))
    state_path = tmp_path / "state.json"

    first = run_tick(
        config,
        datetime(2026, 5, 22, 10, 0, tzinfo=CN_TZ),
        emit_status=False,
        ignore_trading_time=False,
        quote_fetcher=lambda _targets: quote_snapshot(
            {"code": "000021", "latest": 37.1, "pct_change": 2.1}
        ),
        state_path=state_path,
        dedupe_minutes=30,
    )
    second = run_tick(
        config,
        datetime(2026, 5, 22, 10, 10, tzinfo=CN_TZ),
        emit_status=False,
        ignore_trading_time=False,
        quote_fetcher=lambda _targets: quote_snapshot(
            {"code": "000021", "latest": 37.1, "pct_change": 2.1}
        ),
        state_path=state_path,
        dedupe_minutes=30,
    )
    state = load_monitor_state(state_path)

    assert "[Hermes股票监控提醒]" in first
    assert second == ""
    assert state["last_quote_snapshot"]["quotes"][0]["code"] == "000021"
    assert state["alert_history"]


def test_tick_keeps_last_good_snapshot_when_fetch_fails(tmp_path):
    config = load_monitor_config(make_rule_config_dir(tmp_path))
    state_path = tmp_path / "state.json"
    save_monitor_state(
        state_path,
        {
            "version": 1,
            "last_quote_snapshot": quote_snapshot(
                {"code": "000021", "latest": 37.1, "pct_change": 2.1}
            ),
        },
    )

    message = run_tick(
        config,
        datetime(2026, 5, 22, 10, 0, tzinfo=CN_TZ),
        emit_status=False,
        ignore_trading_time=False,
        quote_fetcher=lambda _targets: {
            "source": "test",
            "quotes": [],
            "errors": ["temporary failure"],
            "elapsed_ms": 1.0,
        },
        state_path=state_path,
        dedupe_minutes=30,
    )
    state = load_monitor_state(state_path)

    assert message == ""
    assert state["last_quote_snapshot"]["quotes"][0]["latest"] == 37.1
    assert state["last_fetch_error"]["errors"] == ["temporary failure"]


def test_sector_signal_counts_increment_and_reset():
    alert = RuleAlert(
        action="进攻回流观察",
        stock_code="tech_vs_defense",
        stock_name="板块强弱",
        price=2.1,
        trigger="科技强于防御",
        severity="observe",
        summary="进攻回流观察：科技强于防御",
    )
    state = {}

    update_sector_signal_counts(
        state, [alert], datetime(2026, 5, 22, 10, 0, tzinfo=CN_TZ)
    )
    update_sector_signal_counts(
        state, [alert], datetime(2026, 5, 22, 10, 10, tzinfo=CN_TZ)
    )

    key = alert_fingerprint(alert)
    assert state["sector_signal_counts"][key]["count"] == 2

    update_sector_signal_counts(
        state, [], datetime(2026, 5, 22, 10, 20, tzinfo=CN_TZ)
    )

    assert state["sector_signal_counts"] == {}


def test_update_market_state_summarizes_latest_tick():
    state = {}
    alerts = [
        RuleAlert(
            action="风控观察",
            stock_code="000021.SZ",
            stock_name="深科技",
            price=35.8,
            trigger="跌破风险线",
            severity="risk",
            summary="风控观察",
        ),
        RuleAlert(
            action="进攻回流观察",
            stock_code="tech_vs_defense",
            stock_name="板块强弱",
            price=2.1,
            trigger="科技强于防御",
            severity="observe",
            summary="进攻回流观察",
        ),
    ]

    update_market_state(
        state,
        alerts,
        quote_snapshot({"code": "000021", "latest": 35.8}),
        datetime(2026, 5, 22, 10, 0, tzinfo=CN_TZ),
    )

    assert state["last_market_state"]["alert_count"] == 2
    assert state["last_market_state"]["risk_count"] == 1
    assert state["last_market_state"]["sector_actions"] == ["进攻回流观察"]
    assert state["last_market_state"]["quote_count"] == 1


def test_agent_analysis_schedule_rows_uses_configured_key_times(tmp_path):
    config = load_monitor_config(make_rule_config_dir(tmp_path))

    rows = agent_analysis_schedule_rows(config)

    assert [row["id"] for row in rows] == [
        "open_auction",
        "morning_confirm",
        "close_review",
    ]
    assert rows[0]["time"] == "09:26"


def test_scheduled_agent_analysis_triggers_once_per_day(tmp_path):
    config = load_monitor_config(make_rule_config_dir(tmp_path))
    state = {}
    current = datetime(2026, 5, 22, 9, 26, tzinfo=CN_TZ)

    trigger = find_agent_analysis_trigger(config, state, current, [])
    assert trigger is not None
    assert trigger.kind == "scheduled"
    assert trigger.id == "open_auction"

    record_agent_analysis_trigger(state, trigger, current)

    assert find_agent_analysis_trigger(config, state, current, []) is None


def test_event_agent_analysis_triggers_for_new_alerts(tmp_path):
    config = load_monitor_config(make_rule_config_dir(tmp_path))
    alert = RuleAlert(
        action="风控观察",
        stock_code="000021.SZ",
        stock_name="深科技",
        price=35.8,
        trigger="触及或跌破风险线35.9",
        severity="risk",
        summary="风控观察：深科技触及风险线",
    )

    trigger = find_agent_analysis_trigger(
        config, {}, datetime(2026, 5, 22, 10, 0, tzinfo=CN_TZ), [alert]
    )

    assert trigger is not None
    assert trigger.kind == "event"
    assert trigger.id == "rule_alert"
    assert "风控观察" in trigger.reason


def test_agent_analysis_context_contains_trigger_alerts_and_quotes(tmp_path):
    config = load_monitor_config(make_rule_config_dir(tmp_path))
    trigger = AgentAnalysisTrigger(
        kind="scheduled",
        id="morning_confirm",
        title="30分钟确认",
        reason="底部钝化和主线修复质量是否成立",
        dedupe_key="scheduled:morning_confirm:2026-05-22",
    )
    alert = RuleAlert(
        action="减仓观察",
        stock_code="000021.SZ",
        stock_name="深科技",
        price=37.1,
        trigger="进入预设减仓区36.9-37.5",
        severity="observe",
        summary="减仓观察：深科技进入减仓区",
    )

    message = format_agent_analysis_context(
        config,
        datetime(2026, 5, 22, 10, 30, tzinfo=CN_TZ),
        trigger,
        [alert],
        quote_snapshot({"label": "深科技(000021.SZ)", "code": "000021", "latest": 37.1}),
        {"last_market_state": {"alert_count": 1}},
    )

    assert "[Hermes股票监控大模型分析上下文]" in message
    assert "30分钟确认" in message
    assert "【减仓观察】" in message or "减仓观察" in message
    assert "深科技" in message
    assert "深科技(000021.SZ)" in message
    assert "观察池现在能不能买" in message
    assert "最多450字" in message
    assert "禁止Markdown表格" in message
    assert "禁止把多只股票写成同一段" in message
    assert "【重点分析】1-2只重点票，每只80-100字" in message
    assert "【其他持仓】剩余持仓每只15字" in message


def test_tick_emits_agent_context_at_key_time_and_dedupes(tmp_path):
    config = load_monitor_config(make_rule_config_dir(tmp_path))
    state_path = tmp_path / "state.json"
    current = datetime(2026, 5, 22, 9, 26, tzinfo=CN_TZ)

    first = run_tick(
        config,
        current,
        emit_status=False,
        ignore_trading_time=False,
        quote_fetcher=lambda _targets: quote_snapshot(
            {"label": "上证指数", "code": "000001", "latest": 4112.9}
        ),
        state_path=state_path,
        agent_context_on_trigger=True,
    )
    second = run_tick(
        config,
        current,
        emit_status=False,
        ignore_trading_time=False,
        quote_fetcher=lambda _targets: quote_snapshot(
            {"label": "上证指数", "code": "000001", "latest": 4112.9}
        ),
        state_path=state_path,
        agent_context_on_trigger=True,
    )

    assert "[Hermes股票监控大模型分析上下文]" in first
    assert "集合竞价后" in first
    assert second == ""


def test_tick_emits_agent_context_after_close_scheduled_time(tmp_path):
    config = load_monitor_config(make_rule_config_dir(tmp_path))

    message = run_tick(
        config,
        datetime(2026, 5, 22, 15, 5, tzinfo=CN_TZ),
        emit_status=False,
        ignore_trading_time=False,
        quote_fetcher=lambda _targets: quote_snapshot(
            {"label": "上证指数", "code": "000001", "latest": 4112.9}
        ),
        state_path=tmp_path / "state.json",
        agent_context_on_trigger=True,
    )

    assert "[Hermes股票监控大模型分析上下文]" in message
    assert "收盘复盘" in message


def test_alert_to_log_entry_captures_review_fields():
    alert = RuleAlert(
        action="减仓观察",
        stock_code="000021.SZ",
        stock_name="深科技",
        price=37.1,
        trigger="进入预设减仓区36.9-37.5",
        severity="observe",
        summary="减仓观察：深科技进入减仓区",
    )

    entry = alert_to_log_entry(
        alert, datetime(2026, 5, 22, 10, 30, tzinfo=CN_TZ), status="emitted"
    )

    assert entry["date"] == "2026-05-22"
    assert entry["status"] == "emitted"
    assert entry["fingerprint"] == alert_fingerprint(alert)
    assert entry["stock_name"] == "深科技"


def test_record_alert_decision_log_marks_suppressed_alerts():
    emitted = RuleAlert(
        action="风控观察",
        stock_code="000021.SZ",
        stock_name="深科技",
        price=35.8,
        trigger="触及或跌破风险线35.9",
        severity="risk",
        summary="风控观察：深科技触及风险线",
    )
    suppressed = RuleAlert(
        action="减仓观察",
        stock_code="002185.SZ",
        stock_name="华天科技",
        price=15.5,
        trigger="进入预设减仓区15.4-15.8",
        severity="observe",
        summary="减仓观察：华天科技进入减仓区",
    )
    state = {}

    record_alert_decision_log(
        state,
        [emitted, suppressed],
        [emitted],
        datetime(2026, 5, 22, 10, 30, tzinfo=CN_TZ),
    )

    assert [entry["status"] for entry in state["alert_decision_log"]] == [
        "emitted",
        "suppressed",
    ]


def test_summarize_daily_review_groups_today_entries():
    state = {
        "alert_decision_log": [
            {"date": "2026-05-22", "status": "emitted", "summary": "A"},
            {"date": "2026-05-22", "status": "suppressed", "summary": "B"},
            {"date": "2026-05-21", "status": "emitted", "summary": "old"},
        ],
        "agent_analysis_history": {
            "scheduled:open:2026-05-22": {"time": "2026-05-22T09:26:00+08:00"},
            "scheduled:open:2026-05-21": {"time": "2026-05-21T09:26:00+08:00"},
        },
        "last_market_state": {"alert_count": 1},
        "last_fetch_error": {"errors": ["temporary failure"]},
    }

    summary = summarize_daily_review(state, "2026-05-22")

    assert len(summary["emitted_alerts"]) == 1
    assert len(summary["suppressed_alerts"]) == 1
    assert len(summary["agent_runs"]) == 1
    assert summary["last_market_state"]["alert_count"] == 1
    assert summary["last_fetch_error"]["errors"] == ["temporary failure"]


def test_daily_review_context_asks_for_false_positive_and_yaml_updates(tmp_path):
    config = load_monitor_config(make_rule_config_dir(tmp_path))
    state = {
        "alert_decision_log": [
            {
                "date": "2026-05-22",
                "time": "2026-05-22T10:30:00+08:00",
                "status": "emitted",
                "action": "减仓观察",
                "stock_name": "深科技",
                "summary": "减仓观察：深科技进入减仓区",
            },
            {
                "date": "2026-05-22",
                "time": "2026-05-22T10:40:00+08:00",
                "status": "suppressed",
                "action": "减仓观察",
                "stock_name": "深科技",
                "summary": "减仓观察：深科技进入减仓区",
            },
        ],
        "last_market_state": {"alert_count": 1, "sector_actions": ["进攻回流观察"]},
    }

    message = format_daily_review_context(
        config, datetime(2026, 5, 22, 15, 20, tzinfo=CN_TZ), state
    )

    assert "[Hermes股票监控收盘复盘上下文]" in message
    assert "已发送提醒" in message
    assert "被去重压制" in message
    assert "误报" in message
    assert "漏报" in message
    assert "YAML" in message


def test_daily_review_cli_prints_context(tmp_path, capsys):
    config_dir = make_rule_config_dir(tmp_path)
    state_path = config_dir / "state.json"
    save_monitor_state(
        state_path,
        {
            "alert_decision_log": [
                {
                    "date": datetime.now(tz=CN_TZ).strftime("%Y-%m-%d"),
                    "time": datetime.now(tz=CN_TZ).isoformat(),
                    "status": "emitted",
                    "action": "减仓观察",
                    "stock_name": "深科技",
                    "summary": "减仓观察：深科技进入减仓区",
                }
            ]
        },
    )

    from qing_investment.stock_monitor import main

    exit_code = main(
        [
            "--config-dir",
            str(config_dir),
            "--state-file",
            str(state_path),
            "--daily-review-context",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "[Hermes股票监控收盘复盘上下文]" in output


def test_action_to_dedupe_type_mapping():
    """_action_to_dedupe_type correctly maps action strings to type keys."""
    from qing_investment.monitor.output import _action_to_dedupe_type
    assert _action_to_dedupe_type("风控观察") == "risk_alert"
    assert _action_to_dedupe_type("减仓观察") == "reduce_alert"
    assert _action_to_dedupe_type("进攻回流观察") == "sector_rotation"
    assert _action_to_dedupe_type("防御切换观察") == "sector_rotation"
    assert _action_to_dedupe_type("指数趋势防线观察") == "sector_rotation"
    assert _action_to_dedupe_type("指数弱修复观察") == "sector_rotation"
    assert _action_to_dedupe_type("指数规则触发") == "sector_rotation"
    assert _action_to_dedupe_type("只观察不介入") == "default"
    assert _action_to_dedupe_type("风险控制") == "risk_alert"
    assert _action_to_dedupe_type("板块轮动观察") == "sector_rotation"


def test_dedupe_by_type_overrides_global_dedupe_minutes():
    """dedupe_by_type config overrides global dedupe_minutes per alert action."""
    state = {}
    alert = RuleAlert(
        action="风控观察",
        stock_code="000021.SZ",
        stock_name="深科技",
        price=35.0,
        trigger="触及或跌破风险线35.9",
        severity="risk",
        summary="风控观察：深科技触及风险线",
    )
    first_time = datetime(2026, 6, 4, 10, 0, tzinfo=CN_TZ)
    # 10 min later — should be suppressed by risk_alert dedupe_minutes=15
    second_time = datetime(2026, 6, 4, 10, 10, tzinfo=CN_TZ)
    # 20 min later — should pass risk_alert dedupe_minutes=15
    third_time = datetime(2026, 6, 4, 10, 20, tzinfo=CN_TZ)

    dedupe_by_type = {
        "risk_alert": {"dedupe_minutes": 15},
        "reduce_alert": {"dedupe_minutes": 30},
    }

    first = filter_new_alerts(
        [alert], state, first_time,
        dedupe_minutes=30,
        dedupe_by_type=dedupe_by_type,
    )
    record_emitted_alerts(state, first, first_time)
    second = filter_new_alerts(
        [alert], state, second_time,
        dedupe_minutes=30,
        dedupe_by_type=dedupe_by_type,
    )
    third = filter_new_alerts(
        [alert], state, third_time,
        dedupe_minutes=30,
        dedupe_by_type=dedupe_by_type,
    )

    assert len(first) == 1       # first time: always fresh
    assert len(second) == 0      # 10 min < 15 min risk_alert: suppressed
    assert len(third) == 1       # 20 min >= 15 min risk_alert: passes


def test_dedupe_by_type_breakthrough_triggers_on_price_change():
    """breakthrough_if_price_change_pct allows alert through dedupe when price moves significantly."""
    state = {}
    alert = RuleAlert(
        action="风控观察",
        stock_code="000021.SZ",
        stock_name="深科技",
        price=35.0,
        trigger="触及或跌破风险线35.9",
        severity="risk",
        summary="风控观察：深科技触及风险线",
    )
    first_time = datetime(2026, 6, 4, 10, 0, tzinfo=CN_TZ)
    # Same fingerprint, but price dropped 2% (35.0 → 34.3)
    alert_new_price = RuleAlert(
        action="风控观察",
        stock_code="000021.SZ",
        stock_name="深科技",
        price=34.3,
        trigger="触及或跌破风险线35.9",
        severity="risk",
        summary="风控观察：深科技触及风险线",
    )
    second_time = datetime(2026, 6, 4, 10, 6, tzinfo=CN_TZ)  # only 6 min later

    dedupe_by_type = {
        "risk_alert": {
            "dedupe_minutes": 15,
            "breakthrough_if_price_change_pct": 1.0,
        },
    }

    first = filter_new_alerts(
        [alert], state, first_time,
        dedupe_minutes=30,
        dedupe_by_type=dedupe_by_type,
    )
    record_emitted_alerts(state, first, first_time)
    second = filter_new_alerts(
        [alert_new_price], state, second_time,
        dedupe_minutes=30,
        dedupe_by_type=dedupe_by_type,
    )

    assert len(first) == 1       # first time: fresh
    assert len(second) == 1      # price dropped 2% > 1% threshold: breakthrough


def test_dedupe_by_type_breakthrough_suppressed_when_price_stable():
    """breakthrough_if_price_change_pct does NOT fire when price hasn't moved enough."""
    state = {}
    alert = RuleAlert(
        action="风控观察",
        stock_code="000021.SZ",
        stock_name="深科技",
        price=35.0,
        trigger="触及或跌破风险线35.9",
        severity="risk",
        summary="风控观察：深科技触及风险线",
    )
    # Same price (no breakthrough), only 6 min later
    alert_same_price = RuleAlert(
        action="风控观察",
        stock_code="000021.SZ",
        stock_name="深科技",
        price=35.0,
        trigger="触及或跌破风险线35.9",
        severity="risk",
        summary="风控观察：深科技触及风险线",
    )
    first_time = datetime(2026, 6, 4, 10, 0, tzinfo=CN_TZ)
    second_time = datetime(2026, 6, 4, 10, 6, tzinfo=CN_TZ)

    dedupe_by_type = {
        "risk_alert": {
            "dedupe_minutes": 15,
            "breakthrough_if_price_change_pct": 1.0,
        },
    }

    first = filter_new_alerts(
        [alert], state, first_time,
        dedupe_minutes=30,
        dedupe_by_type=dedupe_by_type,
    )
    record_emitted_alerts(state, first, first_time)
    second = filter_new_alerts(
        [alert_same_price], state, second_time,
        dedupe_minutes=30,
        dedupe_by_type=dedupe_by_type,
    )

    assert len(first) == 1       # first time: fresh
    assert len(second) == 0      # price unchanged, within 15 min dedupe: suppressed


def test_dedupe_by_type_falls_back_to_global_when_missing():
    """dedupe_by_type default type falls back to global dedupe_minutes."""
    state = {}
    alert = RuleAlert(
        action="只观察不介入",
        stock_code="000021.SZ",
        stock_name="深科技",
        price=35.0,
        trigger="普通波动",
        severity="observe",
        summary="只观察不介入：深科技",
    )
    first_time = datetime(2026, 6, 4, 10, 0, tzinfo=CN_TZ)
    second_time = datetime(2026, 6, 4, 10, 10, tzinfo=CN_TZ)   # 10 min < 30
    third_time = datetime(2026, 6, 4, 10, 31, tzinfo=CN_TZ)    # 31 min >= 30

    dedupe_by_type = {
        "risk_alert": {"dedupe_minutes": 15},   # non-matching type
    }

    first = filter_new_alerts(
        [alert], state, first_time,
        dedupe_minutes=30,
        dedupe_by_type=dedupe_by_type,
    )
    record_emitted_alerts(state, first, first_time)
    second = filter_new_alerts(
        [alert], state, second_time,
        dedupe_minutes=30,
        dedupe_by_type=dedupe_by_type,
    )
    third = filter_new_alerts(
        [alert], state, third_time,
        dedupe_minutes=30,
        dedupe_by_type=dedupe_by_type,
    )

    assert len(first) == 1       # first time: fresh
    assert len(second) == 0      # 10 min < 30 global: suppressed
    assert len(third) == 1       # 31 min >= 30 global: passes


def test_dedupe_by_type_backward_compat_with_old_string_format():
    """Old-format alert_history (string timestamp) still works with new filter_new_alerts."""
    # Simulate old-format state
    old_entry = "2026-06-04T10:00:00+08:00"
    state = {
        "alert_history": {
            "风控观察|000021.SZ|深科技|触及或跌破风险线35.9": old_entry,
        }
    }
    alert = RuleAlert(
        action="风控观察",
        stock_code="000021.SZ",
        stock_name="深科技",
        price=35.0,
        trigger="触及或跌破风险线35.9",
        severity="risk",
        summary="风控观察：深科技触及风险线",
    )
    current_time = datetime(2026, 6, 4, 10, 10, tzinfo=CN_TZ)  # 10 min later

    dedupe_by_type = {
        "risk_alert": {"dedupe_minutes": 15},
    }

    result = filter_new_alerts(
        [alert], state, current_time,
        dedupe_minutes=30,
        dedupe_by_type=dedupe_by_type,
    )

    # 10 min < 15 min risk_alert dedupe: suppressed
    assert len(result) == 0


def test_tick_passes_dedupe_by_type_from_config(tmp_path):
    """run_tick reads dedupe_by_type from strategy_pack notification_policy."""
    config_dir = make_rule_config_dir(tmp_path)
    config = load_monitor_config(config_dir)

    # Verify config has notification_policy but no dedupe_by_type
    notification_policy = config.strategy_pack.get("notification_policy", {}) or {}
    assert "dedupe_by_type" not in notification_policy

    # If no dedupe_by_type in config, fall back to global dedupe_minutes
    state_path = config_dir / "state.json"
    first = run_tick(
        config,
        datetime(2026, 6, 4, 10, 0, tzinfo=CN_TZ),
        emit_status=False,
        ignore_trading_time=True,
        quote_fetcher=lambda _targets: quote_snapshot(
            {"code": "000021", "latest": 37.1, "pct_change": 2.1}
        ),
        state_path=state_path,
        dedupe_minutes=30,
    )
    second = run_tick(
        config,
        datetime(2026, 6, 4, 10, 5, tzinfo=CN_TZ),
        emit_status=False,
        ignore_trading_time=True,
        quote_fetcher=lambda _targets: quote_snapshot(
            {"code": "000021", "latest": 37.1, "pct_change": 2.1}
        ),
        state_path=state_path,
        dedupe_minutes=30,
    )

    assert "[Hermes股票监控提醒]" in first
    assert second == ""  # suppressed by global dedupe


def test_strategy_pack_contains_market_gate_rules(tmp_path):
    config_dir = make_rule_config_dir(tmp_path)
    # 手动追加 market_gate_rules 到 strategy_pack.yaml
    sp_path = config_dir / "strategy_pack.yaml"
    sp = yaml.safe_load(sp_path.read_text(encoding="utf-8"))
    sp.setdefault("market_gate_rules", {
        "index_checks": [{"index": "上证指数", "condition": "not_close_below", "level": 3950}],
        "actionable_min_pass": 2,
    })
    sp_path.write_text(yaml.safe_dump(sp, allow_unicode=True), encoding="utf-8")

    config = load_monitor_config(config_dir)
    mgr = config.strategy_pack.get("market_gate_rules", {})
    assert "index_checks" in mgr
    assert mgr.get("actionable_min_pass") == 2


def test_direction_pool_yaml_is_valid(tmp_path):
    """direction_pool.yaml 必须能被 PyYAML 解析且包含至少一个方向。"""
    repo_root = Path(__file__).resolve().parents[1]
    dp_path = repo_root / "config" / "stock_monitor" / "direction_pool.yaml"
    assert dp_path.exists(), "direction_pool.yaml should exist"
    data = yaml.safe_load(dp_path.read_text(encoding="utf-8"))
    assert "directions" in data
    assert len(data["directions"]) >= 1
    first = data["directions"][0]
    assert "id" in first
    assert "industry_chain" in first
    assert "pre_condition" in first


def test_stock_pool_yaml_is_valid(tmp_path):
    """stock_pool.yaml 必须能被 PyYAML 解析且每个标的有 direction。"""
    repo_root = Path(__file__).resolve().parents[1]
    sp_path = repo_root / "config" / "stock_monitor" / "stock_pool.yaml"
    assert sp_path.exists(), "stock_pool.yaml should exist"
    data = yaml.safe_load(sp_path.read_text(encoding="utf-8"))
    assert "stocks" in data
    assert len(data["stocks"]) >= 1
    first = data["stocks"][0]
    assert "code" in first
    assert "direction" in first
    assert "entry" in first
    assert "pre_condition" in first


def test_load_monitor_config_loads_direction_and_stock_pool(tmp_path):
    config_dir = make_config_dir(tmp_path)
    # 写入最小 direction_pool / stock_pool
    write_yaml(
        config_dir / "direction_pool.yaml",
        {"directions": [{"id": "test_dir", "name": "测试方向"}]},
    )
    write_yaml(
        config_dir / "stock_pool.yaml",
        {"stocks": [{"code": "000021.SZ", "name": "深科技", "direction": "test_dir"}]},
    )

    config = load_monitor_config(config_dir)
    assert config.direction_pool["directions"][0]["id"] == "test_dir"
    assert config.stock_pool["stocks"][0]["direction"] == "test_dir"
