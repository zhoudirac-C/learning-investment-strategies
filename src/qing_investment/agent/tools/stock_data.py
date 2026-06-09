from __future__ import annotations

"""个股和指数实时数据获取（支持多数据源降级）。"""

import json
import urllib.request
import urllib.error


# ── 通用HTTP请求工具 ──
def _http_get(url: str, timeout: float = 10.0, encoding: str = "utf-8", headers: dict | None = None) -> str:
    """发送GET请求并返回文本内容。"""
    default_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    }
    if headers:
        default_headers.update(headers)
    
    req = urllib.request.Request(url, headers=default_headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode(encoding, errors="ignore")


def _normalize_code(code: str) -> tuple[str, str]:
    """标准化股票代码，返回 (pure_code, full_code)。"""
    pure_code = code.replace("sh", "").replace("sz", "").replace(".", "")
    market = "sh" if pure_code.startswith("6") else "sz"
    full_code = f"{market}{pure_code}"
    return pure_code, full_code


# ── 实时行情 ──
def fetch_stock_quotes_tencent(codes: list[str]) -> list[dict]:
    """腾讯实时行情。"""
    if not codes:
        return []
    
    url = f"https://qt.gtimg.cn/q={','.join(codes)}"
    try:
        data = _http_get(url, encoding="gbk")
    except Exception:
        return []
    
    quotes = []
    for line in data.strip().split(";"):
        line = line.strip()
        if not line or "=" not in line:
            continue
        
        var, val = line.split("=", 1)
        val = val.strip('"')
        parts = val.split("~")
        if len(parts) < 35:
            continue
        
        try:
            price = float(parts[3]) if parts[3] else None
            prev_close = float(parts[4]) if parts[4] else None
            open_p = float(parts[5]) if parts[5] else None
            high = float(parts[33]) if parts[33] else None
            low = float(parts[34]) if parts[34] else None
            volume = float(parts[36]) if parts[36] else None
            amount = float(parts[37]) if parts[37] else None
            pct_change = float(parts[32]) if parts[32] else None
            is_index = parts[2] in ("000001", "399001", "399006", "000688")
            
            quotes.append({
                "code": parts[2],
                "name": parts[1],
                "price": price,
                "open": open_p,
                "high": high,
                "low": low,
                "prev_close": prev_close,
                "pct_change": pct_change,
                "volume": volume,
                "amount": amount,
                "is_index": is_index,
                "source": "tencent_gtimg",
            })
        except (ValueError, IndexError):
            continue
    
    return quotes


def fetch_stock_quotes_eastmoney(codes: list[str]) -> list[dict]:
    """东方财富实时行情（降级用）。"""
    if not codes:
        return []
    
    # 转换代码格式
    secids = []
    for code in codes:
        pure, full = _normalize_code(code)
        market_num = "1" if full.startswith("sh") else "0"
        secids.append(f"{market_num}.{pure}")
    
    url = (
        "https://push2.eastmoney.com/api/qt/ulist.np/get"
        "?fltt=2&invt=2"
        "&fields=f12,f13,f14,f2,f3,f4,f5,f6,f15,f16,f17,f18"
        f"&secids={','.join(secids)}"
    )
    headers = {"Referer": "https://quote.eastmoney.com/"}
    
    try:
        data = json.loads(_http_get(url, headers=headers))
    except Exception:
        return []
    
    quotes = []
    diff = data.get("data", {}).get("diff", {})
    for _, q in diff.items():
        try:
            code = q.get("f12", "")
            name = q.get("f14", "")
            price = float(q.get("f2", 0)) if q.get("f2") else None
            pct_change = float(q.get("f3", 0)) if q.get("f3") else None
            open_p = float(q.get("f17", 0)) if q.get("f17") else None
            high = float(q.get("f15", 0)) if q.get("f15") else None
            low = float(q.get("f16", 0)) if q.get("f16") else None
            prev_close = float(q.get("f18", 0)) if q.get("f18") else None
            volume = float(q.get("f5", 0)) if q.get("f5") else None
            amount = float(q.get("f6", 0)) if q.get("f6") else None
            
            is_index = code in ("000001", "399001", "399006", "000688")
            
            quotes.append({
                "code": code,
                "name": name,
                "price": price,
                "open": open_p,
                "high": high,
                "low": low,
                "prev_close": prev_close,
                "pct_change": pct_change,
                "volume": volume,
                "amount": amount,
                "is_index": is_index,
                "source": "eastmoney_push2",
            })
        except (ValueError, TypeError):
            continue
    
    return quotes


def fetch_stock_quotes(codes: list[str]) -> list[dict]:
    """获取个股/指数实时行情（腾讯优先，失败降级东方财富）。"""
    quotes = fetch_stock_quotes_tencent(codes)
    if len(quotes) >= len(codes):
        return quotes
    
    # 腾讯失败，尝试东方财富
    em_quotes = fetch_stock_quotes_eastmoney(codes)
    if em_quotes:
        return em_quotes
    
    return quotes


def fetch_index_quotes() -> list[dict]:
    """获取主要指数行情。"""
    return fetch_stock_quotes(["sh000001", "sz399001", "sz399006", "sh000688", "sh000985"])


def fetch_single_stock(code: str) -> dict | None:
    """获取单只股票行情。"""
    pure_code, full_code = _normalize_code(code)
    quotes = fetch_stock_quotes([full_code])
    return quotes[0] if quotes else None


# ── 历史K线 ──
def fetch_stock_kline_tencent(code: str, days: int = 90) -> list[dict]:
    """腾讯历史K线。"""
    pure_code, full_code = _normalize_code(code)
    
    from datetime import datetime, timedelta
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days + 15)
    
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")
    
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={full_code},day,{start_str},{end_str},{days + 15},qfq"
    
    try:
        data = json.loads(_http_get(url))
    except Exception:
        return []
    
    klines = data.get("data", {}).get(full_code, {}).get("qfqday", [])
    if not klines:
        return []
    
    result = []
    prev_close = None
    for k in klines:
        try:
            date = k[0]
            open_p = float(k[1])
            close = float(k[2])
            low = float(k[3])
            high = float(k[4])
            volume = float(k[5])
            
            pct_change = ((close / prev_close) - 1) * 100 if prev_close else 0
            prev_close = close
            
            result.append({
                "date": date,
                "open": open_p,
                "close": close,
                "high": high,
                "low": low,
                "volume": volume,
                "pct_change": round(pct_change, 2),
                "source": "tencent_kline",
            })
        except (ValueError, IndexError):
            continue
    
    return result[-days:] if len(result) > days else result


