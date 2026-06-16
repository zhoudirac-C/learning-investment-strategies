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

import argparse
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


@dataclass(frozen=True)
class AgentAnalysisTrigger:
    kind: str
    id: str
    title: str
    reason: str
    dedupe_key: str


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
            # 支持两种格式: {"hour": 9, "minute": 26} 或 {"time": "09:26"}
            h = row.get("hour")
            m = row.get("minute")
            if h is None or m is None:
                time_str = str(row.get("time", ""))
                if time_str and ":" in time_str:
                    try:
                        h_str, m_str = time_str.split(":")
                        h = int(h_str)
                        m = int(m_str)
                    except ValueError:
                        continue
                else:
                    continue
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
        """生成 Agent 分析去重键。"""
        date_text = value.astimezone(_CN_TZ).strftime("%Y-%m-%d")
        return f"scheduled:{row.get('id', row.get('time', 'unknown'))}:{date_text}"


def _agent_dedupe_key_for_schedule(row: dict, value: datetime) -> str:
    """获取Agent分析去重键。"""
    date_text = value.astimezone(_CN_TZ).strftime("%Y-%m-%d")
    return f"scheduled:{row.get('id', row.get('time', 'unknown'))}:{date_text}"


def agent_analysis_schedule_rows(config: Any) -> list[dict]:
    """获取Agent分析计划行。"""
    rows = config.strategy_pack.get("agent_analysis_schedule")
    if not rows:
        rows = DEFAULT_AGENT_ANALYSIS_SCHEDULE
    return [dict(row) for row in rows if isinstance(row, dict)]


# ──────────────────────────────────────────
# 5. 向后兼容的函数委托
# ──────────────────────────────────────────


def update_sector_signal_counts(
    state: dict,
    alerts: list,
    value: datetime,
) -> None:
    """更新板块信号计数 — 向后兼容的委托函数。"""
    from qing_investment.stock_monitor import alert_fingerprint

    sector_alerts = [alert for alert in alerts if alert.stock_name == "板块强弱"]
    if not sector_alerts:
        state["sector_signal_counts"] = {}
        return

    previous = state.get("sector_signal_counts", {})
    if not isinstance(previous, dict):
        previous = {}
    current_counts: dict[str, dict] = {}
    current_time = value.astimezone(_CN_TZ).isoformat()
    for alert in sector_alerts:
        key = alert_fingerprint(alert)
        prior = previous.get(key, {})
        count = int(prior.get("count", 0)) + 1 if isinstance(prior, dict) else 1
        current_counts[key] = {
            "action": alert.action,
            "count": count,
            "last_seen_at": current_time,
        }
    state["sector_signal_counts"] = current_counts


def update_market_state(
    state: dict,
    alerts: list,
    value: datetime,
    quote_snapshot: dict | None = None,
) -> None:
    """更新市场状态 — 向后兼容的委托函数。"""
    from qing_investment.stock_monitor import alert_fingerprint

    # 1. 板块信号
    update_sector_signal_counts(state, alerts, value)

    # 2. 大盘状态
    market_alerts = [alert for alert in alerts if alert.stock_name == "大盘状态"]
    if market_alerts:
        latest = market_alerts[-1]
        state["market_state"] = {
            "action": latest.action,
            "summary": latest.summary,
            "price": latest.price,
            "trigger": latest.trigger,
            "last_seen_at": value.astimezone(_CN_TZ).isoformat(),
        }

    # 3. 持仓状态
    position_alerts = [alert for alert in alerts if alert.stock_name != "板块强弱" and alert.stock_name != "大盘状态"]
    if position_alerts:
        current = state.get("position_alerts", {})
        if not isinstance(current, dict):
            current = {}
        for alert in position_alerts:
            key = alert_fingerprint(alert)
            current[key] = {
                "action": alert.action,
                "price": alert.price,
                "trigger": alert.trigger,
                "last_seen_at": value.astimezone(_CN_TZ).isoformat(),
            }
        state["position_alerts"] = current

    # 4. 最新市场状态摘要（兼容旧测试）
    risk_count = sum(1 for a in alerts if a.severity == "risk")
    sector_actions = [a.action for a in alerts if a.stock_name == "板块强弱"]
    quote_count = len(quote_snapshot.get("quotes", [])) if isinstance(quote_snapshot, dict) else len(alerts)
    state["last_market_state"] = {
        "alert_count": len(alerts),
        "risk_count": risk_count,
        "sector_actions": sector_actions,
        "quote_count": quote_count,
    }


def _hhmm(value: datetime) -> str:
    """获取时间HH:MM格式。"""
    return value.astimezone(_CN_TZ).strftime("%H:%M")


def _agent_history(state: dict) -> dict:
    """获取Agent分析历史。"""
    history = state.get("agent_analysis_history", {})
    return history if isinstance(history, dict) else {}


def find_agent_analysis_trigger(
    config: Any,
    state: dict,
    value: datetime,
    alerts: list,
) -> Any | None:
    """查找Agent分析触发器。"""
    from qing_investment.stock_monitor import alert_fingerprint

    history = _agent_history(state)

    # ── 买入信号候选优先 ──
    buy_candidates = [a for a in alerts if a.action == "机会候选"]
    if buy_candidates:
        codes = ",".join(dict.fromkeys(a.stock_code for a in buy_candidates))
        dedupe_key = f"buy_candidate:{value.astimezone(_CN_TZ).strftime('%Y-%m-%d')}:{codes}"
        if dedupe_key not in history:
            names = "、".join(dict.fromkeys(a.stock_name for a in buy_candidates))
            return AgentAnalysisTrigger(
                kind="buy_signal_candidate",
                id="buy_signal_candidate",
                title="买入信号候选触发",
                reason=f"{names}({codes}) 满足买入条件，需要深度确认",
                dedupe_key=dedupe_key,
            )
        return None

    if alerts:
        actions = "、".join(dict.fromkeys(alert.action for alert in alerts))
        fingerprints = ",".join(alert_fingerprint(alert) for alert in alerts)
        dedupe_key = (
            f"event:{value.astimezone(_CN_TZ).strftime('%Y-%m-%d')}:{fingerprints}"
        )
        if dedupe_key not in history:
            return AgentAnalysisTrigger(
                kind="event",
                id="rule_alert",
                title="规则触发",
                reason=f"出现新的规则信号：{actions}",
                dedupe_key=dedupe_key,
            )

    current_hhmm = _hhmm(value)
    for row in agent_analysis_schedule_rows(config):
        row_time = str(row.get("time", ""))
        if not row_time:
            # 新格式: {"hour": 9, "minute": 26}
            h = row.get("hour", 0)
            m = row.get("minute", 0)
            row_time = f"{h:02d}:{m:02d}"
        if row_time != current_hhmm:
            continue
        dedupe_key = _agent_dedupe_key_for_schedule(row, value)
        if dedupe_key in history:
            return None
        return AgentAnalysisTrigger(
            kind="scheduled",
            id=str(row.get("id", current_hhmm)),
            title=str(row.get("name", current_hhmm)),
            reason=str(row.get("focus", "")),
            dedupe_key=dedupe_key,
        )
    return None


