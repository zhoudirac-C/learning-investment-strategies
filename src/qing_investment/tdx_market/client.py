"""通达信行情客户端 —— 能力感知的连接池。

设计要点
========

1. 能力路由
   一次请求只应发给「支持该能力」的服务器。例如实时行情 (CapMainQuote)
   只能发给 mainCapabilities 的服务器，不能发给只有 metadataCapabilities
   的「列表专用」服务器。HostsForCapability(cap) 负责筛选。

2. 加权负载均衡
   候选服务器按 Weight 加权随机排序，优先尝试权重高的；失败再试下一台。

3. 故障转移 + 熔断
   每台服务器维护 (连续失败次数, 熔断到期时间)。连续失败 >= fail_threshold
   则熔断 cooldown 秒，期间不再被选中。成功则清零。

4. 按需连接
   每次 execute 选一台服务器 connect → 执行 op(api) → disconnect，
   无状态、线程安全。pytdx 的 auto_retry 负责单连接内的瞬时重试，
   本层负责跨服务器的故障转移。短连接对 A 股中低频查询足够；
   高频场景后续可演进为长连接池。

5. 协议选择
   Ex 类（港股，port 7727）用 TdxExHq_API；其余用 TdxHq_API。
"""

from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass

from .exceptions import TdxConnectionError, TdxDataError
from .hosts import (
    HostCapability,
    HostInfo,
    HostsForCapability,
    HostClassEx,
    HostClassMACEx,
    weighted_choice,
)

logger = logging.getLogger(__name__)

# 默认连接/读取超时（秒）
DEFAULT_CONNECT_TIMEOUT = 15.0
# 单台服务器连续失败多少次后熔断
DEFAULT_FAIL_THRESHOLD = 3
# 熔断时长（秒）
DEFAULT_COOLDOWN = 60.0
# 一次 execute 最多尝试多少台服务器
DEFAULT_MAX_ATTEMPTS = 5


@dataclass
class _HostState:
    """单台服务器的运行时健康状态。"""

    fail_count: int = 0
    cooldown_until: float = 0.0
    last_error: str = ""


