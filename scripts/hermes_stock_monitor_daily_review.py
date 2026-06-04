#!/usr/bin/env python3

import subprocess
import sys
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
    root = Path(repo_root())

    # Use project venv directly to avoid uv run overhead in cron
    venv_python = root / ".venv" / "bin" / "python"
    if venv_python.exists():
        python_cmd = str(venv_python)
    else:
        # Fallback to uv run if venv not found
        return subprocess.call(
            ["uv", "run", "python", "scripts/stock_monitor.py", "--daily-review-context"]
            + sys.argv[1:],
            cwd=root,
        )

    command = [
        python_cmd,
        "scripts/stock_monitor.py",
        "--daily-review-context",
    ] + sys.argv[1:]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    return subprocess.call(command, cwd=root, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
