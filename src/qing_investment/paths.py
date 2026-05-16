from __future__ import annotations

from pathlib import Path


def repo_root() -> Path:
    """Return the repository root by walking up from this file."""
    return Path(__file__).resolve().parents[2]


def resolve_repo_path(*parts: str) -> Path:
    """Resolve a path under the repository root."""
    return repo_root().joinpath(*parts)
