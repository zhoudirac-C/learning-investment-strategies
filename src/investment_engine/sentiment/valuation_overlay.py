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
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
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

# ── 并发参数（2026-10-16 方案 B1）─────────────────────────────────────────
# 背景：串行版 31 cold 板块需 30-50 分钟，超过 cron 900s 窗口 → 必然超时。
# 并发化把「板块 × 成分股」两层都并行：单板块内并发抓成分股，
# 板块之间也并发。目标是 900s 内以充裕余量跑完全部 cold 板块。
OVERLAY_WORKERS = 8       # 单板块内成分股并发数
BOARD_WORKERS = 4         # 板块间并发数
MAX_INFLIGHT = 12         # 全局在飞请求上界（保护 datacenter-web 不被瞬时打爆）
# 全局限速：令牌桶，允许 MAX_INFLIGHT 个请求瞬时并行，
# 超出的排队等待，稳态速率约 1/_RATE_INTERVAL_S 请求/秒。
_RATE_INTERVAL_S = 0.05

_RATE_LOCK = threading.Lock()
_rate_last = 0.0


def _rate_limit() -> None:
    """跨线程令牌桶节流。

    关键：**不在持锁状态下 sleep 整个间隔**（那会把并发串行化，
    抵消掉并行收益）。改为：持锁只推进令牌时间戳、算出本请求的
    应发时刻，释放锁后再 sleep 到该时刻——这样多个线程可重叠等待，
    稳态放行速率 ≈ 1/_RATE_INTERVAL_S，同时不阻塞其他线程取号。
    """
    global _rate_last
    with _RATE_LOCK:
        now = time.monotonic()
        # 允许最多 MAX_INFLIGHT 个请求"预支"到未来，形成并行窗口
        next_slot = max(now, _rate_last + _RATE_INTERVAL_S)
        _rate_last = next_slot - (MAX_INFLIGHT * _RATE_INTERVAL_S)
        if _rate_last < now - 1.0:
            _rate_last = now
        wait_until = next_slot
    delay = wait_until - time.monotonic()
    if delay > 0:
        time.sleep(delay)


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


def _assess_one_stock(code: str, field: str) -> tuple[float, float] | None:
    """抓取单只成分股，返回 (当前分位, 当前值)；数据不足/异常返回 None。

    并发安全：仅做 HTTP + 纯计算，无共享可变态（限速经 _rate_limit 全局锁）。
    """
    try:
        _rate_limit()
        latest = fetch_valuation_latest(code)
        cur = latest and latest.get(field)
        if not cur or float(cur) <= 0:
            return None
        cur = float(cur)
        _rate_limit()
        hist = fetch_history(code, field)
        if len(hist) < 60:
            return None
        return _pct(cur, hist), cur
    except Exception:  # noqa: BLE001
        return None


def _compute_from_pcts(pcts: list[float], latest_vals: list[float],
                       board: str, kind: str, method: str,
                       threshold: float) -> dict:
    if len(pcts) < MIN_STOCKS:
        return {"board": board, "method": method, "value": -1.0, "cheap": None,
                "n_stocks": len(pcts),
                "as_of": datetime.now().isoformat(timespec="seconds")}
    med_pct = round(statistics.median(pcts), 1)
    return {"board": board, "method": method, "value": med_pct,
            "cheap": med_pct < threshold,
            f"median_{'pb' if kind == 'cyclical' else 'pe'}": round(
                statistics.median(latest_vals), 2),
            "n_stocks": len(pcts),
            "as_of": datetime.now().isoformat(timespec="seconds")}


def assess_valuation(board: str, use_cache: bool = True) -> dict:
    """评估板块估值便宜度（单板块；成分股并发抓取）。

    返回: {"board", "method": "pe_percentile"|"pb_percentile", "value": 分位中位数,
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
    if stocks:
        with ThreadPoolExecutor(max_workers=OVERLAY_WORKERS) as ex:
            for res in ex.map(lambda c: _assess_one_stock(c, field), stocks):
                if res is not None:
                    pcts.append(res[0])
                    latest_vals.append(res[1])

    result = _compute_from_pcts(pcts, latest_vals, board, kind, method, threshold)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_p.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result


def assess_all_valuations(boards: list[str],
                          use_cache: bool = True) -> dict[str, dict]:
    """批量并发评估多个板块估值（板块间并发；单板块内成分股并发）。

    板块情绪温度计的冷区覆盖入口：对全部 cold 板块一次性评估，
    使 31+ 板块能在 cron 超时窗口内完成（串行版需 30-50 分钟）。
    返回 {board: assessment}，键与输入 boards 一一对应。
    """
    if not boards:
        return {}
    out: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=BOARD_WORKERS) as pool:
        futs = {pool.submit(assess_valuation, b, use_cache): b for b in boards}
        for fut in as_completed(futs):
            b = futs[fut]
            try:
                out[b] = fut.result()
            except Exception as e:  # noqa: BLE001
                out[b] = {"board": b, "error": str(e)[:80], "cheap": None}
    return out
