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
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

QING_AGENT_URL = os.environ.get("QING_AGENT_URL", "http://localhost:8000/analyze/trigger")
QING_AGENT_TIMEOUT = float(os.environ.get("QING_AGENT_TIMEOUT", "240"))
QING_AGENT_MAX_RETRIES = int(os.environ.get("QING_AGENT_MAX_RETRIES", "3"))

# Cron job wrapper timeout (seconds) — must be >= QING_AGENT_TIMEOUT + 20s margin
# to avoid the cron killing the script while it's still retrying.
CRON_WRAPPER_TIMEOUT = float(os.environ.get("CRON_WRAPPER_TIMEOUT", "260"))


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
        command = [python_cmd, "-m", "qing_investment.stock_monitor", *extra_args]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(root / "src")
        return subprocess.run(command, cwd=root, env=env, capture_output=True, text=True)

    # Fallback to uv run
    return subprocess.run(
        ["uv", "run", "python", "-m", "qing_investment.stock_monitor", *extra_args],
        cwd=root,
        capture_output=True,
        text=True,
    )


def fetch_json_context(root: Path) -> dict | None:
    """Run stock_monitor tick and return parsed JSON context (replaces subprocess call)."""
    # Add src to sys.path for direct imports
    src_dir = str(root / "src")
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)

    from qing_investment.stock_monitor import load_monitor_config
    from qing_investment.monitor.scheduler import run_tick
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from pathlib import Path

    cn_tz = ZoneInfo("Asia/Shanghai")
    config = load_monitor_config(root / "config" / "stock_monitor")

    message = run_tick(
        config,
        datetime.now(cn_tz),
        emit_status=False,
        ignore_trading_time=True,
        state_path=root / "config" / "stock_monitor" / "state.json",
        agent_json_context=True,
        agent_any_time=True,
    )
    if not message:
        return None
    try:
        return json.loads(message) if isinstance(message, str) else message
    except (json.JSONDecodeError, TypeError):
        return None


def fetch_fallback_text_context(root: Path) -> str:
    """Run stock_monitor tick and return plain text context (replaces subprocess call)."""
    src_dir = str(root / "src")
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)

    from qing_investment.stock_monitor import load_monitor_config
    from qing_investment.monitor.scheduler import run_tick
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from pathlib import Path

    cn_tz = ZoneInfo("Asia/Shanghai")
    config = load_monitor_config(root / "config" / "stock_monitor")

    message = run_tick(
        config,
        datetime.now(cn_tz),
        emit_status=False,
        ignore_trading_time=True,
        state_path=root / "config" / "stock_monitor" / "state.json",
        agent_context_on_trigger=True,
        agent_any_time=True,
    )
    return message if isinstance(message, str) else ""


def call_qing_agent(data: dict) -> dict | None:
    """POST the context dict to qing-agent and return the response JSON.
    
    Retries with exponential backoff on transient failures (URLError, timeout, HTTP 5xx).
    """
    analysis_type = data.get("analysis_type", "market")
    stock_code = data.get("stock_code", "")
    payload = json.dumps({
        "query": f"{data.get('trigger', {}).get('title', '')}：{data.get('trigger', {}).get('reason', '')}",
        "session_id": f"hermes-{data.get('timestamp', 'now')}",
        "stock_code": stock_code,
        "analysis_type": analysis_type,
        "trigger": data.get("trigger", {}),
        "alerts": data.get("alerts", []),
        "buy_signal_candidates": data.get("buy_signal_candidates", []),
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

    for attempt in range(1, QING_AGENT_MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=QING_AGENT_TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8") if e.fp else ""
            if 500 <= e.code < 600:
                print(f"[qing-agent HTTP {e.code} retry {attempt}/{QING_AGENT_MAX_RETRIES}] {body}", file=sys.stderr)
                if attempt < QING_AGENT_MAX_RETRIES:
                    import time
                    time.sleep(2 ** attempt)  # 2, 4, 8s backoff
                    continue
            print(f"[qing-agent HTTP {e.code}] {body}", file=sys.stderr)
            return None
        except urllib.error.URLError as e:
            print(f"[qing-agent unreachable retry {attempt}/{QING_AGENT_MAX_RETRIES}] {e.reason}", file=sys.stderr)
            if attempt < QING_AGENT_MAX_RETRIES:
                import time
                time.sleep(2 ** attempt)
                continue
            return None
        except TimeoutError as e:
            print(f"[qing-agent timeout retry {attempt}/{QING_AGENT_MAX_RETRIES}] {e}", file=sys.stderr)
            if attempt < QING_AGENT_MAX_RETRIES:
                import time
                time.sleep(2 ** attempt)
                continue
            return None
        except Exception as e:
            print(f"[qing-agent error retry {attempt}/{QING_AGENT_MAX_RETRIES}] {e}", file=sys.stderr)
            if attempt < QING_AGENT_MAX_RETRIES:
                import time
                time.sleep(2 ** attempt)
                continue
            return None
    return None


# ── 幻觉检测模式 ──
_HALLUCINATION_PATTERNS = [
    re.compile(r"202[0-5]年"),
    re.compile(r"数据断链|数据缺失|数据不可用|暂无数据|量化API断供"),
    re.compile(r"数据恢复是最关键"),
    re.compile(r"这是\d{4}年\d{1,2}月\d{1,2}日(盘后)?复盘"),
]


def _is_hallucinated(output: str) -> bool:
    current_year = datetime.now(timezone.utc).year
    year_matches = re.findall(r"(20\d{2})年", output)
    for y_str in year_matches:
        y = int(y_str)
        if abs(y - current_year) >= 1:
            return True
    for pat in _HALLUCINATION_PATTERNS:
        if pat.search(output):
            return True
    return False


def main():
    root = Path(repo_root())

    # 1. Get structured JSON context from stock_monitor
    data = fetch_json_context(root)
    if data is None:
        # No trigger at this time — silently exit (Hermes expects empty output = no action)
        return 0

    # 2. Call qing-agent
    response = call_qing_agent(data)

    # 3. Citation validation (new)
    citation_warning = ""
    if response and response.get("final_output"):
        try:
            from qing_investment.agent.validators.citation_validator import CitationValidator
            validator = CitationValidator(coverage_threshold=0.6)
            report = validator.validate(response["final_output"])
            if report.coverage < 0.6:
                citation_warning = f"[引用警告: 覆盖率{report.coverage:.0%}，建议补充来源标注]"
        except Exception as e:
            # Validator not available or error — non-blocking
            citation_warning = f"[引用检查未运行: {e}]"

    # 4. Output with hallucination check + citation warning
    if response and response.get("final_output"):
        output = response["final_output"]
        if _is_hallucinated(output):
            import logging
            logging.warning("Qing-Agent output hallucinated (wrong date/patterns), falling back to live context")
            print("[Qing-Agent ✗ HALLUCINATION]")
            print(fetch_fallback_text_context(root))
            return 0
        print("[Qing-Agent ✓]" + (f" {citation_warning}" if citation_warning else ""))
        print(output)
        if response.get("claims_cited"):
            print(f"\n[引用claims: {', '.join(response['claims_cited'])}]")
        return 0

    # 4. Fallback: qing-agent unavailable or returned empty — print original text context
    print("[Qing-Agent ✗ FALLBACK]")
    print(fetch_fallback_text_context(root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
