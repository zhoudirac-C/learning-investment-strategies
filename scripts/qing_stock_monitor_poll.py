#!/usr/bin/env python3
"""条件驱动轮询 — 纯规则价格触发检查。

⚠️ 【已退役 2026-09-16】本脚本不再被任何 cron 任务调用。

原 cron「条件驱动轮询（add_zone/风控）」(*/5 9-11,14-15 * * 1-5) 已删除。
positions.yaml 的 reduce_zone / risk_zone / add_zone 仍由
`PositionRuleEngine.evaluate()` (src/qing_investment/monitor/rules/__init__.py
L218–L281) 读取，但触发结算改走 agent 通道：
    hermes_stock_monitor_agent.py → run_tick(agent_json_context=True) → alerts[]
即由「持仓双引擎盘中监控」等 30 分钟粒度的 cron 承载，不再有 5 分钟机械提醒。

保留本文件的原因：便于需要时手动单跑一次（例如盘中人工核查 zone 是否穿越）：
    bash ~/.hermes/scripts/qing_stock_monitor_poll.py

字段覆盖率（2026-09-16）：risk_zone ×6、reduce_zone ×1、add_zone ×0。
详见 config/stock_monitor/README.md「价格区间的三条触发链」。
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
