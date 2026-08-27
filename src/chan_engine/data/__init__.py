"""M6-1 数据接入层：长历史日线获取与本地存储。

口径与设计依据：`docs/design/chanlun-m6-strategy-backtest.md` §4。

- fetch：akshare → baostock 降级链，统一归一为
  ``{"date", "open", "high", "low", "close", "volume"(股), "amount"}``；
  双源皆挂抛 ``DataFetchError``，禁止编造数据。
- store：``infra/data/chan_bars.db``（gitignored），独立于监控
  ``kline_cache.db``（后者 per-code 覆盖写会销毁长历史）；幂等 upsert。
- Bar 适配：``load_bars`` 直供引擎（ts=窗口内递增序号）。
"""

from chan_engine.data.fetch import (
    DataFetchError,
    fetch_daily,
    is_index,
    normalize_akshare_index_records,
    normalize_akshare_stock_records,
    normalize_baostock_rows,
    to_baostock_code,
)
from chan_engine.data.store import (
    DEFAULT_DB,
    coverage,
    init_db,
    load_bars,
    load_daily,
    save_daily,
)

__all__ = [
    "DEFAULT_DB",
    "DataFetchError",
    "coverage",
    "fetch_daily",
    "init_db",
    "is_index",
    "load_bars",
    "load_daily",
    "normalize_akshare_index_records",
    "normalize_akshare_stock_records",
    "normalize_baostock_rows",
    "save_daily",
    "to_baostock_code",
]