class TdxClient:
    """能力感知的通达信行情客户端。

    用法::

        from qing_investment.tdx_market import TdxClient, Cap

        client = TdxClient()
        # op 接收一个已连接的 pytdx API 实例
        quotes = client.execute(Cap.MainQuote, lambda api: api.get_security_quotes([(1, '600519')]))
    """

    def __init__(
        self,
        *,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        fail_threshold: int = DEFAULT_FAIL_THRESHOLD,
        cooldown: float = DEFAULT_COOLDOWN,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        heartbeat: bool = True,
        auto_retry: bool = True,
        rng: random.Random | None = None,
    ) -> None:
        self.connect_timeout = connect_timeout
        self.fail_threshold = fail_threshold
        self.cooldown = cooldown
        self.max_attempts = max_attempts
        self.heartbeat = heartbeat
        self.auto_retry = auto_retry
        self._rng = rng or random.Random()
        self._states: dict[str, _HostState] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def execute(self, cap: HostCapability, op, *args, retry_empty: bool = False, **kwargs):
        """在支持 ``cap`` 能力的服务器上执行 ``op(api, *args, **kwargs)``。

        按加权随机顺序尝试多台服务器，任一成功即返回；全部失败抛
        TdxConnectionError。

        Args:
            retry_empty: True 时，若某台服务器返回空结果（None/空 list/空 dict），
                视为「软失败」并切换下一台（计入熔断）。用于实时行情/证券列表
                这类「服务器可能连上但不返回数据」的场景。全部候选都空时返回
                最后的空结果（不抛异常），由调用方判断。
        """
        candidates = self._ordered_candidates(cap)
        if not candidates:
            raise TdxConnectionError(f"没有已启用的服务器支持能力 {cap!r}")

        last_err: Exception | None = None
        last_result = None
        tried = 0
        for host in candidates:
            if tried >= self.max_attempts:
                break
            if self._is_cooled_down(host.ID):
                continue
            tried += 1
            try:
                result = self._run_on_host(host, cap, op, args, kwargs)
                if retry_empty and _is_empty(result):
                    # 软失败：服务器连上了但不返回数据，切换下一台并计入熔断
                    self._mark_fail(host.ID, TdxDataError(f"{host.Name} 返回空结果"))
                    last_result = result
                    logger.debug(
                        "tdx host %s(%s) 能力 %s 返回空，尝试下一台",
                        host.Name, host.IP, cap,
                    )
                    continue
                self._mark_ok(host.ID)
                return result
            except Exception as e:  # noqa: BLE001 —— 任意异常都视为该主机失败
                self._mark_fail(host.ID, e)
                last_err = e
                logger.debug(
                    "tdx host %s(%s:%s) 执行能力 %s 失败: %r",
                    host.Name, host.IP, host.Port, cap, e,
                )
                continue

        # 有硬异常 → 抛出；否则（全部软失败/空）返回最后的空结果
        if last_err is not None and last_result is None:
            raise TdxConnectionError(
                f"尝试 {tried} 台服务器均失败 (能力={cap!r}): {last_err!r}"
            )
        return last_result

    def status(self) -> dict:
        """返回各服务器健康状态摘要（调试用）。"""
        with self._lock:
            return {
                h.ID: {
                    "name": h.Name,
                    "ip": h.IP,
                    "port": h.Port,
                    "fail_count": self._states.get(h.ID, _HostState()).fail_count,
                    "cooldown_until": self._states.get(h.ID, _HostState()).cooldown_until,
                    "enabled": h.Enabled,
                }
                for h in _all_hosts()
            }

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _ordered_candidates(self, cap: HostCapability) -> list[HostInfo]:
        """按加权随机顺序返回支持 cap 的候选服务器（enabled 且未熔断优先）。"""
        hosts = HostsForCapability(cap)
        # 加权随机不放回排序：重复加权抽样
        ordered: list[HostInfo] = []
        pool = list(hosts)
        while pool:
            pick = weighted_choice(pool, self._rng)
            if pick is None:
                break
            ordered.append(pick)
            pool.remove(pick)
        return ordered

    def _is_cooled_down(self, host_id: str) -> bool:
        with self._lock:
            st = self._states.get(host_id)
            if st is None:
                return False
            return st.cooldown_until > time.time()

    def _mark_ok(self, host_id: str) -> None:
        with self._lock:
            if host_id in self._states:
                self._states[host_id].fail_count = 0
                self._states[host_id].cooldown_until = 0.0

    def _mark_fail(self, host_id: str, err: Exception) -> None:
        with self._lock:
            st = self._states.setdefault(host_id, _HostState())
            st.fail_count += 1
            st.last_error = repr(err)
            if st.fail_count >= self.fail_threshold:
                st.cooldown_until = time.time() + self.cooldown
                logger.info(
                    "tdx host %s 连续失败 %d 次，熔断 %ss",
                    host_id, st.fail_count, self.cooldown,
                )

    def _run_on_host(self, host: HostInfo, cap: HostCapability, op, args, kwargs):
        api = self._make_api(host)
        try:
            api.connect(host.IP, host.Port, time_out=self.connect_timeout)
        except Exception as e:  # noqa: BLE001
            raise TdxConnectionError(
                f"连接 {host.Name}({host.IP}:{host.Port}) 失败: {e!r}"
            ) from e
        try:
            return op(api, *args, **kwargs)
        finally:
            try:
                api.disconnect()
            except Exception:  # noqa: BLE001
                pass

    def _make_api(self, host: HostInfo):
        """根据 host 协议类创建对应 pytdx API 实例。"""
        from pytdx.hq import TdxHq_API
        from pytdx.exhq import TdxExHq_API

        if host.Class in (HostClassEx, HostClassMACEx):
            api = TdxExHq_API(heartbeat=self.heartbeat, auto_retry=self.auto_retry)
        else:
            api = TdxHq_API(heartbeat=self.heartbeat, auto_retry=self.auto_retry)
        return api


def _is_empty(result) -> bool:
    """判断结果是否为「空」（None / 空 list / 空 dict / 空 str）。"""
    if result is None:
        return True
    if isinstance(result, (list, dict, str, tuple, set)):
        return len(result) == 0
    return False


def _all_hosts() -> list[HostInfo]:
    from .hosts import DefaultHostCatalog
    return list(DefaultHostCatalog)
