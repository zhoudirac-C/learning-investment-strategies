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
    # 优先东财（字段全），失败则回退到新浪/通用 spot（已验证在东财连接重置时仍可用）
    up_down_errors = []
    for provider, fetch_fn in (
        ("eastmoney", lambda: ak.stock_zh_a_spot_em()),
        ("sina", lambda: ak.stock_zh_a_spot()),
    ):
        try:
            import akshare as ak

            df = fetch_fn()
            pct_col = "涨跌幅"
            if pct_col in df.columns and not df.empty:
                result["up_count"] = int((df[pct_col] > 0).sum())
                result["down_count"] = int((df[pct_col] < 0).sum())
                result["up_down_provider"] = provider
                logger.info("[market_sentiment] 涨跌家数来自 %s: up=%s down=%s", provider, result["up_count"], result["down_count"])
                break
        except Exception as e:
            up_down_errors.append(f"{provider}: {e}")
    else:
        result["errors"].append(f"涨跌家数: {'; '.join(up_down_errors)}")

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
