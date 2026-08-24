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
from datetime import date, datetime, timezone
from pathlib import Path

from qing_investment.agent.tools.daily_state import (
    load_daily_state,
    save_daily_state,
    update_market_stage,
)
from qing_investment.agent.tools.market_sentiment import fetch_market_sentiment

QING_AGENT_URL = os.environ.get("QING_AGENT_URL", "http://localhost:8000/analyze/trigger")
QING_AGENT_HEALTH_URL = os.environ.get("QING_AGENT_HEALTH_URL", "http://localhost:8000/health")
# 切到本地 Kimi Code CLI 后 worst case 可能 10-15 分钟；默认超时给足
QING_AGENT_TIMEOUT = float(os.environ.get("QING_AGENT_TIMEOUT", "1200"))
QING_AGENT_MAX_RETRIES = int(os.environ.get("QING_AGENT_MAX_RETRIES", "2"))

# 请求/响应详细日志：按天拆分，便于后续统一清理
REQUEST_LOG_DIR = Path(os.environ.get("QING_AGENT_REQUEST_LOG_DIR", "")) or Path(
    __file__
).resolve().parents[1] / "logs"


def _request_log_path() -> Path:
    REQUEST_LOG_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return REQUEST_LOG_DIR / f"qing-agent-request.{today}.log"


def _log_request_payload(
    data: dict,
    payload: bytes,
    response: dict | None,
    error: str | None = None,
    elapsed_ms: float | None = None,
) -> None:
    """将本次定时任务调用 qing-agent 的完整入参与结果写入按天日志。"""
    try:
        log_path = _request_log_path()
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trigger": data.get("trigger", {}),
            "analysis_type": data.get("analysis_type", "market"),
            "request_payload_size": len(payload),
            "request_payload": json.loads(payload.decode("utf-8")),
            "response_status": "success"
            if response
            else ("error" if error else "empty"),
            "response_size": len(json.dumps(response, ensure_ascii=False))
            if response
            else 0,
            "response_payload": response if response else None,
            "error": error,
            "elapsed_ms": elapsed_ms,
        }
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[request log] failed to write: {e}", file=sys.stderr)

# 当 qing-agent 不可用时是否输出本地规则 fallback。设为 0/false/no 可关闭，避免大 context
# 通过命令行传递时触发 "argument list too long" 或产生无意义的降级输出。
QING_AGENT_FALLBACK_ENABLED = os.environ.get("QING_AGENT_FALLBACK_ENABLED", "1").lower() in ("1", "true", "yes", "on")

# Cron job wrapper timeout (seconds) — must be >= QING_AGENT_TIMEOUT + 20s margin
# to avoid the cron killing the script while it's still retrying.
CRON_WRAPPER_TIMEOUT = float(os.environ.get("CRON_WRAPPER_TIMEOUT", "1300"))  # 1200s POST + 60s health + 40s margin


_STOCK_CODE_RE = re.compile(r"(\d{6})")


def _pure_stock_code(code: object) -> str:
    """从 '002008.SZ' / '0.002008' 中提取 6 位数字代码。"""
    text = str(code or "").strip()
    match = _STOCK_CODE_RE.search(text)
    return match.group(1) if match else text


def _build_quote_lookup(quote_snapshot: dict) -> dict[str, dict]:
    """按 6 位纯代码索引行情快照。"""
    lookup: dict[str, dict] = {}
    for q in (quote_snapshot or {}).get("quotes", []) or []:
        for key in (q.get("code"), q.get("secid")):
            pure = _pure_stock_code(key)
            if pure:
                lookup[pure] = q
    return lookup


def _enrich_stock_with_quote(stock: dict, quote_lookup: dict[str, dict]) -> None:
    """为单只股票字典注入 current_price / change_pct。"""
    if not isinstance(stock, dict):
        return
    pure = _pure_stock_code(stock.get("code", ""))
    if not pure:
        return
    q = quote_lookup.get(pure)
    if not q:
        return
    latest = q.get("latest")
    pct_change = q.get("pct_change")
    # 保留原始字段的同时注入 agent 易识别的字段
    if latest is not None:
        stock["current_price"] = latest
        stock["price"] = latest
    if pct_change is not None:
        stock["change_pct"] = pct_change
        stock["pct_change"] = pct_change


