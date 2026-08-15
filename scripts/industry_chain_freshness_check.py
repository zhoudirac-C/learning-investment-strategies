#!/usr/bin/env python
"""产业链保鲜巡检入口（M5 提前项）。

建议每周五收盘后随 graduation_check 同跑。产物：logs/industry-chain-freshness.md。

手动: .venv/bin/python scripts/industry_chain_freshness_check.py [--stale-days 90]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from investment_engine.industry_chain.freshness import run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="产业链知识库保鲜巡检")
    parser.add_argument("--stale-days", type=int, default=90)
    args = parser.parse_args(argv)
    out = run(stale_days=args.stale_days)
    print(f"[freshness] 巡检报告 → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
