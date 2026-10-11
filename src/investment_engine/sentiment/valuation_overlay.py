"""冰封区板块估值 overlay（板块情绪温度计的"便宜"判定层）。

设计（2026-10-11 用户拍板）：无人问津 ≠ 机会，无人问津 + 便宜才是机会。
- growth（默认）：PE_TTM 成分股中位分位 <30% → cheap
  （每股口径：当前 PE 在自身 3 年历史中的分位，再取全成分中位数）
- cyclical（config/stock_monitor/sentiment_board_class.yaml）：PB_MRQ 同口径 <20%

数据源：东财 datacenter RPT_VALUEANALYSIS_DET（与 fetch_board_valuation.py 同通道同口径）。
性能：冷板块惰性计算 + 3 天结果缓存（infra/data/board_valuation_overlay/{board}.json）。
"""
from __future__ import annotations

import json
import statistics
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from investment_engine.sentiment.board_members import get_board_stocks

ROOT = Path(__file__).resolve().parents[3]
CLASS_CFG = ROOT / "config" / "stock_monitor" / "sentiment_board_class.yaml"
CACHE_DIR = ROOT / "infra" / "data" / "board_valuation_overlay"
EM_BASE = "https://datacenter-web.eastmoney.com/api/data/v1/get"
EM_HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"}
SLEEP_S = 1.5
CACHE_TTL_DAYS = 3
HISTORY_DAYS = 3 * 365
PE_PCT_MAX = 30.0   # growth: PE 分位上限
PB_PCT_MAX = 20.0   # cyclical: PB 分位上限（与 fetch_board_valuation.py 纪律一致）
MAX_STOCKS = 60     # 成分股取样上限（控制耗时）
MIN_STOCKS = 3      # 样本下限


def classify_board(board_name: str) -> str:
    cfg = yaml.safe_load(CLASS_CFG.read_text(encoding="utf-8")) or {}
    cyclical = set(cfg.get("cyclical_boards") or [])
    return "cyclical" if board_name in cyclical else "growth"


def _em_rows(report: str, filter_str: str, page_size: int = 500,
             sort: str = "TRADE_DATE") -> list[dict]:
    params = {"reportName": report, "columns": "ALL", "filter": filter_str,
              "pageNumber": 1, "pageSize": page_size,
              "sortColumns": sort, "sortTypes": "-1", "source": "DataCenter"}
    url = f"{EM_BASE}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers=EM_HEADERS)
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.loads(r.read().decode())
    return (d.get("result") or {}).get("data") or []


def fetch_valuation_latest(code: str) -> dict | None:
    rows = _em_rows("RPT_VALUEANALYSIS_DET", f'(SECURITY_CODE="{code}")',
                    page_size=1)
    return rows[0] if rows else None


def fetch_history(code: str, field: str, days: int = HISTORY_DAYS) -> list[float]:
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = _em_rows(
        "RPT_VALUEANALYSIS_DET",
        f'(SECURITY_CODE="{code}")(TRADE_DATE>=\'{start}\')',
        page_size=500)
    return [float(r[field]) for r in rows if r.get(field) and float(r[field]) > 0]


def _pct(cur: float, hist: list[float]) -> float:
    return round(sum(1 for v in hist if v < cur) / len(hist) * 100, 1) if hist else -1.0


def assess_valuation(board: str, use_cache: bool = True) -> dict:
    """评估板块估值便宜度。返回:
    {"board", "method": "pe_percentile"|"pb_percentile", "value": 分位中位数,
     "cheap": bool|None, "median_pe"/"median_pb": float, "n_stocks": int, "as_of": str}
    """
    cache_p = CACHE_DIR / f"{board}.json"
    if use_cache and cache_p.exists():
        d = json.loads(cache_p.read_text(encoding="utf-8"))
        ts = datetime.fromisoformat(d["as_of"])
        if datetime.now() - ts < timedelta(days=CACHE_TTL_DAYS):
            return d

    kind = classify_board(board)
    method = "pb_percentile" if kind == "cyclical" else "pe_percentile"
    field = "PB_MRQ" if kind == "cyclical" else "PE_TTM"
    threshold = PB_PCT_MAX if kind == "cyclical" else PE_PCT_MAX

    stocks = get_board_stocks(board)[:MAX_STOCKS]
    pcts: list[float] = []
    latest_vals: list[float] = []
    for code in stocks:
        try:
            latest = fetch_valuation_latest(code)
            cur = latest and latest.get(field)
            if not cur or float(cur) <= 0:
                continue
            cur = float(cur)
            hist = fetch_history(code, field)
            if len(hist) < 60:
                continue
            pcts.append(_pct(cur, hist))
            latest_vals.append(cur)
        except Exception:  # noqa: BLE001
            continue
        time.sleep(SLEEP_S)

    if len(pcts) < MIN_STOCKS:
        result = {"board": board, "method": method, "value": -1.0, "cheap": None,
                  "n_stocks": len(pcts),
                  "as_of": datetime.now().isoformat(timespec="seconds")}
    else:
        med_pct = round(statistics.median(pcts), 1)
        result = {"board": board, "method": method, "value": med_pct,
                  "cheap": med_pct < threshold,
                  f"median_{'pb' if kind == 'cyclical' else 'pe'}": round(
                      statistics.median(latest_vals), 2),
                  "n_stocks": len(pcts),
                  "as_of": datetime.now().isoformat(timespec="seconds")}

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_p.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result