def _normalize_positions(positions_raw: dict | list, quote_lookup: dict[str, dict] | None = None) -> list:
    """Normalize positions from config format (dict with accounts) to flat list for qing-agent API.

    如果提供 quote_lookup，会给每个 position 注入 current_price / change_pct / price / pct_change，
    避免 qing-agent 在生成持仓段落时出现“实时行情数据缺失”。
    """
    if isinstance(positions_raw, list):
        for pos in positions_raw:
            _enrich_stock_with_quote(pos, quote_lookup or {})
        return positions_raw
    if not isinstance(positions_raw, dict):
        return []
    result = []
    lookup = quote_lookup or {}
    # Handle dict format: {"accounts": [{"name": "...", "positions": [...]}]}
    accounts = positions_raw.get("accounts", [])
    for account in accounts:
        if not isinstance(account, dict):
            continue
        for pos in account.get("positions", []):
            if isinstance(pos, dict):
                pos["account"] = account.get("name", "")
                _enrich_stock_with_quote(pos, lookup)
                result.append(pos)
    # Also handle direct portfolio_stats or positions list at top level
    direct_positions = positions_raw.get("positions", [])
    if isinstance(direct_positions, list):
        for pos in direct_positions:
            if isinstance(pos, dict) and pos not in result:
                _enrich_stock_with_quote(pos, lookup)
                result.append(pos)
    return result


def _normalize_watchlist(watchlist_raw: dict | list, quote_lookup: dict[str, dict] | None = None) -> list:
    """Normalize watchlist from config format (dict with themes) to flat list for qing-agent API.

    如果提供 quote_lookup，会给每只股票注入 current_price / change_pct / price / pct_change。
    """
    if isinstance(watchlist_raw, list):
        for stock in watchlist_raw:
            _enrich_stock_with_quote(stock, quote_lookup or {})
        return watchlist_raw
    if not isinstance(watchlist_raw, dict):
        return []
    result = []
    lookup = quote_lookup or {}
    # Handle dict format: {"themes": [{"stocks": [...]}]} or {"stocks": [...]}
    themes = watchlist_raw.get("themes", [])
    for theme in themes:
        if not isinstance(theme, dict):
            continue
        for stock in theme.get("stocks", []):
            if isinstance(stock, dict):
                stock["theme"] = theme.get("name", "")
                _enrich_stock_with_quote(stock, lookup)
                result.append(stock)
    # Also handle direct stocks list at top level
    direct_stocks = watchlist_raw.get("stocks", [])
    if isinstance(direct_stocks, list):
        for stock in direct_stocks:
            if isinstance(stock, dict) and stock not in result:
                _enrich_stock_with_quote(stock, lookup)
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
    # 先从 quote_snapshot 构建行情索引，注入到 positions / watchlist
    quote_lookup = _build_quote_lookup(data.get("quote_snapshot", {}))

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
    position_rows: list[dict] = []
    if isinstance(positions, dict):
        for account in positions.get("accounts", []):
            if isinstance(account, dict):
                for pos in account.get("positions", []) or []:
                    if isinstance(pos, dict):
                        pos = dict(pos)
                        pos["account"] = account.get("name", "")
                        _enrich_stock_with_quote(pos, quote_lookup)
                        position_rows.append(pos)
    elif isinstance(positions, list):
        position_rows = []
        for p in positions:
            if isinstance(p, dict):
                p = dict(p)
                _enrich_stock_with_quote(p, quote_lookup)
                position_rows.append(p)

    if position_rows:
        lines.append(f"持仓：{len(position_rows)} 只")
        for pos in position_rows:
            name = pos.get("name", "")
            code = pos.get("code", "")
            price = pos.get("current_price") or pos.get("price", "")
            change = pos.get("change_pct") if pos.get("change_pct") is not None else pos.get("pct_change", "")
            cost = pos.get("cost", "")
            shares = pos.get("shares", "")
            parts = [f"  - {name}({code})"]
            if price:
                parts.append(f"现价 {price}")
            if change != "":
                parts.append(f"{change:+.2f}%")
            if cost:
                parts.append(f"成本 {cost}")
            if shares:
                parts.append(f"{shares} 股")
            lines.append(" | ".join(parts))
    else:
        lines.append("持仓：未配置")

    watchlist = data.get("watchlist", [])
    watchlist_rows: list[dict] = []
    if isinstance(watchlist, dict):
        for theme in watchlist.get("themes", []):
            if isinstance(theme, dict):
                for stock in theme.get("stocks", []) or []:
                    if isinstance(stock, dict):
                        stock = dict(stock)
                        stock["theme"] = theme.get("name", "")
                        _enrich_stock_with_quote(stock, quote_lookup)
                        watchlist_rows.append(stock)
        for stock in watchlist.get("stocks", []) or []:
            if isinstance(stock, dict) and stock not in watchlist_rows:
                s = dict(stock)
                _enrich_stock_with_quote(s, quote_lookup)
                watchlist_rows.append(s)
    elif isinstance(watchlist, list):
        watchlist_rows = []
        for s in watchlist:
            if isinstance(s, dict):
                s = dict(s)
                _enrich_stock_with_quote(s, quote_lookup)
                watchlist_rows.append(s)

    if watchlist_rows:
        lines.append(f"观察池：{len(watchlist_rows)} 只")
        for stock in watchlist_rows[:10]:
            name = stock.get("name", "")
            code = stock.get("code", "")
            price = stock.get("current_price") or stock.get("price", "")
            change = stock.get("change_pct") if stock.get("change_pct") is not None else stock.get("pct_change", "")
            parts = [f"  - {name}({code})"]
            if price:
                parts.append(f"现价 {price}")
            if change != "":
                parts.append(f"{change:+.2f}%")
            lines.append(" | ".join(parts))
    else:
        lines.append("观察池：未配置")
    lines.append("")

    snapshot = data.get("quote_snapshot", {})
    quotes = snapshot.get("quotes", [])
    if quotes:
        lines.append("行情快照：")
        for q in quotes[:15]:  # Limit to first 15
            name = q.get("name", "")
            code = q.get("code", "")
            # quote 字段来自行情 fetcher：latest / pct_change
            price = q.get("latest") or q.get("price", "")
            change = q.get("pct_change") if q.get("pct_change") is not None else q.get("change_pct", "")
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


