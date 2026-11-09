#!/usr/bin/env python
"""Qing-Agent 冻结记录结算与每日/滚动可靠性报告。"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from investment_engine.qing_validation.records import normalize_day
from investment_engine.qing_validation.report import write_reports
from investment_engine.qing_validation.settle import settle_records


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Qing-Agent 市场验证与报告")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("settle", "report", "run"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--date", default=date.today().isoformat())
        subparser.add_argument("--root", default="infra/data/qing_agent")
        subparser.add_argument("--db", default="infra/data/kline_cache.db")
        subparser.add_argument("--out-dir", default="logs")
        if command in {"settle", "run"}:
            subparser.add_argument("--config-dir", default="config/stock_monitor")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    day = normalize_day(args.date)
    root = Path(args.root)
    db_path = Path(args.db)
    if args.command in {"settle", "run"}:
        stats = settle_records(
            day,
            root=root,
            config_dir=Path(args.config_dir),
            db_path=db_path,
        )
        print(f"[settle] {stats}")
    if args.command in {"report", "run"}:
        paths = write_reports(
            day,
            root=root,
            db_path=db_path,
            out_dir=Path(args.out_dir),
        )
        print(f"[daily] {paths['daily']}")
        print(f"[reliability] {paths['reliability']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
