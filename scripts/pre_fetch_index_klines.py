#!/usr/bin/env python3
"""
指数多级别K线预拉取 + MACD计算 + 入库。

用法:
  python scripts/pre_fetch_index_klines.py           # 拉取全部（~4个月）
  python scripts/pre_fetch_index_klines.py --days 30  # 仅拉30天
  python scripts/pre_fetch_index_klines.py --dry-run   # 仅测试，不写DB

设计目标:
  - 支持 4 个指数 × 4 个时间周期（30/60/120分钟 + 日线）
  - 拉取后立即计算 MACD（DIF/DEA/柱）
  - 存入 SQLite，与个股日K缓存共享同一DB
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# ── 路径 ──
REPO_ROOT = Path(__file__).resolve().parents[1] if __file__ != "__main__" else Path.cwd()
DB_PATH = REPO_ROOT / "infra" / "data" / "kline_cache.db"
CN_TZ = timezone(timedelta(hours=8))

# ── 配置 ──
INDICES = {
    "sh000001": {"secid": "1.000001", "name": "上证指数"},
    "sh000985": {"secid": "1.000985", "name": "中证全指"},
    "sz399001": {"secid": "0.399001", "name": "深证成指"},
    "sz399006": {"secid": "0.399006", "name": "创业板指"},
    "sh000932": {"secid": "1.000932", "name": "中证2000"},
}

TIMEFRAMES = {
    "30min": {"klt": 30, "name": "30分钟"},
    "60min": {"klt": 60, "name": "60分钟"},
    "120min": {"klt": 120, "name": "120分钟"},
    "daily": {"klt": 101, "name": "日线"},
}

# 每个级别拉取的数量（预留buffer）
DAYS_DEFAULT = 120  # ~4个月交易日
KLINES_PER_DAY = {"30min": 8, "60min": 4, "120min": 2, "daily": 1}

# API限流控制
DELAY_PER_REQUEST = 1.5   # 两次请求间隔（秒）
MAX_RETRIES = 3


# ═══════════════════════════════════════════════════════════
# DB 层
# ═══════════════════════════════════════════════════════════

def init_db() -> None:
    """创建 index_klines 表（幂等）。"""
    import sqlite3
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS index_klines (
            code       TEXT NOT NULL,
            timeframe  TEXT NOT NULL,
            bar_time   TEXT NOT NULL,
            open       REAL,
            high       REAL,
            low        REAL,
            close      REAL,
            volume     REAL,
            amount     REAL,
            dif        REAL,
            dea        REAL,
            macd_hist  REAL,
            updated_at TEXT,
            PRIMARY KEY (code, timeframe, bar_time)
        );

        CREATE INDEX IF NOT EXISTS idx_index_klines_code_tf
            ON index_klines(code, timeframe);

        CREATE TABLE IF NOT EXISTS index_klines_meta (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
    """)
    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════════════
# API 拉取
# ═══════════════════════════════════════════════════════════