def _build_market_snapshot(data: dict) -> tuple[dict, dict[str, dict]]:
    """从 data 构建注入实时价格与技术面信号的 market_snapshot，并返回 quote_lookup。"""
    quote_snapshot = data.get("quote_snapshot", {}) or {}
    quote_lookup = _build_quote_lookup(quote_snapshot)
    market_snapshot = dict(quote_snapshot)
    enriched_quotes = []
    for q in market_snapshot.get("quotes", []) or []:
        enriched = dict(q)
        latest = q.get("latest")
        pct_change = q.get("pct_change")
        if latest is not None:
            enriched.setdefault("price", latest)
        if pct_change is not None:
            enriched.setdefault("change_pct", pct_change)
        enriched_quotes.append(enriched)
    market_snapshot["quotes"] = enriched_quotes

    tech_signals = data.get("tech_signals", {})
    if isinstance(tech_signals, dict):
        market_snapshot.update({
            k: v for k, v in tech_signals.items()
            if k in ("tech_signals", "macd_multi_tf_report", "td_sequential_report", "fibonacci_time_report")
        })

    # Phase 9: 注入市场情绪数据
    try:
        sentiment = fetch_market_sentiment()
        market_snapshot["sentiment"] = sentiment
    except Exception as e:
        market_snapshot["sentiment"] = {"errors": [str(e)]}

    # 隔夜外盘映射股（盘前 08:20 由 scripts/overnight_us_fetch.py 落盘；缺失则不注入）
    overnight = _load_overnight_us()
    if overnight:
        market_snapshot["overnight_us"] = overnight

    # 昨日涨停梯队（15:37 由 scripts/limit_pool_fetch.py 落盘；供早盘看晋级率/反包/一字）
    limit_pool = _load_limit_pool_latest()
    if limit_pool:
        market_snapshot["limit_pool_yesterday"] = limit_pool

    # 集合竞价摘要（仅 09:25-09:40 触发时拉取：竞价额 top + 竞价涨停名单——UP"一字定方向"）
    auction = _fetch_auction_digest()
    if auction:
        market_snapshot["auction_digest"] = auction

    # 昨日盘后公告/资讯警示（KPL 资讯关键词过滤：停牌/复牌/核查/立案/处罚等）
    alerts = _load_post_close_alerts()
    if alerts:
        market_snapshot["post_close_alerts"] = alerts

    return market_snapshot, quote_lookup


