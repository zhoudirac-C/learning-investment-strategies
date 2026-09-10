#!/usr/bin/env python3
"""
指数多级别K线盘中增量更新。

设计目标:
  - 每30分钟运行一次（交易时段 9:30-15:00）
  - 只拉最新几根K线，与DB对比，发现新bar就入库
  - 增量计算 MACD（重算最近35根以保证EMA连续性）
  - 幂等：重复运行不会产生重复数据（PRIMARY KEY约束自动去重）

用法:
  python scripts/update_index_klines_intraday.py
  python scripts/update_index_klines_intraday.py --dry-run
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1] if __file__ != "__main__" else Path.cwd()
DB_PATH = REPO_ROOT / "infra" / "data" / "kline_cache.db"
CN_TZ = timezone(timedelta(hours=8))

INDICES = {
    "sh000001": {"secid": "1.000001", "name": "上证指数"},
    "sh000300": {"secid": "1.000300", "name": "沪深300"},
    "sh000852": {"secid": "1.000852", "name": "中证1000"},
    "sh000985": {"secid": "1.000985", "name": "中证全指"},
    "sz399001": {"secid": "0.399001", "name": "深证成指"},
    "sz399006": {"secid": "0.399006", "name": "创业板指"},
    "sh000688": {"secid": "1.000688", "name": "科创50"},
    # ⚠️ 原注释误标为「中证2000」，实测 sh000932 = 中证消费（中证2000 应为 sh932000）
    "sh000932": {"secid": "1.000932", "name": "中证消费"},
    # 微盘股指数（同花顺 883418，市值最小 400 只等权，与万得同口径）
    # 2026-09-10：原 TDX 880823 因接口封禁无数据，改用同花顺
    "883418": {"secid": "", "name": "微盘股", "ths_only": True},
}

TIMEFRAMES = {
    "30min": {"klt": 30, "name": "30分钟"},
    "60min": {"klt": 60, "name": "60分钟"},
    "120min": {"klt": 120, "name": "120分钟"},
    "daily": {"klt": 101, "name": "日线"},
}

FETCH_BARS = 5          # 每次拉最新5根

# 进程内熔断标志（2026-09-10：TDX 常规 K线接口被封禁 / 东财对云 IP 断连）
_TDX_DEAD = False
_EM_DEAD = False
RECOMPUTE_BARS = 35     # 重算最近35根的MACD（保证EMA稳定）
DELAY = 1.0             # 请求间隔
HTTP_TIMEOUT = 30       # 单次请求超时（秒），东财偶发连接重置，放宽等待
HTTP_MAX_RETRIES = 3    # HTTP 失败重试次数

# 腾讯财经接口 symbol 映射（日线兜底）
_TENCENT_SYMBOLS = {
    "sh000001": "sh000001",
    "sh000300": "sh000300",
    "sh000852": "sh000852",
    "sh000985": "sh000985",
    "sz399001": "sz399001",
    "sz399006": "sz399006",
    "sh000688": "sh000688",
    "sh000932": "sh000932",
}

# ---------------------------------------------------------------------------
# 同花顺板块指数（2026-09-10 新增，替代被封禁的 TDX 独有指数）
# 微盘股 883418：与万得微盘股同口径（市值最小 400 只等权）
# 接口: https://d.10jqka.com.cn/v6/line/<prefix><code>/<period>/last.js
# ---------------------------------------------------------------------------
_THS_PREFIX = "bk_"
# 同花顺周期码: 00=日线 41=30min 50=60min（⚠️ 无 120min，由 60min 合成）
# 键与 TIMEFRAMES 的 klt 一致（101=日线）
_THS_PERIOD_MAP = {
    "883418": {101: "00", 30: "41", 60: "50"},
}
# 进程内熔断（与东财/TDX 同范式）
_THS_DEAD = False


def _http_get(url: str, *, headers: dict | None = None, timeout: int = HTTP_TIMEOUT) -> str:
    default_headers = {
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://quote.eastmoney.com/",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Connection": "keep-alive",
    }
    if headers:
        default_headers.update(headers)
    last_err: Exception | None = None
    for attempt in range(HTTP_MAX_RETRIES):
        try:
            req = urllib.request.Request(url, headers=default_headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode()
        except Exception as e:
            last_err = e
            wait = 2.0 * (attempt + 1)
            print(f"    [WARN] 请求失败 ({attempt + 1}/{HTTP_MAX_RETRIES}): {str(e)[:80]}，{wait}s 后重试...")
            time.sleep(wait)
    raise last_err or ConnectionError(f"请求失败: {url}")


def _eastmoney_get(url: str, *, timeout: int = HTTP_TIMEOUT) -> str:
    """带进程内熔断的东财请求。

    2026-09-10：东财 push2his 对云环境 IP 持续 `Remote end closed connection`，
    每次重试 3 轮耗时约 12s。首次确认失败后本进程短路，
    直接转腾讯通道，避免 36 次调用累计 ~7 分钟拖垮 cron。
    """
    global _EM_DEAD
    if _EM_DEAD:
        raise ConnectionError("东财本进程内已熔断")
    try:
        return _http_get(url, timeout=timeout)
    except Exception:
        _EM_DEAD = True
        print("    [INFO] 东财不可用，本进程内已熔断（后续直接走腾讯）")
        raise


def _ema(values: list[float], period: int) -> list[float | None]:
    if len(values) < period:
        return [None] * len(values)
    k = 2 / (period + 1)
    result: list[float | None] = [None] * (period - 1)
    result.append(sum(values[:period]) / period)
    for v in values[period:]:
        result.append(v * k + result[-1] * (1 - k))  # type: ignore[operator]
    return result


def _parse_eastmoney_klines(raw: list[str]) -> list[dict]:
    """解析东财 klines 列表为统一格式。"""
    result = []
    for row in raw:
        parts = row.split(",")
        if len(parts) < 6:
            continue
        try:
            result.append({
                "bar_time": parts[0],
                "open": float(parts[1]),
                "close": float(parts[2]),
                "high": float(parts[3]),
                "low": float(parts[4]),
                "volume": float(parts[5]),
                "amount": float(parts[6]) if len(parts) > 6 else 0.0,
            })
        except (ValueError, IndexError):
            continue
    return result


def _parse_ths_klines(raw: list[str]) -> list[dict]:
    """解析同花顺 d.10jqka.com.cn 的 K线 data 串。

    每根格式：`时间,开,高,低,收,成交量,成交额,...,0`
    - 日线时间 = `YYYYMMDD`（8 位）
    - 分钟线时间 = `YYYYMMDDHHMM`（12 位）
    """
    result = []
    for row in raw:
        parts = row.split(",")
        if len(parts) < 6:
            continue
        try:
            t = parts[0]
            if len(t) >= 12:
                bar_time = f"{t[0:4]}-{t[4:6]}-{t[6:8]} {t[8:10]}:{t[10:12]}"
            else:
                bar_time = f"{t[0:4]}-{t[4:6]}-{t[6:8]}"
            result.append({
                "bar_time": bar_time,
                "open": float(parts[1]),
                "close": float(parts[4]),
                "high": float(parts[2]),
                "low": float(parts[3]),
                "volume": float(parts[5]),
                "amount": float(parts[6]) if len(parts) > 6 and parts[6] else 0.0,
            })
        except (ValueError, IndexError):
            continue
    return result


def _synth_daily_from_intraday(code: str, count: int) -> list[dict]:
    """同花顺日线兜底：由 30 分钟 K线聚合出日线。

    ⚠️ 2026-09-10 实测：同花顺**日线接口 (00) 不可信** ——
    同一天的收盘在三个口径下互相矛盾，且会随时间被"改写"：
        - 00/last.js   → 2179.375  (V=885627490)
        - 00/2026.js   → 2167.324  (V=195645730)  ← 同一接口前后两次请求也不同
        - 50/last.js 60min → 2168.664
        - 41/last.js 30min → 2168.664
        - 当日分时末点     → 2168.664  ← 与官网显示 2168.66 一致
    因 30min/60min/分时三者一致且自洽（开盘 2186.112 = 日线最高价），
    判定 **分钟线为权威源**，日线一律由 30min 聚合，不取 00 接口。

    聚合规则：open=首根开盘，close=末根收盘，high=max，low=min，
    volume/amount=求和。按自然日分组。
    """
    bars = fetch_latest_klines_from_ths(code, 30, count=240 * (count + 2))
    if not bars:
        return []

    agg: dict[str, list[dict]] = {}
    for b in bars:
        day = b["bar_time"][:10]
        agg.setdefault(day, []).append(b)

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
    # 最后一个交易日可能不完整（盘中），但收盘后即为完整日
    return daily[-count:] if len(daily) > count else daily


def fetch_latest_klines_from_ths(code: str, klt: int, count: int = FETCH_BARS) -> list[dict]:
    """同花顺板块指数 K线（微盘股 883418 等 TDX 独有指数的替代源）。

    2026-09-10 新增：TDX 常规 K线接口被按接口粒度封禁后，微盘股指数
    (原 TDX 880823) 失去数据。同花顺 883418「微盘股」是同口径替代
    （市值最小400只等权，2025 年度涨幅 +69.4% vs 万得微盘股 +70.70%）。

    接口: https://d.10jqka.com.cn/v6/line/bk_<code>/<period>/last.js
    周期码: 00=日线  41=30分钟  50=60分钟  10=周  11=月  12=年
    ⚠️ 无 120 分钟周期（上层由 60min 合成）。

    ⚠️ 坑：日线 (00) 收盘价可能滞后一个 tick（2026-09-10 实测日线
    2167.324 vs 分钟线/官方 2168.664）。分钟线更准。
    需要 headers: Referer https://q.10jqka.com.cn/
    """
    import urllib.request

    period = _THS_PERIOD_MAP.get(code, {}).get(klt)
    if not period:
        return []

    url = f"https://d.10jqka.com.cn/v6/line/{_THS_PREFIX}{code}/{period}/last.js"
    headers = {
        "Referer": "https://q.10jqka.com.cn/",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            text = resp.read().decode("utf-8", errors="ignore")
        m = re.search(r"\((.*)\)\s*;?\s*$", text, re.S)
        if not m:
            return []
        payload = json.loads(m.group(1))
        raw = [r for r in payload.get("data", "").split(";") if r]
    except Exception:
        return []

    result = _parse_ths_klines(raw)
    result.sort(key=lambda k: k["bar_time"])
    return result[-count:] if len(result) > count else result


def fetch_latest_klines_from_tencent(code: str, count: int = FETCH_BARS,
                                     klt: int = 101) -> list[dict]:
    """腾讯财经指数 K线兜底（日线 + 分钟线，2026-09-10 扩展分钟线）。

    日线走 fqkline/get（qfq 前复权）；分钟线走 kline/mkline。
    返回与东财统一格式。
    """
    tencent_symbol = _TENCENT_SYMBOLS.get(code)
    if not tencent_symbol:
        return []

    tencent_headers = {
        "Referer": "https://gu.qq.com/",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
    }

    # 分钟线：klt -> 腾讯周期名
    _MIN_MAP = {30: "m30", 60: "m60", 120: "m120", 1: "m1", 5: "m5", 15: "m15"}
    if klt in _MIN_MAP:
        period = _MIN_MAP[klt]
        # ⚠️ 必须用 ifzq.gtimg.cn（无 web. 前缀）——带 web. 的域名会 301 跳转
        url = (
            "https://ifzq.gtimg.cn/appstock/app/kline/mkline"
            f"?param={tencent_symbol},{period},,{count + 5}"
        )
        try:
            payload = json.loads(_http_get(url, headers=tencent_headers))
            raw = payload.get("data", {}).get(tencent_symbol, {}).get(period, [])
        except Exception:
            return []
        result = []
        for parts in raw or []:
            if len(parts) < 6:
                continue
            try:
                # 腾讯分钟线：时间(YYYYMMDDHHMM), 开盘, 收盘, 最高, 最低, 成交量
                t = str(parts[0])
                bar_time = (
                    f"{t[0:4]}-{t[4:6]}-{t[6:8]} {t[8:10]}:{t[10:12]}"
                    if len(t) >= 12 else t
                )
                result.append({
                    "bar_time": bar_time,
                    "open": float(parts[1]),
                    "close": float(parts[2]),
                    "high": float(parts[3]),
                    "low": float(parts[4]),
                    "volume": float(parts[5]),
                    "amount": 0.0,
                })
            except (ValueError, IndexError):
                continue
        result.sort(key=lambda k: k["bar_time"])
        return result[-count:] if len(result) > count else result

    # 日线
    url = (
        "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        f"?param={tencent_symbol},day,,,{count + 3},qfq"
    )
    try:
        text = _http_get(url, headers=tencent_headers)
        payload = json.loads(text)
        raw = payload.get("data", {}).get(tencent_symbol, {}).get("day", [])
        if not raw:
            return []
    except Exception:
        return []

    result = []
    for parts in raw:
        if len(parts) < 6:
            continue
        try:
            # 腾讯日线字段：日期, 开盘, 收盘, 最高, 最低, 成交量
            result.append({
                "bar_time": parts[0],
                "open": float(parts[1]),
                "close": float(parts[2]),
                "high": float(parts[3]),
                "low": float(parts[4]),
                "volume": float(parts[5]),
                "amount": 0.0,
            })
        except (ValueError, IndexError):
            continue

    result.sort(key=lambda k: k["bar_time"])
    return result[-count:] if len(result) > count else result


def fetch_latest_klines_from_tdx(code: str, klt: int, count: int = FETCH_BARS) -> list[dict]:
    """TDX 拉指数K线兜底（东财反爬断连时）。120min 由 60min 按 bar 时点合成。

    klt=101（日线）也支持——微盘股指数（880823）等 TDX 独有指数的唯一通道。
    """
    try:
        from qing_investment.tdx_market import TdxMarket
    except Exception as e:
        print(f"    [WARN] TDX 导入失败: {str(e)[:60]}")
        return []

    if klt not in (30, 60, 101, 120):
        return []  # 其余级别不支持

    mkt = TdxMarket()
    tdx_cat = {30: "30min", 60: "60min", 101: "daily"}.get(klt, "60min")
    need = count * 2 + 2 if klt == 120 else count + 2
    try:
        rows = mkt.get_kline(code, tdx_cat, count=need)
    except Exception as e:
        print(f"    [WARN] TDX 拉取失败 {INDICES[code]['name']} klt={klt}: {str(e)[:60]}")
        return []
    if not rows:
        return []

    # 日线 bar_time 统一用纯日期（与东财/腾讯落库格式一致，BETWEEN 字符串比较才不漏当日）
    bars = [{
        "bar_time": str((r.get("date") if klt == 101 else None)
                        or r.get("datetime") or r.get("date") or ""),
        "open": r.get("open"),
        "close": r.get("close"),
        "high": r.get("high"),
        "low": r.get("low"),
        "volume": r.get("volume"),
        "amount": r.get("amount"),
    } for r in rows]
    bars.sort(key=lambda k: k["bar_time"])

    if klt == 120:
        # 60min → 120min：10:30+11:30 → 11:30，14:00+15:00 → 15:00（按 bar 时点对齐，避免错位）
        bars = _synth_120min_from_60min(bars)

    return bars[-count:] if len(bars) > count else bars


def _synth_120min_from_60min(bars: list[dict]) -> list[dict]:
    """60min → 120min 合成：10:30+11:30 → 11:30，14:00+15:00 → 15:00。

    按 bar 时点对齐，避免错位。TDX 与同花顺路径共用。
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


