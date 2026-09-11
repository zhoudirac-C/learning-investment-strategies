from __future__ import annotations

"""个股和指数实时数据获取（支持多数据源降级）。"""

def _normalize_code(code: str) -> tuple[str, str]:
    """标准化股票代码，返回 (pure_code, full_code)。"""
    code = code.strip().lower()
    # 先去掉 .sz / .sh 后缀（如果有）
    if code.endswith(".sz"):
        code = code[:-3]
    elif code.endswith(".sh"):
        code = code[:-3]
    pure_code = code.replace("sh", "").replace("sz", "")
    market = "sh" if pure_code.startswith("6") else "sz"
    full_code = f"{market}{pure_code}"
    return pure_code, full_code


# ── 实时行情 ──
# ---------------------------------------------------------------------------
# 数据抓取层已收口到 qing_investment.marketdata（2026-09-11 统一数据源层）。
# 降级链由 router 统一提供：腾讯 → 东财 → TDX → 新浪（每源限流+熔断）。
# 下方薄适配层保持 legacy 返回 shape（agent prompt / limit_pool /
# pre_fetch_klines 等下游零改动），字段差异在适配层归一。
# ⚠️ 修复存量 bug：原 fetch_stock_kline_eastmoney 把东财 high/low 解析反了
#    （东财字段序为 开,收,高,低）。
# ---------------------------------------------------------------------------
from qing_investment.marketdata import router as _md_router
from qing_investment.marketdata.symbol import norm_ticker, prefix_for


def _normalize_code(code: str) -> tuple[str, str]:
    """标准化代码 → (pure_code, full_code)。

    迁移自旧实现：号段判定从 startswith('6') 修正为号段规则
    （'6' 判沪会把 510300/588000/900901 错判成深市）。
    显式前缀优先保留（sh000932 必须是 sh，不能按 000 段推断）。
    """
    raw = str(code).strip()
    low = raw.lower()
    m = __import__("re").match(r"^(sh|sz|bj)", low)
    if m:
        return norm_ticker(low), f"{m.group(1)}{norm_ticker(low)}"
    if ".sh" in low or ".sz" in low:
        low = low.split(".")[0]
        return low, f"{prefix_for(low)}{low}"
    pure = norm_ticker(low)
    return pure, f"{prefix_for(pure)}{pure}"


_LEGACY_INDEX_CODES = {"000001", "399001", "399006", "000688", "000300", "000985", "000932"}


def fetch_stock_quotes(codes: list[str]) -> list[dict]:
    """获取个股/指数实时行情（router 链：腾讯→东财→TDX→新浪）。

    返回 legacy shape：{code,name,price,open,high,low,prev_close,
    pct_change,volume,amount,is_index,source}。空输入返 []；
    全源失败返 []（调用方按空处理——与旧行为一致）。
    """
    if not codes:
        return []
    r = _md_router.get_quotes(codes)
    out = []
    for q in r.get("quotes", []):
        raw_code = str(q.get("code", ""))
        # 归一为纯 6 位（对齐旧行为：腾讯 parts[2] 恒为纯码；
        # 显式前缀入参 sh000001 旧实现也返回 000001）
        try:
            code = norm_ticker(raw_code)
        except ValueError:
            code = raw_code
        out.append({
            "code": code,
            "name": q.get("name"),
            "price": q.get("price"),
            "open": q.get("open"),
            "high": q.get("high"),
            "low": q.get("low"),
            "prev_close": q.get("prev_close"),
            "pct_change": q.get("change_pct") if q.get("change_pct") is not None
                          else q.get("pct_change"),
            "volume": q.get("volume"),
            "amount": q.get("amount"),
            "is_index": code in _LEGACY_INDEX_CODES,
            "source": q.get("source"),
        })
    if r.get("errors"):
        print(f"[stock_data] quotes errors: {r['errors']}")
    return out


def fetch_index_quotes() -> list[dict]:
    """获取主要指数行情。"""
    return fetch_stock_quotes(["sh000001", "sz399001", "sz399006",
                               "sh000688", "sh000985", "sh000932"])