_AUCTION_URL = "https://push2.eastmoney.com/api/qt/clist/get"


def _fetch_auction_digest(now: datetime | None = None) -> dict | None:
    """集合竞价摘要：仅 09:25-09:40 窗口拉取；其余时间返回 None。

    一次请求全市场按成交额排序：竞价涨停（涨幅≈涨停=一字/准一字）+ 竞价额 top。
    """
    now = now or datetime.now()
    # 仅 09:25-09:40 窗口有意义（集合竞价 print 已出、连续竞价初期）
    if not (now.hour == 9 and 25 <= now.minute <= 40):
        return None
    params = {
        "pn": 1, "pz": 60, "po": 1, "np": 1,
        "fltt": 2, "invt": 2, "fid": "f6",  # 按成交额降序
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",  # 沪深A股
        "fields": "f2,f3,f6,f12,f14",
    }
    url = _AUCTION_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    rows = ((payload.get("data") or {}).get("diff")) or []
    sealed, top_amount = [], []
    for r in rows:
        name, pct, amt = r.get("f14"), r.get("f3"), r.get("f6")
        code = r.get("f12") or ""
        if pct is None or amt is None:
            continue
        top_amount.append(f"{name}{pct:+.1f}%/额{amt / 1e8:.1f}亿")
        limit = 19.8 if code.startswith(("30", "68")) else 9.8
        if pct >= limit:
            sealed.append(f"{name}{pct:+.1f}%/额{amt / 1e8:.1f}亿")
    return {"data_note": "集合竞价快照（09:25 成交 print，UP'一字定方向'输入）",
            "auction_sealed": sealed,
            "top_amount": top_amount[:20]}


_KPL_NEWS_DIR = Path("infra/data/kpl/news")
_ALERT_KEYWORDS = ("停牌", "复牌", "核查", "立案", "处罚", "警示函", "退市", "风险提示")


def _load_post_close_alerts(before_day: str | None = None) -> dict | None:
    """昨日盘后公告/资讯警示：从最近一日 KPL 资讯 index.json 过滤监管关键词。"""
    before_day = before_day or date.today().isoformat()
    if not _KPL_NEWS_DIR.exists():
        return None
    days = sorted(d for d in _KPL_NEWS_DIR.iterdir()
                  if d.is_dir() and d.name < before_day
                  and (d / "index.json").exists())
    if not days:
        return None
    latest = days[-1]
    try:
        articles = json.loads((latest / "index.json").read_text(encoding="utf-8"))
    except Exception:
        return None
    hits = []
    for a in articles or []:
        title = a.get("title") or a.get("Title") or ""
        if any(k in title for k in _ALERT_KEYWORDS):
            stocks = [s.get("StockID") for s in (a.get("stocks") or a.get("Stock") or [])
                      if s.get("StockID")]
            hits.append({"title": title, "stocks": stocks})
    if not hits:
        return None
    return {"news_date": latest.name, "items": hits[:15]}


_LIMIT_POOL_DIR = Path("infra/data/limit_pool")


def _load_limit_pool_latest(before_day: str | None = None) -> dict | None:
    """读最近一个交易日的涨停梯队落盘，压缩为 LLM 友好形态；无落盘返回 None。"""
    before_day = before_day or date.today().isoformat()
    if not _LIMIT_POOL_DIR.exists():
        return None
    candidates = sorted(p for p in _LIMIT_POOL_DIR.glob("*.json")
                        if p.stem.replace("-", "") < before_day.replace("-", ""))
    if not candidates:
        return None
    try:
        d = json.loads(candidates[-1].read_text(encoding="utf-8"))
    except Exception:
        return None
    cmp_ = d.get("compare") or {}
    out = {"date": d.get("date"), "zt_count": d.get("zt_count"),
           "zb_count": d.get("zb_count"), "max_lbc": d.get("max_lbc"),
           "ladder": d.get("ladder") or {},
           "auction_sealed": d.get("auction_sealed") or []}
    if cmp_.get("promotion_rate") is not None:
        out["promotion_rate"] = cmp_["promotion_rate"]
        out["fanbao"] = cmp_.get("fanbao") or []
    # 连板个股明细（含封单额/炸板次数），首板不注入以控制体量
    out["lianban_items"] = [
        {"name": it.get("name"), "lbc": it.get("lbc"), "hybk": it.get("hybk"),
         "fund": it.get("fund"), "zbc": it.get("zbc")}
        for it in (d.get("zt_items") or []) if (it.get("lbc") or 0) >= 2
    ]
    return out


