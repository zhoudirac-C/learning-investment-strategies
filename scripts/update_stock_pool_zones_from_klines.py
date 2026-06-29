#!/usr/bin/env python3
"""基于 SQLite K线缓存更新 stock_pool.yaml 的 entry.primary_zone。

用法：
    cd ~/learning-investment-strategies
    python3 scripts/update_stock_pool_zones_from_klines.py [--dry-run]

逻辑：
    1. 读取 stock_pool.yaml 中所有标的。
    2. 从 kline_cache.db 读取最新日K（今日收盘价、最低价、涨跌幅、MA20）。
    3. 当下列条件满足时重新计算介入区间：
       - 当前价高于原区间上沿 20% 以上，或低于原区间下沿 15% 以上（区间失效）。
       - method 含“涨停回踩”且今日涨停（涨幅 >= 9.5%），需以涨停价为锚重新算回踩区间。
    4. 按 method 选择锚点：
       - 涨停回踩法/涨停回踩补缺口：close * [0.93, 0.98]
       - 板块共振法：close * [0.95, 0.99]
       - 分歧日回踩法/分歧日回踩：close * [0.97, 1.00]
       - 算力材料波动法：close * [0.97, 1.01]
       - 均线法：min(close, MA20) * [0.97, 1.01]
       - 量能回踩法：close * [0.95, 0.99]
       - 情绪回踩法：close * [0.94, 0.98]
       - 联动法：close * [0.95, 0.99]
       - 回撤法：close * [0.92, 0.97]
       - 其他：close * [0.94, 0.99]
    5. 旧区间自动备份到 entry.backup_zones（避免覆盖人工判断）。
    6. 若 hard_stop 比新区间下沿还高，同步下调为下沿 * 0.96。
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

CN_TZ = timezone(timedelta(hours=8))
REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "config" / "stock_monitor"
DB_PATH = REPO_ROOT / "infra" / "data" / "kline_cache.db"


# ── YAML 工具 ──
def load_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_yaml(path: Path, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(
            data,
            f,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            width=120,
        )


# ── K线读取 ──
def get_today_kline(conn: sqlite3.Connection, code: str) -> dict | None:
    row = conn.execute(
        """SELECT open, high, low, close, pct_change, volume, trade_date
           FROM stocks_kline
           WHERE code = ?
           ORDER BY trade_date DESC
           LIMIT 1""",
        (code,),
    ).fetchone()
    return dict(row) if row else None


def get_ma20(conn: sqlite3.Connection, code: str) -> float | None:
    rows = conn.execute(
        """SELECT close FROM stocks_kline
           WHERE code = ? AND close IS NOT NULL
           ORDER BY trade_date DESC
           LIMIT 20""",
        (code,),
    ).fetchall()
    closes = [r["close"] for r in rows]
    if len(closes) < 20:
        return None
    return sum(closes) / len(closes)


# ── 区间计算 ──
def zone_from_method(method: str, close: float, ma20: float | None) -> tuple[float, float] | None:
    """根据 method 计算新的介入区间。"""
    m = (method or "").strip()

    if "涨停回踩" in m:
        return round(close * 0.93, 2), round(close * 0.98, 2)
    if "板块共振" in m:
        return round(close * 0.95, 2), round(close * 0.99, 2)
    if "分歧日回踩" in m or ("分歧日" in m and "回踩" in m):
        return round(close * 0.97, 2), round(close * 1.00, 2)
    if "算力材料波动" in m:
        return round(close * 0.97, 2), round(close * 1.01, 2)
    if "均线" in m:
        # 价格与 MA20 偏离在 10% 以内时，以 MA20 为锚；否则以收盘价为锚，避免预期过深回踩
        if ma20 and abs(close - ma20) / close <= 0.10:
            return round(ma20 * 0.97, 2), round(ma20 * 1.01, 2)
        return round(close * 0.95, 2), round(close * 0.99, 2)
    if "量能回踩" in m:
        return round(close * 0.95, 2), round(close * 0.99, 2)
    if "情绪回踩" in m:
        return round(close * 0.94, 2), round(close * 0.98, 2)
    if "联动" in m:
        return round(close * 0.95, 2), round(close * 0.99, 2)
    if "回撤法" in m:
        return round(close * 0.92, 2), round(close * 0.97, 2)

    # 默认 fallback
    return round(close * 0.94, 2), round(close * 0.99, 2)


def is_zone_stale(current: list | None, close: float) -> bool:
    """判断当前区间是否已失效。"""
    if not current or len(current) != 2:
        return True
    low, high = float(current[0]), float(current[1])
    if low <= 0 or high <= 0:
        return True
    # 收盘价超出区间上沿 20% 以上，或低于下沿 15% 以上
    if close > high * 1.20 or close < low * 0.85:
        return True
    return False


def should_skip_by_method(method: str) -> bool:
    """明确不写介入区间的票跳过。"""
    m = (method or "").strip()
    if "不设介入区间" in m:
        return True
    if "纯观察" in m and "回踩" not in m:
        return True
    return False


# ── 主流程 ──
def main() -> int:
    parser = argparse.ArgumentParser(description="基于K线缓存更新 stock_pool 介入区间")
    parser.add_argument("--dry-run", action="store_true", help="只打印变更，不写入文件")
    parser.add_argument("--force", action="store_true", help="强制重算所有非跳过标的的介入区间")
    args = parser.parse_args()

    pool_path = CONFIG_PATH / "stock_pool.yaml"
    pool = load_yaml(pool_path)
    if not pool or "stocks" not in pool:
        print("[ERROR] 无法读取 stock_pool.yaml", file=sys.stderr)
        return 1

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    updated = 0
    skipped = 0
    unchanged = 0
    today_str = datetime.now(CN_TZ).strftime("%Y-%m-%d")

    for stock in pool["stocks"]:
        code = stock.get("code", "")
        name = stock.get("name", "")
        entry = stock.setdefault("entry", {})
        method = entry.get("method", "")

        if should_skip_by_method(method):
            skipped += 1
            continue

        kline = get_today_kline(conn, code)
        if not kline:
            print(f"  ⚠️ {code} {name}: 无K线数据，跳过")
            skipped += 1
            continue

        close = float(kline["close"])
        pct_change = float(kline["pct_change"] or 0)
        ma20 = get_ma20(conn, code)

        current_zone = entry.get("primary_zone")
        is_limit_up = pct_change >= 9.5

        # 更新触发条件：强制模式、区间失效，或涨停回踩票今日涨停
        need_update = args.force or is_zone_stale(current_zone, close) or (
            is_limit_up and "涨停回踩" in method
        )

        if not need_update:
            unchanged += 1
            continue

        new_zone = zone_from_method(method, close, ma20)
        if not new_zone:
            skipped += 1
            continue

        new_zone_list = [new_zone[0], new_zone[1]]

        # 备份旧区间
        if current_zone and current_zone != new_zone_list:
            backups = entry.setdefault("backup_zones", [])
            if not any(
                isinstance(b, list) and len(b) == 2 and b == current_zone
                for b in backups
            ):
                backups.insert(0, current_zone)

        entry["primary_zone"] = new_zone_list

        # hard_stop 同步：不存在、高于区间下沿、或过于宽松（< 下沿*0.90）时，重置为下沿*0.96
        try:
            hs_raw = entry.get("hard_stop")
            hs = float(hs_raw) if hs_raw is not None else None
        except (TypeError, ValueError):
            hs = None
        if hs is None or hs > new_zone[0] or hs < new_zone[0] * 0.90:
            entry["hard_stop"] = round(new_zone[0] * 0.96, 2)

        # 记录本次更新来源
        human_note = stock.setdefault("human_note", {})
        if isinstance(human_note, dict):
            human_note["kline_zone_updated_at"] = today_str
            human_note["kline_zone_update_reason"] = (
                "limit_up_recalc" if (is_limit_up and "涨停回踩" in method) else "stale_zone_recalc"
            )

        updated += 1
        print(
            f"  {code} {name}: {current_zone} → {new_zone_list} "
            f"(close={close:.2f}, pct={pct_change:+.2f}%, method={method})"
        )

    conn.close()

    pool["updated_at"] = today_str

    if args.dry_run:
        print(
            f"\n[DRY-RUN] 本次将更新 {updated} 只，跳过 {skipped} 只，"
            f"保持不变 {unchanged} 只。"
        )
        return 0

    save_yaml(pool_path, pool)
    print(
        f"\n[OK] {pool_path} 已更新: {updated} 只更新，"
        f"{skipped} 只跳过，{unchanged} 只保持不变。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
