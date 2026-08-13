"""按日期区间的历史数据访问（kline_cache 只支持"最近 N 日"，这里补区间查询）。

读路径纯 SQLite，无网络，可完全离线回放。
quote 字段契约对齐生产 fetcher（monitor/fetchers/__init__.py，东财/腾讯）：
{"code": "600519"(裸码), "secid": "1.600519", "name", "latest", "open", "high",
 "low", "volume", "amount", "pct_change", "turnover_rate"}。
（monitor/tests/test_e2e.py 的 mock 把 secid 塞进 code 且无 secid 字段，
会导致 _quote_for_stock 匹配失败——以生产 fetcher 为准。）
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

_DEFAULT_DB = Path("infra/data/kline_cache.db")

_KLINE_COLS = (
    "trade_date AS date, open, high, low, close, volume, turnover, amplitude, pct_change"
)

# 盲判/评分用的指数 IDX 别名 → index_klines 表的实际 code（2026-08-13 起指数统一读 index_klines）
INDEX_ALIAS_TO_CODE = {
    "IDX000300": "sh000300",  # 沪深300
    "IDX000001": "sh000001",  # 上证
    "IDX399006": "sz399006",  # 创业板指
    "IDX399001": "sz399001",  # 深证成指
    "IDX000852": "sh000852",  # 中证1000
}


def _connect(db_path: Path | None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path or _DEFAULT_DB))
    conn.row_factory = sqlite3.Row
    return conn


def get_index_daily(
    code: str, start: str, end: str, db_path: Path | None = None
) -> list[dict]:
    """按日期区间取指数日 K（从 index_klines 表 daily 级别）。

    指数统一读 index_klines 表（2026-08-13 起），code 接受 IDX 别名
    （如 'IDX000300'）或实际代码（'sh000300'），内部映射后查表。
    返回与 get_klines_range 兼容的字段：date/open/high/low/close/volume/pct_change。
    pct_change 由 close 序列补算（index_klines 表不存该字段）。
    """
    actual = INDEX_ALIAS_TO_CODE.get(code, code)
    sql = (
        "SELECT bar_time AS date, open, high, low, close, volume "
        "FROM index_klines WHERE code = ? AND timeframe = 'daily' "
        "AND bar_time BETWEEN ? AND ? ORDER BY bar_time"
    )
    with _connect(db_path) as conn:
        rows = conn.execute(sql, (actual, start, end)).fetchall()
    bars = [dict(r) for r in rows]
    prev: float | None = None
    for b in bars:
        close = b.get("close")
        b["pct_change"] = (close / prev - 1.0) * 100 if (prev and close) else None
        prev = close
    return bars



def get_klines_range(
    code: str, start: str, end: str, db_path: Path | None = None
) -> list[dict]:
    """按日期区间取日 K（含首尾），date 升序。

    code 传裸码（'002371'）或带后缀（'002371.SZ'）均可；缓存里两种格式
    并存（pre_fetch 写 '000636.SZ'，早期写入为裸码），查询同时兼容。
    """
    bare = code.split(".")[0]
    sql = (
        f"SELECT {_KLINE_COLS} FROM stocks_kline "
        "WHERE (code = ? OR code LIKE ?) AND trade_date BETWEEN ? AND ? ORDER BY trade_date"
    )
    with _connect(db_path) as conn:
        rows = conn.execute(sql, (bare, f"{bare}.%", start, end)).fetchall()
    return [dict(r) for r in rows]


def list_trading_days(start: str, end: str, db_path: Path | None = None) -> list[str]:
    """回测可用交易日 = 缓存里实际存在数据的日期（免交易日历）。"""
    sql = "SELECT DISTINCT trade_date FROM stocks_kline WHERE trade_date BETWEEN ? AND ? ORDER BY trade_date"
    with _connect(db_path) as conn:
        return [r[0] for r in conn.execute(sql, (start, end)).fetchall()]


def coverage(db_path: Path | None = None) -> dict[str, tuple[str, str]]:
    """各标的缓存日期范围 {bare_code: (min_date, max_date)}。

    键统一为裸码（'002371'）；缓存里 '002371' 与 '002371.SZ' 并存时合并取首尾。
    """
    sql = "SELECT code, MIN(trade_date), MAX(trade_date) FROM stocks_kline GROUP BY code"
    cov: dict[str, tuple[str, str]] = {}
    with _connect(db_path) as conn:
        for code, lo, hi in conn.execute(sql).fetchall():
            bare = str(code).split(".")[0]
            if bare in cov:
                old_lo, old_hi = cov[bare]
                cov[bare] = (min(old_lo, lo), max(old_hi, hi))
            else:
                cov[bare] = (lo, hi)
    return cov


def _secid(code: str) -> str:
    """'600519.SH'/'600519' → '1.600519'；'002371.SZ' → '0.002371'。"""
    bare = code.split(".")[0]
    market = "1" if bare.startswith(("5", "6", "9")) else "0"
    return f"{market}.{bare}"


def quote_from_kline(code: str, name: str, kline: dict) -> dict:
    """由单日 K 线重建规则引擎可消费的 quote 条目。

    契约对齐生产 fetcher（monitor/fetchers/__init__.py）：code=裸 6 位代码，
    secid='市场.代码'。引擎 _quote_for_stock 靠 code 精确/标准化匹配 + secid 回退，
    只给 secid 形式的 code 会匹配不上 stock_pool 的 '000636.SZ'。
    """
    return {
        "code": code.split(".")[0],
        "secid": _secid(code),
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
