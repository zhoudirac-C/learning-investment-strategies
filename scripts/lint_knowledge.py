#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

from qing_investment.knowledge_linter import lint_markdown_placeholders


def main() -> int:
    root = Path.cwd()
    issues = lint_markdown_placeholders(root)
    for issue in issues:
        print(f"{issue.path}:{issue.line_number}: forbidden marker {issue.marker}: {issue.line}")
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
