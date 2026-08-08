"""按日期区间的历史数据访问（kline_cache 只支持"最近 N 日"，这里补区间查询）。

读路径纯 SQLite，无网络，可完全离线回放。
quote 字段契约对齐 monitor/tests/test_e2e.py 的 mock_quote_snapshot：
{"code": "1.600519"(secid), "name", "latest", "open", "high", "low",
 "volume", "amount", "pct_change", "turnover_rate"}。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

_DEFAULT_DB = Path("infra/data/kline_cache.db")

_KLINE_COLS = (
    "trade_date AS date, open, high, low, close, volume, turnover, amplitude, pct_change"
)


def _connect(db_path: Path | None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path or _DEFAULT_DB))
    conn.row_factory = sqlite3.Row
    return conn


def get_klines_range(
    code: str, start: str, end: str, db_path: Path | None = None
) -> list[dict]:
    """按日期区间取日 K（含首尾），date 升序。code 用缓存里的裸码（'002371'）。"""
    bare = code.split(".")[0]
    sql = (
        f"SELECT {_KLINE_COLS} FROM stocks_kline "
        "WHERE code = ? AND trade_date BETWEEN ? AND ? ORDER BY trade_date"
    )
    with _connect(db_path) as conn:
        rows = conn.execute(sql, (bare, start, end)).fetchall()
    return [dict(r) for r in rows]


def list_trading_days(start: str, end: str, db_path: Path | None = None) -> list[str]:
    """回测可用交易日 = 缓存里实际存在数据的日期（免交易日历）。"""
    sql = "SELECT DISTINCT trade_date FROM stocks_kline WHERE trade_date BETWEEN ? AND ? ORDER BY trade_date"
    with _connect(db_path) as conn:
        return [r[0] for r in conn.execute(sql, (start, end)).fetchall()]


def coverage(db_path: Path | None = None) -> dict[str, tuple[str, str]]:
    """各标的缓存日期范围 {code: (min_date, max_date)}。"""
    sql = "SELECT code, MIN(trade_date), MAX(trade_date) FROM stocks_kline GROUP BY code"
    with _connect(db_path) as conn:
        return {r[0]: (r[1], r[2]) for r in conn.execute(sql).fetchall()}


def _secid(code: str) -> str:
    """'600519.SH'/'600519' → '1.600519'；'002371.SZ' → '0.002371'。"""
    bare = code.split(".")[0]
    market = "1" if bare.startswith(("5", "6", "9")) else "0"
    return f"{market}.{bare}"


def quote_from_kline(code: str, name: str, kline: dict) -> dict:
    """由单日 K 线重建规则引擎可消费的 quote 条目。"""
    return {
        "code": _secid(code),
        "name": name,
        "latest": kline["close"],
        "open": kline["open"],
        "high": kline["high"],
        "low": kline["low"],
        "volume": kline["volume"],
        "amount": None,  # K 线表无成交额字段，如实为 None
        "pct_change": kline.get("pct_change"),
        "turnover_rate": kline.get("turnover"),
        "trade_date": kline["date"],
    }


def build_quote_snapshot(quotes: list[dict]) -> dict:
    return {"source": "kline_cache_backtest", "quotes": quotes}