def find_any_agent_analysis_trigger(
    config: Any,
    state: dict,
    value: datetime,
    alerts: list,
) -> Any | None:
    """查找任意Agent分析触发器。"""
    from qing_investment.stock_monitor import alert_fingerprint

    history = _agent_history(state)

    # ── 买入信号候选优先 ──
    buy_candidates = [a for a in alerts if a.action == "机会候选"]
    if buy_candidates:
        codes = ",".join(dict.fromkeys(a.stock_code for a in buy_candidates))
        dedupe_key = f"buy_candidate:{value.astimezone(_CN_TZ).strftime('%Y-%m-%d')}:{codes}"
        if dedupe_key not in history:
            names = "、".join(dict.fromkeys(a.stock_name for a in buy_candidates))
            return AgentAnalysisTrigger(
                kind="buy_signal_candidate",
                id="buy_signal_candidate",
                title="买入信号候选触发",
                reason=f"{names}({codes}) 满足买入条件，需要深度确认",
                dedupe_key=dedupe_key,
            )
        return None

    # First check event-driven triggers (alerts)
    if alerts:
        actions = "、".join(dict.fromkeys(alert.action for alert in alerts))
        fingerprints = ",".join(alert_fingerprint(alert) for alert in alerts)
        dedupe_key = (
            f"event:{value.astimezone(_CN_TZ).strftime('%Y-%m-%d')}:{fingerprints}"
        )
        if dedupe_key not in history:
            return AgentAnalysisTrigger(
                kind="event",
                id="rule_alert",
                title="规则触发",
                reason=f"出现新的规则信号：{actions}",
                dedupe_key=dedupe_key,
            )

    # Build trigger from current time — no schedule restriction
    current_hhmm = _hhmm(value)

    # Try to find matching row in schedule for metadata
    schedule_rows = agent_analysis_schedule_rows(config)
    current_row = None
    for row in schedule_rows:
        if str(row.get("time", "")) == current_hhmm:
            current_row = row
            break

    # If matched scheduled row, use its metadata
    if current_row:
        dedupe_key = _agent_dedupe_key_for_schedule(current_row, value)
        if dedupe_key in history:
            return None
        return AgentAnalysisTrigger(
            kind="scheduled",
            id=str(current_row.get("id", current_hhmm)),
            title=str(current_row.get("name", current_hhmm)),
            reason=str(current_row.get("focus", "")),
            dedupe_key=dedupe_key,
        )

    # No scheduled row for this time — create a generic trigger
    dedupe_key = f"scheduled:any:{value.astimezone(_CN_TZ).strftime('%Y-%m-%d')}:{current_hhmm}"
    if dedupe_key in history:
        return None
    return AgentAnalysisTrigger(
        kind="scheduled",
        id=f"any_{current_hhmm}",
        title=f"{current_hhmm} 定时分析",
        reason="定时触发分析",
        dedupe_key=dedupe_key,
    )


def record_agent_analysis_trigger(
    state: dict,
    trigger: Any,
    value: datetime,
) -> None:
    """记录Agent分析触发器。"""
    history = state.setdefault("agent_analysis_history", {})
    # 兼容 list 格式（来自 TickState.agent_analysis_log）
    if isinstance(history, list):
        # 转换为 dict 格式
        history_dict = {}
        for entry in history:
            if isinstance(entry, dict) and "dedupe_key" in entry:
                history_dict[entry["dedupe_key"]] = entry
        history = history_dict
        state["agent_analysis_history"] = history
    history[trigger.dedupe_key] = {
        "time": value.astimezone(_CN_TZ).isoformat(),
        "kind": trigger.kind,
        "id": trigger.id,
        "title": trigger.title,
        "reason": trigger.reason,
    }


# ──────────────────────────────────────────
# 6. 配置热更新
# ──────────────────────────────────────────


class ConfigWatcher:
    """配置热更新监听器（轮询模式）。"""

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


