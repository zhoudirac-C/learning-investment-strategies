#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

from qing_investment.mention_extractor import extract_mentions


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: extract_mentions.py <markdown-file>", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    mentions = extract_mentions(path.read_text(encoding="utf-8"))
    print("stock_codes:", ",".join(mentions.stock_codes))
    print("stock_names:", ",".join(mentions.stock_names))
    print("sectors:", ",".join(mentions.sectors))
    return 0


if __name__ == "__main__":
    sys.exit(main())
