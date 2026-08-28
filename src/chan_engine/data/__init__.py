"""M6-1 数据接入层：长历史日线获取与本地存储；M7-1 增补分钟线（60m/30m）。

口径与设计依据：`docs/design/chanlun-m6-strategy-backtest.md` §4（日线）、
`docs/design/chanlun-m7-multitimeframe-skill.md` §4（分钟线）。

- fetch：日线 akshare → baostock；分钟线新浪 → TDX（腾讯分钟线不可用，
  curl+完整 UA，datalen=260 上限）。统一归一；双源皆挂抛 ``DataFetchError``。
- store：``infra/data/chan_bars.db``（gitignored），独立于监控
  ``kline_cache.db``（后者 per-code 覆盖写会销毁长历史）；幂等 upsert。
  分钟行带 ``complete`` 标记：盘中未完成 bar=0，读取默认剔除。
- Bar 适配：``load_bars`` 直供引擎（ts=窗口内递增序号；tf=60/30 走分钟库）。
"""

from chan_engine.data.fetch import (
    VALID_MINUTE_TF,
    DataFetchError,
    fetch_daily,
    fetch_minute,
    is_index,
    mark_complete,
    normalize_akshare_index_records,
    normalize_akshare_stock_records,
    normalize_baostock_rows,
    normalize_sina_minute_records,
    normalize_tdx_minute_records,
    to_baostock_code,
    to_sina_symbol,
    validate_minute_rows,
)
from chan_engine.data.store import (
    DEFAULT_DB,
    coverage,
    coverage_minute,
    init_db,
    load_bars,
    load_daily,
    load_minute,
    save_daily,
    save_minute,
)

__all__ = [
    "DEFAULT_DB",
    "DataFetchError",
    "VALID_MINUTE_TF",
    "coverage",
    "coverage_minute",
    "fetch_daily",
    "fetch_minute",
    "init_db",
    "is_index",
    "load_bars",
    "load_daily",
    "load_minute",
    "mark_complete",
    "normalize_akshare_index_records",
    "normalize_akshare_stock_records",
    "normalize_baostock_rows",
    "normalize_sina_minute_records",
    "normalize_tdx_minute_records",
    "save_daily",
    "save_minute",
    "to_baostock_code",
    "to_sina_symbol",
    "validate_minute_rows",
]
