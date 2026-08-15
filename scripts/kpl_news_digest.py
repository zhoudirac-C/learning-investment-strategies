#!/usr/bin/env python
"""KPL 资讯初调摘要入口（v2.2 §16.4 初调层）。

建议在 kpl_daily_fetch 之后跑（cron 17:50 左右）。幂等覆盖写。

手动:
  .venv/bin/python scripts/kpl_news_digest.py [--date 2026-08-14]
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from investment_engine.kpl.digest import run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="KPL 资讯初调摘要")
    parser.add_argument("--date", default=date.today().isoformat())
    args = parser.parse_args(argv)
    out = run(args.date)
    if out is None:
        print(f"[digest] {args.date} 无资讯落盘，跳过")
        return 0
    print(f"[digest] {args.date} → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
