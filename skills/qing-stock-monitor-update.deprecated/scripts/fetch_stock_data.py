#!/usr/bin/env python3
"""
股票数据获取脚本（qing-stock-monitor-update 配套）

功能：
- 读取 config/stock_monitor/watchlist.yaml + positions.yaml 中的标的
- 获取实时行情、K线、主力资金、分时图
- 输出结构化 JSON 供 LLM 分析

数据源优先级：
1. 东方财富实时行情（stock_monitor 已有接口）
2. glmv-stock-analyst/fetch_all.py（K线、基本面、主力资金、分时图）
3. 新浪财经（降级）

用法：
  python3 fetch_stock_data.py --config-dir config/stock_monitor --output /tmp/data.json
  python3 fetch_stock_data.py --codes 600246.SH,002055.SZ --output /tmp/data.json
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time as time_module
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# 尝试导入 stock_monitor 的已有工具
HAS_MONITOR_IMPORTS = False
MARKET_INDEXES: dict[str, str] = {}
QUOTE_FIELDS = "f12,f13,f14,f2,f3,f4,f5,f6,f15,f16,f17,f18"
EASTMONEY_QUOTE_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"
QUOTE_CHUNK_SIZE = 15

try:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
    from qing_investment.stock_monitor import (
        QUOTE_FIELDS as _QUOTE_FIELDS,
        EASTMONEY_QUOTE_URL as _EASTMONEY_QUOTE_URL,
        QUOTE_CHUNK_SIZE as _QUOTE_CHUNK_SIZE,
        MARKET_INDEXES as _MARKET_INDEXES,
        chunk_quote_targets,
        fetch_eastmoney_quotes,
        parse_eastmoney_quote_rows,
        stock_code_to_secid,
        _to_float,
        load_yaml,
        now_cn,
    )
    HAS_MONITOR_IMPORTS = True
    QUOTE_FIELDS = _QUOTE_FIELDS
    EASTMONEY_QUOTE_URL = _EASTMONEY_QUOTE_URL
    QUOTE_CHUNK_SIZE = _QUOTE_CHUNK_SIZE
    MARKET_INDEXES = _MARKET_INDEXES
except ImportError as e:
    print(f"⚠ 无法导入 stock_monitor 模块: {e}", file=sys.stderr)
    # Fallback values
    MARKET_INDEXES = {
        "上证指数": "1.000001",
        "深证成指": "0.399001",
        "创业板指": "0.399006",
        "科创50": "1.000688",
    }


CN_TZ = datetime.now().astimezone().tzinfo


@dataclass
class StockData:
    code: str
    name: str = ""
    latest: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    pct_change: float | None = None
    volume: int | None = None
    amount: float | None = None
    prev_close: float | None = None
    kline: dict = field(default_factory=dict)
    capital_flow: dict = field(default_factory=dict)
    technical_narrative: dict = field(default_factory=dict)
    sector_narrative: dict = field(default_factory=dict)
    charts: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def _load_config(config_dir: Path) -> tuple[dict, dict]:
    """Load watchlist and positions from config directory."""
    if HAS_MONITOR_IMPORTS:
        watchlist = load_yaml(config_dir / "watchlist.yaml")
        positions = load_yaml(config_dir / "positions.yaml")
    else:
        import yaml
        watchlist = yaml.safe_load((config_dir / "watchlist.yaml").read_text()) if (config_dir / "watchlist.yaml").exists() else {}
        positions = yaml.safe_load((config_dir / "positions.yaml").read_text()) if (config_dir / "positions.yaml").exists() else {}
    return watchlist or {}, positions or {}


def _collect_codes(watchlist: dict, positions: dict, extra_codes: list[str] | None = None) -> list[str]:
    """Collect all stock codes from watchlist, positions, and extra codes."""
    codes: set[str] = set()
    
    # From watchlist
    for theme in watchlist.get("themes", []) or []:
        for stock in theme.get("stocks", []) or []:
            code = stock.get("code")
            if code:
                codes.add(str(code))
    
    # From positions
    for account in positions.get("accounts", []) or []:
        for pos in account.get("positions", []) or []:
            code = pos.get("code")
            if code:
                codes.add(str(code))
    
    # Extra codes
    if extra_codes:
        codes.update(extra_codes)
    
    return sorted(codes)


def _fetch_eastmoney_quotes(codes: list[str]) -> dict:
    """Fetch real-time quotes from Eastmoney."""
    if not HAS_MONITOR_IMPORTS:
        return {"source": "degraded", "quotes": [], "errors": ["stock_monitor imports unavailable"]}
    
    targets = dict(MARKET_INDEXES)
    seen = set(targets.values())
    
    for code in codes:
        secid = stock_code_to_secid(code)
        if secid and secid not in seen:
            targets[code] = secid
            seen.add(secid)
    
    return fetch_eastmoney_quotes(targets)


def _fetch_glmv_data(code: str, output_dir: Path) -> dict:
    """Fetch detailed data using glmv-stock-analyst fetch_all.py."""
    glmv_script = Path(__file__).resolve().parents[1] / ".." / "qing-stock-analysis" / "vendor" / "glmv-stock-analyst" / "scripts" / "fetch_all.py"
    
    if not glmv_script.exists():
        return {"error": f"glmv script not found: {glmv_script}"}
    
    out = output_dir / f"glmv_{code.replace('.', '_')}"
    out.mkdir(parents=True, exist_ok=True)
    
    try:
        result = subprocess.run(
            [sys.executable, str(glmv_script), code, "--output-dir", str(out)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            return {"error": f"glmv exit {result.returncode}", "stderr": result.stderr[:500]}
        
        # Parse output directory for generated files
        data_json = list(out.rglob("data.json"))
        summary_json = list(out.rglob("summary.json"))
        
        return {
            "output_dir": str(out),
            "data_json": str(data_json[0]) if data_json else None,
            "summary_json": str(summary_json[0]) if summary_json else None,
            "stdout": result.stdout[-1000:] if result.stdout else "",
        }
    except subprocess.TimeoutExpired:
        return {"error": "glmv timeout after 60s"}
    except Exception as e:
        return {"error": str(e)}


def _to_float_safe(value: object) -> float | None:
    """Safely convert value to float."""
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    text = str(value).strip()
    if not text or text in {"-", "--"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _build_technical_narrative(quote: dict, glmv_data: dict | None) -> dict:
    """Build technical narrative from quote and glmv data."""
    narrative = {
        "trend": "",
        "volume_character": "",
        "key_levels": [],
        "pattern": "",
        "note": "",
    }
    
    latest = _to_float_safe(quote.get("latest"))
    high = _to_float_safe(quote.get("high"))
    low = _to_float_safe(quote.get("low"))
    open_price = _to_float_safe(quote.get("open"))
    prev_close = _to_float_safe(quote.get("previous_close"))
    pct_change = _to_float_safe(quote.get("pct_change"))
    volume = _to_float_safe(quote.get("volume"))
    
    if latest is None:
        return narrative
    
    # Trend
    if pct_change is not None:
        if pct_change > 9.5:
            narrative["trend"] = "涨停，强势"
        elif pct_change > 5:
            narrative["trend"] = "大涨，偏强"
        elif pct_change > 0:
            narrative["trend"] = "小涨，震荡偏强"
        elif pct_change > -5:
            narrative["trend"] = "小跌，震荡偏弱"
        else:
            narrative["trend"] = "大跌，弱势"
    
    # Key levels
    if high is not None and low is not None:
        narrative["key_levels"].append(f"日内高点：{high}")
        narrative["key_levels"].append(f"日内低点：{low}")
    if prev_close is not None:
        narrative["key_levels"].append(f"昨收：{prev_close}")
    
    # Pattern detection
    if high and low and open_price and latest:
        body = abs(latest - open_price)
        range_ = high - low
        if range_ > 0 and body / range_ < 0.3:
            narrative["pattern"] = "十字星，方向不明"
        elif latest > open_price and (high - latest) > body * 2:
            narrative["pattern"] = "长上影线，上方有抛压"
        elif latest < open_price and (latest - low) > body * 2:
            narrative["pattern"] = "长下影线，下方有承接"
        elif latest == high and latest > open_price:
            narrative["pattern"] = "光头阳线，强势"
        elif latest == low and latest < open_price:
            narrative["pattern"] = "光头阴线，弱势"
    
    return narrative


def _build_sector_narrative(theme_name: str, stocks_in_sector: list[dict]) -> dict:
    """Build sector narrative from stocks in the same theme."""
    if not stocks_in_sector:
        return {}
    
    pct_changes = [_to_float_safe(s.get("pct_change")) for s in stocks_in_sector if _to_float_safe(s.get("pct_change")) is not None]
    if not pct_changes:
        return {}
    
    avg_change = sum(pct_changes) / len(pct_changes)
    red_count = sum(1 for p in pct_changes if p > 0)
    
    return {
        "relative_strength": f"组内平均涨幅 {avg_change:.2f}%，红盘率 {red_count}/{len(pct_changes)}",
        "money_flow": "",
        "leader_follower": "",
        "catalyst": "",
        "risk": "",
    }


def fetch_data(codes: list[str], config_dir: Path, output_dir: Path) -> dict:
    """Main data fetching orchestrator."""
    result = {
        "meta": {
            "fetch_time": datetime.now().isoformat(),
            "data_source": "eastmoney_push2",
            "degraded": False,
            "missing_fields": [],
        },
        "market": {
            "indexes": {},
            "context": {},
        },
        "stocks": [],
    }
    
    # Fetch real-time quotes
    quote_snapshot = _fetch_eastmoney_quotes(codes)
    result["meta"]["data_source"] = quote_snapshot.get("source", "unknown")
    result["meta"]["elapsed_ms"] = quote_snapshot.get("elapsed_ms", 0)
    
    if quote_snapshot.get("errors"):
        result["meta"]["degraded"] = True
        result["meta"]["missing_fields"].append("realtime_quotes")
    
    quotes = {}
    for quote in quote_snapshot.get("quotes", []) or []:
        secid = quote.get("secid")
        code = quote.get("code")
        if secid:
            quotes[secid] = quote
        if code:
            quotes[code] = quote
    
    # Build index data
    for name, secid in MARKET_INDEXES.items():
        q = quotes.get(secid)
        if q:
            result["market"]["indexes"][name] = {
                "latest": _to_float_safe(q.get("latest")),
                "pct_change": _to_float_safe(q.get("pct_change")),
                "volume": q.get("volume"),
                "amount": q.get("amount"),
            }
    
    # Build per-stock data
    for code in codes:
        secid = None
        if HAS_MONITOR_IMPORTS:
            secid = stock_code_to_secid(code)
        quote = quotes.get(secid) or quotes.get(code[-6:] if len(code) > 6 else code)
        
        if not quote:
            result["stocks"].append({
                "code": code,
                "name": "",
                "errors": ["No quote data"],
            })
            continue
        
        stock_data = StockData(
            code=code,
            name=str(quote.get("name") or ""),
            latest=_to_float_safe(quote.get("latest")),
            open=_to_float_safe(quote.get("open")),
            high=_to_float_safe(quote.get("high")),
            low=_to_float_safe(quote.get("low")),
            close=_to_float_safe(quote.get("latest")),  # close = latest for realtime
            pct_change=_to_float_safe(quote.get("pct_change")),
            volume=int(_to_float_safe(quote.get("volume")) or 0) if quote.get("volume") else None,
            amount=_to_float_safe(quote.get("amount")),
            prev_close=_to_float_safe(quote.get("previous_close")),
        )
        
        # Technical narrative
        stock_data.technical_narrative = _build_technical_narrative(quote, None)
        
        # Try glmv for deeper data
        glmv_result = _fetch_glmv_data(code, output_dir)
        if "error" not in glmv_result:
            stock_data.charts["glmv_output"] = glmv_result.get("output_dir")
        else:
            stock_data.errors.append(f"glmv: {glmv_result['error']}")
            result["meta"]["missing_fields"].append(f"{code}_glmv")
        
        result["stocks"].append({
            "code": stock_data.code,
            "name": stock_data.name,
            "latest": stock_data.latest,
            "open": stock_data.open,
            "high": stock_data.high,
            "low": stock_data.low,
            "close": stock_data.close,
            "pct_change": stock_data.pct_change,
            "volume": stock_data.volume,
            "amount": stock_data.amount,
            "prev_close": stock_data.prev_close,
            "technical_narrative": stock_data.technical_narrative,
            "sector_narrative": stock_data.sector_narrative,
            "charts": stock_data.charts,
            "errors": stock_data.errors,
        })
    
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Stock data fetcher for monitor update")
    parser.add_argument("--config-dir", default="config/stock_monitor", help="Config directory")
    parser.add_argument("--codes", default="", help="Comma-separated stock codes")
    parser.add_argument("--output", required=True, help="Output JSON file path")
    parser.add_argument("--include-lhb", action="store_true", help="Include 龙虎榜 data (if available)")
    args = parser.parse_args()
    
    config_dir = Path(args.config_dir)
    output_path = Path(args.output)
    output_dir = output_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Collect codes
    extra_codes = [c.strip() for c in args.codes.split(",") if c.strip()] if args.codes else None
    
    if extra_codes:
        codes = extra_codes
    else:
        watchlist, positions = _load_config(config_dir)
        codes = _collect_codes(watchlist, positions, extra_codes)
    
    if not codes:
        print("No codes to fetch", file=sys.stderr)
        return 1
    
    print(f"Fetching data for {len(codes)} stocks...")
    result = fetch_data(codes, config_dir, output_dir)
    
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Output written to {output_path}")
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