def _fetch_ths_with_breaker(code: str, klt: int, count: int) -> list[dict]:
    """带进程内熔断的同花顺拉取。

    同花顺无 120min 周期 → 取 60min 合成（与 TDX 路径同逻辑）。
    """
    global _THS_DEAD
    if _THS_DEAD:
        return []
    if klt == 101:
        # ⚠️ 日线接口(00)不可信 → 由 30min 聚合（见 _synth_daily_from_intraday）
        result = _synth_daily_from_intraday(code, count)
        if not result:
            _THS_DEAD = True
            print("    [INFO] 同花顺不可用，本进程内已熔断")
        return result
    if klt == 120:
        # 同花顺无 120min 周期 → 取 60min 合成（与 TDX 路径同逻辑）
        bars60 = fetch_latest_klines_from_ths(code, 60, count * 2 + 2)
        if not bars60:
            _THS_DEAD = True
            print("    [INFO] 同花顺不可用，本进程内已熔断")
            return []
        merged = _synth_120min_from_60min(bars60)
        return merged[-count:] if len(merged) > count else merged
    result = fetch_latest_klines_from_ths(code, klt, count)
    if not result:
        _THS_DEAD = True
        print("    [INFO] 同花顺不可用，本进程内已熔断")
    return result


def _fetch_tdx_with_breaker(code: str, klt: int, count: int) -> list[dict]:
    """带进程内熔断的 TDX 拉取。

    2026-09-10：TDX 常规 K线接口被服务端封禁，每次调用会逐台重试
    host（约 20-30s）。本进程一旦确认 TDX 不可用，后续调用直接短路，
    避免 9 指数 × 4 周期 = 36 次调用累计空转数分钟导致 cron 900s 超时。
    """
    global _TDX_DEAD
    if _TDX_DEAD:
        return []
    result = fetch_latest_klines_from_tdx(code, klt, count)
    if not result:
        _TDX_DEAD = True
        print("    [INFO] TDX K线不可用，本进程内已熔断（后续跳过 TDX 兜底）")
    return result


