"""Qing-Agent 监控引擎 — 告警输出层 (Phase 3)

将 stock_monitor.py 中的告警格式化、去重、防刷屏、微信推送逻辑拆分为独立模块。

职责边界:
    - 输入: RuleAlert 列表
    - 输出: 格式化消息字符串（或空，如果全部被去重）
    - 不负责: 规则判断（Phase 1）、数据获取（Phase 0）

核心功能:
    1. 消息格式化: 将 RuleAlert 转为微信/日志可读文本
    2. 去重引擎: 指纹去重 + 时间窗口 + 价格突破
    3. 防刷屏: 同类型告警间隔控制
    4. 状态持久化: 告警历史记录到本地文件

架构:
    ┌─────────────────────────────────────────┐
    │           AlertOutputManager            │
    │  ┌─────────────┐  ┌─────────────────┐ │
    │  │  AlertFormatter│  │  DedupeEngine   │ │
    │  │  (消息格式化) │  │  (去重引擎)      │ │
    │  └─────────────┘  └─────────────────┘ │
    │              ↓                          │
    │  ┌─────────────────────────────────────┐ │
    │  │      StatePersistence             │ │
    │  │  (状态持久化: JSON文件)            │ │
    │  └─────────────────────────────────────┘ │
    └─────────────────────────────────────────┘

使用:
    from qing_investment.monitor.output import AlertOutputManager
    
    manager = AlertOutputManager(state_path=Path("/tmp/monitor_state.json"))
    
    # 处理告警
    message = manager.process_alerts(
        alerts=rule_alerts,
        quote_snapshot=quote_data,
        dedupe_minutes=10,
    )
    if message:
        send_wechat(message)  # 或 print(message)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

CN_TZ = ZoneInfo("Asia/Shanghai")


# ──────────────────────────────────────────
# 数据模型
# ──────────────────────────────────────────

@dataclass
class DedupeConfig:
    """去重配置。"""

    default_minutes: int = 10  # 默认去重时间窗口
    # 按类型配置: {type_name: {"dedupe_minutes": int, "breakthrough_if_price_change_pct": float}}
    by_type: dict[str, dict[str, Any]] = field(default_factory=dict)

    def __post_init__(self):
        # 默认类型配置
        defaults = {
            "risk_alert": {"dedupe_minutes": 5, "breakthrough_if_price_change_pct": 2.0},
            "reduce_alert": {"dedupe_minutes": 10, "breakthrough_if_price_change_pct": 2.0},
            "sector_rotation": {"dedupe_minutes": 30, "breakthrough_if_price_change_pct": 0},
        }
        for k, v in defaults.items():
            if k not in self.by_type:
                self.by_type[k] = v


@dataclass
class EmittedAlert:
    """已发出的告警记录。"""

    fingerprint: str
    time: datetime
    price: float
    action: str
    stock_code: str
    stock_name: str


# ──────────────────────────────────────────
# 格式化器
# ──────────────────────────────────────────


class AlertFormatter:
    """告警格式化器：将 RuleAlert 转为可读文本。"""

    @staticmethod
    def format_wechat_message(
        alerts: list[Any],
        quote_snapshot: dict,
        timestamp: datetime | None = None,
    ) -> str:
        """格式化为微信消息。

        Args:
            alerts: RuleAlert 列表
            quote_snapshot: 行情快照
            timestamp: 时间戳（默认当前时间）
        """
        if not alerts:
            return ""

        ts = timestamp or datetime.now(CN_TZ)
        lines = [
            "[Hermes股票监控提醒]",
            f"时间：{ts.strftime('%Y-%m-%d %H:%M:%S %Z')}",
            f"数据源：{quote_snapshot.get('source', 'unknown')}",
            f"行情请求耗时：{quote_snapshot.get('elapsed_ms', 0)} ms",
            "",
            "触发信号：",
        ]

        for alert in alerts:
            lines.append(f"- {alert.summary}")

        lines.extend([
            "",
            "处理原则：这是规则触发的观察提醒，不是无条件买卖指令；执行前仍需确认指数、板块扩散和分时承接。",
        ])

        return "\n".join(lines)

    @staticmethod
    def format_console_message(
        alerts: list[Any],
        quote_snapshot: dict,
        timestamp: datetime | None = None,
    ) -> str:
        """格式化为控制台消息（更简洁）。"""
        if not alerts:
            return ""

        ts = timestamp or datetime.now(CN_TZ)
        lines = [
            f"[{ts.strftime('%H:%M:%S')}] 监控触发 {len(alerts)} 个信号",
            f"数据源: {quote_snapshot.get('source', 'unknown')} ({quote_snapshot.get('elapsed_ms', 0)}ms)",
        ]

        for alert in alerts:
            severity_emoji = "🔴" if alert.severity == "high" else ("🟡" if alert.severity == "medium" else "🟢")
            lines.append(f"  {severity_emoji} [{alert.action}] {alert.stock_name} {alert.price} — {alert.trigger}")

        return "\n".join(lines)

    @staticmethod
    def format_log_entry(
        alert: Any,
        timestamp: datetime,
        status: str = "emitted",
    ) -> dict:
        """格式化为日志条目。"""
        local = timestamp.astimezone(CN_TZ)
        return {
            "date": local.strftime("%Y-%m-%d"),
            "time": local.isoformat(),
            "status": status,
            "fingerprint": _alert_fingerprint(alert),
            "action": alert.action,
            "stock_code": alert.stock_code,
            "stock_name": alert.stock_name,
            "price": alert.price,
            "severity": alert.severity,
            "trigger": alert.trigger,
            "summary": alert.summary,
        }


# ──────────────────────────────────────────
# 去重引擎
# ──────────────────────────────────────────


class DedupeEngine:
    """去重引擎：指纹去重 + 时间窗口 + 价格突破。"""

    def __init__(self, config: DedupeConfig | None = None):
        self.config = config or DedupeConfig()

    def filter_new_alerts(
        self,
        alerts: list[Any],
        history: dict[str, Any],
        daily_emitted: dict[str, dict[str, float]],
        current_time: datetime,
    ) -> list[Any]:
        """过滤出新告警（未被去重）。

        去重策略:
            1. 指纹去重: 同一标的+同一动作 = 同一指纹
            2. 时间窗口: 同一指纹在 N 分钟内不重复
            3. 价格突破: 价格变化超过阈值可突破去重
            4. 同日复筛: 减仓/风控类同日内额外检查
        """
        if not alerts:
            return []

        current = current_time.astimezone(CN_TZ)
        today_str = current.strftime("%Y-%m-%d")
        today_entry = daily_emitted.get(today_str, {}) if isinstance(daily_emitted, dict) else {}
        fresh: list[Any] = []

        for alert in alerts:
            fp = _alert_fingerprint(alert)
            last_entry = history.get(fp)

            # 确定该类型的去重配置
            dedupe_type = _action_to_dedupe_type(alert.action)
            type_config = self.config.by_type.get(dedupe_type, {})
            effective_minutes = type_config.get("dedupe_minutes", self.config.default_minutes)
            breakthrough_pct = type_config.get("breakthrough_if_price_change_pct", 0)

            # 同日复筛（仅减仓/风控）
            code_action_key = f"{alert.stock_code}_{alert.action}"
            same_day_price = today_entry.get(code_action_key) if isinstance(today_entry, dict) else None

            if same_day_price is not None and alert.action in ("减仓观察", "风控观察"):
                if isinstance(last_entry, dict):
                    last_time = _parse_state_time(last_entry.get("time"))
                    if last_time is not None:
                        elapsed_minutes = (current - last_time).total_seconds() / 60
                        if elapsed_minutes < effective_minutes:
                            pct_change = abs((alert.price - same_day_price) / same_day_price) * 100 if same_day_price > 0 else 0
                            if pct_change < 2.0:
                                # 同日内同标的同动作，价格变化<2%，跳过
                                continue

            # 首次告警
            if last_entry is None:
                fresh.append(alert)
                continue

            # 解析上次记录
            if isinstance(last_entry, str):
                last_time = _parse_state_time(last_entry)
                last_price = None
            else:
                last_time = _parse_state_time(last_entry.get("time"))
                last_price = last_entry.get("price")

            if last_time is None:
                fresh.append(alert)
                continue

            # 时间窗口检查
            elapsed_minutes = (current - last_time).total_seconds() / 60
            if elapsed_minutes >= effective_minutes:
                fresh.append(alert)
                continue

            # 价格突破检查
            if breakthrough_pct > 0 and last_price is not None and last_price > 0:
                pct_change = abs((alert.price - last_price) / last_price) * 100
                if pct_change >= breakthrough_pct:
                    fresh.append(alert)
                    continue

            # 被去重
            pass

        return fresh

    def get_suppressed_reason(
        self,
        alert: Any,
        history: dict[str, Any],
        current_time: datetime,
    ) -> str | None:
        """获取告警被去重的原因（用于日志）。"""
        fp = _alert_fingerprint(alert)
        last_entry = history.get(fp)

        if last_entry is None:
            return None

        dedupe_type = _action_to_dedupe_type(alert.action)
        type_config = self.config.by_type.get(dedupe_type, {})
        effective_minutes = type_config.get("dedupe_minutes", self.config.default_minutes)

        if isinstance(last_entry, dict):
            last_time = _parse_state_time(last_entry.get("time"))
        else:
            last_time = _parse_state_time(last_entry)

        if last_time:
            elapsed = (current_time.astimezone(CN_TZ) - last_time).total_seconds() / 60
            remaining = effective_minutes - elapsed
            if remaining > 0:
                return f"去重窗口内（还剩{remaining:.0f}分钟）"

        return "已去重"


# ──────────────────────────────────────────
# 状态持久化
# ──────────────────────────────────────────


class StatePersistence:
    """状态持久化：告警历史读写。"""

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else Path("/tmp/monitor_state.json")
        self._state: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        """从文件加载状态。"""
        if not self.path.exists():
            self._state = {}
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._state = data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load monitor state: %s", e)
            self._state = {}

    def save(self) -> None:
        """保存状态到文件。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._state, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def get_history(self) -> dict[str, Any]:
        """获取告警历史。"""
        history = self._state.get("alert_history", {})
        return history if isinstance(history, dict) else {}

    def get_daily_emitted(self) -> dict[str, dict[str, float]]:
        """获取同日内已发告警。"""
        daily = self._state.get("daily_emitted", {})
        return daily if isinstance(daily, dict) else {}

    def get_decision_log(self) -> list[dict]:
        """获取决策日志。"""
        log = self._state.get("alert_decision_log", [])
        return log if isinstance(log, list) else []

    def record_emitted(
        self,
        alerts: list[Any],
        current_time: datetime,
    ) -> None:
        """记录已发出的告警。"""
        history = self._state.setdefault("alert_history", {})
        daily = self._state.setdefault("daily_emitted", {})
        current = current_time.astimezone(CN_TZ).isoformat()
        today_str = current_time.astimezone(CN_TZ).strftime("%Y-%m-%d")
        today_entry = daily.setdefault(today_str, {})

        for alert in alerts:
            fp = _alert_fingerprint(alert)
            history[fp] = {
                "time": current,
                "price": alert.price,
            }
            code_action_key = f"{alert.stock_code}_{alert.action}"
            today_entry[code_action_key] = alert.price

        self.save()

    def record_decision_log(
        self,
        all_alerts: list[Any],
        emitted_alerts: list[Any],
        current_time: datetime,
    ) -> None:
        """记录决策日志（包括被去重的）。"""
        log = self._state.setdefault("alert_decision_log", [])
        emitted_keys = {_alert_fingerprint(alert) for alert in emitted_alerts}
        formatter = AlertFormatter()

        for alert in all_alerts:
            status = "emitted" if _alert_fingerprint(alert) in emitted_keys else "suppressed"
            log.append(formatter.format_log_entry(alert, current_time, status=status))

        # 限制日志长度（保留最近1000条）
        if len(log) > 1000:
            self._state["alert_decision_log"] = log[-1000:]

        self.save()

    def clear_old_daily(self, days_to_keep: int = 7) -> None:
        """清理旧的同日复筛记录。"""
        daily = self._state.get("daily_emitted", {})
        if not isinstance(daily, dict):
            return

        cutoff = (datetime.now(CN_TZ) - timedelta(days=days_to_keep)).strftime("%Y-%m-%d")
        old_keys = [k for k in daily.keys() if k < cutoff]
        for k in old_keys:
            del daily[k]

        if old_keys:
            logger.info("Cleared %d old daily_emitted entries", len(old_keys))
            self.save()