def _http_get(url: str, timeout: float = 20.0) -> str:
    headers = {
        "Referer": "https://quote.eastmoney.com/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode()


def fetch_index_klines(code: str, klt: int, count: int) -> list[dict]:
    """
    拉取指数K线。返回按时间升序排列的 K 线列表。
    每项: {"bar_time": "2026-06-12 14:00", "open": ..., "high": ..., "low": ..., "close": ..., "volume": ..., "amount": ...}
    """
    secid = INDICES[code]["secid"]
    url = (
        "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        f"?secid={secid}"
        "&fields1=f1,f2,f3,f4,f5,f6"
        "&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
        f"&klt={klt}&fqt=1&end=20500101&lmt={count + 5}"
    )

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            data = json.loads(_http_get(url))
            raw = data.get("data", {}).get("klines", [])
            if not raw:
                return []

            result = []
            for row in raw:
                parts = row.split(",")
                if len(parts) < 6:
                    continue
                try:
                    # 日线格式: "2026-06-12,4017.86,..."
                    # 分钟格式: "2026-06-12 14:00,4045.69,..."
                    bar_time = parts[0]
                    result.append({
                        "bar_time": bar_time,
                        "open": float(parts[1]),
                        "close": float(parts[2]),
                        "high": float(parts[3]),
                        "low": float(parts[4]),
                        "volume": float(parts[5]),
                        "amount": float(parts[6]) if len(parts) > 6 else 0.0,
                    })
                except (ValueError, IndexError):
                    continue

            # 东财返回可能是升序也可能是降序，显式按时间排序
            result.sort(key=lambda k: k["bar_time"])
            # 截取最后 count 根
            return result[-count:] if len(result) > count else result

        except Exception as e:
            if attempt < MAX_RETRIES:
                time.sleep(5 * attempt)
            else:
                print(f"  ❌ {code} klt={klt}: 重试耗尽 ({str(e)[:60]})")

    return []


# ═══════════════════════════════════════════════════════════
# MACD 计算
# ═══════════════════════════════════════════════════════════

def _ema(values: list[float], period: int) -> list[float | None]:
    """计算指数移动平均。返回与输入同长度的列表，前 period-1 个为 None。"""
    if len(values) < period:
        return [None] * len(values)

    k = 2 / (period + 1)
    result: list[float | None] = [None] * (period - 1)
    # 初始值为前 period 个的 SMA
    result.append(sum(values[:period]) / period)
    for v in values[period:]:
        result.append(v * k + result[-1] * (1 - k))
    return result


def compute_macd(klines: list[dict]) -> list[dict]:
    """
    为K线列表计算 MACD。就地添加 dif/dea/macd_hist 字段。
    只有在数据量足够（>=26根）时才计算真实值，否则填 None。
    """
    closes = [k["close"] for k in klines]
    n = len(closes)

    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)

    # DIF = EMA12 - EMA26
    dif = []
    for i in range(n):
        if ema12[i] is not None and ema26[i] is not None:
            dif.append(ema12[i] - ema26[i])
        else:
            dif.append(None)

    # DEA = EMA(DIF, 9)
    # 先提取 DIF 非 None 的部分
    valid_dif = [d for d in dif if d is not None]
    valid_start = next(i for i, d in enumerate(dif) if d is not None)
    dea_raw = _ema(valid_dif, 9)

    dea: list[float | None] = [None] * n
    for i, val in enumerate(dea_raw):
        if val is not None:
            dea[valid_start + i] = val

    # MACD柱 = (DIF - DEA) * 2
    macd_hist = []
    for i in range(n):
        if dif[i] is not None and dea[i] is not None:
            macd_hist.append((dif[i] - dea[i]) * 2)
        else:
            macd_hist.append(None)

    for i, k in enumerate(klines):
        k["dif"] = round(dif[i], 4) if dif[i] is not None else None
        k["dea"] = round(dea[i], 4) if dea[i] is not None else None
        k["macd_hist"] = round(macd_hist[i], 4) if macd_hist[i] is not None else None  # type: ignore[arg-type]

    return klines


# ═══════════════════════════════════════════════════════════
# 入库
# ═══════════════════════════════════════════════════════════