def fetch_single_stock(code: str) -> dict | None:
    """获取单只股票行情。"""
    quotes = fetch_stock_quotes([code])
    return quotes[0] if quotes else None


def _legacy_kline_shape(bars: list[dict], source: str) -> list[dict]:
    """router bar shape → legacy kline shape（date/pct_change/source）。"""
    out = []
    prev_close = None
    for b in bars:
        close = b.get("close")
        pct = ((close / prev_close) - 1) * 100 if (prev_close and close) else 0
        prev_close = close
        out.append({
            "date": b.get("bar_time"),
            "open": b.get("open"),
            "close": close,
            "high": b.get("high"),
            "low": b.get("low"),
            "volume": b.get("volume"),
            "amount": b.get("amount"),
            "pct_change": round(pct, 2),
            "source": source,
        })
    return out


def fetch_stock_kline(code: str, days: int = 90, force_refresh: bool = False) -> list[dict]:
    """获取个股历史日K线。

    优先级：
    1. 查本地 SQLite 缓存（开盘前 pre_fetch 已预拉取）
    2. 本地 miss 或不足 → marketdata.router（腾讯优先，降级东财/TDX）
    3. API 返回后写入 SQLite 缓存（供下次使用）

    Args:
        force_refresh: True 时跳过本地缓存，强制从 API 拉取（pre_fetch 用）。
    """
    # 1. 优先查本地 SQLite
    if not force_refresh:
        try:
            from qing_investment.kline_cache import get_klines
            local = get_klines(code, days=days)
            if local and len(local) >= max(1, days * 0.8):
                return local
        except Exception:
            pass  # 本地读取失败，继续调 API

    # 2. router 链（腾讯→东财→TDX）
    try:
        bars, source = _md_router.get_kline(code, 101, min(days, 800), kind="stock")
        klines = _legacy_kline_shape(bars, f"{source}_kline")
    except Exception as e:
        print(f"[stock_data] kline {code} 全源失败: {str(e)[:100]}")
        klines = []

    # 3. 写入本地缓存（失败不阻塞主流程）
    if klines:
        try:
            from qing_investment.kline_cache import save_klines
            save_klines(code, klines)
        except Exception:
            pass

    return klines or []


def fetch_stock_kline_tencent(code: str, days: int = 90) -> list[dict]:
    """Legacy 别名（pre_fetch_klines 仍在用）：强制走腾讯档。"""
    try:
        bars, source = _md_router.get_kline(code, 101, min(days, 800),
                                            kind="stock", sources=["tencent"])
    except Exception as e:
        print(f"[stock_data] tencent kline {code} 失败: {str(e)[:100]}")
        return []
    return _legacy_kline_shape(bars, f"{source}_kline")


def fetch_stock_kline_eastmoney(code: str, days: int = 90) -> list[dict]:
    """Legacy 别名（pre_fetch_klines 仍在用）：强制走东财档。"""
    try:
        bars, source = _md_router.get_kline(code, 101, min(days, 800),
                                            kind="stock", sources=["eastmoney"])
    except Exception as e:
        print(f"[stock_data] eastmoney kline {code} 失败: {str(e)[:100]}")
        return []
    return _legacy_kline_shape(bars, f"{source}_kline")


