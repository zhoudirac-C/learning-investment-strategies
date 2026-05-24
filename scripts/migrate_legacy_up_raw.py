#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from qing_investment.legacy_migration import migrate_legacy_up_raw


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--legacy-root",
        type=Path,
        default=Path(os.environ["QING_LEGACY_UP_RAW_ROOT"]).expanduser()
        if os.environ.get("QING_LEGACY_UP_RAW_ROOT")
        else None,
        help="Legacy UP raw root. Defaults to QING_LEGACY_UP_RAW_ROOT.",
    )
    parser.add_argument("--target-root", type=Path, default=Path.cwd())
    parser.add_argument("--min-raw", type=int, default=387)
    args = parser.parse_args()

    if args.legacy_root is None:
        parser.error("set --legacy-root or QING_LEGACY_UP_RAW_ROOT")

    manifest = migrate_legacy_up_raw(args.legacy_root, args.target_root)
    print(f"scope={manifest['scope']}")
    print(f"raw_directories={len(manifest['raw_directories'])}")
    print(f"raw_count={manifest['raw_count']}")

    if manifest["raw_count"] < args.min_raw:
        print(f"raw_count below expected minimum: {manifest['raw_count']} < {args.min_raw}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
