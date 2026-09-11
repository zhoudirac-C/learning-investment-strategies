"""marketdata 异常定义。"""

from __future__ import annotations


class MarketDataError(RuntimeError):
    """全部数据源失败的最终错误。

    消息携带每个源的失败明细（``source: ErrorType: msg``），
    对齐 ``chan_engine.data.fetch.DataFetchError`` 的数据诚实原则：
    双源皆挂抛错，禁止编造。
    """

    def __init__(self, message: str, *, attempts: list[str] | None = None):
        super().__init__(message)
        #: 每次降级尝试的明细，如 ["eastmoney: ConnectionError: ...", ...]
        self.attempts = attempts or []


class SourceUnavailable(RuntimeError):
    """单个源失败（内部用于降级，不抛给调用方）。"""
