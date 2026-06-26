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
QING_AGENT_HEALTH_URL = os.environ.get("QING_AGENT_HEALTH_URL", "http://localhost:8000/health")
QING_AGENT_TIMEOUT = float(os.environ.get("QING_AGENT_TIMEOUT", "180"))
QING_AGENT_MAX_RETRIES = int(os.environ.get("QING_AGENT_MAX_RETRIES", "2"))

# Cron job wrapper timeout (seconds) — must be >= QING_AGENT_TIMEOUT + 20s margin
# to avoid the cron killing the script while it's still retrying.
CRON_WRAPPER_TIMEOUT = float(os.environ.get("CRON_WRAPPER_TIMEOUT", "680"))  # 600s POST + 60s health + 20s margin


def _normalize_positions(positions_raw: dict | list) -> list:
    """Normalize positions from config format (dict with accounts) to flat list for qing-agent API."""
    if isinstance(positions_raw, list):
        return positions_raw
    if not isinstance(positions_raw, dict):
        return []
    result = []
    # Handle dict format: {"accounts": [{"name": "...", "positions": [...]}]}
    accounts = positions_raw.get("accounts", [])
    for account in accounts:
        if not isinstance(account, dict):
            continue
        for pos in account.get("positions", []):
            if isinstance(pos, dict):
                pos["account"] = account.get("name", "")
                result.append(pos)
    # Also handle direct portfolio_stats or positions list at top level
    direct_positions = positions_raw.get("positions", [])
    if isinstance(direct_positions, list):
        for pos in direct_positions:
            if isinstance(pos, dict) and pos not in result:
                result.append(pos)
    return result


def _normalize_watchlist(watchlist_raw: dict | list) -> list:
    """Normalize watchlist from config format (dict with themes) to flat list for qing-agent API."""
    if isinstance(watchlist_raw, list):
        return watchlist_raw
    if not isinstance(watchlist_raw, dict):
        return []
    result = []
    # Handle dict format: {"themes": [{"stocks": [...]}]} or {"stocks": [...]}
    themes = watchlist_raw.get("themes", [])
    for theme in themes:
        if not isinstance(theme, dict):
            continue
        for stock in theme.get("stocks", []):
            if isinstance(stock, dict):
                stock["theme"] = theme.get("name", "")
                result.append(stock)
    # Also handle direct stocks list at top level
    direct_stocks = watchlist_raw.get("stocks", [])
    if isinstance(direct_stocks, list):
        for stock in direct_stocks:
            if isinstance(stock, dict) and stock not in result:
                result.append(stock)
    return result


