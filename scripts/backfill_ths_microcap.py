#!/usr/bin/env python3
"""微盘股指数 (同花顺 883418) 历史回填。

背景 (2026-09-10)：TDX 880823 因接口封禁失效，改用同花顺 883418。
首次接入时 DB 只有当日几根，MACD 需要 >= 35 根才能计算，
因此需要一次性回填历史。

用法:
    python scripts/backfill_ths_microcap.py            # 回填
    python scripts/backfill_ths_microcap.py --dry-run  # 仅查看
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

DB_PATH = REPO_ROOT / "infra" / "data" / "kline_cache.db"
CODE = "883418"

# 同花顺周期码 → (timeframe名, klt)
# ⚠️ 重要：同花顺日线接口 (00) 不可信（同一天收盘在多个口径下矛盾且会被改写）。
# 本脚本的日线仅用于**很久以前的历史回填**（分钟线只回溯约 1 个月，
# 更早的历史只能靠 00 接口），且**会覆盖最近数据**，因此：
#   - 不要用它回填近期日线（近 1 个月请让 update_index_klines_intraday.py
#     从 30min 聚合，那才是权威源）
#   - 回填后必须立即跑 update_index_klines_intraday.py 用 30min 覆盖近期日线
PERIODS = {
    "00": ("daily", 101),
    "41": ("30min", 30),
    "50": ("60min", 60),
}
# 日线按年拉取（覆盖更长历史）；分钟线用 last.js（约140根）
# 只回填 <= 该日期的日线（近期交给 30min 聚合）
DAILY_HISTORY_UNTIL = "2026-07-23"
YEARS = [2024, 2025, 2026]

HEADERS = {
    "Referer": "https://q.10jqka.com.cn/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}


def _fetch(url: str) -> list[dict]:
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=30) as resp:
            text = resp.read().decode("utf-8", errors="ignore")
        m = re.search(r"\((.*)\)\s*;?\s*$", text, re.S)
        if not m:
            return []
        raw = [r for r in json.loads(m.group(1)).get("data", "").split(";") if r]
    except Exception as e:
        print(f"    [WARN] {url[-40:]} 失败: {str(e)[:60]}")
        return []

    out = []
    for row in raw:
        p = row.split(",")
        if len(p) < 6:
            continue
        try:
            t = p[0]
            bar_time = (
                f"{t[0:4]}-{t[4:6]}-{t[6:8]} {t[8:10]}:{t[10:12]}"
                if len(t) >= 12 else f"{t[0:4]}-{t[4:6]}-{t[6:8]}"
            )
            out.append({
                "bar_time": bar_time,
                "open": float(p[1]), "high": float(p[2]), "low": float(p[3]),
                "close": float(p[4]), "volume": float(p[5]),
                "amount": float(p[6]) if len(p) > 6 and p[6] else 0.0,
            })
        except (ValueError, IndexError):
            continue
    return out


def _synth_120(bars: list[dict]) -> list[dict]:
    merged = []
    for i in range(len(bars) - 1):
        b1, b2 = bars[i], bars[i + 1]
        hm1 = b1["bar_time"][11:16]
        hm2 = b2["bar_time"][11:16]
        if (hm1, hm2) in (("10:30", "11:30"), ("14:00", "15:00")):
            merged.append({
                "bar_time": b2["bar_time"], "open": b1["open"],
                "high": max(b1["high"], b2["high"]), "low": min(b1["low"], b2["low"]),
                "close": b2["close"],
                "volume": b1["volume"] + b2["volume"],
                "amount": b1["amount"] + b2["amount"],
            })
    return merged


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    collected: dict[str, dict[str, dict]] = {}

    for period, (tf, _klt) in PERIODS.items():
        bars: dict[str, dict] = {}
        if period == "00":
            for y in YEARS:
                url = f"https://d.10jqka.com.cn/v6/line/bk_{CODE}/{period}/{y}.js"
                got = _fetch(url)
                # 只保留历史部分，近期日线交给 30min 聚合（权威源）
                got = [b for b in got if b["bar_time"] <= DAILY_HISTORY_UNTIL]
                print(f"  日线 {y} (<= {DAILY_HISTORY_UNTIL}): {len(got)} 根")
                for b in got:
                    bars[b["bar_time"]] = b
                time.sleep(0.5)
        else:
            url = f"https://d.10jqka.com.cn/v6/line/bk_{CODE}/{period}/last.js"
            got = _fetch(url)
            print(f"  {tf} ({period}): {len(got)} 根")
            for b in got:
                bars[b["bar_time"]] = b
        collected[tf] = bars

    # 120min 由 60min 合成
    if collected.get("60min"):
        sixty = sorted(collected["60min"].values(), key=lambda k: k["bar_time"])
        collected["120min"] = {b["bar_time"]: b for b in _synth_120(sixty)}
        print(f"  120min 合成: {len(collected['120min'])} 根")

    total = sum(len(v) for v in collected.values())
    print(f"\n  合计 {total} 根待写入")
    if args.dry_run:
        print("  (dry-run，未写库)")
        return 0

    conn = sqlite3.connect(DB_PATH)
    written = 0
    for tf, bars in collected.items():
        for b in bars.values():
            conn.execute(
                """INSERT INTO index_klines
                   (code, timeframe, bar_time, open, high, low, close, volume, amount, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,datetime('now'))
                   ON CONFLICT(code, timeframe, bar_time) DO UPDATE SET
                     open=excluded.open, high=excluded.high, low=excluded.low,
                     close=excluded.close, volume=excluded.volume, amount=excluded.amount,
                     updated_at=datetime('now')""",
                (CODE, tf, b["bar_time"], b["open"], b["high"], b["low"],
                 b["close"], b["volume"], b["amount"]),
            )
            written += 1
    conn.commit()
    conn.close()
    print(f"  ✅ 写入 {written} 根")

    # 重算 MACD（日线）
    print("\n  重算 MACD...")
    import subprocess
    subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "update_index_klines_intraday.py"), "--force"],
        cwd=REPO_ROOT, check=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
