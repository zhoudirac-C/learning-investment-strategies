"""健康指标收集与持久化.

提供全局级别的健康指标注册表，供监控引擎各组件（WsEventDrivenFetcher、
DataCache 等）上报运行状态。Hermes cron 定期读取并推送微信。

设计原则：
- 纯文件持久化，不依赖外部服务
- 支持多进程场景（进程各自写，cron 统一读）
- 区分可恢复警告与持续性故障
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 默认指标文件路径
_DEFAULT_STATS_PATH = Path("/tmp/qing_health_stats.json")


@dataclass
class CircuitBreakerMetrics:
    """断路器指标."""
    is_open: bool = False
    failures: int = 0
    cooldown_remaining_hours: float = 0.0
    last_failure_time: str = ""
    status: str = "closed"  # closed | open | half-open


@dataclass
class DegradationMetrics:
    """降级指标."""
    http_fallback_count: int = 0       # HTTP 降级次数
    ws_not_started_count: int = 0       # WS 未启动次数
    current_source: str = "ws"           # 当前数据源: ws | http_fallback | none
    current_reason: str = ""              # 降级原因


@dataclass
class CacheMetrics:
    """缓存命中率指标."""
    size: int = 0
    max_entries: int = 1000
    hits: int = 0
    misses: int = 0
    hit_rate: float = 0.0
    sets: int = 0
    expired: int = 0
    evictions: int = 0


@dataclass
class HealthSnapshot:
    """完整健康快照."""
    timestamp: str = ""
    circuit_breaker: CircuitBreakerMetrics = field(default_factory=CircuitBreakerMetrics)
    degradation: DegradationMetrics = field(default_factory=DegradationMetrics)
    cache: CacheMetrics = field(default_factory=CacheMetrics)
    agent_status: str = "unknown"   # running | down | degraded
    uptime_hours: float = 0.0


class HealthStatsRegistry:
    """健康指标注册表（单例，文件持久化）.

    使用方式:
        registry = HealthStatsRegistry()
        registry.update_circuit_breaker(is_open=True, failures=3)
        registry.update_cache_hit_rate(hit_rate=0.85)
        snapshot = registry.get_snapshot()
    """

    _instance: HealthStatsRegistry | None = None

    def __new__(cls, *args, **kwargs) -> HealthStatsRegistry:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, stats_path: str | Path | None = None) -> None:
        if hasattr(self, "_initialized"):
            return
        self._initialized = True
        self._stats_path = Path(stats_path) if stats_path else _DEFAULT_STATS_PATH
        self._uptime_start = time.time()
        # 进程内缓存
        self._circuit_breaker = CircuitBreakerMetrics()
        self._degradation = DegradationMetrics()
        self._cache = CacheMetrics()
        # 标记是否有跨进程写入（共享文件场景）
        self._file_mode = False
        logger.info("HealthStatsRegistry initialized, path=%s", self._stats_path)

    # ── 进程内更新 ──────────────────────────────────────────────────

    def update_circuit_breaker(
        self,
        is_open: bool = False,
        failures: int = 0,
        cooldown_remaining_hours: float = 0.0,
        last_failure_time: str = "",
    ) -> None:
        """更新断路器指标."""
        self._circuit_breaker.is_open = is_open
        self._circuit_breaker.failures = failures
        self._circuit_breaker.cooldown_remaining_hours = cooldown_remaining_hours
        if last_failure_time:
            self._circuit_breaker.last_failure_time = last_failure_time
        self._circuit_breaker.status = "open" if is_open else "closed"
        self._persist()

    def record_degradation(
        self,
        source: str = "ws",
        reason: str = "",
    ) -> None:
        """记录降级事件."""
        if source == "http_fallback" and reason == "circuit_breaker":
            self._degradation.http_fallback_count += 1
        elif source == "http_fallback" and reason == "ws_not_started":
            self._degradation.ws_not_started_count += 1
        self._degradation.current_source = source
        self._degradation.current_reason = reason
        self._persist()

    def update_cache_stats(self, cache: dict) -> None:
        """更新缓存命中率指标."""
        self._cache.size = cache.get("size", 0)
        self._cache.max_entries = cache.get("max_entries", 1000)
        self._cache.hits = cache.get("hits", 0)
        self._cache.misses = cache.get("misses", 0)
        self._cache.hit_rate = cache.get("hit_rate", 0.0)
        self._cache.sets = cache.get("sets", 0)
        self._cache.expired = cache.get("expired", 0)
        self._cache.evictions = cache.get("evictions", 0)
        self._persist()

    def update_agent_status(self, status: str) -> None:
        """更新 Agent 运行状态."""
        self._agent_status = status
        self._persist()

    # ── 快照读取 ────────────────────────────────────────────────────

    def get_snapshot(self) -> HealthSnapshot:
        """获取当前健康快照（优先读文件，fallback 到进程内缓存）."""
        # 先尝试从文件加载（跨进程场景）
        if self._stats_path.exists():
            try:
                data = json.loads(self._stats_path.read_text(encoding="utf-8"))
                return self._dict_to_snapshot(data)
            except Exception as e:
                logger.warning("Failed to load health stats file: %s", e)

        # fallback 到进程内缓存
        return self._build_snapshot()

    def format_for_wechat(self) -> str:
        """格式化健康快照为微信消息."""
        snapshot = self.get_snapshot()
        cb = snapshot.circuit_breaker
        dg = snapshot.degradation
        ca = snapshot.cache
        ts = snapshot.timestamp or datetime.now().strftime("%m-%d %H:%M")

        lines = [
            f"📊 监控引擎健康报告 @ {ts}",
            f"━━━━━━━━━━━━━━━━━━━━",
            f"Agent: {self._status_icon(snapshot.agent_status)} {snapshot.agent_status}",
            f"运行: {snapshot.uptime_hours:.1f}h",
            "",
            f"🔌 断路器: {self._status_icon(cb.status)} {cb.status}",
            f"  失败次数: {cb.failures}",
        ]
        if cb.is_open:
            lines.append(f"  冷却剩余: {cb.cooldown_remaining_hours:.1f}h")
            lines.append(f"  上次失败: {cb.last_failure_time}")
        lines.append("")
        lines.append(f"📡 数据源: {dg.current_source}")
        if dg.current_source != "ws":
            lines.append(f"  降级原因: {dg.current_reason}")
            lines.append(f"  HTTP降级: {dg.http_fallback_count}次")
            lines.append(f"  WS未启动: {dg.ws_not_started_count}次")
        lines.append("")
        lines.append(f"💾 缓存命中率: {ca.hit_rate:.1%}")
        lines.append(f"  条目: {ca.size}/{ca.max_entries} | "
                     f"命中/请求: {ca.hits}/{ca.hits + ca.misses}")
        if ca.evictions > 0:
            lines.append(f"  淘汰: {ca.evictions} | 过期: {ca.expired}")

        return "\n".join(lines)

    # ── 内部 ────────────────────────────────────────────────────────

    def _persist(self) -> None:
        """持久化到文件（供跨进程读取）."""
        try:
            snapshot = self._build_snapshot()
            data = {
                "timestamp": snapshot.timestamp,
                "circuit_breaker": asdict(snapshot.circuit_breaker),
                "degradation": asdict(snapshot.degradation),
                "cache": asdict(snapshot.cache),
                "agent_status": snapshot.agent_status,
                "uptime_hours": snapshot.uptime_hours,
            }
            self._stats_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("Failed to persist health stats: %s", e)

    def _build_snapshot(self) -> HealthSnapshot:
        """从进程内缓存构建快照."""
        return HealthSnapshot(
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            circuit_breaker=self._circuit_breaker,
            degradation=self._degradation,
            cache=self._cache,
            agent_status=getattr(self, "_agent_status", "unknown"),
            uptime_hours=(time.time() - self._uptime_start) / 3600,
        )

    @staticmethod
    def _dict_to_snapshot(data: dict) -> HealthSnapshot:
        """从 dict 还原快照."""
        cb_data = data.get("circuit_breaker", {})
        dg_data = data.get("degradation", {})
        ca_data = data.get("cache", {})
        return HealthSnapshot(
            timestamp=data.get("timestamp", ""),
            circuit_breaker=CircuitBreakerMetrics(**cb_data),
            degradation=DegradationMetrics(**dg_data),
            cache=CacheMetrics(**ca_data),
            agent_status=data.get("agent_status", "unknown"),
            uptime_hours=data.get("uptime_hours", 0.0),
        )

    @staticmethod
    def _status_icon(status: str) -> str:
        mapping = {
            "closed": "✅", "open": "🔴", "half-open": "⚠️",
            "running": "✅", "down": "❌", "degraded": "⚠️",
            "ws": "✅", "http_fallback": "⚠️", "none": "❌",
            "unknown": "❓",
        }
        return mapping.get(status, "❓")


# ── 便捷函数 ──────────────────────────────────────────────────────

def get_health_registry(stats_path: str | Path | None = None) -> HealthStatsRegistry:
    """获取健康指标注册表单例."""
    return HealthStatsRegistry(stats_path=stats_path)


def format_health_report() -> str:
    """一键格式化健康报告."""
    return get_health_registry().format_for_wechat()
