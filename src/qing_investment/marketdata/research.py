"""东财研报层：个股/行业研报列表 + 一致预期（reportapi，公开 A 级接口）。

⚠️ reportapi 只认纯 6 位数字：传 "SH600519" 返回 hits=0，
看似「无研报覆盖」实为格式未归一——必须先过 norm_ticker。
走 eastmoney 限流器（reportapi 与 push2 同属东财风控面）。
"""

from __future__ import annotations

from qing_investment.marketdata import ratelimit
from qing_investment.marketdata.errors import SourceUnavailable
from qing_investment.marketdata.http import http_get_json
from qing_investment.marketdata.symbol import norm_ticker

REPORT_API = "https://reportapi.eastmoney.com/report/list"
_HEADERS = {"Referer": "https://data.eastmoney.com/"}


def eastmoney_reports(code: str, max_pages: int = 2) -> list[dict]:
    """个股研报列表（标题/机构/评级/EPS 预测）。空列表=确无覆盖（格式错已在上游抛）。"""
    digits = norm_ticker(code)  # stock_only 场景由调用方保证（指数无研报）
    all_records: list[dict] = []
    for page in range(1, max_pages + 1):
        params = (
            f"?industryCode=*&pageSize=100&industry=*&rating=*&ratingChange=*"
            f"&beginTime=2000-01-01&endTime=2030-01-01&pageNo={page}"
            f"&fields=&qType=0&orgCode=&code={digits}&rcode="
            f"&p={page}&pageNum={page}&pageNumber={page}"
        )
        ratelimit.acquire("eastmoney")
        try:
            d = http_get_json(REPORT_API + params, headers=_HEADERS, timeout=30)
        except Exception as e:
            raise SourceUnavailable(f"reportapi request failed: {type(e).__name__}: {e}") from e
        rows = d.get("data") or []
        if not rows:
            break
        all_records.extend(rows)
        if page >= (d.get("TotalPage", 1) or 1):
            break
    return all_records


def ths_eps_forecast(code: str) -> list[dict]:
    """同花顺机构一致预期 EPS（直连 basic.10jqka.com.cn，零 key）。"""
    digits = norm_ticker(code)
    url = (f"https://basic.10jqka.com.cn/api/stock/forecast/{digits}/"
           f"?type=1&code={digits}")
    ratelimit.acquire("ths")
    try:
        d = http_get_json(
            url,
            headers={"Referer": f"https://basic.10jqka.com.cn/{digits}/"},
            timeout=10,
        )
    except Exception as e:
        raise SourceUnavailable(f"ths eps forecast failed: {type(e).__name__}: {e}") from e
    data = d.get("data") or {}
    return data.get("forecast_list") or data.get("list") or []
