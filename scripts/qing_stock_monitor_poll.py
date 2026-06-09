#!/usr/bin/env python3
"""条件驱动轮询 — 纯规则价格触发检查。

每 5 分钟拉行情，检查持仓的 add_zone/reduce_zone/risk_zone，
有触发就输出提醒消息。不需要 LLM。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path("/home/ubuntu/learning-investment-strategies")


def main() -> int:
    venv_python = REPO_ROOT / ".venv" / "bin" / "python"

    if not venv_python.exists():
        print("[poll error] .venv not found", file=sys.stderr)
        return 1

    command = [
        str(venv_python),
        str(REPO_ROOT / "scripts" / "stock_monitor.py"),
        "--ignore-trading-time",
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")

    result = subprocess.run(command, cwd=REPO_ROOT, env=env, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"[poll error] exit={result.returncode}", file=sys.stderr)
        if result.stderr:
            print(result.stderr[:500], file=sys.stderr)
        return result.returncode

    msg = result.stdout.strip()
    if msg:
        print(msg)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
