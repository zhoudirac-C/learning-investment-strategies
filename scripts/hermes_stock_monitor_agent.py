#!/usr/bin/env python3
"""
Hermes cron entrypoint for qing-agent integration.

1. Runs stock_monitor.py --agent-json-context to get structured context
2. POSTs the JSON to qing-agent /analyze/trigger
3. Prints the UP-styled final_output from qing-agent
4. Fallback: if qing-agent is unreachable, prints the original text context
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

QING_AGENT_URL = os.environ.get("QING_AGENT_URL", "http://localhost:8000/analyze/trigger")
QING_AGENT_TIMEOUT = float(os.environ.get("QING_AGENT_TIMEOUT", "45"))


def repo_root() -> str:
    configured = os.environ.get("HERMES_REPO_ROOT")
    if configured:
        return configured
    cwd = Path.cwd()
    if (cwd / "scripts" / "stock_monitor.py").exists():
        return str(cwd)
    return str(Path(__file__).resolve().parents[1])


def _run_stock_monitor(root: Path, *extra_args: str) -> subprocess.CompletedProcess:
    """Run stock_monitor.py with given extra args and return CompletedProcess."""
    venv_python = root / ".venv" / "bin" / "python"
    if venv_python.exists():
        python_cmd = str(venv_python)
        command = [python_cmd, "scripts/stock_monitor.py", *extra_args]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(root / "src")
        return subprocess.run(command, cwd=root, env=env, capture_output=True, text=True)

    # Fallback to uv run
    return subprocess.run(
        ["uv", "run", "python", "scripts/stock_monitor.py", *extra_args],
        cwd=root,
        capture_output=True,
        text=True,
    )


def fetch_json_context(root: Path) -> dict | None:
    """Run stock_monitor.py --agent-json-context and parse the JSON output."""
    result = _run_stock_monitor(root, "--agent-json-context", "--ignore-trading-time")
    stdout = result.stdout.strip()
    if not stdout:
        return None
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return None


def fetch_fallback_text_context(root: Path) -> str:
    """Run stock_monitor.py --agent-context-on-trigger to get plain text context."""
    result = _run_stock_monitor(root, "--agent-context-on-trigger", "--ignore-trading-time")
    return result.stdout


def call_qing_agent(data: dict) -> dict | None:
    """POST the context dict to qing-agent and return the response JSON."""
    payload = json.dumps({
        "query": f"{data.get('trigger', {}).get('title', '')}：{data.get('trigger', {}).get('reason', '')}",
        "session_id": f"hermes-{data.get('timestamp', 'now')}",
        "stock_code": "",
        "analysis_type": "market",
        "trigger": data.get("trigger", {}),
        "alerts": data.get("alerts", []),
        "market_snapshot": data.get("quote_snapshot", {}),
        "positions": data.get("positions", []),
        "watchlist": data.get("watchlist", []),
        "sector_strengths": data.get("sector_strengths", []),
        "external_sector_boards": data.get("external_sector_boards", {}),
    }, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(
        QING_AGENT_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=QING_AGENT_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8") if e.fp else ""
        print(f"[qing-agent HTTP {e.code}] {body}", file=sys.stderr)
        return None
    except urllib.error.URLError as e:
        print(f"[qing-agent unreachable] {e.reason}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[qing-agent error] {e}", file=sys.stderr)
        return None


def main():
    root = Path(repo_root())

    # 1. Get structured JSON context from stock_monitor
    data = fetch_json_context(root)
    if data is None:
        # No trigger at this time — silently exit (Hermes expects empty output = no action)
        return 0

    # 2. Call qing-agent
    response = call_qing_agent(data)

    # 3. Output
    if response and response.get("final_output"):
        print(response["final_output"])
        if response.get("claims_cited"):
            print(f"\n[引用claims: {', '.join(response['claims_cited'])}]")
        return 0

    # 4. Fallback: qing-agent unavailable or returned empty — print original text context
    print("[qing-agent fallback — 输出原始监控上下文]")
    print(fetch_fallback_text_context(root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
