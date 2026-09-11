"""能力路由：统一 K线 / 快照 / 分时入口，内嵌降级链 + 熔断 + strict 空语义。

降级链（2026-09-11 用户拍板：腾讯优先——长期防封正确方向，东财第二档）：

==================  =====================================================
能力                降级链
==================  =====================================================
K线 120min          腾讯(原生m120) → TDX(60min合成) → 同花顺(60min合成, 仅ths代码)
K线 101/60/30       腾讯 → 东财 → TDX → 新浪(仅30/60) → 同花顺(仅ths代码)
实时快照            腾讯 → 东财 → TDX → 新浪
==================  =====================================================

strict 空语义（2026-09-10 修复定义，全局化）：
- K线/快照属 strict：源返回空 = 软失败 → 降级下一源；
  全部源空 → 抛 :class:`MarketDataError`（**绝不静默返回 []**——
  selftest 假绿灯事故的根源）。
- 熔断 key=(source, "kline"/"quotes")：能力粒度，源整体误伤规避
  （TDX K线全灭但历史分时/元数据存活，9/10 实测）。

返回值一律带 ``source`` 字段（bar 列表除外——由 :func:`get_kline` 的
``(bars, source)`` 元组携带），满足多口径对账纪律。
"""

from __future__ import annotations

from qing_investment.marketdata.breaker import breaker
from qing_investment.marketdata.errors import MarketDataError, SourceUnavailable
from qing_investment.marketdata.symbol import norm_ticker

#: K线降级链（按 klt 分派；entries 为 (source_name, fetch_fn) 元组，惰性 import）
_KLT_SOURCES: dict[int, list[str]] = {
    101: ["tencent", "eastmoney", "tdx", "ths"],
    60: ["tencent", "eastmoney", "tdx", "sina", "ths"],
    30: ["tencent", "eastmoney", "tdx", "sina", "ths"],
    120: ["tencent", "tdx", "ths"],  # 东财无原生 120min，跳过
}


def _source_mod(name: str):
    from qing_investment.marketdata.sources import tencent, eastmoney, tdx, sina, ths
    return {"tencent": tencent, "eastmoney": eastmoney, "tdx": tdx,
            "sina": sina, "ths": ths}[name]


def get_kline(
    code: str,
    klt: int = 101,
    count: int = 8,
    *,
    kind: str = "auto",
    sources: list[str] | None = None,
) -> tuple[list[dict], str]:
    """拉 K线，返回 ``(bars, source_name)``，bars 升序、统一 shape。

    全部源失败抛 :class:`MarketDataError`（附每源失败明细）。
    个别源可强制排除/重排：``sources=["tencent"]``（直连）。
    """
    digits = norm_ticker(code)
    # THS 登记指数（微盘股 883418 等）直连同花顺：腾讯/东财均无此指数，
    # 不让"源不支持该代码"的空结果污染其他源的熔断状态
    # （等价 update_index_klines_intraday 的 ths_only 旗标）
    from qing_investment.marketdata.sources import ths as ths_mod
    if ths_mod.supported(digits) and not sources:
        return _try_chain(["ths"], code, klt, count, kind)
    chain = sources if sources else _KLT_SOURCES.get(klt)
    if not chain:
        raise ValueError(f"不支持的 klt={klt}（支持 30/60/120/101）")
    return _try_chain(chain, code, klt, count, kind)


