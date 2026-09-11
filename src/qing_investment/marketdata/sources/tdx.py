"""TDX 源：委托 ``qing_investment.tdx_market``，不重写。

tdx_market 已实现：22 台 host 能力路由 + 加权负载均衡 + strict 空语义
（2026-09-10 修复：K线全 host 返回空抛 TdxDataError 而非静默 []）。
本模块只做 symbol 归一 + 返回 shape 对齐 + 异常捕获（软失败语义交 router）。

TDX 的定位（2026-09-10 之后）：第三档兜底 + TDX 独有指数唯一通道。
"""

from __future__ import annotations

SOURCE = "tdx"


def fetch_kline(code: str, klt: int, count: int, *, kind: str = "auto") -> list[dict]:
    """TDX K线（30/60/101/120）。120min 由 60min 按 bar 时点合成（兜底路径）。"""
    if klt not in (30, 60, 101, 120):
        raise ValueError(f"TDX 源不支持 klt={klt}")
    try:
        from qing_investment.tdx_market import TdxMarket
    except Exception:
        return []

    cat = {30: "30min", 60: "60min", 101: "daily"}.get(klt, "60min")
    need = count * 2 + 2 if klt == 120 else count + 2
    from qing_investment.marketdata.symbol import prefix_for, norm_ticker
    try:
        # ⚠️ 必须传带前缀形式（'sh512400'）：TdxMarket.resolve_symbol 对裸码
        # 的市场推断不含 ETF 段（5 开头），'512400' 直接抛 TdxSymbolError——
        # 2026-09-11 实测：裸码导致 TDX 腿全程静默失效（被封禁熔断掩盖）。
        digits = norm_ticker(code)
        prefixed = f"{prefix_for(digits, kind=kind)}{digits}"
        rows = TdxMarket().get_kline(prefixed, cat, count=need)
    except Exception:
        return []
    if not rows:
        return []

    bars = [{
        "bar_time": str((r.get("date") if klt == 101 else None)
                        or r.get("datetime") or r.get("date") or ""),
        "open": r.get("open"), "close": r.get("close"),
        "high": r.get("high"), "low": r.get("low"),
        "volume": r.get("volume"), "amount": r.get("amount"),
    } for r in rows]
    bars = [b for b in bars if b["bar_time"]]
    bars.sort(key=lambda k: k["bar_time"])

    if klt == 120:
        bars = synth_120min_from_60min(bars)
    return bars[-count:] if len(bars) > count else bars


def synth_120min_from_60min(bars: list[dict]) -> list[dict]:
    """60min → 120min 合成：10:30+11:30 → 11:30，14:00+15:00 → 15:00。

    ⚠️ 已知偏差（与腾讯原生 m120 对比实测，2026-09-10）：close 最大偏差 6.73。
    仅在同花顺路径（腾讯无该指数）等无原生源时使用。
    """
    merged = []
    for i in range(len(bars) - 1):
        b1, b2 = bars[i], bars[i + 1]
        hm1 = b1["bar_time"][11:16] if len(b1["bar_time"]) >= 16 else ""
        hm2 = b2["bar_time"][11:16] if len(b2["bar_time"]) >= 16 else ""
        if (hm1, hm2) in (("10:30", "11:30"), ("14:00", "15:00")):
            merged.append({
                "bar_time": b2["bar_time"],
                "open": b1["open"],
                "high": max((b1["high"] or 0), (b2["high"] or 0)),
                "low": min((b1["low"] or 0), (b2["low"] or 0)),
                "close": b2["close"],
                "volume": (b1["volume"] or 0) + (b2["volume"] or 0),
                "amount": (b1["amount"] or 0) + (b2["amount"] or 0),
            })
    return merged


def fetch_quotes(codes: list[str], *, kind: str = "auto") -> list[dict]:
    """TDX 批量行情（委托 TdxMarket.get_quotes）。"""
    try:
        from qing_investment.tdx_market import TdxMarket
    except Exception:
        return []
    prefixed = []
    from qing_investment.marketdata.symbol import prefix_for, norm_ticker
    for c in codes:
        try:
            digits = norm_ticker(c)
            prefixed.append(prefix_for(digits, kind=kind) + digits)
        except ValueError:
            continue
    try:
        rows = TdxMarket().get_quotes(prefixed)
    except Exception:
        return []
    return [{
        "code": (r.get("code") or "").lstrip("shzbj"),
        "name": r.get("name"),
        "price": r.get("price") or r.get("latest"),
        "prev_close": r.get("prev_close") or r.get("previous_close"),
        "high": r.get("high"), "low": r.get("low"),
        "open": r.get("open"),
        "change_pct": r.get("change_pct") or r.get("pct_change"),
        "amount": r.get("amount"),
        "source": SOURCE,
    } for r in rows]
