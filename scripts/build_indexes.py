#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

from qing_investment.index_builder import write_markdown_index


def main() -> int:
    root = Path.cwd()
    write_markdown_index(root / "knowledge" / "wiki", "Wiki Index")
    write_markdown_index(
        root / "knowledge" / "claims",
        "Claims Index",
        extensions=(".md", ".yaml", ".yml"),
    )
    write_markdown_index(root / "knowledge" / "cases", "Cases Index")
    print("indexes rebuilt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
