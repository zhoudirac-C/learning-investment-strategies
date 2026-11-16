#!/usr/bin/env python3
"""查询鳄鱼规则演进待办，或应用用户已批准的演进提案。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from investment_engine.pattern_eval.gator_evolution import (
    apply_gator_evolution,
    list_pending,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("proposal", nargs="?")
    parser.add_argument(
        "--patterns", default=str(REPO_ROOT / "framework/reasoning-patterns-gator.yaml")
    )
    parser.add_argument(
        "--state",
        default=str(REPO_ROOT / "infra/data/gator_pattern_evolution/state.json"),
    )
    parser.add_argument("--claims-dir", default=str(REPO_ROOT / "knowledge/claims"))
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--list-pending", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if args.list_pending:
        if args.proposal:
            parser.error("--list-pending 不接受 proposal")
        report = list_pending(
            patterns_path=Path(args.patterns),
            state_path=Path(args.state),
            claims_dir=Path(args.claims_dir),
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    if not args.proposal:
        parser.error("需要 proposal，或使用 --list-pending")
    report = apply_gator_evolution(
        Path(args.proposal),
        patterns_path=Path(args.patterns),
        state_path=Path(args.state),
        claims_dir=Path(args.claims_dir),
        repo_root=Path(args.repo_root),
        dry_run=args.dry_run,
    )
    print(f"[version] {report['version']}")
    print(f"[applied] {len(report['applied'])}")
    print(f"[skipped] {len(report['skipped'])}")
    if args.dry_run:
        print(report["diff"])
        print("[dry-run] 未落盘")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
