#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from qing_investment.legacy_migration import migrate_legacy_up_raw

DEFAULT_LEGACY_ROOT = Path("/Users/cong.zhou/Documents/quantitative/赛博青哥wiki")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--legacy-root", type=Path, default=DEFAULT_LEGACY_ROOT)
    parser.add_argument("--target-root", type=Path, default=Path.cwd())
    parser.add_argument("--min-raw", type=int, default=387)
    args = parser.parse_args()

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
