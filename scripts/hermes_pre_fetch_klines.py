#!/usr/bin/env python3
"""
Hermes cron entrypoint for K-line pre-fetch.

Runs pre_fetch_klines.py at 06:30 CST to batch-populate SQLite cache
with yesterday's closing K-lines + today's pre-open state.

Cloud cron setup:
    TZ=Asia/Shanghai 0 30 6 * * 1-5 /path/to/.hermes/scripts/qing_pre_fetch_klines.py
"""
import os
import subprocess
import sys
from pathlib import Path


def repo_root() -> str:
    configured = os.environ.get("HERMES_REPO_ROOT")
    if configured:
        return configured
    cwd = Path.cwd()
    if (cwd / "scripts" / "pre_fetch_klines.py").exists():
        return str(cwd)
    return str(Path(__file__).resolve().parents[1])


def main() -> int:
    root = Path(repo_root())

    # Use project venv directly to avoid uv run overhead in cron
    venv_python = root / ".venv" / "bin" / "python"
    if venv_python.exists():
        python_cmd = str(venv_python)
    else:
        # Fallback to uv run if venv not found
        return subprocess.call(
            ["uv", "run", "python", "scripts/pre_fetch_klines.py"] + sys.argv[1:],
            cwd=root,
        )

    command = [python_cmd, "scripts/pre_fetch_klines.py"] + sys.argv[1:]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    return subprocess.call(command, cwd=root, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