_OVERNIGHT_US_DIR = Path("infra/data/overnight_us")


def _load_overnight_us(day: str | None = None) -> dict | None:
    """读当日外盘映射落盘，压缩为 LLM 友好形态；文件缺失/损坏返回 None。"""
    day = day or date.today().isoformat()
    path = _OVERNIGHT_US_DIR / f"{day}.json"
    if not path.exists():
        return None
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    themes = []
    for t in d.get("themes") or []:
        movers = []
        for s in t.get("stocks") or []:
            if "error" in s or s.get("pct_change") is None:
                continue
            note = f"（{s['earnings_note']}）" if s.get("earnings_note") else ""
            movers.append(f"{s.get('name') or s['symbol']}{s['pct_change']:+.1f}%{note}")
        if movers:
            themes.append({"theme": t.get("name") or t.get("id"), "movers": movers})
    if not themes:
        return None
    return {"data_note": "昨夜美股收盘涨跌幅", "themes": themes}


def _post_analyze_trigger(payload: dict, timeout: float | None = None) -> dict | None:
    """发送单个 /analyze/trigger 请求，返回响应 JSON。

    包含重试与指数退避；不执行 health check（调用方应已确认服务可用）。
    """
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        QING_AGENT_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    import time as _time

    t0 = _time.perf_counter()
    response: dict | None = None
    last_error: str | None = None
    post_timeout = timeout if timeout is not None else QING_AGENT_TIMEOUT

    for attempt in range(1, QING_AGENT_MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=post_timeout) as resp:
                response = json.loads(resp.read().decode("utf-8"))
                return response
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8") if e.fp else ""
            last_error = f"HTTP {e.code}: {err_body}"
            if 500 <= e.code < 600:
                print(f"[qing-agent HTTP {e.code} retry {attempt}/{QING_AGENT_MAX_RETRIES}] {err_body}", file=sys.stderr)
                if attempt < QING_AGENT_MAX_RETRIES:
                    _time.sleep(2 ** attempt)
                    continue
            print(f"[qing-agent HTTP {e.code}] {err_body}", file=sys.stderr)
            return None
        except urllib.error.URLError as e:
            last_error = f"URLError: {e.reason}"
            print(f"[qing-agent unreachable retry {attempt}/{QING_AGENT_MAX_RETRIES}] {e.reason}", file=sys.stderr)
            if attempt < QING_AGENT_MAX_RETRIES:
                _time.sleep(2 ** attempt)
                continue
            return None
        except (TimeoutError, OSError) as e:
            last_error = f"timeout: {e}"
            print(f"[qing-agent timeout retry {attempt}/{QING_AGENT_MAX_RETRIES}] {e}", file=sys.stderr)
            if attempt < QING_AGENT_MAX_RETRIES:
                _time.sleep(2 ** attempt)
                continue
            return None
        except Exception as e:
            last_error = f"error: {e}"
            print(f"[qing-agent error retry {attempt}/{QING_AGENT_MAX_RETRIES}] {e}", file=sys.stderr)
            if attempt < QING_AGENT_MAX_RETRIES:
                _time.sleep(2 ** attempt)
                continue
            return None

    elapsed_ms = (_time.perf_counter() - t0) * 1000
    _log_request_payload(payload, body, response, error=last_error, elapsed_ms=elapsed_ms)
    return response