def fetch_latest_klines(code: str, klt: int, count: int = FETCH_BARS) -> list[dict]:
    """拉取最新 N 根K线（升序）。

    降级链（2026-09-10 调整）：
        东财 push2his  →  腾讯(日线+分钟线)  →  TDX  →  []

    ⚠️ 2026-09-10 起 TDX 公网节点对 get_security_bars/get_index_bars
    按接口粒度封禁（全 host 返回空），因此 TDX 从「分钟线首选兜底」
    降为最后一档；且一旦失败即熔断，避免每次逐台空转 20-30s。

    ths_only 指数（微盘股 883418）走同花顺：TDX 880823 已不可用，
    东财/腾讯均无此指数。
    """
    if INDICES[code].get("ths_only"):
        return _fetch_ths_with_breaker(code, klt, count)
    if INDICES[code].get("tdx_only"):
        return _fetch_tdx_with_breaker(code, klt, count)
    secid = INDICES[code]["secid"]
    url = (
        "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        f"?secid={secid}"
        "&fields1=f1,f2,f3,f4,f5,f6"
        "&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
        f"&klt={klt}&fqt=1&end=20500101&lmt={count + 3}"
    )
    try:
        data = json.loads(_eastmoney_get(url))
        raw = data.get("data", {}).get("klines", [])
        result = _parse_eastmoney_klines(raw)
        if result:
            result.sort(key=lambda k: k["bar_time"])
            return result[-count:] if len(result) > count else result
    except Exception as e:
        print(f"    [WARN] 东财 {INDICES[code]['name']} klt={klt} 失败: {str(e)[:80]}")

    # 腾讯兜底：日线 + 分钟线（2026-09-10 扩展）
    print(f"    [INFO] 尝试腾讯兜底 {INDICES[code]['name']} klt={klt}...")
    result = fetch_latest_klines_from_tencent(code, count, klt=klt)
    if result:
        print(f"    [INFO] 腾讯兜底成功 {INDICES[code]['name']}: {len(result)} 根")
        return result

    # TDX 最后一档（已熔断保护）
    return _fetch_tdx_with_breaker(code, klt, count)


