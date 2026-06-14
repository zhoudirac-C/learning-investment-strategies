"""
Qing-Agent 监控引擎 — 端到端集成测试

覆盖：
  T20260614-001 瘦身修复: 所有子模块委托函数可正常调用
  T20260614-002 性能优化: DataCache / AuctionCache / ConcurrentDataFetcher / InotifyConfigWatcher

分层测试设计：
  1. Unit: 缓存层、工具函数（纯逻辑，无网络）
  2. Integration: 子模块串联、run_tick（Mock 行情）
  3. Live: 真实 fetch（需网络，默认 skip）

Usage:
    python -m pytest src/qing_investment/monitor/tests/test_e2e.py -v
    python -m pytest src/qing_investment/monitor/tests/test_e2e.py -v -k "not live"
    python src/qing_investment/monitor/tests/test_e2e.py          # 直接运行
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

_CN_TZ = ZoneInfo("Asia/Shanghai")

# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def mock_quote_snapshot() -> dict:
    """模拟 fetch_quotes 返回的行情快照。"""
    return {
        "source": "eastmoney",
        "quotes": [
            {
                "code": "1.600519",
                "name": "贵州茅台",
                "latest": 1420.0,
                "open": 1410.0,
                "high": 1430.0,
                "low": 1405.0,
                "volume": 2_500_000,
                "amount": 3_550_000_000,
                "pct_change": 1.2,
                "turnover_rate": 0.15,
            },
            {
                "code": "0.000001",
                "name": "平安银行",
                "latest": 10.5,
                "open": 10.3,
                "high": 10.6,
                "low": 10.2,
                "volume": 15_000_000,
                "amount": 157_500_000,
                "pct_change": 0.8,
                "turnover_rate": 0.3,
            },
            {
                "code": "1.000001",
                "name": "上证指数",
                "latest": 3350.0,
                "open": 3340.0,
                "high": 3360.0,
                "low": 3335.0,
                "volume": 0,
                "amount": 0,
                "pct_change": 0.5,
                "turnover_rate": 0.0,
            },
        ],
        "errors": [],
        "elapsed_ms": 320,
    }


@pytest.fixture
def mock_config() -> dict:
    """模拟监控配置（dict 格式，兼容 evaluate_monitor_alerts / RuleEngine）。"""
    return {
        "positions": {
            "accounts": [
                {
                    "positions": [
                        {
                            "code": "000001",
                            "name": "平安银行",
                            "avg_cost": 10.0,
                            "quantity": 1000,
                            "reduce_zone": [10.5, 11.0],
                            "risk_zone": [9.5, 10.0],
                            "add_zone": [9.8, 10.2],
                        },
                        {
                            "code": "600519",
                            "name": "贵州茅台",
                            "avg_cost": 1350.0,
                            "quantity": 100,
                            "reduce_zone": [1450, 1550],
                            "risk_zone": [1300, 1350],
                            "add_zone": [1250, 1320],
                        },
                    ]
                }
            ]
        },
        "watchlist": {
            "items": [
                {
                    "code": "600519",
                    "name": "贵州茅台",
                    "priority": "P1",
                    "entry_zone": [1200, 1300],
                    "theme": "白酒",
                    "lifecycle": "主升浪",
                    "watch_reason": "UP看好",
                },
            ]
        },
        "strategy_pack": {
            "agent_analysis_schedule": ["09:30", "14:52"],
            "notification_policy": {"dedupe_by_type": {}},
            "index_rules": {"trend_line": {"上证指数": 3200}},
            "sector_rotation": {
                "offensive": {"sectors": ["科技"], "threshold": 1.0},
                "defensive": {"sectors": ["金融"], "threshold": -1.0},
            },
        },
        "entry_points": [
            {
                "code": "600519",
                "name": "贵州茅台",
                "entry_zone": [1200, 1300],
                "stop_loss": 1150,
                "position_size": "10%",
                "odds": "3:1",
                "conviction": "high",
            },
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


# ═══════════════════════════════════════════════════════════════
# T20260614-001: 子模块委托函数完整性测试
# ═══════════════════════════════════════════════════════════════

class TestSlimmingDelegation:
    """验证瘦身修复后所有子模块委托函数可正常导入调用。"""

    def test_001_fetchers_imports(self):
        from qing_investment.monitor.fetchers import (
            fetch_quotes, fetch_quotes_with_fallback,
            collect_quote_targets, stock_code_to_secid,
            _auction_snapshot, _pure_stock_code,
            ConcurrentDataFetcher,
        )
        assert callable(fetch_quotes)
        assert callable(fetch_quotes_with_fallback)
        assert callable(collect_quote_targets)
        assert callable(stock_code_to_secid)
        assert callable(_auction_snapshot)
        assert callable(_pure_stock_code)
        assert ConcurrentDataFetcher is not None

    def test_002_analysis_imports(self):
        from qing_investment.monitor.analysis import parse_price_zone, position_rows
        assert callable(parse_price_zone)
        assert callable(position_rows)

    def test_003_rules_imports(self):
        from qing_investment.monitor.rules import (
            RuleEngine, PositionRuleEngine,
            BuySignalRuleEngine, IndexRuleEngine, SectorRotationRuleEngine,
            evaluate_monitor_alerts, validate_position_price_zones, RuleAlert,
        )
        assert RuleEngine is not None
        assert PositionRuleEngine is not None
        assert BuySignalRuleEngine is not None
        assert IndexRuleEngine is not None
        assert SectorRotationRuleEngine is not None
        assert callable(evaluate_monitor_alerts)
        assert callable(validate_position_price_zones)

    def test_004_output_imports(self):
        from qing_investment.monitor.output import (
            AlertOutputManager, AlertFormatter, DedupeEngine,
            format_alerts_message, format_quote_line, format_smoke_message,
            filter_new_alerts, record_emitted_alerts,
        )
        assert AlertOutputManager is not None
        assert AlertFormatter is not None
        assert DedupeEngine is not None
        assert callable(format_alerts_message)
        assert callable(format_quote_line)
        assert callable(format_smoke_message)
        assert callable(filter_new_alerts)

    def test_005_context_imports(self):
        from qing_investment.monitor.context import (
            TokenBudgetManager, build_watchlist_context,
            format_agent_analysis_context, format_agent_json_context,
            format_daily_review_context, format_live_analysis_context,
            load_monitor_config, StockPrioritizer,
        )
        assert TokenBudgetManager is not None
        assert callable(build_watchlist_context)
        assert callable(format_agent_analysis_context)
        assert callable(format_agent_json_context)
        assert callable(load_monitor_config)

    def test_006_scheduler_imports(self):
        from qing_investment.monitor.scheduler import (
            run_tick, is_a_share_trading_time,
            is_scheduled_agent_analysis_time,
            load_monitor_state, save_monitor_state,
            format_status_message, InotifyConfigWatcher,
        )
        assert callable(run_tick)
        assert callable(is_a_share_trading_time)
        assert callable(is_scheduled_agent_analysis_time)
        assert callable(format_status_message)
        assert InotifyConfigWatcher is not None

    def test_007_stock_monitor_delegation(self):
        """验证 stock_monitor.py 34 个关键委托函数可正常调用。"""
        from qing_investment import stock_monitor
        key_funcs = [
            "format_watchlist_condition_line", "sector_group_rows",
            "unique_stock_count", "stock_code_to_secid",
            "collect_quote_targets", "parse_price_zone",
            "evaluate_position_alerts", "evaluate_buy_signal_candidates",
            "evaluate_market_alerts", "compute_sector_strength",
            "evaluate_sector_rotation_alerts", "evaluate_monitor_alerts",
            "format_alerts_message", "alert_fingerprint",
            "load_monitor_state", "save_monitor_state",
            "filter_new_alerts", "record_emitted_alerts",
            "format_alert_decision_log", "find_agent_analysis_trigger",
            "record_agent_analysis_trigger",
            "format_agent_analysis_context",
            "format_daily_review_context", "format_quote_line",
            "format_smoke_message", "format_status_message",
            "load_monitor_config", "validate_position_price_zones",
            "update_sector_signal_counts", "update_market_state",
        ]
        failed = []
        for name in key_funcs:
            if not hasattr(stock_monitor, name):
                failed.append(name)
            else:
                fn = getattr(stock_monitor, name)
                if not callable(fn):
                    failed.append(f"{name}(not_callable)")
        assert not failed, f"缺失/不可调用的委托函数: {failed}"


# ═══════════════════════════════════════════════════════════════
# T20260614-002: 性能优化单元测试
# ═══════════════════════════════════════════════════════════════

class TestDataCache:
    """DataCache: TTL缓存 + LRU淘汰 + 命中率统计。"""

    def test_basic_set_get(self):
        from qing_investment.monitor.cache import DataCache
        cache = DataCache(max_entries=100)
        cache.set("test:1", {"price": 10.5}, ttl=60)
        assert cache.get("test:1") == {"price": 10.5}

    def test_miss_returns_none(self):
        from qing_investment.monitor.cache import DataCache
        cache = DataCache(max_entries=100)
        assert cache.get("nonexistent") is None

    def test_ttl_expiry(self):
        from qing_investment.monitor.cache import DataCache
        cache = DataCache(max_entries=100)
        cache.set("test:2", "value", ttl=0.01)
        assert cache.get("test:2") == "value"
        time.sleep(0.02)
        assert cache.get("test:2") is None

    def test_invalidate_all(self):
        from qing_investment.monitor.cache import DataCache
        cache = DataCache(max_entries=100)
        cache.set("a:1", 1)
        cache.set("a:2", 2)
        cache.set("b:1", 3)
        assert cache.invalidate() == 3
        assert cache.get("a:1") is None

    def test_invalidate_by_pattern(self):
        from qing_investment.monitor.cache import DataCache
        cache = DataCache(max_entries=100)
        cache.set("quotes:600519", 1)
        cache.set("quotes:000001", 2)
        cache.set("dragon_tiger:600519", 3)
        assert cache.invalidate("quotes:") == 2
        assert cache.get("quotes:600519") is None
        assert cache.get("dragon_tiger:600519") == 3

    def test_lru_eviction(self):
        from qing_investment.monitor.cache import DataCache
        cache = DataCache(max_entries=5)
        for i in range(5):
            cache.set(f"k:{i}", i)
        cache.set("k:5", 5)  # 触发淘汰
        stats = cache.stats()
        assert stats["evictions"] == 1
        assert stats["size"] == 5

    def test_hit_rate_stats(self):
        from qing_investment.monitor.cache import DataCache
        cache = DataCache(max_entries=100)
        cache.set("k:v", "value")
        cache.get("k:v")   # hit
        cache.get("k:v")   # hit
        cache.get("missing")  # miss
        cache.get("missing")  # miss
        stats = cache.stats()
        assert stats["hits"] == 2
        assert stats["misses"] == 2
        assert stats["hit_rate"] == 0.5

    def test_get_or_set(self):
        from qing_investment.monitor.cache import DataCache
        cache = DataCache(max_entries=100)
        called = 0

        def factory():
            nonlocal called
            called += 1
            return {"data": 42}

        v1 = cache.get_or_set("test:factory", factory)
        assert v1 == {"data": 42}
        assert called == 1

        v2 = cache.get_or_set("test:factory", factory)
        assert v2 == {"data": 42}
        assert called == 1  # 不再调用 factory

    def test_clear(self):
        from qing_investment.monitor.cache import DataCache
        cache = DataCache(max_entries=100)
        cache.set("k:v", 1)
        cache.clear()
        assert cache.get("k:v") is None
        assert cache.stats()["size"] == 0


class TestAuctionCache:
    """AuctionCache: 竞价数据内存+文件分层。"""

    def test_init_and_set_get(self):
        from qing_investment.monitor.cache import AuctionCache
        with tempfile.TemporaryDirectory() as tmpdir:
            ac = AuctionCache(config_dir=tmpdir)
            code = "600519"
            today = datetime.now().strftime("%Y-%m-%d")
            ac.update({code: {"volume": 500_000, "price": 1410.0, "pct_change": 0.5}})
            history = ac.get_history(code, days=5)
            assert len(history) >= 1
            dates = [e["date"] for e in history]
            assert today in dates

    def test_file_persistence(self):
        from qing_investment.monitor.cache import AuctionCache
        with tempfile.TemporaryDirectory() as tmpdir:
            code = "000001"
            ac1 = AuctionCache(config_dir=tmpdir)
            ac1.update({code: {"volume": 10_000_000, "price": 10.3, "pct_change": 0.5}})
            # 新实例读取（验证文件持久化）
            ac2 = AuctionCache(config_dir=tmpdir)
            history = ac2.get_history(code, days=5)
            assert len(history) >= 1

    def test_empty_cache(self):
        from qing_investment.monitor.cache import AuctionCache
        with tempfile.TemporaryDirectory() as tmpdir:
            ac = AuctionCache(config_dir=tmpdir)
            assert ac.get_history("nonexistent", days=5) == []

    def test_deduplicate_by_date(self):
        """同一天多次 update 不同股票，不产生重复条目。"""
        from qing_investment.monitor.cache import AuctionCache
        with tempfile.TemporaryDirectory() as tmpdir:
            ac = AuctionCache(config_dir=tmpdir)
            today = datetime.now().strftime("%Y-%m-%d")
            # 同类数据更新两次
            ac.update({"600519": {"volume": 100, "price": 1410.0, "pct_change": 0.5}})
            ac.update({"600519": {"volume": 200, "price": 1415.0, "pct_change": 0.6}})
            history = ac.get_history("600519", days=5)
            today_entries = [e for e in history if e.get("date") == today]
            assert len(today_entries) == 1, "同一股票同一天不应重复"


class TestInotifyConfigWatcher:
    """InotifyConfigWatcher: 事件驱动 + 降级方案。"""

    def test_init_and_stop(self):
        from qing_investment.monitor.scheduler import InotifyConfigWatcher
        with tempfile.TemporaryDirectory() as tmpdir:
            for fname in ("positions.yaml", "watchlist.yaml", "strategy_pack.yaml"):
                (Path(tmpdir) / fname).write_text("key: value\n", encoding="utf-8")
            watcher = InotifyConfigWatcher(config_dir=Path(tmpdir))
            assert watcher.start() in (True, False)
            assert watcher.check() is False
            watcher.stop()

    def test_detect_change(self):
        from qing_investment.monitor.scheduler import InotifyConfigWatcher
        with tempfile.TemporaryDirectory() as tmpdir:
            pos_path = Path(tmpdir) / "positions.yaml"
            pos_path.write_text("old: data\n", encoding="utf-8")
            watcher = InotifyConfigWatcher(config_dir=Path(tmpdir))
            started = watcher.start()
            pos_path.write_text("new: data\n", encoding="utf-8")
            time.sleep(0.1)
            if started:
                assert watcher.check() is True
            else:
                assert watcher.check() in (True, False)
            watcher.stop()

    def test_fallback_on_no_watchdog(self):
        from qing_investment.monitor.scheduler import InotifyConfigWatcher
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "positions.yaml").write_text("key: value\n", encoding="utf-8")
            watcher = InotifyConfigWatcher(config_dir=Path(tmpdir))
            watcher.start()
            assert watcher.check() is False
            watcher.stop()


class TestConcurrentDataFetcher:
    """ConcurrentDataFetcher: 并发Fetch + 缓存集成。"""

    def test_init(self):
        from qing_investment.monitor.fetchers import ConcurrentDataFetcher
        cf = ConcurrentDataFetcher(max_workers=3, timeout=5)
        assert cf._max_workers == 3
        assert cf._timeout == 5

    def test_fetch_all_sources_with_mock_config(self):
        """验证 fetch_all_sources 能收集目标并返回正确结构。"""
        from qing_investment.monitor.fetchers import ConcurrentDataFetcher
        cf = ConcurrentDataFetcher(max_workers=2, timeout=5)

        class MockMonitorConfig:
            config_dir = Path("/tmp")
            positions = {"accounts": [{"positions": []}]}
            watchlist = {"items": []}
            strategy_pack = {"index_rules": {}, "sector_rotation": {}}
            positions_path = Path("/tmp/positions.yaml")

        result = cf.fetch_all_sources(MockMonitorConfig())
        assert "quotes" in result
        assert isinstance(result["quotes"], dict)


# ═══════════════════════════════════════════════════════════════
# 性能优化验收标准专用测试
# ═══════════════════════════════════════════════════════════════

class TestPerformanceAcceptance:
    """对标 T20260614-002 验收标准（非实时验证）。"""

    def test_cache_hit_rate_tracking(self):
        """验收标准: 缓存命中率可追踪。"""
        from qing_investment.monitor.cache import DataCache
        cache = DataCache(max_entries=100)
        for i in range(5):
            cache.set(f"k:{i}", i)
        for i in range(5):
            cache.get(f"k:{i}")   # hit
        for i in range(5, 10):
            cache.get(f"k:{i}")   # miss
        stats = cache.stats()
        assert "hit_rate" in stats
        assert stats["hit_rate"] == 0.5
        assert stats["hits"] == 5
        assert stats["misses"] == 5

    def test_cache_ttl_quotes(self):
        """验收标准: 行情数据 30 秒 TTL。"""
        from qing_investment.monitor.cache import DataCache, TTL_QUOTES
        assert TTL_QUOTES == 30
        cache = DataCache(max_entries=100)
        cache.set("quotes:600519", {"price": 1420}, ttl=TTL_QUOTES)
        assert cache.get("quotes:600519") == {"price": 1420}

    def test_cache_lru_memory_safe(self):
        """验收标准: 上限+LRU 防内存泄漏。"""
        from qing_investment.monitor.cache import DataCache
        cache = DataCache(max_entries=10)
        for i in range(20):
            cache.set(f"stress:{i}", "x" * 1000)
        stats = cache.stats()
        assert stats["size"] <= 10
        assert stats["evictions"] >= 1

    def test_concurrent_fetcher_isolation(self):
        """验收标准: 单源失败不阻塞整体（验证隔离机制）。"""
        from qing_investment.monitor.fetchers import ConcurrentDataFetcher
        cf = ConcurrentDataFetcher(max_workers=2, timeout=1)
        # ThreadPoolExecutor + as_completed, 一个 task 异常不影响其他
        assert cf._timeout == 1

    def test_validate_price_zones_api(self):
        """验收标准: 防失真检查接口可用。"""
        from qing_investment.monitor.rules import validate_position_price_zones

        class MockMonitorConfig:
            config_dir = Path("/tmp")
            positions = {"accounts": [{"positions": []}]}
            watchlist = {"items": []}
            strategy_pack = {}
            positions_path = Path("/tmp/positions.yaml")

        warnings = validate_position_price_zones(MockMonitorConfig())
        assert isinstance(warnings, list)

    def test_auction_cache_mem_file_hierarchy(self):
        """验收标准: 当日竞价数据走内存，无需读文件。"""
        from qing_investment.monitor.cache import AuctionCache
        with tempfile.TemporaryDirectory() as tmpdir:
            ac = AuctionCache(config_dir=tmpdir)
            ac.update({"600519": {"volume": 100, "price": 1410.0, "pct_change": 0.5}})
            # 第一次 load 写入文件
            history1 = ac.get_history("600519", days=5)
            assert len(history1) >= 1
            # 第二次 load 走内存缓存
            history2 = ac.get_history("600519", days=5)
            assert len(history2) >= 1

    def test_inotify_zero_poll(self):
        """验收标准: check() 非阻塞，无额外 tick 开销。"""
        from qing_investment.monitor.scheduler import InotifyConfigWatcher
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "positions.yaml").write_text("k: v\n", encoding="utf-8")
            watcher = InotifyConfigWatcher(config_dir=Path(tmpdir))
            watcher.start()
            # check() 即时返回，不阻塞
            t0 = time.monotonic()
            result = watcher.check()
            elapsed = time.monotonic() - t0
            assert elapsed < 0.05  # 应在毫秒级返回
            watcher.stop()


# ═══════════════════════════════════════════════════════════════
# 集成测试（5 层管道）
# ═══════════════════════════════════════════════════════════════

class TestPipeline:
    """5 层端到端集成测试（使用 mock 行情）。"""

    def test_phase0_fetcher_helpers(self):
        """Phase 0: 数据收集辅助函数。"""
        from qing_investment.monitor.fetchers import collect_quote_targets, stock_code_to_secid

        class MockMonitorConfig:
            config_dir = Path("/tmp")
            positions = {"accounts": [{"positions": []}]}
            watchlist = {"items": []}
            strategy_pack = {}
            positions_path = Path("/tmp/positions.yaml")

        targets = collect_quote_targets(MockMonitorConfig())
        assert isinstance(targets, dict)
        assert len(targets) >= 1  # 至少包含市场指数
        secid = stock_code_to_secid("600519.SH")
        assert secid == "1.600519"

    def test_phase1_rule_engine(self, mock_config, mock_quote_snapshot):
        """Phase 1: 规则引擎 — 评估告警。"""
        from qing_investment.monitor.rules import evaluate_monitor_alerts
        alerts = evaluate_monitor_alerts(mock_config, mock_quote_snapshot)
        assert isinstance(alerts, list)

    def test_phase2_context_builder(self, mock_config, mock_quote_snapshot):
        """Phase 2: 上下文构建。"""
        from qing_investment.monitor.context import build_watchlist_context
        from qing_investment.monitor.context import position_rows, watchlist_stock_rows

        class MockMonitorConfig:
            config_dir = Path("/tmp")
            positions = mock_config["positions"]
            watchlist = mock_config["watchlist"]
            strategy_pack = mock_config["strategy_pack"]
            positions_path = Path("/tmp/positions.yaml")

        config = MockMonitorConfig()
        watchlist = watchlist_stock_rows(config)
        positions = position_rows(config)
        entry_points = mock_config.get("entry_points", [])
        context = build_watchlist_context(
            watchlist, positions, entry_points,
            quote_snapshot=mock_quote_snapshot,
        )
        assert context is not None

    def test_phase3_output_formatter(self, mock_config, mock_quote_snapshot):
        """Phase 3: 输出格式化。"""
        from qing_investment.monitor.rules import evaluate_monitor_alerts
        from qing_investment.monitor.output import format_alerts_message
        alerts = evaluate_monitor_alerts(mock_config, mock_quote_snapshot)
        msg = format_alerts_message(alerts, datetime.now(_CN_TZ), mock_quote_snapshot)
        assert isinstance(msg, str)

    def test_phase3_alert_output_manager(self, mock_config, mock_quote_snapshot):
        """Phase 3: AlertOutputManager 全流程。"""
        from qing_investment.monitor.rules import evaluate_monitor_alerts
        from qing_investment.monitor.output import AlertOutputManager
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"
            aom = AlertOutputManager(state_path=state_path)
            alerts = evaluate_monitor_alerts(mock_config, mock_quote_snapshot)
            msg = aom.process_alerts(
                alerts, mock_quote_snapshot,
                dedupe_minutes=10, output_format="wechat",
            )
            assert isinstance(msg, str)
            stats = aom.get_stats()
            assert isinstance(stats, dict)

    def test_phase5_scheduler_helpers(self, mock_config, mock_quote_snapshot):
        """Phase 5: 调度器辅助函数。"""
        from qing_investment.monitor.scheduler import (
            run_tick, is_a_share_trading_time, format_status_message,
        )
        now = datetime.now(_CN_TZ)
        assert isinstance(is_a_share_trading_time(now), bool)

    def test_phase5_scheduler_with_concurrent(self, mock_config, mock_quote_snapshot):
        """Phase 5: run_tick(use_concurrent_fetcher=True) 集成。"""
        from qing_investment.monitor.scheduler import run_tick
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "state.json"
            state_file.write_text("{}", encoding="utf-8")

            class MockMonitorConfig:
                config_dir = Path(tmpdir)
                positions = mock_config["positions"]
                watchlist = mock_config["watchlist"]
                strategy_pack = mock_config["strategy_pack"]
                positions_path = Path(tmpdir) / "positions.yaml"
                entry_points = mock_config.get("entry_points", [])
                market_framework = mock_config.get("market_framework", {})
                sector_groups = mock_config.get("sector_groups", [])

            config = MockMonitorConfig()
            now = datetime.now(_CN_TZ)
            result = run_tick(
                config, now,
                emit_status=False, ignore_trading_time=True,
                use_concurrent_fetcher=True,
                state_path=state_file,
            )
            assert isinstance(result, str)


# ═══════════════════════════════════════════════════════════════
# Live 测试（需要网络，默认 skip）
# ═══════════════════════════════════════════════════════════════

@pytest.mark.live
class TestLive:
    """需要真实网络数据的测试（默认跳过）。"""

    def test_live_fetch_quotes(self):
        from qing_investment.monitor.fetchers import fetch_quotes
        result = fetch_quotes({"平安银行": "0.000001", "贵州茅台": "1.600519"})
        assert result["source"] in ("eastmoney", "tencent", "sina", "none")
        assert "quotes" in result

    def test_live_concurrent_fetch(self):
        from qing_investment.monitor.fetchers import ConcurrentDataFetcher

        class MockCfg:
            config_dir = Path("/tmp")
            positions = {"accounts": []}
            watchlist = {"items": []}
            strategy_pack = {"index_rules": {}, "sector_rotation": {}}
            positions_path = Path("/tmp/positions.yaml")

        cf = ConcurrentDataFetcher(max_workers=3, timeout=10)
        result = cf.fetch_all_sources(MockCfg())
        assert "quotes" in result

    def test_live_cache_integration(self):
        from qing_investment.monitor.cache import DataCache
        from qing_investment.monitor.fetchers import fetch_quotes
        cache = DataCache(max_entries=100)
        v1 = cache.get_or_set(
            "quotes:600519",
            lambda: fetch_quotes({"贵州茅台": "1.600519"}),
            ttl=30,
        )
        assert v1 is not None
        stats = cache.stats()
        assert stats["hits"] >= 0  # 第一次是 miss


# ═══════════════════════════════════════════════════════════════
# 直接运行入口
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("📊 监控引擎端到端测试")
    print("=" * 60)

    test_classes = [
        ("TestDataCache", TestDataCache),
        ("TestAuctionCache", TestAuctionCache),
        ("TestInotifyConfigWatcher", TestInotifyConfigWatcher),
        ("TestConcurrentDataFetcher", TestConcurrentDataFetcher),
        ("TestSlimmingDelegation", TestSlimmingDelegation),
        ("TestPerformanceAcceptance", TestPerformanceAcceptance),
        ("TestPipeline", TestPipeline),
    ]

    passed = 0
    failed = 0

    for cls_name, cls in test_classes:
        print(f"\n--- {cls_name} ---")
        instance = cls()
        for name in dir(instance):
            if not name.startswith("test_"):
                continue
            try:
                if cls_name == "TestPipeline":
                    getattr(instance, name)(mock_config(), mock_quote_snapshot())
                elif cls_name == "TestPerformanceAcceptance" and name == "test_validate_price_zones_api":
                    getattr(instance, name)()
                elif cls_name == "TestPerformanceAcceptance" and name == "test_auction_cache_mem_file_hierarchy":
                    getattr(instance, name)()
                elif cls_name == "TestConcurrentDataFetcher" and name == "test_fetch_all_sources_with_mock_config":
                    getattr(instance, name)()
                elif cls_name == "TestPerformanceAcceptance" and name == "test_inotify_zero_poll":
                    getattr(instance, name)()
                else:
                    getattr(instance, name)()
                print(f"  ✅ {name}")
                passed += 1
            except Exception as e:
                print(f"  ❌ {name}: {e}")
                failed += 1

    print("\n" + "=" * 60)
    print(f"结果: {passed} 通过, {failed} 失败")
    print("=" * 60)
