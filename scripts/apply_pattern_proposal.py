#!/usr/bin/env python
"""应用人工评审过的 pattern validation 提案（--dry-run 预览不落盘）。

用法: .venv/bin/python scripts/apply_pattern_proposal.py framework/proposals/<file>.yaml
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from investment_engine.pattern_eval.apply import apply_proposal


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="应用 pattern validation 提案")
    parser.add_argument("proposal")
    parser.add_argument("--patterns", default="framework/reasoning-patterns.yaml")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    report = apply_proposal(args.proposal, patterns_path=args.patterns,
                            dry_run=args.dry_run)
    print(f"[applied] {report['applied']}")
    for s in report["skipped"]:
        print(f"[skipped] {s['pattern_id']}: {s['reason']}")
    if args.dry_run:
        print("[dry-run] 未落盘")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