def compute_macd_range(klines: list[dict]) -> list[dict]:
    """为K线列表计算 MACD。"""
    closes = [k["close"] for k in klines]
    n = len(closes)
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)

    dif = []
    for i in range(n):
        if ema12[i] is not None and ema26[i] is not None:
            dif.append(ema12[i] - ema26[i])
        else:
            dif.append(None)

    valid_dif = [d for d in dif if d is not None]
    if not valid_dif:
        return klines

    valid_start = next(i for i, d in enumerate(dif) if d is not None)
    dea_raw = _ema(valid_dif, 9)

    dea: list[float | None] = [None] * n
    for i, val in enumerate(dea_raw):
        if val is not None:
            dea[valid_start + i] = val

    for i, k in enumerate(klines):
        k["dif"] = round(dif[i], 4) if dif[i] is not None else None  # type: ignore[arg-type]
        k["dea"] = round(dea[i], 4) if dea[i] is not None else None  # type: ignore[arg-type]
        if dif[i] is not None and dea[i] is not None:
            k["macd_hist"] = round((dif[i] - dea[i]) * 2, 4)
        else:
            k["macd_hist"] = None

    return klines


def update_one(code: str, timeframe: str, dry_run: bool = False) -> dict:
    """更新单个指数×周期的K线。返回统计。"""
    import sqlite3

    klt = TIMEFRAMES[timeframe]["klt"]
    idx_name = INDICES[code]["name"]
    tf_name = TIMEFRAMES[timeframe]["name"]

    # 1. 从API拉最新N根
    latest = fetch_latest_klines(code, klt, FETCH_BARS)
    if not latest:
        return {"status": "no_api_data", "code": code, "tf": timeframe}

    newest_bar = latest[-1]["bar_time"]

    # 2. 查DB中最新的 bar_time
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    db_latest = conn.execute(
        "SELECT MAX(bar_time) as latest FROM index_klines WHERE code=? AND timeframe=?",
        (code, timeframe)
    ).fetchone()["latest"]

    if db_latest and db_latest > newest_bar:
        conn.close()
        return {"status": "up_to_date", "code": code, "tf": timeframe, "db_latest": db_latest}

    # 3. 有新bar：从DB取最近 RECOMPUTE_BARS 根（含新bar之前的历史）
    existing = conn.execute(
        "SELECT * FROM index_klines WHERE code=? AND timeframe=? ORDER BY bar_time ASC",
        (code, timeframe)
    ).fetchall()

    existing_bars = [dict(r) for r in existing]
    existing_times = {r["bar_time"] for r in existing_bars}
    # 同 bar_time 的旧 close（用于 daily 收盘价覆盖早盘快照的判断）
    existing_close = {r["bar_time"]: r["close"] for r in existing_bars}

    # 找出新bar；daily 级别同 bar_time 但 close 变化 → 视为待覆盖更新
    new_bars = [k for k in latest if k["bar_time"] not in existing_times]
    override_bars = [
        k for k in latest
        if k["bar_time"] in existing_times
        and k["bar_time"] == newest_bar
        and k["bar_time"] in existing_close
        and abs((existing_close[k["bar_time"]] or 0) - (k["close"] or 0)) > 1e-6
    ]

    if not new_bars and not override_bars:
        conn.close()
        return {"status": "up_to_date", "code": code, "tf": timeframe, "db_latest": db_latest}

    # 4. 取最近 RECOMPUTE_BARS 根用于重算MACD（覆盖 bar 先移除旧值再并入新值）
    replace_times = {k["bar_time"] for k in override_bars}
    base_bars = [b for b in existing_bars if b["bar_time"] not in replace_times]
    all_bars = base_bars + new_bars + override_bars
    all_bars.sort(key=lambda k: k["bar_time"])
    compute_window = all_bars[-RECOMPUTE_BARS:] if len(all_bars) > RECOMPUTE_BARS else all_bars
    compute_window = compute_macd_range(compute_window)

    # 5. 写入新bar/覆盖bar（含重算的MACD）
    if not dry_run:
        now = datetime.now(CN_TZ).isoformat()
        # 只写入新bar + 覆盖bar（compute_window的后半部分）
        write_times = {k["bar_time"] for k in new_bars + override_bars}
        bars_to_write = [k for k in compute_window if k["bar_time"] in write_times]

        conn.executemany(
            """INSERT OR REPLACE INTO index_klines
                (code, timeframe, bar_time, open, high, low, close, volume, amount,
                 dif, dea, macd_hist, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    code, timeframe, k["bar_time"],
                    k["open"], k["high"], k["low"], k["close"],
                    k["volume"], k["amount"],
                    k.get("dif"), k.get("dea"), k.get("macd_hist"),
                    now,
                )
                for k in bars_to_write
            ]
        )
        conn.commit()

    conn.close()

    return {
        "status": "updated",
        "code": code,
        "tf": timeframe,
        "new_bars": len(new_bars),
        "newest_bar": newest_bar,
        "bars": [k["bar_time"] for k in new_bars],
    }


# ── 90分钟合成 ──

def _fetch_and_compute_macd(klines: list[dict]) -> list[dict]:
    """为K线列表计算MACD（内联版，避免重复导入EMA逻辑）。"""
    def _ema(values, period):
        if len(values) < period:
            return [None] * len(values)
        k = 2 / (period + 1)
        result = [None] * (period - 1)
        result.append(sum(values[:period]) / period)
        for v in values[period:]:
            result.append(v * k + result[-1] * (1 - k))  # type: ignore[operator]
        return result

    closes = [k["close"] for k in klines]
    n = len(closes)
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)

    dif = []
    for i in range(n):
        if ema12[i] is not None and ema26[i] is not None:
            dif.append(ema12[i] - ema26[i])
        else:
            dif.append(None)

    valid_dif = [d for d in dif if d is not None]
    if not valid_dif:
        return klines

    valid_start = next(i for i, d in enumerate(dif) if d is not None)
    dea_raw = _ema(valid_dif, 9)

    dea: list[float | None] = [None] * n
    for i, val in enumerate(dea_raw):
        if val is not None:
            dea[valid_start + i] = val

    for i, k in enumerate(klines):
        k["dif"] = round(dif[i], 4) if dif[i] is not None else None
        k["dea"] = round(dea[i], 4) if dea[i] is not None else None
        if dif[i] is not None and dea[i] is not None:
            k["macd_hist"] = round((dif[i] - dea[i]) * 2, 4)
        else:
            k["macd_hist"] = None

    return klines


def synthesize_90min_klines(code: str, dry_run: bool = False) -> int:
    """从30分钟K线合成90分钟K线，计算MACD后入库。"""
    import sqlite3

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        "SELECT * FROM index_klines WHERE code=? AND timeframe='30min' ORDER BY bar_time ASC",
        (code,)
    ).fetchall()

    if len(rows) < 3:
        conn.close()
        return 0

    bars_90min = []
    for g in range(len(rows) // 3):
        group = rows[g*3:(g+1)*3]
        bar = {
            "bar_time": group[-1]["bar_time"],
            "open": group[0]["open"],
            "high": max(r["high"] for r in group),
            "low": min(r["low"] for r in group),
            "close": group[-1]["close"],
            "volume": sum(r["volume"] for r in group),
            "amount": sum(r["amount"] for r in group if r["amount"]),
        }
        bars_90min.append(bar)

    bars_90min = _fetch_and_compute_macd(bars_90min)

    if not dry_run:
        now = datetime.now(CN_TZ).isoformat()
        # 删旧写新（90分钟数据量小，全量覆盖）
        conn.execute("DELETE FROM index_klines WHERE code=? AND timeframe='90min'", (code,))
        conn.executemany(
            """INSERT INTO index_klines
                (code, timeframe, bar_time, open, high, low, close, volume, amount,
                 dif, dea, macd_hist, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    code, "90min", k["bar_time"],
                    k["open"], k["high"], k["low"], k["close"],
                    k["volume"], k["amount"],
                    k.get("dif"), k.get("dea"), k.get("macd_hist"),
                    now,
                )
                for k in bars_90min
            ]
        )
        conn.commit()

    conn.close()
    return len(bars_90min)


