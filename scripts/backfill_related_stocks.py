#!/usr/bin/env python3
"""
Backfill related_stocks in YAML claim files with 6-digit stock codes.

Only processes stock-view claims where subject is a stock name.
Looks up code from STOCK_NAME_TO_CODE (positions.yaml + watchlist.yaml).
Never writes bare code without name — skips if code not found.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import migrate_claims_to_neo4j as _mig

CLAIMS_DIR = REPO_ROOT / "knowledge" / "claims"


def process_file(path: Path, dry_run: bool) -> int:
    """Process a single YAML file. Returns number of claims modified."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return 0

    claims_list = []
    root_is_list = False
    if isinstance(data, list):
        claims_list = data
        root_is_list = True
    elif isinstance(data, dict):
        if "claims" in data:
            claims_list = data["claims"]
        else:
            claims_list = [data]
    else:
        return 0

    modified = 0
    for c in claims_list:
        if not isinstance(c, dict):
            continue

        cid = c.get("id", "")
        ct = c.get("claim_type", "")

        # Only process stock-view and sector-theme claims
        if ct not in ("stock-view", "sector-theme"):
            continue

        # Get subject (the stock name)
        subject = (c.get("subject") or "").strip()
        if not subject:
            continue

        # Skip if subject is a pattern/sentence (not a stock name)
        if len(subject) > 10 or "——" in subject or "：" in subject or "（" in subject:
            continue

        # Look up code from STOCK_NAME_TO_CODE
        code = _mig.STOCK_NAME_TO_CODE.get(subject)
        if not code:
            continue

        # Build entry in "股票名(6位代码)" format
        entry = f"{subject}({code})"

        # Get existing related_stocks
        existing = c.get("related_stocks")
        if not isinstance(existing, list):
            existing = []
            c["related_stocks"] = existing

        # Check if already exists
        if entry in existing:
            continue

        # Check for name-only duplicate
        has_name_only = subject in existing
        if has_name_only:
            # Replace name-only with name+code
            existing[:] = [entry if item == subject else item for item in existing]
        else:
            existing.append(entry)

        modified += 1

    if modified > 0 and not dry_run:
        if root_is_list:
            output = data
        elif "claims" in data:
            data["claims"] = claims_list
            output = data
        else:
            output = data

        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(output, f, allow_unicode=True, default_flow_style=None, sort_keys=False)

    return modified


def main():
    parser = argparse.ArgumentParser(description="Backfill stock codes in YAML claims")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    args = parser.parse_args()

    # Pre-warm the mapping
    _mig._load_stock_name_mapping()
    print(f"📋 STOCK_NAME_TO_CODE has {len(_mig.STOCK_NAME_TO_CODE)} entries")

    total_modified = 0
    for yf in sorted(CLAIMS_DIR.glob("*.yaml")):
        modified = process_file(yf, dry_run=args.dry_run)
        if modified:
            status = "[DRY RUN]" if args.dry_run else "[MODIFIED]"
            print(f"  {status} {yf.name}: {modified} claims")
            total_modified += modified

    mode = "DRY RUN (no changes)" if args.dry_run else "applied"
    print(f"\n✅ Done. {total_modified} claims modified ({mode}).")


if __name__ == "__main__":
    main()
