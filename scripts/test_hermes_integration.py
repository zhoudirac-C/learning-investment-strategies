#!/usr/bin/env python3
"""
Test script for Hermes → qing-agent integration.

Bypasses the cron schedule and alert deduplication to force a trigger,
so we can verify the full pipeline works end-to-end.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from qing_investment.stock_monitor import (
    CN_TZ,
    MonitorConfig,
    AgentAnalysisTrigger,
    collect_quote_targets,
    evaluate_monitor_alerts,
    fetch_quotes_with_fallback,
    format_agent_json_context,
    load_monitor_config,
    now_cn,
)

QING_AGENT_URL = os.environ.get("QING_AGENT_URL", "http://localhost:8000/analyze/trigger")


def main():
    config = load_monitor_config()
    current = now_cn()

    # Fetch live quotes
    targets = collect_quote_targets(config)
    quote_snapshot = fetch_quotes_with_fallback(targets)
    alerts = evaluate_monitor_alerts(config, quote_snapshot, current_time=current)

    # Force a mock trigger
    trigger = AgentAnalysisTrigger(
        kind="test",
        id="integration_test",
        title="Hermes集成测试",
        reason="验证Hermes到qing-agent的完整链路",
        dedupe_key=f"test:{current.astimezone(CN_TZ).strftime('%Y-%m-%d')}:integration",
    )

    # Build JSON context
    state = {
        "last_market_state": {
            "time": current.astimezone(CN_TZ).isoformat(),
            "quote_count": len(quote_snapshot.get("quotes", [])),
            "alert_count": len(alerts),
            "risk_count": sum(1 for a in alerts if a.severity == "risk"),
            "observe_count": sum(1 for a in alerts if a.severity == "observe"),
            "sector_actions": [a.action for a in alerts if a.stock_name == "板块强弱"],
        },
        "sector_signal_counts": {},
    }

    json_context = format_agent_json_context(
        config, current, trigger, alerts, quote_snapshot, state
    )
    data = json.loads(json_context)

    # Truncate quotes to reduce payload size and LLM processing time
    quote_snapshot_trimmed = dict(data["quote_snapshot"])
    all_quotes = quote_snapshot_trimmed.get("quotes", []) or []
    quote_snapshot_trimmed["quotes"] = all_quotes[:30]
    quote_snapshot_trimmed["_total_quotes"] = len(all_quotes)

    print("=" * 60)
    print("Generated JSON context (truncated):")
    print(f"  trigger: {data['trigger']}")
    print(f"  alerts: {len(data['alerts'])}")
    print(f"  positions: {len(data['positions'])}")
    print(f"  watchlist: {len(data['watchlist'])}")
    print(f"  quotes: {len(all_quotes)} (sending top 30)")
    print()

    # POST to qing-agent
    payload = json.dumps({
        "query": f"{data['trigger']['title']}：{data['trigger']['reason']}",
        "session_id": f"hermes-test-{current.astimezone(CN_TZ).strftime('%Y%m%d%H%M')}",
        "stock_code": "",
        "analysis_type": "market",
        "trigger": data["trigger"],
        "alerts": data["alerts"],
        "market_snapshot": quote_snapshot_trimmed,
        "positions": data["positions"],
        "watchlist": data["watchlist"],
    }, ensure_ascii=False).encode("utf-8")

    print(f"POST {QING_AGENT_URL}")
    req = urllib.request.Request(
        QING_AGENT_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"ERROR: {e}")
        return 1

    print(f"Response status: {resp.status if 'resp' in dir() else 'N/A'}")
    print(f"review_passed: {result.get('review_passed')}")
    print(f"claims_cited: {result.get('claims_cited')}")
    print(f"confidence: {result.get('confidence')}")
    print()
    print("=" * 60)
    print("FINAL OUTPUT:")
    print("=" * 60)
    print(result.get("final_output", ""))
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
