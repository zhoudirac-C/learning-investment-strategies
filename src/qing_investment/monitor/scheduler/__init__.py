"""Qing-Agent 监控引擎 — 调度层 (Phase 5)

将 stock_monitor.py 中的调度逻辑（定时触发、状态管理、配置热更新）拆分为独立模块。

职责边界:
    - 只负责"何时运行、运行什么"，不负责"如何分析"
    - 输入: 配置 + 当前时间
    - 输出: 调度决策（运行/跳过/重试）

核心功能:
    1. 状态管理: JSON 持久化，自动清理
    2. 定时调度: 交易时段判断、Agent 分析排程
    3. 配置热更新: 文件监听、版本检测
    4. 状态机: tick 生命周期管理

使用:
    from qing_investment.monitor.scheduler import Scheduler, TickState
    
    scheduler = Scheduler(config)
    result = scheduler.tick(value=now, emit_status=False)
    # result 包含 message 和 state
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, time as dt_time, timedelta
from pathlib import Path
from typing import Any, Callable

from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
_CN_TZ = ZoneInfo("Asia/Shanghai")


# ──────────────────────────────────────────
# 数据模型
# ──────────────────────────────────────────


@dataclass
class TickState:
    """单次 tick 的运行状态。"""

    version: int = 1
    last_updated: str = ""  # ISO format
    stale_zone_warnings: list[str] = field(default_factory=list)
    last_quote_snapshot: dict | None = None
    last_fetch_error: dict | None = None
    emitted_alerts: list[dict] = field(default_factory=list)
    alert_decision_log: list[dict] = field(default_factory=list)
    sector_signal_counts: dict[str, Any] = field(default_factory=dict)
    market_state: dict[str, Any] = field(default_factory=dict)
    agent_analysis_log: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "last_updated": self.last_updated,
            "stale_zone_warnings": self.stale_zone_warnings,
            "last_quote_snapshot": self.last_quote_snapshot,
            "last_fetch_error": self.last_fetch_error,
            "emitted_alerts": self.emitted_alerts,
            "alert_decision_log": self.alert_decision_log,
            "sector_signal_counts": self.sector_signal_counts,
            "market_state": self.market_state,
            "agent_analysis_log": self.agent_analysis_log,
        }

    @classmethod
    def from_dict(cls, d: dict) -> TickState:
        return cls(
            version=d.get("version", 1),
            last_updated=d.get("last_updated", ""),
            stale_zone_warnings=d.get("stale_zone_warnings", []),
            last_quote_snapshot=d.get("last_quote_snapshot"),
            last_fetch_error=d.get("last_fetch_error"),
            emitted_alerts=d.get("emitted_alerts", []),
            alert_decision_log=d.get("alert_decision_log", []),
            sector_signal_counts=d.get("sector_signal_counts", {}),
            market_state=d.get("market_state", {}),
            agent_analysis_log=d.get("agent_analysis_log", []),
        )


@dataclass
class ScheduleResult:
    """调度结果。"""

    should_run: bool
    reason: str
    is_trading_time: bool
    is_scheduled_agent_time: bool
    next_tick: datetime | None = None


@dataclass
class TickResult:
    """单次 tick 执行结果。"""

    message: str
    state: TickState
    alerts: list[dict] = field(default_factory=list)
    agent_trigger: dict | None = None
    duration_ms: int = 0


# ──────────────────────────────────────────
# 1. 状态管理器
# ──────────────────────────────────────────


class StateManager:
    """状态管理器：JSON 持久化，自动清理。"""

    def __init__(self, state_path: Path | str):
        self.state_path = Path(state_path) if isinstance(state_path, str) else state_path
        self._state: TickState = TickState()
        self._load()

    def _load(self) -> None:
        """从文件加载状态。"""
        if self.state_path.exists():
            try:
                data = json.loads(self.state_path.read_text(encoding="utf-8"))
                self._state = TickState.from_dict(data)
                logger.info(f"State loaded: {self.state_path}")
            except Exception as e:
                logger.warning(f"State load failed: {e}, starting fresh")
                self._state = TickState()
        else:
            logger.info("State file not found, starting fresh")
            self._state = TickState()

    def save(self) -> None:
        """保存状态到文件。"""
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(
                json.dumps(self._state.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error(f"State save failed: {e}")

    def get(self) -> TickState:
        """获取当前状态。"""
        return self._state

    def update(self, **kwargs) -> None:
        """更新状态字段。"""
        for key, value in kwargs.items():
            if hasattr(self._state, key):
                setattr(self._state, key, value)

    def record_alert(self, alert: dict, value: datetime) -> None:
        """记录告警。"""
        self._state.emitted_alerts.append({
            **alert,
            "recorded_at": value.astimezone(_CN_TZ).isoformat(),
        })
        # 保留最近 100 条
        if len(self._state.emitted_alerts) > 100:
            self._state.emitted_alerts = self._state.emitted_alerts[-100:]

    def record_agent_analysis(self, trigger: dict, value: datetime) -> None:
        """记录 Agent 分析触发。"""
        self._state.agent_analysis_log.append({
            **trigger,
            "recorded_at": value.astimezone(_CN_TZ).isoformat(),
        })
        # 保留最近 50 条
        if len(self._state.agent_analysis_log) > 50:
            self._state.agent_analysis_log = self._state.agent_analysis_log[-50:]

    def record_decision(self, alerts: list, new_alerts: list, value: datetime) -> None:
        """记录决策日志。"""
        self._state.alert_decision_log.append({
            "time": value.astimezone(_CN_TZ).isoformat(),
            "total_alerts": len(alerts),
            "new_alerts": len(new_alerts),
            "alert_types": list(set(a.get("action", "") for a in new_alerts)),
        })
        # 保留最近 200 条
        if len(self._state.alert_decision_log) > 200:
            self._state.alert_decision_log = self._state.alert_decision_log[-200:]

    def update_quote_snapshot(self, snapshot: dict, value: datetime) -> None:
        """更新行情快照。"""
        if snapshot.get("quotes"):
            self._state.last_quote_snapshot = snapshot
            self._state.last_fetch_error = None
            self._state.last_updated = value.astimezone(_CN_TZ).isoformat()
        elif snapshot.get("errors"):
            self._state.last_fetch_error = {
                "time": value.astimezone(_CN_TZ).isoformat(),
                "source": snapshot.get("source", "unknown"),
                "errors": snapshot.get("errors", []),
                "elapsed_ms": snapshot.get("elapsed_ms"),
            }

    def update_market_state(self, alerts: list, snapshot: dict, value: datetime) -> None:
        """更新市场状态。"""
        # 板块信号计数
        for alert in alerts:
            action = alert.get("action", "")
            if "板块" in action or "sector" in action.lower():
                sector = alert.get("stock_name", "unknown")
                self._state.sector_signal_counts[sector] = self._state.sector_signal_counts.get(sector, 0) + 1

        # 市场状态摘要
        quotes = snapshot.get("quotes", [])
        if quotes:
            up_count = sum(1 for q in quotes if (q.get("pct_change") or 0) > 0)
            down_count = sum(1 for q in quotes if (q.get("pct_change") or 0) < 0)
            self._state.market_state = {
                "last_update": value.astimezone(_CN_TZ).isoformat(),
                "up_count": up_count,
                "down_count": down_count,
                "total_quotes": len(quotes),
                "up_ratio": round(up_count / len(quotes), 2) if quotes else 0,
            }


# ──────────────────────────────────────────
# 2. 交易时段判断
# ──────────────────────────────────────────


class TradingTimeChecker:
    """A股交易时段判断。"""

    MORNING_START = dt_time(9, 30)
    MORNING_END = dt_time(11, 30)
    AFTERNOON_START = dt_time(13, 0)
    AFTERNOON_END = dt_time(15, 0)

    @classmethod
    def is_trading_time(cls, value: datetime) -> bool:
        """判断是否为 A 股交易时段。"""
        # 转换为北京时间
        if value.tzinfo is None:
            value = value.replace(tzinfo=_CN_TZ)
        else:
            value = value.astimezone(_CN_TZ)

        # 周末判断
        weekday = value.weekday()
        if weekday >= 5:  # 周六=5, 周日=6
            return False

        # 节假日判断（简化版，实际应调用 holidays 库）
        # TODO: 接入中国节假日 API

        t = value.time()
        return (
            (cls.MORNING_START <= t <= cls.MORNING_END)
            or (cls.AFTERNOON_START <= t <= cls.AFTERNOON_END)
        )

    @classmethod
    def next_trading_start(cls, value: datetime) -> datetime:
        """计算下一个交易时段开始时间。"""
        value = value.astimezone(_CN_TZ)
        t = value.time()

        # 当天还有交易时段
        if value.weekday() < 5:
            if t < cls.MORNING_START:
                return value.replace(hour=9, minute=30, second=0, microsecond=0)
            elif cls.MORNING_END < t < cls.AFTERNOON_START:
                return value.replace(hour=13, minute=0, second=0, microsecond=0)
            elif t < cls.AFTERNOON_END:
                return value  # 当前就在交易时段

        # 下一个交易日
        next_day = value + timedelta(days=1)
        while next_day.weekday() >= 5:
            next_day += timedelta(days=1)
        return next_day.replace(hour=9, minute=30, second=0, microsecond=0)


# ──────────────────────────────────────────
# 3. Agent 分析排程
# ──────────────────────────────────────────


class AgentSchedule:
    """Agent 分析排程器。"""

    def __init__(self, schedule_rows: list[dict] | None = None):
        self.schedule_rows = schedule_rows or []

    @classmethod
    def from_config(cls, strategy_pack: dict) -> AgentSchedule:
        """从 strategy_pack 加载排程。"""
        rows = strategy_pack.get("agent_analysis_schedule", []) or []
        parsed = []
        for row in rows:
            if isinstance(row, str):
                # "HH:MM" 格式
                try:
                    h, m = map(int, row.split(":"))
                    parsed.append({"hour": h, "minute": m, "type": "scheduled"})
                except ValueError:
                    continue
            elif isinstance(row, dict):
                parsed.append(row)
        return cls(parsed)

    def is_scheduled_time(self, value: datetime) -> bool:
        """判断是否为排程时间。"""
        value = value.astimezone(_CN_TZ)
        current_minute = value.hour * 60 + value.minute

        for row in self.schedule_rows:
            h = row.get("hour", 0)
            m = row.get("minute", 0)
            scheduled_minute = h * 60 + m
            # 允许 ±2 分钟误差
            if abs(current_minute - scheduled_minute) <= 2:
                return True
        return False

    def get_next_scheduled(self, value: datetime) -> datetime | None:
        """获取下一个排程时间。"""
        value = value.astimezone(_CN_TZ)
        current_minute = value.hour * 60 + value.minute

        candidates = []
        for row in self.schedule_rows:
            h = row.get("hour", 0)
            m = row.get("minute", 0)
            scheduled_minute = h * 60 + m
            if scheduled_minute > current_minute:
                candidates.append((scheduled_minute, h, m))

        if candidates:
            candidates.sort()
            _, h, m = candidates[0]
            return value.replace(hour=h, minute=m, second=0, microsecond=0)
        return None

    def dedupe_key(self, row: dict, value: datetime) -> str:
        """生成去重键。"""
        h = row.get("hour", 0)
        m = row.get("minute", 0)
        return f"agent_analysis_{value.strftime('%Y%m%d')}_{h:02d}{m:02d}"


# ──────────────────────────────────────────
# 4. 配置热更新
# ──────────────────────────────────────────


class ConfigWatcher:
    """配置热更新监听器。"""

    def __init__(self, config_dir: Path | str, check_interval: int = 30):
        self.config_dir = Path(config_dir) if isinstance(config_dir, str) else config_dir
        self.check_interval = check_interval
        self._last_check: datetime | None = None
        self._file_mtimes: dict[str, float] = {}
        self._config_version: int = 0

    def check(self, force: bool = False) -> bool:
        """检查配置是否有更新。

        Returns:
            True if config changed, False otherwise.
        """
        now = datetime.now(_CN_TZ)
        if not force and self._last_check:
            elapsed = (now - self._last_check).total_seconds()
            if elapsed < self.check_interval:
                return False

        self._last_check = now
        changed = False

        # 监控关键配置文件
        watch_files = [
            "positions.yaml",
            "watchlist.yaml",
            "strategy_pack.yaml",
        ]

        for fname in watch_files:
            fpath = self.config_dir / fname
            if not fpath.exists():
                continue
            mtime = fpath.stat().st_mtime
            key = str(fpath)
            if key in self._file_mtimes and self._file_mtimes[key] != mtime:
                changed = True
                logger.info(f"Config changed: {fname}")
            self._file_mtimes[key] = mtime

        if changed:
            self._config_version += 1

        return changed

    @property
    def config_version(self) -> int:
        return self._config_version


# ──────────────────────────────────────────
# 5. 调度器统一入口
# ──────────────────────────────────────────


class Scheduler:
    """调度器统一入口。

    管理完整的 tick 生命周期:
        1. 检查是否应该运行
        2. 获取数据（委托给 Fetcher）
        3. 运行规则（委托给 RuleEngine）
        4. 构建上下文（委托给 ContextBuilder）
        5. 格式化输出（委托给 AlertOutputManager）
        6. 保存状态

    Usage:
        scheduler = Scheduler(config)
        result = scheduler.tick(value=now)
        if result.message:
            print(result.message)
    """

    def __init__(
        self,
        config: Any,  # MonitorConfig
        state_path: Path | None = None,
        dedupe_minutes: int = 30,
        agent_context_on_trigger: bool = False,
        agent_json_context: bool = False,
        agent_any_time: bool = False,
    ):
        self.config = config
        self.state_path = state_path or config.config_dir / "state.json"
        self.dedupe_minutes = dedupe_minutes
        self.agent_context_on_trigger = agent_context_on_trigger
        self.agent_json_context = agent_json_context
        self.agent_any_time = agent_any_time

        # 子组件
        self.state_manager = StateManager(self.state_path)
        self.trading_checker = TradingTimeChecker()
        self.agent_schedule = AgentSchedule.from_config(config.strategy_pack)
        self.config_watcher = ConfigWatcher(config.config_dir)

        # 委托组件（可选注入）
        self.fetcher: Callable | None = None
        self.rule_engine: Callable | None = None
        self.output_manager: Callable | None = None

    def set_fetcher(self, fetcher: Callable) -> None:
        """注入数据获取器。"""
        self.fetcher = fetcher

    def set_rule_engine(self, engine: Callable) -> None:
        """注入规则引擎。"""
        self.rule_engine = engine

    def set_output_manager(self, manager: Callable) -> None:
        """注入输出管理器。"""
        self.output_manager = manager

    def should_run(self, value: datetime, ignore_trading_time: bool = False) -> ScheduleResult:
        """判断是否应该运行 tick。"""
        is_trading = self.trading_checker.is_trading_time(value)
        is_scheduled = self.agent_schedule.is_scheduled_time(value)

        # 如果有 agent 触发，即使在非交易时段也运行
        if self.agent_context_on_trigger or self.agent_json_context:
            if is_scheduled or self.agent_any_time:
                return ScheduleResult(
                    should_run=True,
                    reason="agent_scheduled",
                    is_trading_time=is_trading,
                    is_scheduled_agent_time=is_scheduled,
                )

        # 交易时段运行
        if ignore_trading_time or is_trading:
            return ScheduleResult(
                should_run=True,
                reason="trading_time",
                is_trading_time=is_trading,
                is_scheduled_agent_time=is_scheduled,
            )

        # 非交易时段，跳过
        next_tick = self.trading_checker.next_trading_start(value)
        return ScheduleResult(
            should_run=False,
            reason="non_trading_time",
            is_trading_time=is_trading,
            is_scheduled_agent_time=is_scheduled,
            next_tick=next_tick,
        )

    def tick(
        self,
        value: datetime,
        *,
        emit_status: bool = False,
        ignore_trading_time: bool = False,
    ) -> TickResult:
        """执行一次 tick。

        流程:
            1. 检查是否应该运行
            2. 如果需要，获取数据
            3. 运行规则
            4. 格式化输出
            5. 保存状态
        """
        _t0 = time.time()
        schedule = self.should_run(value, ignore_trading_time)

        if not schedule.should_run:
            return TickResult(
                message="",
                state=self.state_manager.get(),
                duration_ms=0,
            )

        # 状态更新
        state = self.state_manager.get()
        state.last_updated = value.astimezone(_CN_TZ).isoformat()

        # 如果需要状态输出
        if emit_status:
            # 委托给外部 formatter
            message = self._format_status(value)
            return TickResult(
                message=message,
                state=state,
                duration_ms=int((time.time() - _t0) * 1000),
            )

        # 获取数据（委托给 Fetcher）
        quote_snapshot = None
        if self.fetcher:
            try:
                targets = self._collect_quote_targets()
                quote_snapshot = self.fetcher(targets)
                self.state_manager.update_quote_snapshot(quote_snapshot, value)
            except Exception as e:
                logger.error(f"Fetcher failed: {e}")
                quote_snapshot = {"source": "none", "quotes": [], "errors": [str(e)]}

        # 运行规则（委托给 RuleEngine）
        alerts: list[dict] = []
        if self.rule_engine and quote_snapshot:
            try:
                alerts = self.rule_engine(self.config, quote_snapshot, value)
            except Exception as e:
                logger.error(f"RuleEngine failed: {e}")

        # 去重（委托给外部 dedupe）
        new_alerts = self._filter_new_alerts(alerts, value)

        # 更新市场状态
        if quote_snapshot:
            self.state_manager.update_market_state(alerts, quote_snapshot, value)

        # 记录决策日志
        self.state_manager.record_decision(alerts, new_alerts, value)

        # 格式化输出（委托给 AlertOutputManager）
        message = ""
        agent_trigger = None

        if self.output_manager and new_alerts:
            try:
                message = self.output_manager(new_alerts, value, quote_snapshot)
                for alert in new_alerts:
                    self.state_manager.record_alert(alert, value)
            except Exception as e:
                logger.error(f"OutputManager failed: {e}")

        # Agent 分析触发
        if self.agent_context_on_trigger or self.agent_json_context:
            agent_trigger = self._check_agent_trigger(value, new_alerts, schedule.is_scheduled_agent_time)
            if agent_trigger:
                self.state_manager.record_agent_analysis(agent_trigger, value)
                # 如果 agent 触发，message 会被覆盖为 agent context
                message = self._format_agent_context(agent_trigger, new_alerts, quote_snapshot)

        # 保存状态
        self.state_manager.save()

        _t1 = time.time()
        return TickResult(
            message=message,
            state=self.state_manager.get(),
            alerts=new_alerts,
            agent_trigger=agent_trigger,
            duration_ms=int((_t1 - _t0) * 1000),
        )

    def _collect_quote_targets(self) -> dict[str, str]:
        """收集行情目标（从配置）。"""
        targets: dict[str, str] = {}

        # 指数
        from qing_investment.stock_monitor import MARKET_INDEXES
        targets.update(MARKET_INDEXES)

        # 持仓
        positions = self.config.positions or {}
        accounts = positions.get("accounts", []) if isinstance(positions, dict) else (positions or [])
        for account in accounts:
            for pos in account.get("positions", []) or []:
                code = pos.get("code", "")
                name = pos.get("name", "")
                if code and name:
                    targets[name] = code

        # Watchlist
        watchlist = self.config.watchlist or {}
        items = watchlist.get("items", []) if isinstance(watchlist, dict) else (watchlist or [])
        for item in items:
            code = item.get("code", "")
            name = item.get("name", "")
            if code and name:
                targets[name] = code

        return targets

    def _filter_new_alerts(self, alerts: list[dict], value: datetime) -> list[dict]:
        """过滤新告警（简单去重）。"""
        # 这里简化处理，实际应调用 DedupeEngine
        # 基于时间窗口去重
        state = self.state_manager.get()
        recent_emitted = state.emitted_alerts[-20:]  # 最近20条
        recent_keys = set()
        for e in recent_emitted:
            key = f"{e.get('action', '')}:{e.get('stock_code', '')}:{e.get('trigger', '')}"
            emitted_at = e.get("recorded_at", "")
            if emitted_at:
                try:
                    emitted_dt = datetime.fromisoformat(emitted_at)
                    if (value - emitted_dt).total_seconds() < self.dedupe_minutes * 60:
                        recent_keys.add(key)
                except Exception:
                    pass

        new_alerts = []
        for alert in alerts:
            key = f"{alert.get('action', '')}:{alert.get('stock_code', '')}:{alert.get('trigger', '')}"
            if key not in recent_keys:
                new_alerts.append(alert)

        return new_alerts

    def _check_agent_trigger(self, value: datetime, new_alerts: list[dict], is_scheduled: bool) -> dict | None:
        """检查是否需要触发 Agent 分析。"""
        if self.agent_any_time:
            # 任意时间触发（cron job 模式）
            return {
                "type": "any_time",
                "time": value.astimezone(_CN_TZ).isoformat(),
                "alerts_count": len(new_alerts),
            }

        if is_scheduled:
            # 排程时间触发
            return {
                "type": "scheduled",
                "time": value.astimezone(_CN_TZ).isoformat(),
                "alerts_count": len(new_alerts),
            }

        # 检查是否有重要告警触发
        important_actions = {"风控观察", "减仓观察", "指数趋势防线观察", "板块轮动"}
        for alert in new_alerts:
            if alert.get("action", "") in important_actions:
                return {
                    "type": "alert_triggered",
                    "trigger_alert": alert,
                    "time": value.astimezone(_CN_TZ).isoformat(),
                }

        return None

    def _format_status(self, value: datetime) -> str:
        """格式化状态消息（简化版）。"""
        state = self.state_manager.get()
        return (
            f"[监控状态] {value.astimezone(_CN_TZ).strftime('%H:%M:%S')}\n"
            f"  最后更新: {state.last_updated}\n"
            f"  最近告警: {len(state.emitted_alerts)} 条\n"
            f"  市场状态: {state.market_state.get('up_count', 0)} 涨 / {state.market_state.get('down_count', 0)} 跌"
        )

    def _format_agent_context(self, trigger: dict, alerts: list[dict], snapshot: dict | None) -> str:
        """格式化 Agent 分析上下文（简化版）。"""
        # 这里简化处理，实际应调用完整的 format_agent_analysis_context
        lines = [
            f"[Agent分析触发] {trigger.get('type', 'unknown')}",
            f"时间: {trigger.get('time', '')}",
            f"新告警: {len(alerts)} 条",
        ]
        if snapshot:
            lines.append(f"行情源: {snapshot.get('source', 'unknown')}")
        return "\n".join(lines)

    def check_config_update(self) -> bool:
        """检查配置是否有更新。"""
        return self.config_watcher.check()

    def get_next_tick_time(self, value: datetime) -> datetime:
        """获取下一个 tick 时间。"""
        # 优先检查 Agent 排程
        next_agent = self.agent_schedule.get_next_scheduled(value)
        next_trading = self.trading_checker.next_trading_start(value)

        if next_agent and next_trading:
            return min(next_agent, next_trading)
        return next_agent or next_trading or value


# ──────────────────────────────────────────
# 向后兼容：委托函数
# ──────────────────────────────────────────


def is_a_share_trading_time(value: datetime) -> bool:
    """向后兼容：委托给 TradingTimeChecker。"""
    return TradingTimeChecker.is_trading_time(value)


def load_monitor_state(path: Path) -> dict:
    """向后兼容：加载监控状态。"""
    manager = StateManager(path)
    return manager.get().to_dict()


def save_monitor_state(path: Path, state: dict) -> None:
    """向后兼容：保存监控状态。"""
    manager = StateManager(path)
    for key, value in state.items():
        manager.update(**{key: value})
    manager.save()


def agent_analysis_schedule_rows(config: Any) -> list[dict]:
    """向后兼容：获取 Agent 分析排程。"""
    schedule = AgentSchedule.from_config(config.strategy_pack)
    return schedule.schedule_rows


def is_scheduled_agent_analysis_time(config: Any, value: datetime) -> bool:
    """向后兼容：判断是否为 Agent 分析排程时间。"""
    schedule = AgentSchedule.from_config(config.strategy_pack)
    return schedule.is_scheduled_time(value)


def _agent_dedupe_key_for_schedule(row: dict, value: datetime) -> str:
    """向后兼容：生成 Agent 分析去重键。"""
    schedule = AgentSchedule()
    return schedule.dedupe_key(row, value)
