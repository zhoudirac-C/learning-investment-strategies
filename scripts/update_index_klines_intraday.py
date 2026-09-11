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
RECOMPUTE_BARS = 35     # 重算最近35根的MACD（保证EMA稳定）
DELAY = 1.0             # 请求间隔

# ---------------------------------------------------------------------------
# 数据获取：已收口到 qing_investment.marketdata（2026-09-11 统一数据源层）
#
# 原 510 行 fetch 层（东财/腾讯/TDX/同花顺 4 套抓取 + 解析 + 进程内熔断）
# 全部删除，降级链由 marketdata.router 提供：
#     腾讯(原生m120) → 东财 → TDX(strict) → 新浪(30/60) → 同花顺(ths登记指数)
# 熔断为 (source, capability) 粒度 + 半开自愈；strict 空语义=空即失败降级，
# 全链空抛 MarketDataError（不静默返 []，对齐 2026-09-10 修复纪律）。
# 字段序解析、新浪限流 UA、同花顺 00 日线不可信聚合、腾讯 301 坑等
# 经验已内嵌到 marketdata.sources 各适配器。
# ---------------------------------------------------------------------------

from qing_investment.marketdata import MarketDataError
from qing_investment.marketdata import router as _md


def fetch_latest_klines(code: str, klt: int, count: int = 5) -> list[dict]:
    """拉取最新 N 根K线（升序，统一 bar shape）。

    委托 marketdata.router.get_kline。降级链/熔断/strict 空语义见模块头注释。
    本脚本 INDICES 里 sh000932 等显式前缀代码直接透传（router 内部
    resolve_symbol 显式前缀优先，不会误判 000 段市场）。
    883418（ths 登记指数）自动直连同花顺。
    全部源失败抛 MarketDataError —— 调用方 update_one 捕获记 no_api_data。
    """
    kind = "index" if code in INDICES else "auto"
    try:
        bars, source = _md.get_kline(code, klt, count, kind=kind)
    except MarketDataError as e:
        print(f"    [WARN] {INDICES.get(code, {}).get('name', code)} klt={klt} 全源失败: {str(e)[:120]}")
        return []
    return bars


def _ema(values: list[float], period: int) -> list[float | None]:
    if len(values) < period:
        return [None] * len(values)
    k = 2 / (period + 1)
    result: list[float | None] = [None] * (period - 1)
    result.append(sum(values[:period]) / period)
    for v in values[period:]:
        result.append(v * k + result[-1] * (1 - k))  # type: ignore[operator]
    return result


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
    """从30分钟K线合成90分钟K线，计算MACD后入库。

    ⚠️ 必须**按交易日分组**切分（2026-09-10 修复）。

    原实现用 `for g in range(len(rows) // 3)` 全局按 bar 数硬切，问题：
      1. **跨日拼接**：某日 30min 根数 != 9 时错位传染到之后所有交易日。
         实测上证 249 组里 48 组混了不同日期的数据。
      2. **跨午休拼接**：11:30+13:00+13:30 拼成的"90min"实际跨 2 小时。
      3. **末组残缺**：7/9 个指数 30min 总数不整除 3，末尾 1-2 根被静默丢弃。

    污染会传导到盲判 `_compute_cycle_states`（用 90min 做 recent_bottom
    识别）→ cycle_state / "反弹第N天" 判断失真。

    修复：按日分组，日内每 3 根切一根；不足 3 根的尾组跳过
    （盘中不完整日，待数据补齐后下次运行自动纳入）。
    """
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

    # 按交易日分组（防止跨日拼接与错位传染）
    by_day: dict[str, list] = {}
    for r in rows:
        by_day.setdefault(r["bar_time"][:10], []).append(r)

    bars_90min = []
    for day in sorted(by_day):
        day_rows = by_day[day]
        for i in range(0, len(day_rows) - 2, 3):  # 不足3根的尾组跳过
            group = day_rows[i:i + 3]
            bars_90min.append({
                "bar_time": group[-1]["bar_time"],
                "open": group[0]["open"],
                "high": max(r["high"] for r in group),
                "low": min(r["low"] for r in group),
                "close": group[-1]["close"],
                "volume": sum(r["volume"] for r in group),
                "amount": sum(r["amount"] for r in group if r["amount"]),
            })

    if not bars_90min:
        conn.close()
        return 0

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
