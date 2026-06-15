#!/usr/bin/env python3
"""Health alert entrypoint — 收集监控引擎健康指标并输出到 stdout.

Hermes cron (no_agent=True) 模式直接发送 stdout 到微信。
输出格式：纯文本，微信友好。

使用方式:
    python -m hermes_health_alert              # 完整报告
    python -m hermes_health_alert --brief       # 精简版（仅异常时输出）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# 添加 src 到路径
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# 指标文件路径
STATS_PATH = Path("/tmp/qing_health_stats.json")


def load_stats() -> dict:
    """从文件加载健康指标."""
    if not STATS_PATH.exists():
        return {}
    try:
        return json.loads(STATS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def check_agent_health() -> str:
    """检查 Agent FastAPI 是否可达."""
    try:
        import urllib.request
        resp = urllib.request.urlopen("http://localhost:8000/health", timeout=5)
        if resp.status == 200:
            return "running"
        return f"down (status={resp.status})"
    except Exception as e:
        return f"down ({e})"


def format_brief(stats: dict, agent_status: str) -> str | None:
    """精简版：仅在有异常时输出消息."""
    cb = stats.get("circuit_breaker", {})
    dg = stats.get("degradation", {})
    ca = stats.get("cache", {})
    issues: list[str] = []

    # 断路器打开
    if cb.get("is_open"):
        issues.append(f"🔴 断路器打开 (失败{cb.get('failures', 0)}次)")

    # 数据源非 WS
    source = dg.get("current_source", "ws")
    if source != "ws":
        reason = dg.get("current_reason", "")
        issues.append(f"⚠️ 数据源降级: {source} (原因: {reason})")

    # Agent 不可达
    if "down" in agent_status:
        issues.append(f"❌ Agent 不可达: {agent_status}")

    # 缓存命中率过低
    hit_rate = ca.get("hit_rate", 1.0)
    if hit_rate < 0.5 and hit_rate > 0:
        issues.append(f"💾 缓存命中率过低: {hit_rate:.0%}")

    if not issues:
        return None  # 无异常，静默

    return "\n".join([
        "⚠️ 监控引擎健康告警",
        "━━━━━━━━━━━━━━━",
    ] + issues)


def format_full(stats: dict, agent_status: str) -> str:
    """完整版健康报告."""
    cb = stats.get("circuit_breaker", {})
    dg = stats.get("degradation", {})
    ca = stats.get("cache", {})
    ts = stats.get("timestamp", "N/A")
    uptime = stats.get("uptime_hours", 0)

    lines = [
        f"📊 监控引擎健康报告 @ {ts}",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"运行时长: {uptime:.1f}h",
        "",
        f"🤖 Agent: {_icon(agent_status)} {agent_status}",
        "",
        f"🔌 断路器: {_icon('open' if cb.get('is_open') else 'closed')} "
        f"{'打开' if cb.get('is_open') else '关闭'}",
        f"  失败次数: {cb.get('failures', 0)}",
    ]

    if cb.get("is_open"):
        remaining = cb.get("cooldown_remaining_hours", 0)
        lines.append(f"  冷却剩余: {remaining:.1f}h")
        lines.append(f"  上次失败: {cb.get('last_failure_time', 'N/A')}")

    lines.append("")
    lines.append(f"📡 数据源: {_icon(dg.get('current_source', 'ws'))} "
                 f"{dg.get('current_source', 'ws')}")

    source = dg.get("current_source", "ws")
    if source != "ws":
        lines.append(f"  降级原因: {dg.get('current_reason', 'N/A')}")
        lines.append(f"  HTTP降级: {dg.get('http_fallback_count', 0)}次")
        lines.append(f"  WS未启动: {dg.get('ws_not_started_count', 0)}次")

    lines.append("")
    hit_rate = ca.get("hit_rate", 0.0)
    hits = ca.get("hits", 0)
    misses = ca.get("misses", 0)
    total_req = hits + misses
    lines.append(f"💾 缓存命中率: {_rate_icon(hit_rate)} {hit_rate:.1%}")
    lines.append(f"  条目: {ca.get('size', 0)}/{ca.get('max_entries', 1000)}")
    lines.append(f"  命中/请求: {hits}/{total_req}" if total_req > 0 else "  命中/请求: 0/0")
    if ca.get("evictions", 0) > 0 or ca.get("expired", 0) > 0:
        lines.append(f"  淘汰: {ca.get('evictions', 0)} | 过期: {ca.get('expired', 0)}")

    return "\n".join(lines)


def _icon(status: str) -> str:
    mapping = {
        "closed": "✅", "open": "🔴", "half-open": "⚠️",
        "running": "✅", "down": "❌", "degraded": "⚠️",
        "ws": "✅", "http_fallback": "⚠️", "none": "❌",
        "unknown": "❓",
    }
    return mapping.get(status, "❓")


def _rate_icon(rate: float) -> str:
    if rate >= 0.8:
        return "🟢"
    elif rate >= 0.5:
        return "🟡"
    return "🔴"


def main() -> int:
    stats = load_stats()
    agent_status = check_agent_health()

    if "--brief" in sys.argv:
        msg = format_brief(stats, agent_status)
        if msg:
            print(msg)
        return 0

    print(format_full(stats, agent_status))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
