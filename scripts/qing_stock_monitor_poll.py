#!/usr/bin/env python3
"""条件驱动轮询 — 纯规则价格触发检查。

每 5 分钟拉行情，检查持仓的 add_zone/reduce_zone/risk_zone，
有触发就输出提醒消息。不需要 LLM。
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, time
from pathlib import Path

REPO_ROOT = Path("/home/ubuntu/learning-investment-strategies")

# ── 交易时段门控 ──────────────────────────────────
MORNING_START = time(9, 15)
MORNING_END   = time(11, 30)
AFTERNOON_START = time(14, 0)
AFTERNOON_END   = time(15, 0)


def _in_trading_window() -> bool:
    """只在 09:15–11:30 或 14:00–15:00 执行。"""
    now = datetime.now().time()
    return (MORNING_START <= now <= MORNING_END) or (AFTERNOON_START <= now <= AFTERNOON_END)


def main() -> int:
    if not _in_trading_window():
        # 不在交易时段，静默退出，不打扰用户
        return 0
    venv_python = REPO_ROOT / ".venv" / "bin" / "python"

    if not venv_python.exists():
        print("[poll error] .venv not found", file=sys.stderr)
        return 1

    command = [
        str(venv_python),
        "-m", "qing_investment.stock_monitor",
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
