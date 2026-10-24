#!/usr/bin/env python3
"""批量 claim 判向（M3 direction 标注，spec 2026-10-24-m3-outcome-writeback）。

scope：stance ∈ {view, market-regime}，或 claim_type=stock-view 且
related_stocks 非空。已有 direction.annotated_at 的跳过（断点续跑），
--force 重判。逐条落盘（每判一条写一条，防中断丢失）。
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import yaml  # noqa: E402

from investment_engine.claim_direction import annotate_claim  # noqa: E402
from investment_engine.claim_outcome import write_block_to_yaml  # noqa: E402
from qing_investment.agent.tools.llm_client import (  # noqa: E402
    SENSENOVA_FALLBACK_MODELS, get_llm_client_with_fallback,
)

CLAIMS_DIR = PROJECT_ROOT / "knowledge" / "claims"


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


def in_scope(c: dict) -> bool:
    if str(c.get("stance") or "") in ("view", "market-regime"):
        return True
    return c.get("claim_type") == "stock-view" and bool(c.get("related_stocks"))


def main() -> int:
    ap = argparse.ArgumentParser(description="批量 claim 判向")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--claim-id", help="只判指定 claim（忽略 scope/续跑跳过）")
    ap.add_argument("--force", action="store_true", help="重判已有 direction 的 claim")
    args = ap.parse_args()

    llm = get_llm_client_with_fallback(
        provider="hermes_global",
        fallback_models=["openrouter:z-ai/glm-5.3-flash", "workbuddy:glm-5.3-flash",
                         *SENSENOVA_FALLBACK_MODELS],
    )

    counts = Counter()
    done = 0
    for yf, c in iter_claims():
        cid = c["id"]
        if args.claim_id and cid != args.claim_id:
            continue
        if not args.claim_id and not args.force:
            existing = c.get("direction") or {}
            if existing.get("annotated_at"):
                counts["skipped_done"] += 1
                continue
        if args.claim_id or in_scope(c):
            direction = annotate_claim(c, llm)
            counts[direction["value"]] += 1
            done += 1
            if not args.dry_run:
                write_block_to_yaml(yf, cid, "direction", direction)
            print(f"[{done}] {cid}: {direction['value']:<8} "
                  f"{direction.get('basis_kind', '')}/{direction.get('basis_code', '')} "
                  f"{(direction.get('rationale') or '')[:50]}", flush=True)
            if args.limit and done >= args.limit:
                break

    print(f"\n✅ 判向完成 {done} 条（跳过已有 {counts['skipped_done']}）；"
          f"分布: {dict((k, v) for k, v in counts.items() if k != 'skipped_done')}")
    if args.dry_run:
        print("   (dry-run，未写盘)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