def save_index_klines(code: str, timeframe: str, klines: list[dict]) -> int:
    """保存指数K线到DB。先删旧、再插入（覆盖策略）。返回写入条数。"""
    import sqlite3

    if not klines:
        return 0

    now = datetime.now(CN_TZ).isoformat()
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")

    # 删除该指数+周期的旧数据
    conn.execute(
        "DELETE FROM index_klines WHERE code = ? AND timeframe = ?",
        (code, timeframe)
    )

    conn.executemany(
        """INSERT INTO index_klines
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
            for k in klines
        ]
    )
    conn.commit()
    conn.close()
    return len(klines)


def mark_fetch_complete(date_str: str) -> None:
    """标记某日预拉取完成。"""
    import sqlite3
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(
        "INSERT OR REPLACE INTO index_klines_meta (key, value) VALUES (?, ?)",
        (f"ready_index_{date_str}", date_str)
    )
    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════════════
# 90分钟合成
# ═══════════════════════════════════════════════════════════

def synthesize_90min_klines(code: str, dry_run: bool = False) -> int:
    """从30分钟K线合成90分钟K线，计算MACD后入库。返回合成根数。"""
    import sqlite3

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # 读取30分钟数据
    rows = conn.execute(
        "SELECT * FROM index_klines WHERE code=? AND timeframe='30min' ORDER BY bar_time ASC",
        (code,)
    ).fetchall()

    if len(rows) < 3:
        conn.close()
        return 0

    # 每3根合并成1根90分钟
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

    # 计算MACD
    bars_90min = compute_macd(bars_90min)

    if not dry_run:
        save_index_klines(code, "90min", bars_90min)

    conn.close()
    return len(bars_90min)


# ═══════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════

def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="指数多级别K线预拉取")
    parser.add_argument("--days", type=int, default=DAYS_DEFAULT, help="拉取天数（默认120）")
    parser.add_argument("--dry-run", action="store_true", help="仅测试，不写DB")
    parser.add_argument("--indices", nargs="*", default=list(INDICES.keys()), help="指定指数")
    parser.add_argument("--timeframes", nargs="*", default=list(TIMEFRAMES.keys()), help="指定周期")
    args = parser.parse_args()

    # ── 初始化 ──
    if not args.dry_run:
        init_db()

    today = datetime.now(CN_TZ).strftime("%Y-%m-%d")
    total_bars = 0
    total_saved = 0
    total_fail = 0

    expected_requests = len(args.indices) * len(args.timeframes)
    print(f"[{datetime.now(CN_TZ).strftime('%H:%M')}] 开始拉取指数多级别K线")
    print(f"  指数: {args.indices}")
    print(f"  周期: {args.timeframes}")
    print(f"  天数: {args.days}")
    print(f"  预计 {expected_requests} 次API请求 (~{expected_requests * DELAY_PER_REQUEST:.0f}秒)\n")

    for code in args.indices:
        idx_name = INDICES[code]["name"]
        for tf in args.timeframes:
            tf_name = TIMEFRAMES[tf]["name"]
            klt = TIMEFRAMES[tf]["klt"]
            bars_per_day = KLINES_PER_DAY[tf]
            count = args.days * bars_per_day + 40  # +40根buffer确保MACD有足够历史

            print(f"  📡 {idx_name}({code}) {tf_name} ... ", end="", flush=True)
            klines = fetch_index_klines(code, klt, count)

            if not klines:
                print(f"❌ 无数据")
                total_fail += 1
                continue

            # 计算 MACD
            klines = compute_macd(klines)

            # 统计有效数据
            valid_bars = len(klines)
            macd_valid = sum(1 for k in klines if k.get("dif") is not None)
            total_bars += valid_bars

            if not args.dry_run:
                saved = save_index_klines(code, tf, klines)
                total_saved += saved
                print(f"✅ {valid_bars}根K线 (MACD有效 {macd_valid}根)")
            else:
                latest = klines[-1]
                print(f"✅ {valid_bars}根K线 (MACD有效 {macd_valid}根) 最新: {latest['bar_time']} C:{latest['close']:.2f}")

            # API限流
            time.sleep(DELAY_PER_REQUEST)

    # ── 90分钟合成（从30分钟）──
    print(f"\n  🔧 合成90分钟K线...")
    for code in args.indices:
        n = synthesize_90min_klines(code, args.dry_run)
        if n:
            total_bars += n
            if not args.dry_run:
                total_saved += n
            print(f"    {INDICES[code]['name']}: {n}根")

    # ── 标记完成 ──
    if not args.dry_run:
        mark_fetch_complete(today)

    print(f"\n[完成] 总计 {total_bars} 根K线, 写入 {total_saved} 条, 失败 {total_fail}")
    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
