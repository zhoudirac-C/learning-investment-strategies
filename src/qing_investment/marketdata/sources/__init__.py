"""marketdata.sources — 每源一个适配器文件。

统一约定：
- 模块级常量 ``SOURCE`` 为源名（router 熔断 key 用）
- ``fetch_kline(code, klt, count, *, kind) -> list[dict]``：统一 bar shape，
  空返回 [] 表示软失败（strict 空语义由 router 统一裁决）；
  结构性异常可抛错（router 捕获后计入 attempts 降级）
- ``fetch_quotes(codes, *, kind) -> list[dict]``：统一 quote shape，必带 source
"""

from qing_investment.marketdata.sources import (
    baidu,
    eastmoney,
    sina,
    tdx,
    tencent,
    ths,
)

__all__ = ["baidu", "eastmoney", "sina", "tdx", "tencent", "ths"]