def fetch_stock_intraday(code: str) -> list[dict]:
    """获取个股当日分时（腾讯分钟线优先，降级东财 trends2）。

    legacy shape: {time(HHMMSS),price,volume,amount,source}。
    腾讯档：由当日 1 分钟线（mkline m1）重建；东财档：trends2 逐笔分时。
    """
    # 腾讯 1 分钟线当日重建
    pure, full = _normalize_code(code)
    try:
        from qing_investment.marketdata.http import http_get_json
        from qing_investment.marketdata import ratelimit
        ratelimit.acquire("tencent")
        url = f"https://ifzq.gtimg.cn/appstock/app/kline/mkline?param={full},m1,,240"
        payload = http_get_json(url, headers={"Referer": "https://gu.qq.com/"}, timeout=10)
        raw = payload.get("data", {}).get(full, {}).get("m1", []) or []
        if raw:
            out = []
            for parts in raw:
                if len(parts) < 6:
                    continue
                try:
                    t = str(parts[0])
                    out.append({
                        "time": t[8:14] if len(t) >= 14 else t,
                        "price": float(parts[2]),   # 腾讯分钟收在第2数据位
                        "volume": float(parts[5]),
                        "amount": 0.0,
                        "source": "tencent_intraday",
                    })
                except (ValueError, IndexError):
                    continue
            if out:
                return out
    except Exception:
        pass

    # 东财 trends2 分时
    pure, full = _normalize_code(code)
    market_num = "1" if full.startswith("sh") else "0"
    try:
        from qing_investment.marketdata.http import http_get_json
        from qing_investment.marketdata import ratelimit
        ratelimit.acquire("eastmoney")
        url = (
            "https://push2.eastmoney.com/api/qt/stock/trends2/get"
            f"?secid={market_num}.{pure}"
            "&fields1=f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13"
            "&fields2=f51,f52,f53,f54,f55,f56,f57,f58"
        )
        data = http_get_json(url, headers={"Referer": "https://quote.eastmoney.com/"}, timeout=10)
        trends = data.get("data", {}).get("trends", []) or []
        out = []
        for row in trends:
            parts = row.split(",")
            if len(parts) < 6:
                continue
            try:
                dt = parts[0]
                time_part = dt.split(" ")[1] if " " in dt else dt
                out.append({
                    "time": time_part.replace(":", ""),
                    "price": float(parts[2]),
                    "volume": float(parts[5]),
                    "amount": 0.0,
                    "source": "eastmoney_intraday",
                })
            except (ValueError, IndexError):
                continue
        return out
    except Exception:
        return []


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


# ── 财报数据 ──
def fetch_financial_reports(
    code: str,
    years: int = 2,
) -> dict[str, list[dict]]:
    """拉取个股近 N 年财报数据（利润表、资产负债表、现金流量表）。

    使用 akshare 的东方财富三大报表接口，返回报告期维度的原始数据。

    Args:
        code: 股票代码（6位纯数字，如 "600519"）
        years: 读取最近多少年，默认 2 年

    Returns:
        {
            "profit": [...],      # 利润表
            "balance": [...],     # 资产负债表
            "cash_flow": [...],   # 现金流量表
        }
    """
    from datetime import datetime, timedelta
    from concurrent.futures import ThreadPoolExecutor, as_completed

    try:
        import akshare as ak
    except ImportError:
        return {"profit": [], "balance": [], "cash_flow": []}

    # 禁用 akshare 内部 tqdm 进度条，避免 cron 日志噪音
    os.environ.setdefault("TQDM_DISABLE", "1")

    pure_code = _normalize_code(code)[0]
    prefix = "SH" if pure_code.startswith("6") else "SZ"
    symbol = f"{prefix}{pure_code}"

    cutoff = (datetime.now() - timedelta(days=years * 365)).strftime("%Y-%m-%d")

    fetchers = {
        "profit": ak.stock_profit_sheet_by_report_em,
        "balance": ak.stock_balance_sheet_by_report_em,
        "cash_flow": ak.stock_cash_flow_sheet_by_report_em,
    }

    def _fetch_one(statement_type: str, fetcher) -> tuple[str, list[dict]]:
        try:
            df = fetcher(symbol=symbol)
            if df is None or df.empty:
                return statement_type, []

            df["REPORT_DATE"] = df["REPORT_DATE"].astype(str).str[:10]
            df = df[df["REPORT_DATE"] >= cutoff]

            records = df.to_dict("records")
            for r in records:
                for k, v in list(r.items()):
                    if v != v:  # NaN
                        r[k] = None
            return statement_type, records
        except Exception:
            return statement_type, []

    result: dict[str, list[dict]] = {"profit": [], "balance": [], "cash_flow": []}
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(_fetch_one, stmt, fn): stmt
            for stmt, fn in fetchers.items()
        }
        for future in as_completed(futures):
            stmt, records = future.result()
            result[stmt] = records

    return result