class InotifyConfigWatcher:
    """配置热更新监听器（inotify 事件驱动模式）。

    使用 watchdog 库监听文件变更事件，无需轮询。
    必须在事件循环线程中运行（watchdog 内部管理线程）。

    降级: 如果 import watchdog 失败，使用 ConfigWatcher（轮询）。

    用法:
        watcher = InotifyConfigWatcher(config_dir)
        watcher.start()
        ...
        if watcher.check():  # 非阻塞，检查是否有变更
            reload_config()
        ...
        watcher.stop()
    """

    def __init__(self, config_dir: Path | str):
        self.config_dir = Path(config_dir) if isinstance(config_dir, str) else config_dir
        self._changed = False
        self._observer = None
        self._watch_files = {
            "positions.yaml",
            "watchlist.yaml",
            "strategy_pack.yaml",
        }

    def start(self) -> bool:
        """启动 inotify 监听。

        Returns:
            True if started successfully, False if watchdog unavailable.
        """
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler

            class _Handler(FileSystemEventHandler):
                def __init__(self, parent):
                    self.parent = parent

                def on_modified(self, event):
                    if not event.is_directory:
                        fname = Path(event.src_path).name
                        if fname in self.parent._watch_files:
                            self.parent._changed = True

            self._observer = Observer()
            self._handler = _Handler(self)
            self._observer.schedule(self._handler, str(self.config_dir), recursive=False)
            self._observer.start()
            return True
        except ImportError:
            return False
        except Exception:
            return False

    def check(self) -> bool:
        """检查配置是否有变更（非阻塞）。

        Returns:
            True if config changed since last check.
        """
        if self._changed:
            self._changed = False
            return True
        return False

    def stop(self) -> None:
        """停止监听。"""
        if self._observer:
            try:
                self._observer.stop()
                self._observer.join(timeout=2)
            except Exception:
                pass
            self._observer = None


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
        # ⚠️ 2026-06-15: 移除 WebSocket 尝试。ws_client.py 试图连接腾讯/东方财富的 WS 端点，
        #    但中国免费行情供应商（腾讯/东方财富/新浪/同花顺）均不提供公开 WS 接口。
        #    实测所有已知端点均返回非 WS 响应。断路器误报噪音 > 实际价值。
        #    后续如需 WS 实时行情，需接入付费供应商（Wind/Tushare Pro）。
        #    详见 ws_client.py 注释。
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

    def _try_ws_fetch(self, targets: dict[str, str]) -> dict | None:
        """[已禁用] 尝试使用 WebSocket 事件驱动获取行情快照。

        ⚠️ 2026-06-15: 中国免费行情供应商均不提供公开 WS 接口，该方法已禁用。
           保留代码作为架构参考，未来接入付费供应商（Wind/Tushare Pro）时可复用。
           详见 tick() 注释。

        历史实现:
        - 连接 ws_client.py → 腾讯/东方财富 WS 端点 → 全部返回 HTTP 200 非 WS 响应
        - 断路器每次 tick 触发，写健康指标文件，造成误报
        - 实际数据由 HTTP fetcher 正常获取，WS 降级路径从未真正工作过
        """
        return None
        # === 以下代码已禁用（保留供参考） ===
        # try:
        #     import asyncio
        #     from qing_investment.monitor.fetchers.ws_event_fetcher import WsEventDrivenFetcher
        #     from qing_investment.monitor.fetchers import fetch_quotes_with_fallback
        #
        #     codes = list(targets.values())
        #     ws_fetcher = WsEventDrivenFetcher(
        #         http_fetcher=fetch_quotes_with_fallback,
        #         codes=codes,
        #     )
        #     ...
        # except ImportError:
        #     pass
        # except Exception as e:
        #     logger.debug(f"WsEventDrivenFetcher 不可用: {e}")
        # return None

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


def now_cn() -> datetime:
    """获取当前北京时间。"""
    return datetime.now(tz=_CN_TZ)


def is_a_share_trading_day(value: datetime) -> bool:
    """判断是否为A股交易日。"""
    return value.astimezone(_CN_TZ).weekday() < 5


def is_a_share_trading_time(value: datetime) -> bool:
    """向后兼容：委托给 TradingTimeChecker。"""
    return TradingTimeChecker.is_trading_time(value)


def load_monitor_state(path: Path) -> dict:
    """向后兼容：加载监控状态。"""
    manager = StateManager(path)
    result = manager.get().to_dict()
    # 字段映射：新字段名 → 旧字段名（向后兼容）
    if "emitted_alerts" in result:
        result["alert_history"] = result["emitted_alerts"]
    if "agent_analysis_log" in result:
        result["agent_analysis_history"] = result["agent_analysis_log"]
    return result


def save_monitor_state(path: Path, state: dict) -> None:
    """向后兼容：保存监控状态。"""
    manager = StateManager(path)
    # 字段映射：旧字段名 → 新字段名
    field_map = {"alert_history": "emitted_alerts", "agent_analysis_history": "agent_analysis_log"}
    for key, value in state.items():
        mapped_key = field_map.get(key, key)
        manager.update(**{mapped_key: value})
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

# ──────────────────────────────────────────
# 常量：摘要/竞价缓存路径（迁移自 stock_monitor.py）
# ──────────────────────────────────────────

from qing_investment.paths import repo_root
_DEFAULT_CONFIG_DIR = repo_root() / "config" / "stock_monitor"
_SUMMARY_CONFIG_DIR = _DEFAULT_CONFIG_DIR
_SUMMARY_FILENAME = "daily_review_summary.json"
_AUCTION_CACHE_FILENAME = "auction_volume_cache.json"
_AUCTION_CACHE_MAX_DAYS = 10
_SUMMARY_FIELDS_BASIC = ["close", "open", "high", "low", "change_pct", "volume", "amount"]
_SUMMARY_FIELDS_BOARD = ["is_limit_up", "consecutive_limit_ups", "weak_board",
                         "board_open_count", "first_board_time", "board_seal_ratio",
                         "board_quality"]
_SUMMARY_FIELDS_TECH = ["turnover_rate", "amplitude", "volume_ratio",
                        "vs_ma5", "vs_ma10", "near5d_return"]
_SUMMARY_FIELDS_DETAIL = ["intraday_pattern", "sector_avg_change",
                          "dragon_tiger_net", "entry_zone_distance", "entry_zone_range",
                          "dt_seat_type", "dt_top_buy_behavior", "dt_is_pure_hot_money"]
_SUMMARY_FIELDS_COST = ["avg_cost", "unrealized_pct", "cost_protection_line"]
_ALL_SUMMARY_FIELDS = (_SUMMARY_FIELDS_BASIC + _SUMMARY_FIELDS_BOARD + _SUMMARY_FIELDS_TECH
                       + _SUMMARY_FIELDS_DETAIL + _SUMMARY_FIELDS_COST)
_LIMIT_UP_THRESHOLD = 9.5

def _summary_file_path(config_dir: Path | None = None) -> Path:
    """返回 summary 文件路径。"""
    return (config_dir or _SUMMARY_CONFIG_DIR) / _SUMMARY_FILENAME

_AUCTION_CACHE_FILENAME = "auction_volume_cache.json"


def _state_date(value: datetime) -> str:
    return value.astimezone(_CN_TZ).strftime("%Y-%m-%d")



def _auction_cache_path(config_dir: Path | None = None) -> Path:
    """返回竞价量缓存文件路径（向后兼容，委托给 AuctionCache）。"""
    from qing_investment.monitor.cache import AuctionCache
    ac = AuctionCache(config_dir)
    return ac._cache_file


def _load_auction_cache(config_dir: Path | None = None) -> dict:
    """读取竞价量缓存（内存→文件，委托给 AuctionCache）。"""
    from qing_investment.monitor.cache import AuctionCache
    ac = AuctionCache(config_dir)
    return ac.load()


