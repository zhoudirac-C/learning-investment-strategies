from __future__ import annotations

import subprocess
from pathlib import Path


def repo_root() -> Path:
    """Return the repository root.

    In a git worktree this returns the main working tree root, not the
    linked worktree directory, so project-relative paths are stable across
    worktrees.
    """
    module_dir = Path(__file__).resolve().parent
    try:
        common_dir = subprocess.check_output(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=module_dir,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        # git may return a relative path (e.g. "../../../../.git") that is
        # relative to the directory where git was run, not the process cwd.
        # Anchor it to module_dir before resolving.
        common_path = module_dir / common_dir
        return common_path.resolve().parent
    except Exception:
        return module_dir.parents[2]


def resolve_repo_path(*parts: str) -> Path:
    """Resolve a path under the repository root."""
    return repo_root().joinpath(*parts)
