"""市场情绪数据获取。

提供 A 股市场情绪指标：
- 涨跌家数
- 涨停/跌停数
- 连板高度
- 首板数
- 炸板率（估算）

使用 akshare，每个指标独立 try/except，失败不阻塞其他指标。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


def _today_cn_str(fmt: str = "%Y%m%d") -> str:
    return datetime.now().strftime(fmt)


def fetch_market_sentiment() -> dict[str, Any]:
    """获取市场情绪指标。"""
    result = {
        "up_count": None,
        "down_count": None,
        "limit_up_count": None,
        "limit_down_count": None,
        "consecutive_height": None,
        "first_board_count": None,
        "broken_board_rate": None,
        "errors": [],
    }

    # 1. 涨跌家数
    try:
        import akshare as ak

        df = ak.stock_zh_a_spot_em()
        pct_col = "涨跌幅"
        if pct_col in df.columns:
            result["up_count"] = int((df[pct_col] > 0).sum())
            result["down_count"] = int((df[pct_col] < 0).sum())
    except Exception as e:
        result["errors"].append(f"涨跌家数: {e}")

    date_str = _today_cn_str()

    # 2. 涨停池
    try:
        import akshare as ak

        df = ak.stock_zt_pool_em(date=date_str)
        result["limit_up_count"] = len(df)
        if "连板数" in df.columns:
            result["consecutive_height"] = int(df["连板数"].max())
            result["first_board_count"] = int((df["连板数"] == 1).sum())
        if "炸板次数" in df.columns:
            total_broken = int(df["炸板次数"].sum())
            total = len(df)
            if total + total_broken > 0:
                result["broken_board_rate"] = round(total_broken / (total + total_broken), 3)
    except Exception as e:
        result["errors"].append(f"涨停池: {e}")

    # 3. 跌停池
    try:
        import akshare as ak

        df = ak.stock_zt_pool_dtgc_em(date=date_str)
        result["limit_down_count"] = len(df)
    except Exception as e:
        result["errors"].append(f"跌停池: {e}")

    return result
