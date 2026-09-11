"""腾讯财经源（首选源：不封 IP）。

端口：
- 日线 ``web.ifzq.gtimg.cn/appstock/app/fqkline/get``（qfq 前复权）
- 分钟线 ``ifzq.gtimg.cn/appstock/app/kline/mkline``（m30/m60/m120 原生）
- 实时行情 ``qt.gtimg.cn/q=``（GBK，~ 分隔）

经验内嵌（全部为本仓库 2026-09-10 实测 / a-stock-data 实证）：
- 必须用 ``ifzq.gtimg.cn``（无 ``web.`` 前缀）拉分钟线——带 web. 会 301
- ``m120`` 是原生 120min 接口（每日恰好 2 根，间隔 210 分钟=跨午休），
  486 根/年；东财无原生 120min
- 腾讯日线字段序：日期,开,收,高,低,量（**收在 2、高在 3**，与东财"开收高低"
  不同——字段序各厂商不同是 tdx-data-source-troubleshoot 高频误判之一）
- 分钟线字段序：时间,开,收,高,低,量
- web.ifzq 连续 5000+ 次返回空是**限流非封禁**，降速或换源即恢复
"""

from __future__ import annotations

from qing_investment.marketdata import ratelimit
from qing_investment.marketdata.http import http_get_json, http_get
from qing_investment.marketdata.symbol import prefix_for

SOURCE = "tencent"

_MIN_MAP = {1: "m1", 5: "m5", 15: "m15", 30: "m30", 60: "m60", 120: "m120"}


def tencent_symbol(code: str, *, kind: str = "auto") -> str:
    """'sh000001' 原样；'000001'(index)→'sh000001'；'600519'(stock)→'sh600519'。"""
    low = str(code).strip().lower()
    if low.startswith(("sh", "sz", "bj")) and len(low) >= 8:
        return low
    p = prefix_for(str(code).strip(), kind=kind)
    return f"{p}{_digits(code)}"


def _digits(code: str) -> str:
    from qing_investment.marketdata.symbol import norm_ticker
    return norm_ticker(code)


def fetch_kline(code: str, klt: int, count: int, *, kind: str = "auto") -> list[dict]:
    """腾讯 K线。klt: 101=日线, 30/60/120=分钟。返回统一 bar shape，升序。

    空返回 []（软失败语义，由 router 决定是否降级）。
    """
    sym = tencent_symbol(code, kind=kind)
    headers = {"Referer": "https://gu.qq.com/"}
    ratelimit.acquire(SOURCE)

    if klt in _MIN_MAP:
        period = _MIN_MAP[klt]
        url = (f"https://ifzq.gtimg.cn/appstock/app/kline/mkline"
               f"?param={sym},{period},,{count + 5}")
        try:
            payload = http_get_json(url, headers=headers)
        except Exception:
            return []
        raw = payload.get("data", {}).get(sym, {}).get(period, []) or []
        bars = []
        for parts in raw:
            if len(parts) < 6:
                continue
            try:
                t = str(parts[0])
                bar_time = (f"{t[0:4]}-{t[4:6]}-{t[6:8]} {t[8:10]}:{t[10:12]}"
                            if len(t) >= 12 else t)
                bars.append({
                    "bar_time": bar_time,
                    "open": float(parts[1]), "close": float(parts[2]),
                    "high": float(parts[3]), "low": float(parts[4]),
                    "volume": float(parts[5]), "amount": 0.0,
                })
            except (ValueError, IndexError):
                continue
        bars.sort(key=lambda k: k["bar_time"])
        return bars[-count:] if len(bars) > count else bars

    if klt == 101:
        url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
               f"?param={sym},day,,,{count + 3},qfq")
        try:
            payload = http_get_json(url, headers=headers)
        except Exception:
            return []
        node = payload.get("data", {}).get(sym, {})
        # ⚠️ 个股返回键为 qfqday（前复权），指数为 day——必须双键兼容
        # （2026-09-11 实测：只读 day 会让个股日线路径全空触发降级）
        raw = node.get("qfqday", []) or node.get("day", []) or []
        bars = []
        for parts in raw:
            if len(parts) < 6:
                continue
            try:
                bars.append({
                    "bar_time": parts[0],
                    "open": float(parts[1]), "close": float(parts[2]),
                    "high": float(parts[3]), "low": float(parts[4]),
                    "volume": float(parts[5]), "amount": 0.0,
                })
            except (ValueError, IndexError):
                continue
        bars.sort(key=lambda k: k["bar_time"])
        return bars[-count:] if len(bars) > count else bars

    raise ValueError(f"腾讯源不支持 klt={klt}（支持 1/5/15/30/60/120/101）")


def fetch_quotes(codes: list[str], *, kind: str = "auto") -> list[dict]:
    """腾讯批量实时行情（qt.gtimg.cn，GBK）。

    返回统一 quote shape：``{code,name,price,prev_close,open,high,low,
    change_pct,amount,pe_ttm,pb,mcap,source}``。失败的代码静默跳过。
    """
    # 前缀路由：5x 沪 ETF / 000300 沪指数不能落 sz（会返回空或错票，a-stock-data #46）
    SH_INDEX = {"000300", "000905", "000016", "000688", "000852", "000010", "000985"}
    prefixed, key_of = [], {}
    for c in codes:
        low = c.strip().lower()
        digits = _digits(c)
        if low.startswith(("sh", "sz", "bj")) and len(low) >= 8:
            p = low[:2]
        elif kind == "index" or digits.startswith("399") or digits in SH_INDEX \
                or digits.startswith("880"):
            p = prefix_for(digits, kind="index")
        else:
            p = prefix_for(digits, kind="stock")
        sym = f"{p}{digits}"
        prefixed.append(sym)
        key_of[sym] = c.strip()

    url = "https://qt.gtimg.cn/q=" + ",".join(prefixed)
    ratelimit.acquire(SOURCE)
    text = http_get(url, headers={"Referer": "https://gu.qq.com/"}, encoding="gbk")

    quotes = []
    for line in text.strip().split(";"):
        if "=" not in line or '"' not in line:
            continue
        key = line.split("=")[0].split("_")[-1]
        vals = line.split('"')[1].split("~")
        if len(vals) < 53:
            continue
        try:
            quotes.append({
                "code": key_of.get(key, key[2:]),
                "name": vals[1],
                "price": float(vals[3] or 0),
                "prev_close": float(vals[4] or 0),
                "open": float(vals[5] or 0),
                "high": float(vals[33] or 0),
                "low": float(vals[34] or 0),
                "change_pct": float(vals[32] or 0),
                # [35] 是三段拼接（'价格/成交量/成交额'，2026-09-11 实测分隔符为 '/'，
                # a-stock-data 文档写 \x01 系另一版式）——不直接解析；
                # 成交额(万元)取 [37]，×1e4 归一到元；成交量(手)取 [36]
                "amount": float(vals[37] or 0) * 1e4,
                "volume": float(vals[36] or 0),
                "pe_ttm": float(vals[39]) if vals[39] else None,
                "pb": float(vals[46]) if vals[46] else None,
                "mcap": float(vals[45]) if vals[45] else None,  # 总市值(亿)
                "source": SOURCE,
            })
        except (ValueError, IndexError):
            continue
    return quotes
