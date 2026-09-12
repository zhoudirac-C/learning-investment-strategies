#!/usr/bin/env python3
"""stocks_kline 键格式一次性迁移 CLI（2026-09-12 键格式统一）。

把 kline_cache.db 里的裸码键 / 错标键 / 旧市场前缀键统一迁移到规范键
{6位数字}.{SH|SZ|BJ}（与 watchlist/stock_pool/positions 配置码一致）。
碰撞（多旧键归一 / 与现存规范键并存）按 MAX(trade_date) 取更新者整序列。

用法:
    .venv/bin/python scripts/migrate_kline_keys.py            # dry-run 报告
    .venv/bin/python scripts/migrate_kline_keys.py --apply    # 备份后执行
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from qing_investment.kline_cache import migrate_kline_keys  # noqa: E402

DB_PATH = REPO / "infra" / "data" / "kline_cache.db"


def _stats(db: Path) -> dict:
    conn = sqlite3.connect(str(db))
    q = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
    # 非规范键 = 非 IDX 且非 {6位数字}.{后缀} 形态
    s = {
        "total_keys": q("SELECT COUNT(DISTINCT code) FROM stocks_kline"),
        "non_canonical": q(
            "SELECT COUNT(DISTINCT code) FROM stocks_kline "
            "WHERE code NOT LIKE '%.%' AND code NOT LIKE 'IDX%'"
        ),
        "idx_alias": q(
            "SELECT COUNT(DISTINCT code) FROM stocks_kline WHERE code LIKE 'IDX%'"
        ),
        "rows_total": q("SELECT COUNT(*) FROM stocks_kline"),
    }
    conn.close()
    return s


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="实际执行（默认 dry-run）")
    ap.add_argument("--db", type=Path, default=DB_PATH)
    args = ap.parse_args()
    db = args.db

    print("== 迁移前 ==")
    for k, v in _stats(db).items():
        print(f"  {k}: {v}")

    backup = None
    if args.apply:
        backup = db.with_name(f"kline_cache.backup-{datetime.now():%Y%m%d-%H%M%S}.db")
        shutil.copy2(db, backup)
        print(f"[BACKUP] {backup}")

    report = migrate_kline_keys(db_path=db, dry_run=not args.apply)
    print(f"\n== {'执行' if args.apply else 'DRY-RUN'} 报告 ==")
    print(f"  rekeyed ({len(report['rekeyed'])}):")
    for old, new in sorted(report["rekeyed"].items()):
        print(f"    {old} -> {new}")
    print(
        f"  collisions/dropped ({len(report['collisions'])}): "
        f"{report['collisions'][:20]}" + (" ..." if len(report["collisions"]) > 20 else "")
    )

    print("\n== 迁移后 ==")
    for k, v in _stats(db).items():
        print(f"  {k}: {v}")

    conn = sqlite3.connect(str(db))
    residual = [
        r[0] for r in conn.execute(
            "SELECT DISTINCT code FROM stocks_kline WHERE code NOT LIKE '%.%' "
            "AND code NOT LIKE 'IDX%'"
        ).fetchall()
    ]
    conn.close()
    if residual:
        print(f"\n[WARN] 仍残留非规范键 {len(residual)} 个: {residual[:20]}")
        return 1
    print("\n[OK] 全部键已统一为规范后缀键（IDX 别名豁免保留）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