def _try_chain(chain: list[str], code: str, klt: int, count: int,
               kind: str) -> tuple[list[dict], str]:
    from qing_investment.marketdata.sources import ths as ths_mod
    attempts: list[str] = []
    for name in chain:
        mod = _source_mod(name)
        if name == "ths":
            if not ths_mod.supported(norm_ticker(code)):
                continue  # 未登记的同花顺指数直接跳过
        if breaker.is_open(f"{name}:kline"):
            attempts.append(f"{name}: BREAKER-OPEN（本进程内已熔断，跳过）")
            continue
        try:
            bars = mod.fetch_kline(code, klt, count, kind=kind) \
                if name != "ths" else mod.fetch_kline(code, klt, count)
        except Exception as e:  # noqa: BLE001
            breaker.trip(f"{name}:kline")
            attempts.append(f"{name}: {type(e).__name__}: {str(e)[:100]}")
            continue
        if not bars:
            # strict 空语义：K线空 = 软失败，降级下一源；并熔断该源 K线能力
            # （对齐 update_index_klines_intraday 的 _fetch_*_with_breaker 语义：
            #   确认失败后本进程短路，杜绝逐源空转拖垮 cron）
            breaker.trip(f"{name}:kline")
            attempts.append(f"{name}: empty result（strict 空语义，视为失败+熔断）")
            continue
        # 成功 → 该源 K线能力自愈复位（服务恢复后自动回到正常链）
        breaker.reset(f"{name}:kline")
        return bars, name
    raise MarketDataError(
        f"get_kline({code}, klt={klt}) 全部源失败。attempts: {'; '.join(attempts)}",
        attempts=attempts,
    )


def get_index_kline(code: str, klt: int = 101, count: int = 8,
                    **kw) -> tuple[list[dict], str]:
    """指数 K线（kind='index' 消歧：000001 按上证指数处理而非平安银行）。"""
    return get_kline(code, klt, count, kind="index", **kw)


def get_quotes(codes: list[str], *, kind: str = "auto",
               sources: list[str] | None = None) -> dict:
    """批量实时快照。返回 ``{"source", "quotes", "errors", "elapsed_ms"}``。

    shape 对齐 ``monitor/fetchers.fetch_quotes_with_fallback`` 既有契约，
    上游调度器零改动可切。
    """
    import time as _time
    t0 = _time.monotonic()
    digits_list = []
    for c in codes:
        try:
            digits_list.append(str(c).strip())
        except ValueError:
            continue
    if not digits_list:
        return {"source": "none", "quotes": [], "errors": [], "elapsed_ms": 0.0}

    chain = sources if sources else ["tencent", "eastmoney", "tdx", "sina"]
    errors: list[str] = []
    for name in chain:
        if breaker.is_open(f"{name}:quotes"):
            errors.append(f"{name}: BREAKER-OPEN")
            continue
        mod = _source_mod(name)
        try:
            quotes = mod.fetch_quotes(digits_list, kind=kind) \
                if name in ("tencent", "eastmoney", "tdx", "sina") else []
        except Exception as e:  # noqa: BLE001
            breaker.trip(f"{name}:quotes")
            errors.append(f"{name}: {type(e).__name__}: {str(e)[:100]}")
            continue
        if not quotes:
            breaker.trip(f"{name}:quotes")
            errors.append(f"{name}: empty result（strict 空语义+熔断）")
            continue
        breaker.reset(f"{name}:quotes")
        return {
            "source": name if name != "tencent" else "tencent_gtimg",
            "quotes": quotes,
            "errors": errors,
            "elapsed_ms": round((_time.monotonic() - t0) * 1000, 1),
        }
    return {
        "source": "none",
        "quotes": [],
        "errors": errors,
        "elapsed_ms": round((_time.monotonic() - t0) * 1000, 1),
    }


def trip_breaker(source: str, capability: str) -> None:
    """调用方在捕获致命慢/空转后可手动熔断（如 cron 超时场景）。"""
    breaker.trip(f"{source}:{capability}")


def reset_breaker(source: str | None = None) -> None:
    """复位熔断（测试/手动恢复）。"""
    breaker.reset(source)


def get_intraday(code: str, *, kind: str = "auto",
                 sources: list[str] | None = None) -> tuple[list[dict], str]:
    """当日 30 分钟粒度序列（分时的低分辨率代理）。

    复用 K线降级链（klt=30）。需要逐笔/1min 粒度的场景请直接用
    ``qing_investment.tdx_market.TdxMarket.get_intraday``（历史分时接口
    2026-09-10 实测存活）。
    """
    return get_kline(code, 30, 16, kind=kind, sources=sources)