def _save_auction_cache(cache: dict, config_dir: Path | None = None) -> bool:
    """保存竞价量缓存（内存+文件双写，委托给 AuctionCache）。"""
    from qing_investment.monitor.cache import AuctionCache
    ac = AuctionCache(config_dir)
    return ac.save(cache)


def _update_auction_cache(
    auction_data: dict[str, dict],
    config_dir: Path | None = None,
) -> None:
    """更新竞价量缓存（委托给 AuctionCache）。"""
    from qing_investment.monitor.cache import AuctionCache
    ac = AuctionCache(config_dir)
    ac.update(auction_data)




def _save_yesterday_summary(summary: dict, config_dir: Path | None = None) -> bool:
    """持久化昨日特征摘要到 daily_review_summary.json。

    格式：按日期键存储，如 {"2026-06-11": {...}, "2026-06-12": {...}}
    """
    try:
        file_path = _summary_file_path(config_dir)
        existing: dict = {}
        if file_path.exists():
            existing = json.loads(file_path.read_text(encoding="utf-8"))

        date_str = summary.get("date", datetime.now(tz=_CN_TZ).strftime("%Y-%m-%d"))
        existing[date_str] = summary

        file_path.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("昨日特征摘要已保存: %s (%s 条持仓)", file_path,
                     len(summary.get("positions", {})))
        return True
    except Exception as e:
        logger.error("保存昨日特征摘要失败: %s", e)
        return False




def _update_summary_tomorrow_scenarios(
    tomorrow_scenarios: dict,
    config_dir: Path | None = None,
    date_str: str | None = None,
) -> bool:
    """更新已持久化的 summary 中的 tomorrow_scenarios（由收盘复盘 cron 在 LLM 输出后调用）。

    Args:
        tomorrow_scenarios: {"strong_repair": {...}, "weak_consolidation": {...}, ...}
        config_dir: 配置目录
        date_str: 目标日期（默认今天）

    Returns:
        True 更新成功，False 失败
    """
    try:
        file_path = _summary_file_path(config_dir)
        if not file_path.exists():
            logger.warning("summary 文件不存在，无法更新 tomorrow_scenarios")
            return False

        existing = json.loads(file_path.read_text(encoding="utf-8"))
        if date_str is None:
            date_str = datetime.now(tz=_CN_TZ).strftime("%Y-%m-%d")

        if date_str not in existing:
            logger.warning("summary 无 %s 日数据，无法更新 tomorrow_scenarios", date_str)
            return False

        existing[date_str]["tomorrow_scenarios"] = tomorrow_scenarios
        file_path.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("tomorrow_scenarios 已更新到 %s: %s", date_str,
                     list(tomorrow_scenarios.keys()) if isinstance(tomorrow_scenarios, dict) else "N/A")
        return True
    except Exception as e:
        logger.error("更新 tomorrow_scenarios 失败: %s", e)
        return False




def _load_yesterday_summary(
    config_dir: Path | None = None,
    date_str: str | None = None,
) -> dict | None:
    """读取昨日特征摘要，优先级：文件 > state.json 快照 > 无数据。

    Args:
        config_dir: 配置目录（默认 stock_monitor）
        date_str: 目标日期（默认昨天）

    Returns:
        summary dict 或 None（完全无数据）
    """
    config_dir = config_dir or _DEFAULT_CONFIG_DIR
    if date_str is None:
        from datetime import timedelta
        date_str = (datetime.now(tz=_CN_TZ) - timedelta(days=1)).strftime("%Y-%m-%d")

    # ── 优先：从 daily_review_summary.json 读取 ──
    file_path = _summary_file_path(config_dir)
    if file_path.exists():
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                # 如果直接是日期键结构
                if date_str in data:
                    logger.info("读取昨日特征摘要: 文件命中 %s", date_str)
                    return data[date_str]
                # 如果文件里只有一个键且是日期格式，可能是新格式
                # 也尝试按日期匹配
                for key in data:
                    if isinstance(data[key], dict) and "positions" in data.get(key, {}):
                        if key == date_str:
                            logger.info("读取昨日特征摘要: 文件命中 %s", date_str)
                            return data[key]

            # 如果整个文件就是这个日期的 summary（单记录格式）
            if isinstance(data, dict) and "positions" in data and "date" in data:
                if data.get("date") == date_str:
                    return data

            logger.info("读取昨日特征摘要: 文件存在但未命中日期 %s", date_str)
        except Exception as e:
            logger.warning("读取 daily_review_summary.json 失败: %s", e)

    # ── Fallback: 从 state.json 的 last_quote_snapshot 提取 ──
    try:
        state_path = config_dir / "state.json"
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8"))
            qs = state.get("last_quote_snapshot", {})
            if qs and qs.get("quotes"):
                logger.info("读取昨日特征摘要: fallback → state.json last_quote_snapshot")
                summary = {
                    "date": date_str,
                    "built_at": datetime.now(tz=_CN_TZ).isoformat(),
                    "source": "fallback_state_json",
                    "market": {},
                    "positions": {},
                    "tomorrow_scenarios": None,
                }
                for q in qs.get("quotes", []):
                    code = _pure_stock_code(str(q.get("code", "")))
                    summary["positions"][code] = {
                        "close": _to_float(q.get("previous_close")),
                        "open": _to_float(q.get("open")),
                        "high": _to_float(q.get("high")),
                        "low": _to_float(q.get("low")),
                        "change_pct": _to_float(q.get("pct_change")),
                        "volume": _to_float(q.get("volume")),
                        "amount": q.get("amount", ""),
                        **{k: None for k in SUMMARY_FIELDS_BOARD},
                        **{k: None for k in SUMMARY_FIELDS_TECH},
                        **{k: None for k in SUMMARY_FIELDS_DETAIL},
                        **{k: None for k in SUMMARY_FIELDS_COST},
                    }
                return summary
    except Exception as e:
        logger.warning("Fallback state.json 读取失败: %s", e)

    logger.warning("昨日特征摘要完全不可用: %s", date_str)
    return None


# ──────────────────────────────────────────────
# Phase 2: 竞价快照系统
# ──────────────────────────────────────────────

_AUCTION_CACHE_FILENAME = "auction_volume_cache.json"
_AUCTION_CACHE_MAX_DAYS = 10  # keep 10 days, use last 5 for avg