# ──────────────────────────────────────────
# 统一入口
# ──────────────────────────────────────────


class AlertOutputManager:
    """告警输出管理器：统一入口。

    Usage:
        manager = AlertOutputManager(state_path=Path("/tmp/monitor_state.json"))
        
        # 处理告警（去重 + 格式化）
        message = manager.process_alerts(
            alerts=rule_alerts,
            quote_snapshot=quote_data,
            dedupe_minutes=10,
            output_format="wechat",  # or "console"
        )
        if message:
            send_wechat(message)
    """

    def __init__(
        self,
        state_path: Path | None = None,
        dedupe_config: DedupeConfig | None = None,
    ):
        self.persistence = StatePersistence(state_path)
        self.dedupe = DedupeEngine(dedupe_config)
        self.formatter = AlertFormatter()

    def process_alerts(
        self,
        alerts: list[Any],
        quote_snapshot: dict,
        dedupe_minutes: int = 10,
        output_format: str = "wechat",
        timestamp: datetime | None = None,
    ) -> str:
        """处理告警：去重 → 格式化 → 记录状态。

        Args:
            alerts: 原始告警列表
            quote_snapshot: 行情快照
            dedupe_minutes: 去重时间窗口
            output_format: 输出格式 ("wechat" | "console")
            timestamp: 时间戳（默认当前时间）

        Returns:
            str: 格式化消息（如果全部被去重则返回空字符串）
        """
        if not alerts:
            return ""

        ts = timestamp or datetime.now(CN_TZ)

        # 1. 清理旧数据
        self.persistence.clear_old_daily(days_to_keep=7)

        # 2. 去重
        history = self.persistence.get_history()
        daily_emitted = self.persistence.get_daily_emitted()
        new_alerts = self.dedupe.filter_new_alerts(alerts, history, daily_emitted, ts)

        # 3. 记录决策日志
        self.persistence.record_decision_log(alerts, new_alerts, ts)

        if not new_alerts:
            logger.info("All %d alerts deduplicated", len(alerts))
            return ""

        # 4. 记录已发出的
        self.persistence.record_emitted(new_alerts, ts)

        # 5. 格式化
        if output_format == "console":
            message = self.formatter.format_console_message(new_alerts, quote_snapshot, ts)
        else:
            message = self.formatter.format_wechat_message(new_alerts, quote_snapshot, ts)

        logger.info(
            "Emitted %d/%d alerts (deduped %d)",
            len(new_alerts),
            len(alerts),
            len(alerts) - len(new_alerts),
        )

        return message

    def get_stats(self) -> dict:
        """获取告警统计。"""
        history = self.persistence.get_history()
        log = self.persistence.get_decision_log()
        emitted = [e for e in log if e.get("status") == "emitted"]
        suppressed = [e for e in log if e.get("status") == "suppressed"]

        return {
            "total_fingerprints": len(history),
            "total_decisions": len(log),
            "emitted_count": len(emitted),
            "suppressed_count": len(suppressed),
            "suppression_rate": round(len(suppressed) / len(log), 2) if log else 0,
        }


