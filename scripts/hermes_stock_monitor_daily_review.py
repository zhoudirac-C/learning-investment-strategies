#!/usr/bin/env python3

import subprocess
import sys
import os
from pathlib import Path


def repo_root() -> str:
    configured = os.environ.get("HERMES_REPO_ROOT")
    if configured:
        return configured
    # 本地绝对路径
    local_path = Path("/home/ubuntu/learning-investment-strategies")
    if local_path.exists():
        return str(local_path)
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
        "--daily-review-context",
    ] + sys.argv[1:]
    return subprocess.call(command, cwd=repo_root())


if __name__ == "__main__":
    raise SystemExit(main())