def record_alert_decision_log(
    state: dict,
    alerts: list[RuleAlert],
    emitted_alerts: list[RuleAlert],
    value: datetime,
) -> None:
    from qing_investment.monitor.output import _alert_fingerprint; emitted_keys = {_alert_fingerprint(alert) for alert in emitted_alerts}
    log = state.setdefault("alert_decision_log", [])
    for alert in alerts:
        status = "emitted" if _alert_fingerprint(alert) in emitted_keys else "suppressed"
        from qing_investment.monitor.output import AlertFormatter; log.append(AlertFormatter().format_log_entry(alert, value, status=status))




def _build_yesterday_summary(
    config: "MonitorConfig",
    quote_snapshot: dict,
    state: dict,
    daily_state: dict | None = None,
) -> dict:
    """构建昨日特征摘要：从 state.json + daily_state.json + K线缓存 提取。

    产出物结构（设计文档 §1.1）：
    {
        "date": "2026-06-11",
        "market": {...},
        "positions": {
            "002409": { 18+ 字段 },
            "000636": { 18+ 字段 }
        },
        "tomorrow_scenarios": null,  # 由收盘复盘 LLM 填充
    }
    """
    # 本地导入避免循环依赖 — 这些函数定义在 qing_investment.monitor.context 中
    from qing_investment.monitor.context import (  # noqa: F811
        _pure_stock_code,
        _quotes_by_code,
        _quote_for_stock,
        _to_float,
        position_rows,
    )
    from qing_investment.stock_monitor import (  # noqa: F811
        _check_entry_zone_distance,
        _compute_near5d_return,
        _compute_volume_ratio,
        _compute_vs_ma,
        _fetch_dragon_tiger_data,
    )
    # lazy__fetch_dt — 龙虎榜数据懒加载包装
    def lazy__fetch_dt(code: str, date_str: str) -> dict:
        return _fetch_dragon_tiger_data(code, date_str)

    date_str = datetime.now(tz=_CN_TZ).strftime("%Y-%m-%d")
    quotes = _quotes_by_code(quote_snapshot)

    # ── 市场层面数据（来自 daily_state + strategy_pack）──
    market_info = {
        "stage": (daily_state or {}).get("market_stage", {}).get("phase", ""),
        "stage_detail": (daily_state or {}).get("market_stage", {}).get("detail", ""),
        "direction_priority": (daily_state or {}).get("direction_priority", []),
        "position_stance": (daily_state or {}).get("position_stance", ""),
        "key_levels": config.strategy_pack.get("key_levels", {}),
    }

    # ── 逐个持仓计算 ──
    positions_summary: dict[str, dict] = {}
    for pos in position_rows(config):
        code_raw = str(pos.get("code", ""))
        code_pure = _pure_stock_code(code_raw)
        quote = _quote_for_stock(quotes, code_pure) or _quote_for_stock(quotes, code_raw) or {}

        # ── A. 基础行情（7个字段）──
        close = _to_float(quote.get("latest"))
        open_ = _to_float(quote.get("open"))
        high = _to_float(quote.get("high"))
        low = _to_float(quote.get("low"))
        change_pct = _to_float(quote.get("pct_change"))
        volume = _to_float(quote.get("volume"))
        amount = quote.get("amount", "")

        if close is None:
            continue  # 无有效行情，跳过

        entry: dict = {
            "close": close,
            "open": open_,
            "high": high,
            "low": low,
            "change_pct": change_pct,
            "volume": volume,
            "amount": amount,
            # 默认 null 占位
            **{k: None for k in _SUMMARY_FIELDS_BOARD},
            **{k: None for k in _SUMMARY_FIELDS_TECH},
            **{k: None for k in _SUMMARY_FIELDS_DETAIL},
            **{k: None for k in _SUMMARY_FIELDS_COST},
        }

        # ── is_limit_up 从 change_pct 推导 ──
        if change_pct is not None and change_pct >= _LIMIT_UP_THRESHOLD:
            entry["is_limit_up"] = True
        elif change_pct is not None:
            entry["is_limit_up"] = False

        # ── C. 技术/量价特征（从 K线缓存）──
        try:
            from qing_investment.kline_cache import get_klines
            klines = get_klines(code_pure, days=30)
            if len(klines) >= 2:
                last_kline = klines[-1]
                # turnover: 换手率（从 K线直接取）
                entry["turnover_rate"] = _to_float(last_kline.get("turnover"))
                # amplitude: 振幅 = (high - low) / pre_close * 100
                if all(v is not None for v in [high, low, close]):
                    # 用当日最高最低算振幅
                    pass  # 下面单独算
                # 从 K线 amplitude 字段（如果存在）
                entry["amplitude"] = _to_float(last_kline.get("amplitude"))

            # 量比 (今日量/近5日均量)
            if volume is not None:
                entry["volume_ratio"] = _compute_volume_ratio(volume, klines)

            # vs_ma5, vs_ma10
            if close:
                entry["vs_ma5"] = _compute_vs_ma(close, klines, 5)
                entry["vs_ma10"] = _compute_vs_ma(close, klines, 10)

            # 近5日涨幅
            entry["near5d_return"] = _compute_near5d_return(klines)

            # 若 K线缓存有振幅而上面没取到，补充
            if entry["amplitude"] is None and all(v is not None for v in [high, low]):
                entry["amplitude"] = round((high - low) / close * 100, 2)
        except Exception as e:
            logger.warning("K线缓存计算失败 %s: %s", code_pure, e)

        # ── D. entry_zone 距离 ──
        zone_info = _check_entry_zone_distance(code_pure, close, config)
        entry["entry_zone_distance"] = zone_info["entry_zone_distance"]
        entry["entry_zone_range"] = zone_info["entry_zone_range"]

        # ── 持仓成本 ──
        cost = _to_float(pos.get("cost"))
        shares = pos.get("shares", 0)
        if cost is not None and cost > 0:
            entry["avg_cost"] = cost
            if close:
                unrealized = round((close - cost) / cost * 100, 2)
                entry["unrealized_pct"] = unrealized
                # 成本保护线：浮盈>10% → 成本+5%；浮盈5-10% → 成本+3%；浮盈<5% → 成本
                if unrealized > 10:
                    entry["cost_protection_line"] = round(cost * 1.05, 2)
                elif unrealized > 5:
                    entry["cost_protection_line"] = round(cost * 1.03, 2)
                else:
                    entry["cost_protection_line"] = round(cost * 1.00, 2)

        # ── E. 龙虎榜数据（akshare 东方财富接口）──
        # 仅对涨停/连板持仓采集（非涨停不用费 API 调用）
        if entry.get("is_limit_up"):
            try:
                dt_data = lazy__fetch_dt(code_pure, date_str)
                if dt_data.get("_error") and "未上榜" in dt_data["_error"]:
                    pass  # 当日未上榜，保留 null
                else:
                    for key in ["dragon_tiger_net", "dt_seat_type",
                                "dt_top_buy_behavior", "dt_is_pure_hot_money",
                                "board_quality"]:
                        if dt_data.get(key) is not None:
                            entry[key] = dt_data[key]
            except Exception as e:
                logger.warning("龙虎榜数据获取失败 %s: %s", code_pure, e)

        positions_summary[code_pure] = entry

    return {
        "date": date_str,
        "built_at": datetime.now(tz=_CN_TZ).isoformat(),
        "market": market_info,
        "positions": positions_summary,
        "tomorrow_scenarios": None,  # 由收盘复盘 LLM 填充
    }