# ──────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────


def _alert_fingerprint(alert: Any) -> str:
    """生成告警指纹。"""
    return "|".join([
        alert.action,
        alert.stock_code,
        alert.trigger,
    ])


def alert_to_log_entry(
    alert: Any,
    value: datetime,
    *,
    status: str,
) -> dict:
    """格式化单条告警为日志条目（模块级便捷函数）。

    Args:
        alert: RuleAlert 或兼容对象
        value: 时间戳
        status: 状态字符串

    Returns:
        日志条目字典
    """
    from qing_investment.monitor.scheduler import _CN_TZ
    local = value.astimezone(_CN_TZ)
    return {
        "date": local.strftime("%Y-%m-%d"),
        "time": local.isoformat(),
        "status": status,
        "fingerprint": _alert_fingerprint(alert),
        "action": alert.action,
        "stock_code": alert.stock_code,
        "stock_name": getattr(alert, "stock_name", ""),
        "price": getattr(alert, "price", 0.0),
        "severity": getattr(alert, "severity", "medium"),
        "trigger": alert.trigger,
        "summary": getattr(alert, "summary", ""),
    }


def _action_to_dedupe_type(action: str) -> str:
    """映射告警动作到去重类型。"""
    if "风控" in action or "风险" in action:
        return "risk_alert"
    if "减仓" in action:
        return "reduce_alert"
    if any(kw in action for kw in ("进攻", "防御", "指数", "回流", "轮动", "板块")):
        return "sector_rotation"
    return "default"


