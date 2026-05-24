#!/usr/bin/env python3

import subprocess
import os
from pathlib import Path


def repo_root() -> str:
    configured = os.environ.get("HERMES_REPO_ROOT")
    if configured:
        return configured
    cwd = Path.cwd()
    if (cwd / "scripts" / "stock_monitor.py").exists():
        return str(cwd)
    return str(Path(__file__).resolve().parents[1])


def main():
    command = [
        "uv",
        "run",
        "python",
        "scripts/stock_monitor.py",
        "--live-analysis-context",
        "--ignore-trading-time",
    ]
    return subprocess.call(command, cwd=repo_root())


if __name__ == "__main__":
    raise SystemExit(main())
