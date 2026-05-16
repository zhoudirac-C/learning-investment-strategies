#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

from qing_investment.processed_log import load_processed_sources


def find_unprocessed(repo_root: Path) -> list[Path]:
    raw_dir = repo_root / "sources" / "raw"
    log_path = repo_root / "sources" / "processed-log.md"
    processed = load_processed_sources(log_path)
    result: list[Path] = []
    for path in sorted(raw_dir.rglob("*.md")):
        if path.name == "README.md":
            continue
        rel = path.relative_to(repo_root)
        if rel.as_posix() not in processed:
            result.append(rel)
    return result


def main() -> int:
    root = Path.cwd()
    for path in find_unprocessed(root):
        print(path.as_posix())
    return 0


if __name__ == "__main__":
    sys.exit(main())