def summarize_daily_review(state: dict, date_text: str) -> dict:
    decision_log = state.get("alert_decision_log", [])
    if not isinstance(decision_log, list):
        decision_log = []
    today_entries = [
        entry
        for entry in decision_log
        if isinstance(entry, dict) and entry.get("date") == date_text
    ]

    agent_history = state.get("agent_analysis_history", {})
    if not isinstance(agent_history, dict):
        agent_history = {}
    agent_runs = [
        value
        for value in agent_history.values()
        if isinstance(value, dict) and str(value.get("time", "")).startswith(date_text)
    ]

    return {
        "date": date_text,
        "emitted_alerts": [
            entry for entry in today_entries if entry.get("status") == "emitted"
        ],
        "suppressed_alerts": [
            entry for entry in today_entries if entry.get("status") == "suppressed"
        ],
        "agent_runs": agent_runs,
        "last_market_state": state.get("last_market_state", {}),
        "sector_signal_counts": state.get("sector_signal_counts", {}),
        "last_fetch_error": state.get("last_fetch_error", {}),
    }




def _append_review_entries(lines: list[str], entries: list[dict], limit: int = 12) -> None:
    if not entries:
        lines.append("- 无")
        return
    for entry in entries[:limit]:
        lines.append(
            "- {time} {action} {stock}: {summary}".format(
                time=str(entry.get("time", ""))[11:19],
                action=entry.get("action", ""),
                stock=entry.get("stock_name") or entry.get("stock_code", ""),
                summary=entry.get("summary", ""),
            )
        )
    if len(entries) > limit:
        lines.append(f"- 另有 {len(entries) - limit} 条未展开")




def unique_stock_count(rows: list[dict]) -> int:
    """统计唯一股票数量。"""
    return len({row.get("code") for row in rows if row.get("code")})


def format_status_message(config: "MonitorConfig", value: datetime) -> str:
    from qing_investment.monitor.context import position_rows, watchlist_stock_rows
    positions = position_rows(config)
    watch_stocks = watchlist_stock_rows(config)
    theme_count = len(config.watchlist.get("themes", []) or [])
    buy_setup_count = sum(1 for row in watch_stocks if row.get("buy_setup"))
    invalidation_setup_count = sum(
        1 for row in watch_stocks if row.get("invalidation_setup")
    )
    sell_setup_count = sum(1 for row in watch_stocks if row.get("sell_setup"))
    stage = (
        config.strategy_pack.get("market_framework", {})
        .get("current_stage", "未配置")
    )
    trading_state = "交易时段内" if is_a_share_trading_time(value) else "非交易时段"
    path_note = "private" if config.positions_path.name == "positions.yaml" else "example"

    return "\n".join(
        [
            "[Hermes股票监控状态]",
            f"时间：{value.astimezone(_CN_TZ).strftime('%Y-%m-%d %H:%M:%S %Z')}",
            f"交易状态：{trading_state}",
            f"持仓配置：{config.positions_path} ({path_note})",
            f"持仓条目：{len(positions)}",
            f"观察主题：{theme_count}",
            f"观察标的：{unique_stock_count(watch_stocks)}",
            f"观察池买入条件：{buy_setup_count}",
            f"观察池买点失效条件：{invalidation_setup_count}",
            f"持仓卖出/做T条件：{sell_setup_count}",
            f"当前框架：{stage}",
            "提醒策略：默认只在触发条件时输出；空输出表示静默。",
        ]
    )