def fetch_stock_kline_eastmoney(code: str, days: int = 90) -> list[dict]:
    """东方财富历史K线（降级用）。"""
    pure_code, full_code = _normalize_code(code)
    market_num = "1" if full_code.startswith("sh") else "0"
    
    # 东方财富K线接口
    url = (
        "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        f"?secid={market_num}.{pure_code}"
        "&fields1=f1,f2,f3,f4,f5,f6"
        "&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
        f"&klt=101&fqt=1&end=20500101&lmt={days + 15}"
    )
    headers = {"Referer": "https://quote.eastmoney.com/"}
    
    try:
        data = json.loads(_http_get(url, headers=headers))
    except Exception:
        return []
    
    raw_klines = data.get("data", {}).get("klines", [])
    if not raw_klines:
        return []
    
    result = []
    prev_close = None
    for row in raw_klines:
        # 格式: "2026-06-05,17.74,17.05,16.98,17.74,1707095"
        parts = row.split(",")
        if len(parts) < 6:
            continue
        try:
            date = parts[0]
            open_p = float(parts[1])
            close = float(parts[2])
            low = float(parts[3])
            high = float(parts[4])
            volume = float(parts[5])
            
            pct_change = ((close / prev_close) - 1) * 100 if prev_close else 0
            prev_close = close
            
            result.append({
                "date": date,
                "open": open_p,
                "close": close,
                "high": high,
                "low": low,
                "volume": volume,
                "pct_change": round(pct_change, 2),
                "source": "eastmoney_kline",
            })
        except (ValueError, IndexError):
            continue
    
    return result[-days:] if len(result) > days else result


def fetch_stock_kline(code: str, days: int = 90) -> list[dict]:
    """获取个股历史日K线（腾讯优先，失败降级东方财富）。"""
    klines = fetch_stock_kline_tencent(code, days)
    if klines:
        return klines
    return fetch_stock_kline_eastmoney(code, days)


# ── 当日分时 ──
def fetch_stock_intraday_tencent(code: str) -> list[dict]:
    """腾讯当日分时。"""
    pure_code, full_code = _normalize_code(code)
    url = f"https://web.ifzq.gtimg.cn/appstock/app/minute/query?code={full_code}"
    
    try:
        data = json.loads(_http_get(url))
    except Exception:
        return []
    
    raw = data.get("data", {}).get(full_code, {}).get("data", {}).get("data", [])
    if not raw:
        return []
    
    result = []
    for row in raw:
        parts = row.split()
        if len(parts) < 4:
            continue
        try:
            result.append({
                "time": parts[0],
                "price": float(parts[1]),
                "volume": float(parts[2]),
                "amount": float(parts[3]),
                "source": "tencent_intraday",
            })
        except (ValueError, IndexError):
            continue
    
    return result


