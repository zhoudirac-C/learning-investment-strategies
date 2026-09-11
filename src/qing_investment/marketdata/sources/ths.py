"""同花顺源：板块/特色指数 K线（微盘股 883418 等 TDX 独有指数替代）。

经验内嵌（2026-09-10 接入实测，见 tdx-data-source-troubleshoot skill）：
- 接口 ``d.10jqka.com.cn/v6/line/bk_<code>/<period>/last.js``，前缀 ``bk_`` 非 ``hs_``
- 必须带 Referer ``https://q.10jqka.com.cn/``
- 周期码：00=日线 41=30min 50=60min 10=周 11=月 12=年；**无 120min**（60min 合成）
- 字段序：时间,开,高,低,收,量,额（第 4 家不同字段序）
- ⚠️ 日线接口 (00) **不可信**：收盘滞后一个 tick 且前后两次请求不一致
  （2026-09-10 实测 00/last.js 2179.375 vs 分钟线/官方 2168.66）；
  分钟线三者自洽 → 判定分钟线为权威，日线一律由 30min 聚合
- 响应是 JSONP：``var xxx=(...)(...)`` 形式，需正则提取括号内 JSON
"""

from __future__ import annotations

import json
import re

from qing_investment.marketdata import ratelimit
from qing_investment.marketdata.errors import SourceUnavailable
from qing_investment.marketdata.http import http_get
from qing_investment.marketdata.sources.tdx import synth_120min_from_60min

SOURCE = "ths"

#: 支持的同花顺指数 → 周期码映射（新增指数在此登记）
THS_PERIOD_MAP: dict[str, dict[int, str]] = {
    "883418": {101: "00", 30: "41", 60: "50"},  # 微盘股（市值最小400只等权）
}


def supported(code: str) -> bool:
    """该代码是否有同花顺通道。"""
    from qing_investment.marketdata.symbol import norm_ticker
    try:
        return norm_ticker(code) in THS_PERIOD_MAP
    except ValueError:
        return False


def fetch_kline(code: str, klt: int, count: int) -> list[dict]:
    """同花顺指数 K线（仅 THS_PERIOD_MAP 登记的代码）。升序 bar 列表。

    分支顺序：101（30min 聚合）与 120（60min 合成）是**合成能力**，
    不依赖原生周期码，必须在周期码查找之前处理——
    否则 120 会被误判"无周期码"抛错并连带熔断（2026-09-11 实测）。
    """
    from qing_investment.marketdata.symbol import norm_ticker
    digits = norm_ticker(code)
    if digits not in THS_PERIOD_MAP:
        raise ValueError(f"同花顺源未登记代码 {digits}（THS_PERIOD_MAP）")

    if klt == 101:
        # ⚠️ 日线接口(00)不可信 → 由 30min 聚合
        bars30 = _fetch_raw(digits, "41", 240 * (count + 2))
        return _aggregate_daily(bars30, count)

    if klt == 120:
        # 同花顺无 120min → 60min 合成
        bars60 = fetch_kline(code, 60, count * 2 + 2)
        merged = synth_120min_from_60min(bars60)
        return merged[-count:] if len(merged) > count else merged

    period = THS_PERIOD_MAP[digits].get(klt)
    if not period:
        raise ValueError(f"同花顺源 {digits} 无 klt={klt} 周期码")
    return _fetch_raw(digits, period, count)


def _fetch_raw(digits: str, period: str, count: int) -> list[dict]:
    url = f"https://d.10jqka.com.cn/v6/line/bk_{digits}/{period}/last.js"
    ratelimit.acquire(SOURCE)
    try:
        text = http_get(
            url,
            headers={"Referer": "https://q.10jqka.com.cn/"},
            timeout=15,
        )
    except Exception as e:
        raise SourceUnavailable(f"ths request failed: {type(e).__name__}: {e}") from e
    m = re.search(r"\((.*)\)\s*;?\s*$", text, re.S)
    if not m:
        raise SourceUnavailable(f"ths JSONP 结构异常: {text[:80]}")
    try:
        payload = json.loads(m.group(1))
    except json.JSONDecodeError as e:
        raise SourceUnavailable(f"ths JSON 解析失败: {e}") from e
    raw = [r for r in payload.get("data", "").split(";") if r]
    bars = []
    for row in raw:
        parts = row.split(",")
        if len(parts) < 6:
            continue
        try:
            t = parts[0]
            bar_time = (f"{t[0:4]}-{t[4:6]}-{t[6:8]} {t[8:10]}:{t[10:12]}"
                        if len(t) >= 12 else f"{t[0:4]}-{t[4:6]}-{t[6:8]}")
            bars.append({
                "bar_time": bar_time,
                "open": float(parts[1]), "high": float(parts[2]),
                "low": float(parts[3]), "close": float(parts[4]),
                "volume": float(parts[5]),
                "amount": float(parts[6]) if len(parts) > 6 and parts[6] else 0.0,
            })
        except (ValueError, IndexError):
            continue
    bars.sort(key=lambda k: k["bar_time"])
    return bars[-count:] if len(bars) > count else bars


def _aggregate_daily(bars30: list[dict], count: int) -> list[dict]:
    """30min → 日线聚合：open=首根开盘 close=末根收盘 high=max low=min 量额求和。"""
    if not bars30:
        return []
    agg: dict[str, list[dict]] = {}
    for b in bars30:
        agg.setdefault(b["bar_time"][:10], []).append(b)
    daily = []
    for day in sorted(agg):
        grp = agg[day]
        daily.append({
            "bar_time": day,
            "open": grp[0]["open"],
            "high": max(g["high"] for g in grp),
            "low": min(g["low"] for g in grp),
            "close": grp[-1]["close"],
            "volume": sum(g["volume"] or 0 for g in grp),
            "amount": sum(g["amount"] or 0 for g in grp),
        })
    return daily[-count:] if len(daily) > count else daily