def run_tick(
    config: "MonitorConfig",
    value: datetime,
    *,
    emit_status: bool,
    ignore_trading_time: bool,
    quote_fetcher=None,
    use_concurrent_fetcher: bool = False,
    state_path: Path | None = None,
    dedupe_minutes: int = 30,
    agent_context_on_trigger: bool = False,
    agent_json_context: bool = False,
    agent_any_time: bool = False,
) -> str:
    """Run one monitor tick.

    If agent_any_time=True, bypass the agent_analysis_schedule time restriction
    and always produce an agent trigger when --agent-json-context or
    --agent-context-on-trigger is used. This lets cron jobs run at arbitrary
    times without needing the time to be listed in strategy_pack.yaml.

    If use_concurrent_fetcher=True, uses ConcurrentDataFetcher with ThreadPoolExecutor
    to parallelize data source fetching (行情/龙虎榜) and adds TTL caching.
    """
    # Lazy imports
    from qing_investment.monitor.rules import evaluate_monitor_alerts
    from qing_investment.stock_monitor import evaluate_buy_signal_candidates
    from qing_investment.monitor.fetchers import collect_quote_targets, fetch_quotes_with_fallback as _local_fetch
    from qing_investment.monitor.output import filter_new_alerts, record_emitted_alerts, format_alerts_message
    from qing_investment.monitor.context import format_agent_json_context, format_agent_analysis_context
    fetcher = quote_fetcher or _local_fetch
    
    scheduled_agent_time = (agent_context_on_trigger or agent_json_context) and is_scheduled_agent_analysis_time(
        config, value
    )
    if (
        not ignore_trading_time
        and not is_a_share_trading_time(value)
        and not scheduled_agent_time
    ):
        return ""
    if emit_status:
        return format_status_message(config, value)
    if use_concurrent_fetcher:
        from qing_investment.monitor.fetchers import ConcurrentDataFetcher
        cf = ConcurrentDataFetcher()
        fetcher_result = cf.fetch_all_sources(config, include_dragon_tiger=False)
        quote_snapshot = fetcher_result.get("quotes", {"quotes": [], "errors": []})
    else:
        quote_snapshot = fetcher(collect_quote_targets(config))
    # 防失真检查：验证持仓价格区间是否与当前行情匹配
    from qing_investment.monitor.rules import validate_position_price_zones as _vppz
    stale_warnings = _vppz(config)
    # RuleEngine 内部用 config.get() 访问 dict 格式 → MonitorConfig 需要转换
    _sp = getattr(config, "strategy_pack", {})
    _cfg_dict: dict = {
        "positions": getattr(config, "positions", {}),
        "watchlist": getattr(config, "watchlist", {}),
        "strategy_pack": _sp,
        "entry_points": _sp.get("entry_points", []) or getattr(config, "entry_points", []),
        "market_framework": _sp.get("market_framework", {}) or getattr(config, "market_framework", {}),
        "sector_groups": _sp.get("sector_groups", []) or getattr(config, "sector_groups", []),
        "direction_pool": getattr(config, "direction_pool", {}),
        "stock_pool": getattr(config, "stock_pool", {}),
    }
    alerts = evaluate_monitor_alerts(_cfg_dict, quote_snapshot, current_time=value)
    resolved_state_path = state_path or config.config_dir / "state.json"
    state = load_monitor_state(resolved_state_path)
    state["version"] = 1
    state["last_updated"] = value.astimezone(_CN_TZ).isoformat()
    if stale_warnings:
        state["stale_zone_warnings"] = stale_warnings
    if quote_snapshot.get("quotes"):
        state["last_quote_snapshot"] = quote_snapshot
        state.pop("last_fetch_error", None)
    elif quote_snapshot.get("errors"):
        state["last_fetch_error"] = {
            "time": value.astimezone(_CN_TZ).isoformat(),
            "source": quote_snapshot.get("source", "unknown"),
            "errors": quote_snapshot.get("errors", []),
            "elapsed_ms": quote_snapshot.get("elapsed_ms"),
        }

    # ── Phase 4: 同步买入候选到 daily_state ──
    try:
        from qing_investment.agent.tools.daily_state import (
            load_daily_state,
            save_daily_state,
            sync_buy_candidates,
        )
        daily_state = load_daily_state()
        candidates = evaluate_buy_signal_candidates(config, quote_snapshot)
        candidate_dicts = [
            {
                "stock_code": c.stock_code,
                "stock_name": c.stock_name,
                "price": c.price,
                "entry_zone": list(c.entry_zone) if c.entry_zone else None,
                "stop_loss": c.stop_loss,
                "matched_conditions": c.matched_conditions,
                "odds_analysis": c.odds_analysis,
            }
            for c in candidates if c.is_candidate
        ]
        if candidate_dicts:
            daily_state = sync_buy_candidates(daily_state, candidate_dicts, now=value)
            save_daily_state(daily_state)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Sync buy candidates to daily_state failed: %s", e)

    notification_policy = config.strategy_pack.get("notification_policy", {}) or {}
    dedupe_by_type = notification_policy.get("dedupe_by_type", {}) or {}
    new_alerts = filter_new_alerts(
        alerts, state, value, dedupe_minutes=dedupe_minutes, dedupe_by_type=dedupe_by_type
    )
    update_sector_signal_counts(state, alerts, value)
    update_market_state(state, alerts, value)
    record_alert_decision_log(state, alerts, new_alerts, value)
    agent_trigger = None
    if agent_context_on_trigger or agent_json_context:
        if agent_any_time:
            agent_trigger = find_any_agent_analysis_trigger(config, state, value, new_alerts)
        else:
            agent_trigger = find_agent_analysis_trigger(config, state, value, new_alerts)
    if new_alerts:
        record_emitted_alerts(state, new_alerts, value)
    save_monitor_state(resolved_state_path, state)
    if agent_trigger:
        record_agent_analysis_trigger(state, agent_trigger, value)
        save_monitor_state(resolved_state_path, state)

        # 使用新模块的单 dict 方式构建 context 数据
        from zoneinfo import ZoneInfo
        cn_tz = ZoneInfo("Asia/Shanghai")
        context_data = {
            "timestamp": value.astimezone(cn_tz).isoformat(),
            "trigger": {
                "kind": agent_trigger.kind,
                "id": agent_trigger.id,
                "title": agent_trigger.title,
                "reason": agent_trigger.reason,
            },
            "alerts": [
                {
                    "action": a.action,
                    "stock_code": a.stock_code,
                    "stock_name": getattr(a, "stock_name", ""),
                    "summary": a.summary,
                }
                for a in new_alerts
            ],
            "quote_snapshot": quote_snapshot,
            "positions": config.positions,
            "watchlist": config.watchlist,
            "direction_pool": config.direction_pool,
            "stock_pool": config.stock_pool,
            "market_framework": config.strategy_pack.get("market_framework", {}),
            "state": state,
            "market_state": state.get("last_market_state", {}),
            "sector_signal_counts": state.get("sector_signal_counts", {}),
        }

        if agent_json_context:
            return format_agent_json_context(context_data)
        return format_agent_analysis_context(context_data)
    if new_alerts:
        return format_alerts_message(new_alerts, value, quote_snapshot)
    return ""