def _remove_agent_trigger_dedupe(root: Path, data: dict) -> None:
    """Remove the agent analysis trigger dedupe entry from state to allow retry on next run."""
    try:
        import json
        state_path = root / "config" / "stock_monitor" / "state.json"
        if not state_path.exists():
            return
        with open(state_path, "r", encoding="utf-8") as f:
            state = json.load(f)
        
        trigger = data.get("trigger", {})
        trigger_kind = trigger.get("kind", "")
        trigger_id = trigger.get("id", "")
        
        # Build the dedupe key that was recorded
        from datetime import datetime
        from zoneinfo import ZoneInfo
        cn_tz = ZoneInfo("Asia/Shanghai")
        timestamp = data.get("timestamp", "")
        if timestamp:
            try:
                dt = datetime.fromisoformat(timestamp).astimezone(cn_tz)
                date_text = dt.strftime("%Y-%m-%d")
            except Exception:
                date_text = datetime.now(cn_tz).strftime("%Y-%m-%d")
        else:
            date_text = datetime.now(cn_tz).strftime("%Y-%m-%d")
        
        # Try multiple possible dedupe key formats
        # The dedupe key format varies by trigger kind:
        # - scheduled row: scheduled:{id}:{date}  e.g. scheduled:afternoon_risk:2026-06-15
        # - any time: scheduled:any:{date}:{hhmm}  e.g. scheduled:any:2026-06-15:14:41
        # - buy candidate: buy_candidate:{date}:{codes}
        # - event: event:{date}:{fingerprints}
        current_hhmm = trigger.get('title', '').replace(' ', '').replace('定时分析', '')
        possible_keys = [
            f"scheduled:{trigger_id}:{date_text}",
            f"scheduled:any:{date_text}:{current_hhmm}",
            f"scheduled:any:{date_text}:{trigger_id.replace('any_', '')}",
        ]
        
        agent_log = state.get("agent_analysis_log", {})
        removed = False
        for key in possible_keys:
            if key in agent_log:
                del agent_log[key]
                removed = True
                print(f"[dedupe cleanup] Removed {key} for retry", file=sys.stderr)
        
        if removed:
            with open(state_path, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[dedupe cleanup] Failed: {e}", file=sys.stderr)


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


def fetch_fallback_text_context(root: Path, data: dict | None = None) -> str:
    """Return plain text context for fallback output.
    
    If data is provided, formats it directly without calling run_tick again.
    If data is None, calls run_tick to get fresh context (may be blocked by dedupe).
    """
    if data is not None:
        return _format_fallback_text(data)
    
    # Fallback: try to get fresh data (may return empty due to dedupe)
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
        return ""
    try:
        data = json.loads(message) if isinstance(message, str) else message
        if isinstance(data, dict):
            return _format_fallback_text(data)
    except (json.JSONDecodeError, TypeError):
        pass
    return message if isinstance(message, str) else ""


def _format_fallback_text(data: dict) -> str:
    """Format JSON context data into human-readable text for fallback output."""
    lines = []
    trigger = data.get("trigger", {})
    lines.append(f"[Hermes股票监控分析 - {trigger.get('title', '定时分析')}]")
    lines.append(f"时间：{data.get('timestamp', '')}")
    lines.append(f"触发类型：{trigger.get('kind', 'scheduled')}")
    lines.append(f"触发原因：{trigger.get('reason', '')}")
    lines.append("")
    
    alerts = data.get("alerts", [])
    if alerts:
        lines.append("规则信号：")
        for a in alerts:
            lines.append(f"  - {a.get('action', '')}: {a.get('stock_code', '')} {a.get('stock_name', '')} - {a.get('summary', '')}")
    else:
        lines.append("规则信号：无新增规则信号")
    lines.append("")
    
    positions = data.get("positions", [])
    if isinstance(positions, dict):
        accounts = positions.get("accounts", [])
        total = sum(len(a.get("positions", [])) for a in accounts)
        lines.append(f"持仓：{total} 只")
    elif isinstance(positions, list):
        lines.append(f"持仓：{len(positions)} 只")
    else:
        lines.append("持仓：未配置")
    
    watchlist = data.get("watchlist", [])
    if isinstance(watchlist, list):
        lines.append(f"观察池：{len(watchlist)} 只")
    else:
        lines.append("观察池：未配置")
    lines.append("")
    
    snapshot = data.get("quote_snapshot", {})
    quotes = snapshot.get("quotes", [])
    if quotes:
        lines.append("行情快照：")
        for q in quotes[:10]:  # Limit to first 10
            name = q.get("name", "")
            code = q.get("code", "")
            price = q.get("price", "")
            change = q.get("change_pct", "")
            lines.append(f"  - {name}({code}): 最新价 {price} ({change}%)")
    
    return "\n".join(lines)


def _wait_for_agent_health(health_url: str, max_wait_s: int = 60) -> bool:
    """Poll /health until agent is ready or max_wait_s expires.
    
    Avoids wasting a 300s POST timeout on cold-start -- health check is cheap
    (5s timeout x 12 retries = 60s max). Returns True when healthy.
    """
    import time as _time
    check_interval = 5.0
    max_attempts = max(1, int(max_wait_s / check_interval))  # 12 for 60s
    deadline = _time.monotonic() + max_wait_s
    
    for i in range(max_attempts):
        if _time.monotonic() > deadline:
            break
        try:
            req = urllib.request.Request(health_url, method="GET")
            with urllib.request.urlopen(req, timeout=check_interval) as resp:
                if resp.status == 200:
                    print(f"[health] qing-agent ready (after {i * check_interval:.0f}s)", file=sys.stderr)
                    return True
        except Exception:
            pass
        _time.sleep(check_interval)
    
    print(f"[health] qing-agent NOT ready after {max_wait_s:.0f}s", file=sys.stderr)
    return False


def call_qing_agent(data: dict) -> dict | None:
    """POST the context dict to qing-agent and return the response JSON.
    
    Pre-flights with health check to avoid 300s POST wait during cold start.
    Retries with exponential backoff on transient failures (URLError, timeout, HTTP 5xx).
    """
    # Health check: fail fast if agent is in cold start (<=60s wait)
    if not _wait_for_agent_health(QING_AGENT_HEALTH_URL, max_wait_s=60):
        print("[qing-agent] agent not ready (cold start?), falling back", file=sys.stderr)
        return None
    
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
        "positions": _normalize_positions(data.get("positions", {})),
        "watchlist": _normalize_watchlist(data.get("watchlist", [])),
        "sector_strengths": data.get("sector_strengths", []),
        "external_sector_boards": data.get("external_sector_boards", {}),
    }, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(
        QING_AGENT_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    import socket
    # Set global socket timeout to prevent infinite blocking on hung server
    original_socket_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(QING_AGENT_TIMEOUT)
    
    try:
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
            except (TimeoutError, socket.timeout) as e:
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
    finally:
        socket.setdefaulttimeout(original_socket_timeout)


# ── 幻觉检测模式 ──
# Only flag future years (2027+) and genuine hallucination templates.
# "数据缺失/暂无数据" is legitimate status report when live quotes are unavailable.
_HALLUCINATION_FUTURE_YEAR = re.compile(r"20(2[7-9]|[3-9]\d)年")
_HALLUCINATION_PATTERNS = [
    _HALLUCINATION_FUTURE_YEAR,                                   # future years only
    re.compile(r"数据恢复是最关键"),                               # meta-hallucination
    re.compile(r"这是\d{4}年\d{1,2}月\d{1,2}日(盘后)?复盘"),     # date hallucination
]


def _is_hallucinated(output: str) -> bool:
    """Only flags future years (2027+) or known hallucination templates.
    Past years (2020-2025) are valid references."""
    # Future year check — 2027+ is definitely hallucination
    if _HALLUCINATION_FUTURE_YEAR.search(output):
        return True
    # Specific hallucination templates
    for pat in _HALLUCINATION_PATTERNS[1:]:  # skip first, already checked
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
    import time as _time
    t0 = _time.time()
    # 预估 POST 大小（call_qing_agent 内部会再构建一次 payload）
    approx_size = len(json.dumps(data, ensure_ascii=False)) if isinstance(data, dict) else 0
    print(f"[qing-agent POST] ctx=~{approx_size}bytes(~{approx_size//4}tk) url={QING_AGENT_URL}", file=sys.stderr)
    response = call_qing_agent(data)
    elapsed = _time.time() - t0
    if response:
        resp_size = len(json.dumps(response, ensure_ascii=False))
        print(f"[qing-agent POST] ✓ {elapsed:.1f}s resp={resp_size}bytes", file=sys.stderr)
    else:
        print(f"[qing-agent POST] ✗ {elapsed:.1f}s 无响应", file=sys.stderr)

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
            print(fetch_fallback_text_context(root, data))
            return 0
        print("[Qing-Agent ✓]" + (f" {citation_warning}" if citation_warning else ""))
        print(f"[qing-agent OUTPUT] len={len(output)}chars ~{len(output)//4}tk hallucinated=False", file=sys.stderr)
        print(output)
        if response.get("claims_cited"):
            print(f"\n[引用claims: {', '.join(response['claims_cited'])}]")
        return 0

    # 4. Fallback: qing-agent unavailable or returned empty — print original text context
    fallback_text = fetch_fallback_text_context(root, data)
    if not fallback_text:
        # Fallback also empty — this means the trigger was recorded in state but output failed.
        # Remove the dedupe entry so the next run can retry.
        _remove_agent_trigger_dedupe(root, data)
        return 0
    print("[Qing-Agent ✗ FALLBACK]")
    print(fallback_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
