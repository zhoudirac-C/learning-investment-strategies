from __future__ import annotations

"""个股和指数实时数据获取（基于腾讯gtimg接口）。"""

import urllib.request
import urllib.error


def fetch_stock_quotes(codes: list[str]) -> list[dict]:
    """获取个股/指数实时行情。
    
    Args:
        codes: 股票代码列表，如 ["sh000001", "sz399006", "sz000066"]
        
    Returns:
        行情数据列表，每条包含: code, name, price, open, high, low, prev_close, pct_change, volume, amount
    """
    if not codes:
        return []
    
    url = f"https://qt.gtimg.cn/q={','.join(codes)}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    }
    
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read().decode("gbk", errors="ignore")
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
        
        # 腾讯格式解析
        # parts[0]: 市场标志 1=sh, 0=sz
        # parts[1]: 名称
        # parts[2]: 代码
        # parts[3]: 当前价
        # parts[4]: 昨收
        # parts[5]: 开盘
        # parts[6]: 成交量(手)
        # parts[7]: 外盘
        # parts[8]: 内盘
        # parts[9-18]: 买1-5 价格/数量
        # parts[19-28]: 卖1-5 价格/数量
        # parts[29]: 最近逐笔成交
        # parts[30]: 时间
        # parts[31]: 涨跌
        # parts[32]: 涨跌幅
        # parts[33]: 最高
        # parts[34]: 最低
        # parts[35]: 成交量(股)
        # parts[36]: 成交额(元)
        # parts[37]: 换手率
        # parts[38]: 市盈率
        # ...
        
        try:
            price = float(parts[3]) if parts[3] else None
            prev_close = float(parts[4]) if parts[4] else None
            open_p = float(parts[5]) if parts[5] else None
            high = float(parts[33]) if parts[33] else None
            low = float(parts[34]) if parts[34] else None
            volume = float(parts[36]) if parts[36] else None  # 股数
            amount = float(parts[37]) if parts[37] else None  # 成交额
            pct_change = float(parts[32]) if parts[32] else None
            
            # 处理指数（指数没有换手率等字段）
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
            })
        except (ValueError, IndexError):
            continue
    
    return quotes


def fetch_index_quotes() -> list[dict]:
    """获取主要指数行情。"""
    return fetch_stock_quotes(["sh000001", "sz399001", "sz399006", "sh000688"])


def fetch_single_stock(code: str) -> dict | None:
    """获取单只股票行情。
    
    Args:
        code: 股票代码，如 "000066" 或 "sh000066"
    """
    # 标准化代码
    if not code.startswith(("sh", "sz")):
        if code.startswith("6"):
            code = f"sh{code}"
        else:
            code = f"sz{code}"
    
    quotes = fetch_stock_quotes([code])
    return quotes[0] if quotes else None
