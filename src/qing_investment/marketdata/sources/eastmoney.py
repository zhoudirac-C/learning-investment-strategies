"""东财源（第二档 + 独有数据专用；强制限流）。

覆盖：
- K线 ``push2his.eastmoney.com/api/qt/stock/kline/get``（klt=101/60/30；无原生 120min）
- 实时行情 ``push2.eastmoney.com/api/qt/ulist.np/get``

经验内嵌：
- secid 市场号：**沪=1，深/北=0**。绝不用 ``startswith('6')`` 判市场——
  会把 510300/588000/900901 全错判成深市返回 data:null（a-stock-data #46）
- 东财字段序：开,收,高,低（与腾讯"开收高低"不同！）
- 9/10 实测：本云环境 push2his 对云 IP 持续断连 → 每次调用 3 轮重试 ~12s，
  必须配熔断（router 层 capability 粒度）
- 无原生 120min（klt=120 非标准取值实测返回空）——router 层对 120min 直跳腾讯
"""

from __future__ import annotations

from qing_investment.marketdata import ratelimit
from qing_investment.marketdata.http import http_get_json
from qing_investment.marketdata.symbol import norm_ticker, prefix_for

SOURCE = "eastmoney"

_EM_HEADERS = {"Referer": "https://quote.eastmoney.com/"}


def em_secid(code: str, *, kind: str = "auto") -> str:
    """东财 secid：如 ``1.600519`` / ``0.300750`` / ``1.000001``(上证指数)。"""
    digits = norm_ticker(code)
    return f"{1 if prefix_for(digits, kind=kind) == 'sh' else 0}.{digits}"


def fetch_kline(code: str, klt: int, count: int, *,
                kind: str = "auto", secid: str | None = None) -> list[dict]:
    """东财 K线（101/60/30）。返回统一 bar shape，升序；空返回 []（软失败）。

    kind: 'index'/'stock'/'auto'，消歧 000001 类双义代码（router 统一传）。
    """
    if klt not in (101, 60, 30):
        raise ValueError(f"东财源不支持 klt={klt}（支持 101/60/30，120min 无原生请走腾讯）")
    secid = secid or em_secid(code, kind=kind)
    url = (
        "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        f"?secid={secid}"
        "&fields1=f1,f2,f3,f4,f5,f6"
        "&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
        f"&klt={klt}&fqt=1&end=20500101&lmt={count + 3}"
    )
    ratelimit.acquire(SOURCE)
    try:
        data = http_get_json(url, headers=_EM_HEADERS, timeout=30)
    except Exception:
        return []
    raw = data.get("data", {}).get("klines", []) or []
    bars = []
    for row in raw:
        parts = row.split(",")
        if len(parts) < 6:
            continue
        try:
            bars.append({
                "bar_time": parts[0],
                # 东财字段序：开,收,高,低（⚠️ 与腾讯不同）
                "open": float(parts[1]), "close": float(parts[2]),
                "high": float(parts[3]), "low": float(parts[4]),
                "volume": float(parts[5]),
                "amount": float(parts[6]) if len(parts) > 6 and parts[6] else 0.0,
            })
        except (ValueError, IndexError):
            continue
    bars.sort(key=lambda k: k["bar_time"])
    return bars[-count:] if len(bars) > count else bars


def fetch_quotes(codes: list[str], *, kind: str = "auto") -> list[dict]:
    """东财批量行情（push2 ulist.np，一次 ≤80 只）。返回统一 quote shape。"""
    from qing_investment.marketdata.sources.tencent import _digits  # 复用归一

    out: list[dict] = []
    for i in range(0, len(codes), 80):
        chunk = codes[i:i + 80]
        secids = [(em_secid(c, kind=kind), c.strip()) for c in chunk]
        url = (
            "https://push2.eastmoney.com/api/qt/ulist.np/get"
            "?fltt=2&fields=f12,f14,f2,f18,f15,f16,f3,f6"
            f"&secids={','.join(s for s, _ in secids)}"
        )
        ratelimit.acquire(SOURCE)
        try:
            data = http_get_json(url, headers=_EM_HEADERS, timeout=15)
        except Exception:
            continue
        rows = data.get("data", {}).get("diff", []) or []
        if isinstance(rows, dict):
            rows = list(rows.values())
        code_of = {s: c for s, c in secids}
        for r in rows:
            try:
                out.append({
                    "code": code_of.get(str(r.get("f12")), str(r.get("f12"))),
                    "name": r.get("f14"),
                    "price": float(r.get("f2") or 0),
                    "prev_close": float(r.get("f18") or 0),
                    "high": float(r.get("f15") or 0),
                    "low": float(r.get("f16") or 0),
                    "change_pct": float(r.get("f3") or 0),
                    "amount": float(r.get("f6") or 0),
                    "source": SOURCE,
                })
            except (ValueError, TypeError):
                continue
    return out
