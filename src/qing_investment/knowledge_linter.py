from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

FORBIDDEN_MARKERS = ("T" + "BD", "TO" + "DO", "待" + "定", "以后" + "再", "place" + "holder")
EXCLUDED_DIR_NAMES = {".git", ".venv", "venv", "__pycache__", "vendor", "third_party"}


@dataclass(frozen=True)
class LintIssue:
    path: Path
    marker: str
    line_number: int
    line: str


def lint_markdown_placeholders(root: Path) -> list[LintIssue]:
    issues: list[LintIssue] = []
    for path in sorted(root.rglob("*.md")):
        if _should_skip(path):
            continue
        text = path.read_text(encoding="utf-8")
        for idx, line in enumerate(text.splitlines(), start=1):
            for marker in FORBIDDEN_MARKERS:
                if marker in line:
                    issues.append(LintIssue(path=path, marker=marker, line_number=idx, line=line))
    return issues


def _should_skip(path: Path) -> bool:
    parts = set(path.parts)
    if parts & EXCLUDED_DIR_NAMES:
        return True
    if "sources" in parts and "raw" in parts:
        return True
    return "docs" in parts and "superpowers" in parts and "plans" in parts