def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Hermes-friendly A-share stock monitor entrypoint."
    )
    parser.add_argument(
        "--config-dir",
        default=str(_DEFAULT_CONFIG_DIR),
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
    parser.add_argument(
        "--state-file",
        default=None,
        help="JSON state file for quote snapshots and alert de-duplication.",
    )
    parser.add_argument(
        "--dedupe-minutes",
        type=int,
        default=30,
        help="Suppress the same alert for this many minutes. Use 0 to disable.",
    )
    parser.add_argument(
        "--agent-context-on-trigger",
        action="store_true",
        help=(
            "Emit Hermes model analysis context at configured key times or when "
            "new rule alerts trigger."
        ),
    )
    parser.add_argument(
        "--agent-json-context",
        action="store_true",
        help=(
            "Emit structured JSON context for qing-agent HTTP API at configured "
            "key times or when new rule alerts trigger."
        ),
    )
    parser.add_argument(
        "--agent-any-time",
        action="store_true",
        help=(
            "Bypass agent_analysis_schedule time restriction. "
            "Always produce agent context when --agent-json-context is used, "
            "regardless of whether current time is in the schedule."
        ),
    )
    parser.add_argument(
        "--daily-review-context",
        action="store_true",
        help="Print an end-of-day monitoring review context from the state file.",
    )
    parser.add_argument(
        "--freshness-check",
        action="store_true",
        help="Run knowledge-base freshness check (unprocessed raw docs, stale claims).",
    )
    return parser




def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    from qing_investment.stock_monitor import load_monitor_config
    config = load_monitor_config(Path(args.config_dir))
    current = datetime.now(_CN_TZ)

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
    if args.daily_review_context:
        from qing_investment.stock_monitor import format_daily_review_context
        state_path = Path(args.state_file) if args.state_file else config.config_dir / "state.json"
        state = load_monitor_state(state_path)
        print(format_daily_review_context(config, current, state))

        # ── Phase 1.4: 收盘复盘自动提取昨日特征摘要 ──
        # 从 state.json 的 last_quote_snapshot 提取并保存
        qs = state.get("last_quote_snapshot", {})
        if qs and qs.get("quotes"):
            try:
                daily_state = json.loads(
                    (config.config_dir / "daily_state.json").read_text(encoding="utf-8")
                ) if (config.config_dir / "daily_state.json").exists() else None
            except Exception:
                daily_state = None

            summary = _build_yesterday_summary(config, qs, state, daily_state)
            _save_yesterday_summary(summary, config.config_dir)
            logger.info("收盘复盘: 昨日特征摘要已自动构建并保存 (%s 条持仓)",
                         len(summary.get("positions", {})))

            # ── 龙虎榜全市场总榜（17:00 数据已就绪）──
            try:
                date_today = _state_date(current)
                from qing_investment.stock_monitor import (
                    _fetch_daily_dragon_tiger_board,
                    _filter_dragon_tiger_board,
                )
                raw_board = _fetch_daily_dragon_tiger_board(date_today)
                if raw_board.get("available") and raw_board.get("board"):
                    board_filtered = _filter_dragon_tiger_board(raw_board["board"], config)
                    # 将龙虎榜数据保存到 summary 的 market 字段中
                    summary["dragon_tiger_board"] = {
                        "board_count": len(raw_board["board"]),
                        "watch_dt_items": board_filtered.get("watch_dt_items", []),
                        "dt_nettop5": board_filtered.get("dt_nettop5", []),
                        "dt_sector_summary": board_filtered.get("dt_sector_summary", {}),
                        "fetched_at": raw_board.get("fetched_at"),
                    }
                    _save_yesterday_summary(summary, config.config_dir)
                    logger.info("龙虎榜总榜已采集: %d 只上榜, %d 只持仓/观察池命中",
                                 len(raw_board["board"]),
                                 len(board_filtered.get("watch_dt_items", [])))
            except Exception as e:
                logger.warning("龙虎榜总榜采集失败（不影响主流程）: %s", e)
        else:
            logger.warning("收盘复盘: last_quote_snapshot 无数据，skip 特征摘要保存")
        return 0

    if args.freshness_check:
        import subprocess
        repo_root = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            [sys.executable, str(repo_root / "scripts" / "freshness_check.py")],
            capture_output=True,
            text=True,
        )
        print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        return result.returncode

    message = run_tick(
        config,
        current,
        emit_status=args.emit_status_on_tick,
        ignore_trading_time=args.ignore_trading_time,
        state_path=Path(args.state_file) if args.state_file else None,
        dedupe_minutes=args.dedupe_minutes,
        agent_context_on_trigger=args.agent_context_on_trigger,
        agent_json_context=args.agent_json_context,
        agent_any_time=args.agent_any_time,
    )
    if message:
        print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


def format_analysis_context(config, value):
    from qing_investment.monitor.context import position_rows, watchlist_stock_rows, format_watchlist_condition_line
    positions = position_rows(config)
    watch_stocks = watchlist_stock_rows(config)  # noqa
    stage = config.strategy_pack.get("market_framework", {}).get(
        "current_stage", "未配置"
    )
    core_question = config.strategy_pack.get("market_framework", {}).get(
        "core_question", "未配置"
    )
    rules = config.strategy_pack.get("position_rules", []) or []

    lines = [
        "[Hermes股票监控分析上下文]",
        f"时间：{value.astimezone(_CN_TZ).strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"交易状态：{'交易时段内' if is_a_share_trading_time(value) else '非交易时段'}",
        f"当前框架：{stage}",
        f"核心问题：{core_question}",
        "",
        "=== 持仓池（positions.yaml）===",
        f"状态：{'【空仓】当前无持仓' if not positions else f'共 {len(positions)} 只持仓'}",
        "",
        "重要区分：",
        "- 持仓池 = 你当前实际持有的股票（来自 positions.yaml）",
        "- 观察池 = 你关注但尚未买入的股票（来自 watchlist.yaml）",
        "- 严禁将观察池标的当作持仓分析！",
        "",
        "持仓明细：",
    ]
    if not positions:
        lines.append("  （无持仓）")
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

    lines.extend(["", "=== 观察池（watchlist.yaml）===", "这些标的尚未买入，仅作观察："])
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
        condition_line = format_watchlist_condition_line(row)
        if condition_line:
            lines.append(f"  条件：{condition_line}")

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


def format_agent_json_context(
    config: MonitorConfig,
    value: datetime,
    trigger: AgentAnalysisTrigger,
    alerts: list[RuleAlert],
    quote_snapshot: dict,
    state: dict,
    max_quotes: int = 40,
) -> str:
    """Return the agent context as a JSON string for qing-agent HTTP API.

    Quotes are truncated to ``max_quotes`` to keep the payload small enough
    for LLM prompt limits and reasonable HTTP latency.
    """
    data = _agent_context_data(config, value, trigger, alerts, quote_snapshot, state)
    qs = data.get("quote_snapshot", {})
    all_quotes = qs.get("quotes", []) or []
    if len(all_quotes) > max_quotes:
        qs["quotes"] = all_quotes[:max_quotes]
        qs["_total_quotes"] = len(all_quotes)
    return json.dumps(data, ensure_ascii=False, indent=2)
