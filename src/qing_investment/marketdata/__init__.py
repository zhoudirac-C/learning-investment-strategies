"""marketdata — A股数据源统一收口模块（一期，2026-09-11）。

背景
----
2026-09-10 TDX 按接口粒度封禁事故复盘发现：项目内 K线抓取有 3 套互不一致的
降级链（``scripts/update_index_klines_intraday.py`` / ``agent/tools/stock_data.py``
/ ``chan_engine/data/fetch.py``），快照抓取另有 3 套；东财裸调无全局限流。
本模块将源接入、限流、熔断、降级路由、结果归一收口为唯一入口。

设计决策（对齐 a-stock-data v3.8.0 的防封经验 + 本仓库两次事故教训）：

1. **降级优先级**（2026-09-11 用户拍板）：腾讯优先（不封 IP）→ 东财第二
   → TDX（strict 语义）→ 同花顺（仅 ths_only 指数）→ 新浪。东财有 IP 风控
   （社区实测 5 req/s 触发、20+ 小时 IP 级封禁案例），只兜第二档。
2. **每源限流**：东财强制 QPS≤1 + 抖动 + 会话复用；腾讯/新浪宽松；
   TDX 由 ``qing_investment.tdx_market`` 自身的客户端管理。
3. **接口粒度熔断**：key=(source, capability)。一次确认失败本进程内短路，
   杜绝 9/10 事故里 22 台 host 逐台空转拖垮 cron 的模式。
4. **strict 空语义全局化**（2026-09-10 修复的定义）：
   - ``strict=True``（K线/快照）：源返回空 → 视为软失败，降级下一源；
     全部源空 → 抛 :class:`MarketDataError`，**绝不静默返回 []**。
   - ``strict=False``（元数据/搜索类）：空可能是合法值，原样返回。
5. **返回统一 shape**：bar=``{bar_time,open,high,low,close,volume,amount}``，
   quote=``{code,name,price,...}``，结果必带 ``source`` 标注，便于多口径对账。
6. **TDX 不重写**：``qing_investment.tdx_market`` 已实现能力路由/加权负载
   均衡/strict 空语义，marketdata 只做委托与归一。

子模块
------
- ``symbol``   代码归一化（号段判定 + 显式前缀优先，矛盾抛错）
- ``http``     统一 HTTP 层（UA/超时/重试/编码），消灭 7 处重复 ``_http_get``
- ``ratelimit``每源令牌桶
- ``breaker``  接口粒度进程内熔断
- ``router``   能力路由 ``get_kline`` / ``get_quotes`` / ``get_intraday``
- ``sources``  每源一个文件：tencent / eastmoney / tdx / sina / ths
- ``news``     财联社电报（cls.cn 本地签名零 key）
- ``official`` 中证/国证指数成分与权重、深交所官方交易日历
- ``macro``    人民银行社融 / 统计局 PMI
"""

from __future__ import annotations

from qing_investment.marketdata.errors import MarketDataError, SourceUnavailable
from qing_investment.marketdata.breaker import Breaker, breaker
from qing_investment.marketdata.symbol import (
    is_index_code,
    norm_ticker,
    prefix_for,
    resolve_symbol,
)
from qing_investment.marketdata.router import (
    get_index_kline,
    get_intraday,
    get_kline,
    get_quotes,
)

__all__ = [
    "MarketDataError",
    "SourceUnavailable",
    "Breaker",
    "breaker",
    "is_index_code",
    "norm_ticker",
    "prefix_for",
    "resolve_symbol",
    "get_kline",
    "get_index_kline",
    "get_intraday",
    "get_quotes",
]