def is_trading_time() -> bool:
    """判断当前是否在A股交易时段（含盘前15分钟缓冲与收盘后缓冲）。"""
    now = datetime.now(CN_TZ)
    # 周一至周五
    if now.weekday() >= 5:
        return False
    t = now.hour * 60 + now.minute
    # 9:15 - 15:30，覆盖 cron */30 9-15 的 15:30 那次执行
    return 9 * 60 + 15 <= t <= 15 * 60 + 30


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="指数多级别K线盘中增量更新")
    parser.add_argument("--dry-run", action="store_true", help="仅测试，不写DB")
    parser.add_argument("--force", action="store_true", help="非交易时段也执行")
    args = parser.parse_args()

    if not args.force and not is_trading_time():
        now = datetime.now(CN_TZ)
        print(f"[{now.strftime('%H:%M')}] 非交易时段，跳过（--force 可强制执行）")
        return 0

    now = datetime.now(CN_TZ)
    results = []
    total_new = 0

    print(f"[{now.strftime('%H:%M')}] 盘中增量更新开始")

    for code in INDICES:
        for tf in TIMEFRAMES:
            time.sleep(DELAY)
            try:
                r = update_one(code, tf, args.dry_run)
            except Exception as e:
                err_msg = str(e)[:80]
                print(f"  ❌ {INDICES[code]['name']} {TIMEFRAMES[tf]['name']}: 异常 ({err_msg})")
                results.append({"status": "error", "code": code, "tf": tf, "error": err_msg})
                continue

            results.append(r)

            if r["status"] == "updated":
                bars_str = ", ".join(r.get("bars", []))
                print(f"  ✅ {INDICES[code]['name']} {TIMEFRAMES[tf]['name']}: +{r['new_bars']}根 {bars_str}")
                total_new += r["new_bars"]
            elif r["status"] == "no_new_bars":
                pass  # 静默
            elif r["status"] == "up_to_date":
                pass  # 静默
            else:
                print(f"  ⚠️ {INDICES[code]['name']} {TIMEFRAMES[tf]['name']}: {r['status']}")

    updated = sum(1 for r in results if r["status"] == "updated")
    skipped = sum(1 for r in results if r["status"] in ("up_to_date", "no_new_bars"))
    errors = sum(1 for r in results if r["status"] not in ("updated", "up_to_date", "no_new_bars"))

    # ── 90分钟合成（从30分钟）──
    # 任意指数/周期有更新时，重新合成该指数的90分钟线
    updated_codes = {r["code"] for r in results if r.get("status") == "updated"}
    for code in INDICES:
        if code not in updated_codes:
            continue
        try:
            n = synthesize_90min_klines(code, args.dry_run)
            if n:
                print(f"  🔧 {INDICES[code]['name']}: 90分钟合成 {n}根")
        except Exception as e:
            print(f"  ❌ {INDICES[code]['name']}: 90分钟合成失败 ({str(e)[:80]})")

    print(f"[完成] 新增 {total_new} 根K线, 更新 {updated} 组, 跳过 {skipped} 组, 错误 {errors}")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
