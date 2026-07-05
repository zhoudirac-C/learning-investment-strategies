"""大盘 / 指数 / 板块数据 mock 测试

验证设置 QING_AGENT_MOCK_QUOTES=1 时，返回的行情快照不仅包含个股，
还包含上证指数、全A指数等大盘数据，以及板块样本，供 MarketGate、
IndexRuleEngine、SectorRotationRuleEngine 使用。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

from qing_investment.monitor.fetchers import (
    ConcurrentDataFetcher,
    _mock_quote_snapshot,
    fetch_quotes_with_fallback,
)
from qing_investment.monitor.gates import MarketGate
from qing_investment.monitor.rules import IndexRuleEngine, SectorRotationRuleEngine
from qing_investment.monitor.scheduler import run_tick
from qing_investment.stock_monitor import load_monitor_config


CN_TZ = ZoneInfo("Asia/Shanghai")


def write_yaml(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def make_config_with_market_rules(tmp_path: Path) -> object:
    config_dir = tmp_path / "stock_monitor"
    config_dir.mkdir()
    write_yaml(
        config_dir / "positions.yaml",
        {"accounts": [{"name": "主账户", "positions": []}]},
    )
    write_yaml(config_dir / "watchlist.yaml", {"themes": []})
    write_yaml(
        config_dir / "strategy_pack.yaml",
        {
            "market_framework": {
                "current_stage": "磨底期观察",
                "index_rules": [
                    {
                        "index": "上证指数",
                        "trigger_condition": "intraday_below",
                        "threshold": 3400.0,
                        "action": "指数跌破观察",
                        "severity": "observe",
                    }
                ],
            },
            "sector_groups": [
                {
                    "id": "offensive",
                    "name": "进攻",
                    "members": [
                        {"code": "000021.SZ"},
                        {"code": "002185.SZ"},
                        {"code": "002156.SZ"},
                    ],
                },
                {
                    "id": "defensive",
                    "name": "防御",
                    "members": [
                        {"code": "600036.SH"},
                        {"code": "601318.SH"},
                    ],
                },
            ],
            "sector_rotation_rules": [
                {
                    "id": "offensive_vs_defensive",
                    "offensive_groups": ["offensive"],
                    "defensive_groups": ["defensive"],
                    "min_spread_pct": 1.0,
                }
            ],
        },
    )
    write_yaml(config_dir / "direction_pool.yaml", {"directions": []})
    write_yaml(config_dir / "stock_pool.yaml", {"stocks": []})
    return load_monitor_config(config_dir)


def test_mock_snapshot_contains_index_and_sector_quotes():
    """mock 行情快照同时包含个股、指数和板块样本。"""
    snapshot = _mock_quote_snapshot()
    quotes = {q.get("label") or q.get("name") or q.get("code"): q for q in snapshot["quotes"]}
    assert "上证指数" in quotes
    assert "全A指数" in quotes
    assert "深科技" in quotes
    assert "招商银行" in quotes


def test_env_mock_quotes_returns_snapshot(monkeypatch):
    """QING_AGENT_MOCK_QUOTES=1 时，fetch_quotes_with_fallback 不访问网络。"""
    monkeypatch.setenv("QING_AGENT_MOCK_QUOTES", "1")
    result = fetch_quotes_with_fallback({"深科技": "0.000021"})
    assert result["source"] == "mock"
    assert "上证指数" in {q.get("name") for q in result["quotes"]}


def test_env_mock_quotes_concurrent_fetcher(monkeypatch):
    """QING_AGENT_MOCK_QUOTES=1 时，ConcurrentDataFetcher 不访问网络。"""
    monkeypatch.setenv("QING_AGENT_MOCK_QUOTES", "1")
    cf = ConcurrentDataFetcher()
    result = cf.fetch_all_sources(None, include_dragon_tiger=False)
    quotes = result["quotes"]
    assert quotes["source"] == "mock"
    assert "上证指数" in {q.get("name") for q in quotes["quotes"]}


def test_market_gate_passes_with_mock_index_data():
    """MarketGate 能从 mock 行情快照中提取指数/市场数据并给出判断。"""
    snapshot = _mock_quote_snapshot()
    cfg = {"strategy_pack": {"market_gate_rules": {}}}
    gate = MarketGate()
    result = gate.evaluate(cfg, snapshot)
    assert result.passed
    assert result.checks["非连续恐慌"]
    assert result.bias in ("可操作", "观望")


def test_index_rule_engine_triggers_with_mock_data():
    """IndexRuleEngine 使用 mock 的上证指数数据触发规则。"""
    snapshot = _mock_quote_snapshot()
    config = {
        "market_framework": {
            "index_rules": [
                {
                    "index": "上证指数",
                    "trigger_condition": "intraday_below",
                    "threshold": 3400.0,
                    "action": "跌破防线",
                    "severity": "observe",
                }
            ]
        }
    }
    engine = IndexRuleEngine()
    alerts = engine.evaluate(config, snapshot, current_time=datetime(2026, 5, 22, 10, 30, tzinfo=CN_TZ))
    assert len(alerts) == 1
    assert "跌破防线" in alerts[0].summary
    assert "上证指数" in alerts[0].summary


def test_sector_rotation_rule_engine_triggers_with_mock_data():
    """SectorRotationRuleEngine 使用 mock 板块样本计算强弱并触发规则。"""
    snapshot = _mock_quote_snapshot()
    config = {
        "sector_groups": [
            {
                "id": "offensive",
                "name": "进攻",
                "members": [
                    {"code": "000021.SZ"},
                    {"code": "002185.SZ"},
                    {"code": "002156.SZ"},
                ],
            },
            {
                "id": "defensive",
                "name": "防御",
                "members": [
                    {"code": "600036.SH"},
                    {"code": "601318.SH"},
                ],
            },
        ],
        "sector_rotation_rules": [
            {
                "id": "offensive_vs_defensive",
                "offensive_groups": ["offensive"],
                "defensive_groups": ["defensive"],
                "min_spread_pct": 1.0,
            }
        ],
    }
    engine = SectorRotationRuleEngine()
    alerts = engine.evaluate(config, snapshot)
    assert len(alerts) == 1
    assert alerts[0].action == "进攻回流观察"


def test_run_tick_with_env_mock_quotes_and_market_sector_rules(tmp_path: Path, monkeypatch):
    """run_tick 在 env mock 模式下，大盘/指数/板块规则都能产生告警。"""
    monkeypatch.setenv("QING_AGENT_MOCK_QUOTES", "1")
    monkeypatch.setenv("QING_AGENT_IGNORE_TRADING_TIME", "1")
    config = make_config_with_market_rules(tmp_path)

    message = run_tick(
        config,
        datetime(2026, 5, 22, 10, 30, tzinfo=CN_TZ),
        emit_status=False,
        ignore_trading_time=False,
    )

    assert "[Hermes股票监控提醒]" in message
    assert "数据源：mock" in message
    assert "指数跌破观察" in message
    assert "进攻回流观察" in message
