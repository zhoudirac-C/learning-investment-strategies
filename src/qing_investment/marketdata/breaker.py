"""接口粒度进程内熔断。

2026-09-10 事故模式：TDX K线接口被封后每次调用逐台 host 空转 20-30s，
36 次调用累计拖垮 cron 900s 超时。原修复在
``scripts/update_index_klines_intraday.py`` 用模块级 ``_TDX_DEAD``/
``_EM_DEAD`` 全局布尔实现，本模块将其抽为通用设施。

关键语义：熔断 key 是 **(source, capability)** 而非 source 整体——
9/10 实测 TDX 的 K线接口全灭但历史分时/元数据存活，整源熔断会误伤存活能力。
"""

from __future__ import annotations

import threading
import time


class Breaker:
    """进程内熔断器（线程安全）。

    Parameters
    ----------
    source:
        源名，如 ``"eastmoney"``。
    cooldown:
        熔断后的冷却秒数，过期后允许再探测一次（半开）。默认 1800s：
        东财 IP 级封禁实测持续 20+ 小时，但短冷却只是偶尔多花一次探测，
        长冷却却会在服务恢复后白白跳过好源，故取保守值。
    """

    def __init__(self, source: str, cooldown: float = 1800.0):
        self.source = source
        self.cooldown = cooldown
        self._open_until: dict[str, float] = {}
        self._lock = threading.Lock()

    def is_open(self, capability: str) -> bool:
        """该 (source, capability) 是否处于熔断状态。"""
        with self._lock:
            until = self._open_until.get(capability)
            if until is None:
                return False
            if time.monotonic() >= until:
                # 半开：冷却过期，允许下一次真实调用再探测
                del self._open_until[capability]
                return False
            return True

    def trip(self, capability: str) -> None:
        """确认某能力失败，打开熔断。"""
        with self._lock:
            self._open_until[capability] = time.monotonic() + self.cooldown

    def reset(self, capability: str | None = None) -> None:
        """手动复位（测试用，或确认服务恢复后）。"""
        with self._lock:
            if capability is None:
                self._open_until.clear()
            else:
                self._open_until.pop(capability, None)


breaker = Breaker("global")