def _parse_state_time(value: object) -> datetime | None:
    """解析状态时间。"""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=CN_TZ)
    return parsed.astimezone(CN_TZ)


# ──────────────────────────────────────────
# 向后兼容
# ──────────────────────────────────────────


def format_alerts_message(
    alerts: list[Any],
    timestamp: datetime,
    quote_snapshot: dict,
) -> str:
    """向后兼容：直接格式化告警消息（不去重）。"""
    formatter = AlertFormatter()
    return formatter.format_wechat_message(alerts, quote_snapshot, timestamp)


def filter_new_alerts(
    alerts: list[Any],
    state: dict[str, Any],
    current_time: datetime,
    *,
    dedupe_minutes: int = 10,
    dedupe_by_type: dict[str, dict[str, Any]] | None = None,
) -> list[Any]:
    """向后兼容：从 state 字典中去重。"""
    engine = DedupeEngine(DedupeConfig(default_minutes=dedupe_minutes, by_type=dedupe_by_type or {}))
    history = state.get("alert_history", {})
    daily_emitted = state.get("daily_emitted", {})
    return engine.filter_new_alerts(alerts, history, daily_emitted, current_time)


def record_emitted_alerts(
    state: dict[str, Any],
    alerts: list[Any],
    current_time: datetime,
) -> None:
    """向后兼容：记录到 state 字典。"""
    history = state.setdefault("alert_history", {})
    daily = state.setdefault("daily_emitted", {})
    current = current_time.astimezone(CN_TZ).isoformat()
    today_str = current_time.astimezone(CN_TZ).strftime("%Y-%m-%d")
    today_entry = daily.setdefault(today_str, {})

    for alert in alerts:
        fp = _alert_fingerprint(alert)
        history[fp] = {
            "time": current,
            "price": alert.price,
        }
        code_action_key = f"{alert.stock_code}_{alert.action}"
        today_entry[code_action_key] = alert.price


def format_quote_line(quote: dict) -> str:
    """格式化单条行情为文本行。

    Args:
        quote: 行情数据字典

    Returns:
        str: 格式化后的行情行
    """
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


def format_smoke_message(smoke: dict) -> str:
    """格式化烟雾测试消息。

    Args:
        smoke: 烟雾测试数据字典

    Returns:
        str: 格式化后的烟雾测试消息
    """
    lines = [
        "[Hermes股票监控测试]",
        "这是一条手动 smoke test，不代表买卖建议。",
    ]
    status_msg = smoke.get("status", "")
    if status_msg:
        lines.append(status_msg)
    lines.append("下一步：接入实时行情后，cron tick 将只在触发买入/卖出/风控条件时输出。")
    return "\n".join(lines)
