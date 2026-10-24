#!/usr/bin/env python3
"""claim 市场结果结算回写（M3，spec 2026-10-24-m3-outcome-writeback）。

对有 direction（bullish/bearish）的 claim 跑 5 交易日 forward 结算，outcome
块落盘。已有终态 outcome（非 pending_data）的跳过；pending_data 重跑自动
转终态；--force 全部重结。逐条落盘防中断丢失。
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import yaml  # noqa: E402

from investment_engine.claim_outcome import (  # noqa: E402
    DEFAULT_KLINE_DB, settle_claim, write_outcome_to_yaml,
)

CLAIMS_DIR = PROJECT_ROOT / "knowledge" / "claims"
FINAL_RESULTS = {"hit", "miss", "neutral_window", "insufficient_data"}


def iter_claims():
    for yf in sorted(CLAIMS_DIR.glob("*.yaml")):
        try:
            data = yaml.safe_load(yf.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[parse-skip] {yf.name}: {e}")
            continue
        if data is None:
            continue
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = data.get("claims") if "claims" in data else [data]
            if not isinstance(items, list):
                items = [items]
        else:
            continue
        for c in items:
            if isinstance(c, dict) and c.get("id"):
                yield yf, c


def main() -> int:
    ap = argparse.ArgumentParser(description="claim 市场结果结算回写")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--claim-id")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--db", default=str(DEFAULT_KLINE_DB))
    args = ap.parse_args()

    counts = Counter()
    done = 0
    for yf, c in iter_claims():
        cid = c["id"]
        if args.claim_id and cid != args.claim_id:
            continue
        direction = c.get("direction") or {}
        if direction.get("value") not in ("bullish", "bearish"):
            counts["no_direction"] += 1
            continue
        prev = (c.get("outcome") or {}).get("result")
        if not args.force and not args.claim_id and prev in FINAL_RESULTS:
            counts["skipped_final"] += 1
            continue
        try:
            outcome = settle_claim(c, args.db)
        except ValueError as e:
            counts["error"] += 1
            print(f"[error] {cid}: {e}")
            continue
        counts[outcome["result"]] += 1
        done += 1
        if not args.dry_run:
            write_outcome_to_yaml(yf, cid, outcome)
        print(f"[{done}] {cid}: {outcome['result']:<18} "
              f"{outcome.get('basis_code', '')} "
              f"{outcome.get('fwd_return_pct', '')} {(outcome.get('reason') or '')[:40]}",
              flush=True)
        if args.limit and done >= args.limit:
            break

    print(f"\n✅ 结算 {done} 条（跳过终态 {counts['skipped_final']}，无方向 "
          f"{counts['no_direction']}，错误 {counts['error']}）")
    dist = {k: v for k, v in counts.items()
            if k not in ("skipped_final", "no_direction", "error")}
    print(f"   分布: {dist}")
    if args.dry_run:
        print("   (dry-run，未写盘)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
