"""每源限流器（串行 + 最小间隔 + 抖动）。

东财防封铁律（a-stock-data 社区实测 + 2026-06-30 IP 级封禁 20+ 小时案例）：
- 串行，不并发
- 每次间隔 ≥1s + 随机抖动
- 复用 HTTP 会话

腾讯/新浪实测不封 IP，给宽松限流防意外打爆；TDX 由
``qing_investment.tdx_market`` 自己的连接管理负责，不在本层限流。
"""

from __future__ import annotations

import random
import threading
import time

#: 东财：QPS≤1 + 抖动（对齐 a-stock-data EM_MIN_INTERVAL=1.0）
EM_MIN_INTERVAL = 1.0
#: 腾讯：web.ifzq 连续 5000+ 次会返回空（限流非封禁），给 0.25s 保守间隔
TENCENT_MIN_INTERVAL = 0.25
#: 新浪：urllib 默认 UA 即被限流的先例，0.3s
SINA_MIN_INTERVAL = 0.3
#: 同花顺：0.5s（2026-09-10 接入后未实测风控阈值，保守）
THS_MIN_INTERVAL = 0.5


class RateLimiter:
    """进程内串行限流器（线程安全）。"""

    def __init__(self, name: str, min_interval: float, jitter: float = 0.3):
        self.name = name
        self.min_interval = min_interval
        self.jitter = jitter
        self._next_ok = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        """阻塞到下次允许请求的时刻。"""
        with self._lock:
            now = time.monotonic()
            delay = self._next_ok - now
            if delay > 0:
                time.sleep(delay)
                now = time.monotonic()
            self._next_ok = now + self.min_interval + random.uniform(0, self.jitter)


LIMITERS: dict[str, RateLimiter] = {
    "eastmoney": RateLimiter("eastmoney", EM_MIN_INTERVAL),
    "tencent": RateLimiter("tencent", TENCENT_MIN_INTERVAL),
    "sina": RateLimiter("sina", SINA_MIN_INTERVAL),
    "ths": RateLimiter("ths", THS_MIN_INTERVAL),
}


def acquire(source: str) -> None:
    """声明一次对 source 的请求（阻塞限流）。"""
    lim = LIMITERS.get(source)
    if lim:
        lim.wait()