def call_qing_agent(data: dict) -> dict | None:
    """POST the context dict to qing-agent and return the response JSON."""
    if not _wait_for_agent_health(QING_AGENT_HEALTH_URL, max_wait_s=60):
        print("[qing-agent] agent not ready (cold start?), falling back", file=sys.stderr)
        return None

    market_snapshot, quote_lookup = _build_market_snapshot(data)

    payload = {
        "query": f"{data.get('trigger', {}).get('title', '')}：{data.get('trigger', {}).get('reason', '')}",
        "session_id": f"hermes-{data.get('timestamp', 'now')}",
        "stock_code": data.get("stock_code", ""),
        "analysis_type": data.get("analysis_type", "market"),
        "trigger": data.get("trigger", {}),
        "alerts": data.get("alerts", []),
        "buy_signal_candidates": data.get("buy_signal_candidates", []),
        "market_snapshot": market_snapshot,
        "positions": _normalize_positions(data.get("positions", {}), quote_lookup),
        "watchlist": _normalize_watchlist(data.get("watchlist", []), quote_lookup),
        # 2026-08-24: 显式传 core_only，只扫 P1+持仓（原依赖 agent 进程环境变量
        # WATCHLIST_CORE_ONLY，但 uvicorn 进程没有该变量导致 73 只全量进 22 个 shard，
        # 单轮 analyze 1600s 击穿 cron 900s 超时）
        "core_only": os.environ.get("WATCHLIST_CORE_ONLY", "0").lower() in ("1", "true", "yes", "on"),
        "sector_strengths": data.get("sector_strengths", []),
        "external_sector_boards": data.get("external_sector_boards", {}),
    }

    trigger_id = (data.get("trigger") or {}).get("id", "")
    post_timeout = 90.0 if trigger_id == "pre_market" else None
    response = _post_analyze_trigger(payload, timeout=post_timeout)
    _log_request_payload(
        data,
        json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        response,
        error=None,
        elapsed_ms=None,
    )

    if trigger_id == "pre_market" and response is None:
        try:
            ds = load_daily_state()
            ds["pre_market_brief"] = {"available": False, "errors": ["pre_market 节点调用超时或失败"]}
            ds = update_market_stage(
                ds,
                phase="数据不可用",
                detail="09:00 节点超时",
                updated_by="pre_market:timeout",
            )
            save_daily_state(ds)
        except Exception as e:
            print(f"[pre_market] failed to save degraded state: {e}", file=sys.stderr)

    return response


# ── 幻觉检测模式 ──
# Only flag future years (2027+) and genuine hallucination templates.
# "数据缺失/暂无数据" is legitimate status report when live quotes are unavailable.
_HALLUCINATION_FUTURE_YEAR = re.compile(r"20(2[7-9]|[3-9]\d)年")
_HALLUCINATION_META = re.compile(r"数据恢复是最关键")
# 日期复盘模板：只标记“未来日期”的复盘，当前/历史日期的复盘是正常表述
_HALLUCINATION_DATE_REVIEW = re.compile(r"这是(20\d{2})年(\d{1,2})月(\d{1,2})日(盘后)?复盘")


def _is_hallucinated(output: str) -> bool:
    """Only flags future years (2027+) or known hallucination templates.
    Past/current years (<=2026) are valid references."""
    from datetime import datetime
    current_year = datetime.now().year

    # Future year check — 2027+ is definitely hallucination
    if _HALLUCINATION_FUTURE_YEAR.search(output):
        return True

    # Meta-hallucination
    if _HALLUCINATION_META.search(output):
        return True

    # Date review template: only flag if the year is in the future
    for m in _HALLUCINATION_DATE_REVIEW.finditer(output):
        try:
            year = int(m.group(1))
            if year > current_year:
                return True
        except Exception:
            pass

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

    # 4. Fallback: qing-agent unavailable or returned empty
    if not QING_AGENT_FALLBACK_ENABLED:
        print("[Qing-Agent ✗ FALLBACK DISABLED] 本地规则输出已关闭，仅记录错误", file=sys.stderr)
        # 向 Bridge stdout 输出简短提示，避免 cron 任务静默失败、用户收不到飞书通知
        trigger_title = data.get("trigger", {}).get("title", "定时分析")
        print(f"⚠️ {trigger_title} 分析服务异常，本次未生成报告，已自动清理重试标记。")
        # 清除 dedupe，让下一次调度可以重试
        _remove_agent_trigger_dedupe(root, data)
        return 0

    fallback_text = fetch_fallback_text_context(root, data)
    if not fallback_text:
        # Fallback also empty — this means the trigger was recorded in state but output failed.
        # Remove the dedupe entry so the next run can retry.
        _remove_agent_trigger_dedupe(root, data)
        return 0
    print("[Qing-Agent ✗ FALLBACK]")
    print("[模型路由：未调用 Qing-Agent，走本地规则 fallback]")
    print(fallback_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
