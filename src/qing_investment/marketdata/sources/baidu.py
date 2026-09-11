"""百度股市通 K线（自带 MA5/MA10/MA20，V3.0 独有能力）。

主要用于七轨布林/均线计算的快速交叉校验——返回时直接带均价，
无需本地重算。注意：这是参考校验源，不进降级链（URL 结构变更频繁，
2025 年曾多次换签名）。
"""

from __future__ import annotations

from qing_investment.marketdata.errors import SourceUnavailable
from qing_investment.marketdata.http import http_get_json
from qing_investment.marketdata.symbol import norm_ticker

SOURCE = "baidu"


def baidu_kline_with_ma(code: str, start_time: str = "") -> list[dict]:
    """百度股市通日 K线，自带 ma5/ma10/ma20。返回统一 bar shape + ma 字段。

    ``start_time`` 形如 ``2026-01-01``；响应结构变更抛 SourceUnavailable。
    """
    digits = norm_ticker(code)
    url = "https://finance.pae.baidu.com/selfselect/getstockquotation"
    params = (
        f"?all=1&isIndex=false&isBk=false&isBlock=false&isFutures=false"
        f"&isStock=true&newFormat=1&group=quotation_kline_ab&finClientType=pc"
        f"&code={digits}&start_time={start_time}&ktype=1"
    )
    try:
        d = http_get_json(
            url + params,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/vnd.finance-web.v1+json",
                "Origin": "https://gushitong.baidu.com",
                "Referer": "https://gushitong.baidu.com/",
            },
            timeout=10,
        )
    except Exception as e:
        raise SourceUnavailable(f"baidu kline failed: {type(e).__name__}: {e}") from e
    md = (d.get("Result") or {}).get("newMarketData") or {}
    keys = md.get("keys", [])
    raw_rows = [r for r in str(md.get("marketData", "")).split(";") if r]
    if not keys or not raw_rows:
        raise SourceUnavailable(f"baidu kline 结构变更或无数据: keys={keys[:3]}")
    idx = {k: i for i, k in enumerate(keys)}
    need = ["time", "open", "high", "low", "close", "volume", "amount"]
    if any(k not in idx for k in need):
        raise SourceUnavailable(f"baidu kline 缺字段: {[k for k in need if k not in idx]}")
    bars = []
    for row in raw_rows:
        parts = row.split(",")
        if len(parts) < len(keys):
            continue
        try:
            bar: dict = {"bar_time": parts[idx["time"]][:10]}
            for k in ("open", "high", "low", "close", "volume", "amount"):
                v = parts[idx[k]]
                bar[k] = float(v) if v not in ("", "-", "--") else 0.0
            for ma in ("ma5avgprice", "ma10avgprice", "ma20avgprice"):
                if ma in idx and parts[idx[ma]]:
                    bar[ma] = float(parts[idx[ma]])
            bars.append(bar)
        except (ValueError, IndexError):
            continue
    bars.sort(key=lambda b: b["bar_time"])
    return bars
