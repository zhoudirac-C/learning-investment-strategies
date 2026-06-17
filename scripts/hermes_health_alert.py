#!/usr/bin/env python3
"""Qing-Agent 健康检查脚本（手动/调试用）。

检查 Agent FastAPI 健康端点并输出状态。
Hermes cron 已通过 check_qing_agent.sh (每15min) 覆盖。

使用方式:
    python -m hermes_health_alert
"""
from __future__ import annotations

import urllib.request


def check_agent_health() -> str:
    """检查 Agent FastAPI 是否可达."""
    try:
        resp = urllib.request.urlopen("http://localhost:8000/health", timeout=5)
        if resp.status == 200:
            return "running"
        return f"down (status={resp.status})"
    except Exception as e:
        return f"down ({e})"


def main() -> int:
    status = check_agent_health()
    if "down" in status:
        print(f"❌ Qing-Agent {status}")
        return 1
    print(f"✅ Qing-Agent {status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
