"""qing_investment.tdx_market —— 基于通达信 TDX 协议的 A 股行情数据接口。

本包直连通达信官方行情服务器（多服务器负载均衡 + 故障转移），不依赖
HTTP 免费接口，规避东财 IP 限流、新浪频率限制等问题，为项目提供稳定
的实时行情 / K线 / 分时 / 分笔 / 财务 / 除权除息 / 板块数据。

快速上手::

    from qing_investment.tdx_market import TdxMarket

    mkt = TdxMarket()
    print(mkt.get_quote("600519"))                       # 茅台实时行情
    print(mkt.get_kline("600519", count=10))             # 日K线
    print(mkt.get_quotes(["600519", "000001", "300750"]))# 批量行情
    print(mkt.get_index_kline("999999", count=5))        # 上证指数K线

字段格式与 src/qing_investment/agent/tools/stock_data.py 对齐，
source 字段统一为 'tdx'，便于后续接入多源 fallback 链。
"""

from __future__ import annotations

from .client import TdxClient
from .exceptions import TdxConnectionError, TdxDataError, TdxError, TdxSymbolError
from .hosts import (
    DefaultHostCatalog,
    HostCapability,
    HostInfo,
    HostsForCapability,
    HostsForClass,
)
from .market import TdxMarket, resolve_symbol

# 能力枚举别名（与 gotdx 的 Cap* 命名风格对应，便于直觉使用）
Cap = HostCapability

__all__ = [
    "TdxMarket",
    "TdxClient",
    "resolve_symbol",
    "HostCapability",
    "Cap",
    "HostInfo",
    "DefaultHostCatalog",
    "HostsForCapability",
    "HostsForClass",
    "TdxError",
    "TdxConnectionError",
    "TdxDataError",
    "TdxSymbolError",
]
