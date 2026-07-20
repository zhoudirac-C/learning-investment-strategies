"""tdx_market 异常定义。"""

from __future__ import annotations


class TdxError(Exception):
    """tdx_market 所有异常的基类。"""


class TdxConnectionError(TdxError):
    """连接通达信服务器失败（所有候选服务器均不可用）。"""


class TdxDataError(TdxError):
    """服务器已连接但返回数据异常或为空。"""


class TdxSymbolError(TdxError):
    """股票/指数代码无法识别或无法映射到 (market, code)。"""
