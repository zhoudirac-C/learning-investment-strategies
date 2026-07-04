from __future__ import annotations

import subprocess
from pathlib import Path


def repo_root() -> Path:
    """Return the repository root.

    In a git worktree this returns the main working tree root, not the
    linked worktree directory, so project-relative paths are stable across
    worktrees.
    """
    try:
        common_dir = subprocess.check_output(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=Path(__file__).resolve().parent,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        return Path(common_dir).resolve().parent
    except Exception:
        return Path(__file__).resolve().parents[2]


def resolve_repo_path(*parts: str) -> Path:
    """Resolve a path under the repository root."""
    return repo_root().joinpath(*parts)