def fetch_stock_intraday_eastmoney(code: str) -> list[dict]:
    """东方财富当日分时（降级用）。"""
    pure_code, full_code = _normalize_code(code)
    market_num = "1" if full_code.startswith("sh") else "0"
    
    url = (
        "https://push2.eastmoney.com/api/qt/stock/trends2/get"
        f"?secid={market_num}.{pure_code}"
        "&fields1=f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13"
        "&fields2=f51,f52,f53,f54,f55,f56,f57,f58"
    )
    headers = {"Referer": "https://quote.eastmoney.com/"}
    
    try:
        data = json.loads(_http_get(url, headers=headers))
    except Exception:
        return []
    
    trends = data.get("data", {}).get("trends", [])
    if not trends:
        return []
    
    result = []
    for row in trends:
        # 格式: "2026-06-05 09:15,17.95,17.95,17.95,17.95,0"
        parts = row.split(",")
        if len(parts) < 6:
            continue
        try:
            dt = parts[0]
            time_part = dt.split(" ")[1] if " " in dt else dt
            result.append({
                "time": time_part.replace(":", ""),
                "price": float(parts[2]),
                "volume": float(parts[5]),
                "amount": 0.0,  # 东财接口不直接提供
                "source": "eastmoney_intraday",
            })
        except (ValueError, IndexError):
            continue
    
    return result


def fetch_stock_intraday(code: str) -> list[dict]:
    """获取个股当日分时（腾讯优先，失败降级东方财富）。"""
    minutes = fetch_stock_intraday_tencent(code)
    if minutes:
        return minutes
    return fetch_stock_intraday_eastmoney(code)


# ── 格式化输出 ──
def format_kline_for_prompt(klines: list[dict]) -> str:
    """将K线数据格式化为prompt文本。"""
    if not klines:
        return "暂无历史K线数据"
    
    source = klines[0].get("source", "unknown")
    lines = [f"日期        开盘    收盘    最高    最低    成交量(万手)  涨跌%  [来源:{source}]"]
    lines.append("-" * 70)
    
    for k in klines:
        lines.append(
            f"{k['date']}  {k['open']:6.2f}  {k['close']:6.2f}  {k['high']:6.2f}  {k['low']:6.2f}  "
            f"{k['volume']/10000:8.1f}      {k['pct_change']:+6.2f}%"
        )
    
    if len(klines) >= 5:
        closes = [k["close"] for k in klines]
        highs = [k["high"] for k in klines]
        lows = [k["low"] for k in klines]
        volumes = [k["volume"] for k in klines]
        
        lines.append("-" * 70)
        lines.append(f"统计: 区间高点={max(highs):.2f} 区间低点={min(lows):.2f} "
                    f"区间振幅={((max(highs)/min(lows))-1)*100:.1f}%")
        lines.append(f"      最新价={closes[-1]:.2f} 距高点回撤={(1-closes[-1]/max(highs))*100:.1f}% "
                    f"5日均量={sum(volumes[-5:])/5/10000:.1f}万手")
    
    return "\n".join(lines)


def format_intraday_for_prompt(minutes: list[dict], prev_close: float | None = None) -> str:
    """将分时数据格式化为prompt文本。"""
    if not minutes:
        return "暂无分时数据"
    
    source = minutes[0].get("source", "unknown")
    lines = [f"时间    价格    成交量(手)  成交额(万)  [来源:{source}]"]
    lines.append("-" * 55)
    
    key_indices = [0]
    for i in range(30, len(minutes), 30):
        key_indices.append(i)
    if len(minutes) - 1 not in key_indices:
        key_indices.append(len(minutes) - 1)
    
    for idx in key_indices:
        m = minutes[idx]
        lines.append(
            f"{m['time']}  {m['price']:6.2f}  {m['volume']:10.0f}  {m['amount']/10000:8.1f}"
        )
    
    prices = [m["price"] for m in minutes]
    volumes = [m["volume"] for m in minutes]
    total_amount = sum(m["amount"] for m in minutes)
    
    lines.append("-" * 55)
    lines.append(f"分时统计: 最高={max(prices):.2f} 最低={min(prices):.2f} "
                f"开盘={minutes[0]['price']:.2f} 收盘={minutes[-1]['price']:.2f}")
    lines.append(f"          总成交量={sum(volumes):.0f}手 总成交额={total_amount/10000:.1f}万")
    
    if prev_close:
        pct = ((minutes[-1]["price"] / prev_close) - 1) * 100
        lines.append(f"          相对昨收: {pct:+.2f}%")
    
    return "\n".join(lines)
