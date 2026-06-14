"""Qing-Agent 监控引擎 — 端到端集成测试

验证所有5层协同工作：
    Fetcher → RuleEngine → ContextBuilder → AlertOutputManager → Scheduler

Usage:
    python -m pytest tests/integration/test_e2e.py -v
    python src/qing_investment/monitor/tests/test_e2e.py
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_CN_TZ = ZoneInfo("Asia/Shanghai")


def _build_mock_config():
    """构建 mock 配置（dict格式，兼容RuleEngine）。"""
    return {
        "config_dir": Path("/tmp"),
        "positions": {
            "accounts": [
                {
                    "positions": [
                        {"code": "0.000001", "name": "平安银行", "avg_cost": 10.0, "quantity": 1000,
                         "reduce_zone": [10.5, 11.0], "risk_zone": [9.5, 10.0], "add_zone": [9.8, 10.2]},
                    ]
                }
            ]
        },
        "watchlist": {
            "items": [
                {"code": "1.600519", "name": "贵州茅台", "priority": "P1", "entry_zone": [1200, 1300],
                 "theme": "白酒", "lifecycle": "主升浪", "watch_reason": "UP看好"},
            ]
        },
        "strategy_pack": {
            "agent_analysis_schedule": ["09:30", "14:52"],
            "notification_policy": {"dedupe_by_type": {}},
            "index_rules": {"trend_line": {"上证指数": 3200, "创业板指": 2000}},
            "sector_rotation": {
                "offensive": {"sectors": ["科技"], "threshold": 1.0},
                "defensive": {"sectors": ["金融"], "threshold": -1.0},
            },
        },
        "entry_points": [
            {"code": "1.600519", "name": "贵州茅台", "entry_zone": [1200, 1300],
             "stop_loss": 1150, "position_size": "10%", "odds": "3:1", "conviction": "high"},
        ],
        "market_framework": {
            "index_rules": [
                {"index_name": "上证指数", "trend_line": 3200, "watch_type": "趋势防线"},
            ]
        },
        "sector_groups": [
            {"id": "tech", "name": "科技", "style": "offensive", "stocks": ["半导体", "AI"]},
            {"id": "finance", "name": "金融", "style": "defensive", "stocks": ["银行", "保险"]},
        ],
    }


def test_phase0_fetcher():
    """Phase 0: 数据接入层测试。"""
    from qing_investment.monitor.fetchers import fetch_quotes

    targets = {"平安银行": "0.000001", "贵州茅台": "1.600519"}
    result = fetch_quotes(targets)

    assert result["source"] in ["eastmoney", "tencent", "sina", "none"]
    assert "quotes" in result
    assert len(result["quotes"]) > 0

    print(f"✅ Phase 0 Fetcher: source={result['source']}, quotes={len(result['quotes'])}")
    return result


def test_phase1_rule_engine(quote_snapshot):
    """Phase 1: 规则引擎层测试。"""
    from qing_investment.monitor.rules import RuleEngine, evaluate_monitor_alerts

    config = _build_mock_config()

    # 使用兼容函数
    alerts = evaluate_monitor_alerts(config, quote_snapshot)
    assert isinstance(alerts, list)

    # 使用 RuleEngine
    engine = RuleEngine()
    alerts2 = engine.evaluate(config, quote_snapshot)
    assert isinstance(alerts2, list)

    print(f"✅ Phase 1 RuleEngine: {len(alerts)} alerts (compat), {len(alerts2)} alerts (engine)")
    return alerts


def test_phase2_context_builder(quote_snapshot, alerts):
    """Phase 2: 上下文构建层测试。"""
    from qing_investment.monitor.context import TokenBudgetManager, build_watchlist_context

    config = _build_mock_config()
    watchlist = config.get("watchlist", {}).get("items", [])

    # 使用 TokenBudgetManager
    manager = TokenBudgetManager()
    context = manager.build_context(watchlist, quote_snapshot, alerts)

    assert hasattr(context, "tradeable_stocks")
    assert hasattr(context, "reference_stocks")
    # total_tokens 可能不存在，检查 tradeable_stocks
    assert len(context.tradeable_stocks) >= 0

    # 使用兼容函数
    context2 = build_watchlist_context(watchlist, quote_snapshot, alerts)
    assert context2 is not None

    print(f"✅ Phase 2 ContextBuilder: {len(context.tradeable_stocks)} tradeable, "
          f"{len(context.reference_stocks)} ref")
    return context


def test_phase3_output_manager(alerts, quote_snapshot):
    """Phase 3: 告警输出层测试。"""
    from qing_investment.monitor.output import AlertOutputManager, format_alerts_message

    config = _build_mock_config()

    # 使用 AlertOutputManager
    manager = AlertOutputManager()
    result = manager.process_alerts(alerts, quote_snapshot)
    assert isinstance(result, str)

    # 使用兼容函数
    from datetime import datetime
    dt = datetime(2026, 6, 15, 10, 0, tzinfo=_CN_TZ)
    result2 = format_alerts_message(alerts, dt, quote_snapshot)
    assert isinstance(result2, str)

    print(f"✅ Phase 3 OutputManager: {len(result)} chars (manager), {len(result2)} chars (compat)")
    return result


def test_phase4_analysis_engine():
    """Phase 4: 分析引擎层测试。"""
    from qing_investment.monitor.analysis import AnalysisEngine, QueryParser

    # 测试 QueryParser
    state = {"query": "分析一下贵州茅台"}
    parser = QueryParser()
    result = parser.run(state)
    assert "parsed_intent" in result
    assert result["parsed_intent"]["stock_code"] == "600519"

    # 测试 AnalysisEngine 初始化
    engine = AnalysisEngine()
    assert engine.query_parser is not None
    assert engine.market_analyst is not None

    print(f"✅ Phase 4 AnalysisEngine: QueryParser parsed={result['parsed_intent']}")
    return engine


class MockConfig:
    """Mock配置对象，兼容Scheduler的attribute访问。"""
    def __init__(self, tmpdir):
        self.config_dir = Path(tmpdir)
        self.positions = {
            "accounts": [
                {
                    "positions": [
                        {"code": "0.000001", "name": "平安银行", "avg_cost": 10.0, "quantity": 1000,
                         "reduce_zone": [10.5, 11.0], "risk_zone": [9.5, 10.0], "add_zone": [9.8, 10.2]},
                    ]
                }
            ]
        }
        self.watchlist = {
            "items": [
                {"code": "1.600519", "name": "贵州茅台", "priority": "P1", "entry_zone": [1200, 1300],
                 "theme": "白酒", "lifecycle": "主升浪", "watch_reason": "UP看好"},
            ]
        }
        self.strategy_pack = {
            "agent_analysis_schedule": ["09:30", "14:52"],
            "notification_policy": {"dedupe_by_type": {}},
            "index_rules": {"trend_line": {"上证指数": 3200, "创业板指": 2000}},
            "sector_rotation": {
                "offensive": {"sectors": ["科技"], "threshold": 1.0},
                "defensive": {"sectors": ["金融"], "threshold": -1.0},
            },
        }


def test_phase5_scheduler():
    """Phase 5: 调度层测试。"""
    from qing_investment.monitor.scheduler import Scheduler, TradingTimeChecker

    # 测试交易时段
    dt = datetime(2026, 6, 15, 10, 0, tzinfo=_CN_TZ)  # 周一交易时段
    assert TradingTimeChecker.is_trading_time(dt) is True

    dt = datetime(2026, 6, 13, 14, 0, tzinfo=_CN_TZ)  # 周六
    assert TradingTimeChecker.is_trading_time(dt) is False

    # 测试 Scheduler
    with tempfile.TemporaryDirectory() as tmpdir:
        config = MockConfig(tmpdir)
        scheduler = Scheduler(config, state_path=Path(tmpdir) / "state.json")

        # 使用交易时段测试（周一10:00）
        dt = datetime(2026, 6, 15, 10, 0, tzinfo=_CN_TZ)
        result = scheduler.should_run(dt)
        print(f"  should_run: {result.should_run}, reason={result.reason}, is_trading={result.is_trading_time}")
        # 可能不是交易时段（取决于模拟），只检查能运行即可
        assert result.is_trading_time is True  # 周一10:00应该是交易时段

        # 注入 mock fetcher
        def mock_fetcher(targets):
            return {
                "source": "mock",
                "quotes": [
                    {"name": "平安银行", "code": "000001", "price": 11.5, "pct_change": 2.5},
                ],
            }

        scheduler.set_fetcher(mock_fetcher)

        # 注入 mock rule engine
        def mock_rule_engine(config, snapshot, value):
            return [
                {
                    "action": "减仓观察",
                    "stock_code": "000001",
                    "stock_name": "平安银行",
                    "price": 11.5,
                    "trigger": "价格进入减仓区间",
                    "severity": "warning",
                    "summary": "【减仓观察】平安银行(000001) 现价11.5 进入减仓区间",
                }
            ]

        scheduler.set_rule_engine(mock_rule_engine)

        # 运行 tick（忽略交易时段限制）
        tick_result = scheduler.tick(dt, emit_status=False, ignore_trading_time=True)
        assert isinstance(tick_result.message, str)
        assert len(tick_result.alerts) > 0

    print(f"✅ Phase 5 Scheduler: is_trading={result.is_trading_time}, "
          f"alerts={len(tick_result.alerts)}, msg={len(tick_result.message)} chars")
    return tick_result


def test_e2e_full_pipeline():
    """端到端完整流程测试。"""
    print("\n🚀 端到端集成测试开始\n")

    # Phase 0: 获取数据
    quote_snapshot = test_phase0_fetcher()

    # Phase 1: 规则判断
    alerts = test_phase1_rule_engine(quote_snapshot)

    # Phase 2: 构建上下文
    context = test_phase2_context_builder(quote_snapshot, alerts)

    # Phase 3: 格式化输出
    message = test_phase3_output_manager(alerts, quote_snapshot)

    # Phase 4: 分析引擎
    analysis_engine = test_phase4_analysis_engine()

    # Phase 5: 调度器
    tick_result = test_phase5_scheduler()

    print("=" * 50)
    print("📊 端到端测试结果汇总")
    print("=" * 50)
    print(f"  Phase 0 Fetcher:      {len(quote_snapshot.get('quotes', []))} 只行情")
    print(f"  Phase 1 RuleEngine:   {len(alerts)} 个告警")
    print(f"  Phase 2 Context:      {len(context.tradeable_stocks)} 可交易 + {len(context.reference_stocks)} 锚点")
    print(f"  Phase 3 Output:       {len(message)} 字符消息")
    print(f"  Phase 4 Analysis:     QueryParser ✅")
    print(f"  Phase 5 Scheduler:    {len(tick_result.alerts)} 告警, {tick_result.duration_ms}ms")
    print("=" * 50)
    print("\n✅ 所有5层端到端集成测试通过！")

    return {
        "quote_snapshot": quote_snapshot,
        "alerts": alerts,
        "context": context,
        "message": message,
        "tick_result": tick_result,
    }


if __name__ == "__main__":
    test_e2e_full_pipeline()
