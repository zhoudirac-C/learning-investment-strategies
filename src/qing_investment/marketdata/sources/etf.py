"""ETF 数据源（akshare 同花顺接口）。

覆盖：
- 全市场 ETF 实时行情（fund_etf_spot_ths）
- 返回统一 quote shape：{code, name, price, change_pct, amount, volume, source}

注意：
- akshare fund_etf_spot_ths 返回净值数据（非实时价格），字段为“增长率”即涨跌幅
- 基金代码格式：158066 (无前缀)，需补全为 sh/sz 前缀
- 该接口返回约 1700+ 只 ETF/LOF，覆盖全市场
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

SOURCE = "etf_ths"


def _normalize_etf_code(code: str) -> str:
    """ETF 代码归一化：'158066' -> 'sh158066' 或 'sz158066'。

    规则：
    - 5 开头 -> sh (上交所 ETF)
    - 1/15/16/18 开头 -> sz (深交所 ETF/LOF)
    - 其他按首位判断
    """
    c = str(code).strip()
    if c.startswith(("sh", "sz", "bj")) and len(c) >= 8:
        return c.lower()
    # 纯数字代码
    if c.startswith("5"):  # 51xxxx, 58xxxx 等上交所 ETF
        return f"sh{c}"
    if c.startswith(("15", "16", "18", "1")):  # 15xxxx/16xxxx/18xxxx/1xxxx 深交所 ETF/LOF
        return f"sz{c}"
    # 兜底：按首位判断
    if c[0] in "5689":
        return f"sh{c}"
    return f"sz{c}"


def fetch_all_etf_quotes() -> list[dict[str, Any]]:
    """获取全市场 ETF 实时行情（akshare fund_etf_spot_ths）。

    返回统一 quote shape 列表，每项包含：
    - code: 归一化代码 (sh158066)
    - name: 基金名称
    - price: 最新净值（当前-单位净值）
    - change_pct: 涨跌幅 (增长率, %)
    - amount: 成交额（该接口无，置 0）
    - volume: 成交量（该接口无，置 0）
    - prev_close: 前一日净值
    - source: "etf_ths"

    失败返回 []，由上层 router 处理降级。
    """
    try:
        import akshare as ak
    except ImportError:
        logger.warning("[etf] akshare not installed")
        return []

    try:
        df = ak.fund_etf_spot_ths()
        if df is None or df.empty:
            logger.warning("[etf] fund_etf_spot_ths returned empty")
            return []

        # 字段映射：['序号', '基金代码', '基金名称', '当前-单位净值', '当前-累计净值',
        #         '前一日-单位净值', '前一日-累计净值', '增长值', '增长率', '赎回状态',
        #         '申购状态', '最新-交易日', '最新-单位净值', '最新-累计净值', '基金类型', '查询日期']
        quotes = []
        for _, row in df.iterrows():
            try:
                raw_code = str(row.get("基金代码", "")).strip()
                if not raw_code:
                    continue
                code = _normalize_etf_code(raw_code)
                name = str(row.get("基金名称", "")).strip()

                # 价格用当前单位净值
                price = row.get("当前-单位净值")
                prev_close = row.get("前一日-单位净值")
                change_pct = row.get("增长率")

                # 转 float
                try:
                    price_f = float(price) if price is not None else 0.0
                except (ValueError, TypeError):
                    price_f = 0.0
                # prev_close 可能为 NaN，用增长率反推
                try:
                    prev_f = float(prev_close) if prev_close is not None else 0.0
                except (ValueError, TypeError):
                    prev_f = 0.0
                import math
                if (prev_f == 0.0 or math.isnan(prev_f)) and price_f > 0:
                    # 用增长率反推：prev = current / (1 + pct/100)
                    try:
                        pct_for_prev = float(change_pct) if change_pct is not None else 0.0
                        if pct_for_prev != 0:
                            prev_f = round(price_f / (1 + pct_for_prev / 100), 4)
                    except (ValueError, TypeError, ZeroDivisionError):
                        pass
                try:
                    pct_f = float(change_pct) if change_pct is not None else 0.0
                except (ValueError, TypeError):
                    pct_f = 0.0

                quotes.append({
                    "code": code,
                    "name": name,
                    "price": price_f,
                    "prev_close": prev_f,
                    "change_pct": pct_f,
                    "amount": 0.0,
                    "volume": 0.0,
                    "open": price_f,  # 无开盘价，用净值代替
                    "high": price_f,
                    "low": price_f,
                    "source": SOURCE,
                })
            except Exception as e:
                logger.debug("[etf] parse row failed: %s", e)
                continue

        logger.info("[etf] fetched %d ETF quotes from akshare fund_etf_spot_ths", len(quotes))
        return quotes

    except Exception as e:
        logger.warning("[etf] fetch_all_etf_quotes failed: %s", e)
        return []


def fetch_etf_up_ratio() -> float | None:
    """计算全市场 ETF 上涨家数占比。

    返回：上涨家数 / 总家数 (0.0-1.0)，失败返回 None。
    """
    quotes = fetch_all_etf_quotes()
    if not quotes:
        return None

    total = len(quotes)
    up = sum(1 for q in quotes if q.get("change_pct", 0) > 0)
    return round(up / total, 4) if total > 0 else None


def fetch_etf_all_up() -> bool | None:
    """判断全市场 ETF 是否全部上涨（>0）。

    返回：True(全部上涨) / False(有下跌) / None(数据不可用)
    """
    quotes = fetch_all_etf_quotes()
    if not quotes:
        return None

    for q in quotes:
        if q.get("change_pct", 0) <= 0:
            return False
    return True