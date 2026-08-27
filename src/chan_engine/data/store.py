"""chan_bars SQLite 存储：长历史日线本地库（M6-1，设计文档 §4.3/§4.4）。

独立于监控 ``kline_cache.db``：后者 ``save_klines`` 为 per-code 覆盖写
（DELETE+INSERT），每日 cron 续拉会销毁长历史；本库幂等 upsert，
行级 ``source``/``adjust`` 溯源。
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from chan_engine.spec.model import Bar

DEFAULT_DB = Path(__file__).resolve().parents[3] / "infra" / "data" / "chan_bars.db"

_CN_TZ = timezone(timedelta(hours=8))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_bars (
    code       TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    amount REAL,
    adjust TEXT NOT NULL DEFAULT 'qfq',
    source TEXT NOT NULL,
    updated_at TEXT,
    PRIMARY KEY (code, trade_date, adjust)
);

CREATE INDEX IF NOT EXISTS idx_daily_bars_code_date
    ON daily_bars(code, trade_date);
"""


@contextmanager
def _connect(db_path: Path | None, write: bool = False):
    path = db_path or DEFAULT_DB
    if write:
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    if not write:
        conn.execute("PRAGMA query_only=ON;")
    try:
        yield conn
    finally:
        conn.close()


def init_db(db_path: Path | None = None) -> None:
    """建表（幂等）。"""
    with _connect(db_path, write=True) as conn:
        conn.executescript(_SCHEMA)
        conn.commit()


def save_daily(
    code: str,
    rows: list[dict],
    source: str,
    adjust: str = "qfq",
    db_path: Path | None = None,
) -> int:
    """幂等 upsert 日线（INSERT OR REPLACE，不 DELETE 全量）。返回写入行数。

    rows 每项：{"date", "open", "high", "low", "close", "volume", "amount"}，
    即 fetch.normalize_* 的归一输出。
    """
    if not rows:
        return 0
    init_db(db_path)
    now = datetime.now(_CN_TZ).isoformat()
    with _connect(db_path, write=True) as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO daily_bars
                (code, trade_date, open, high, low, close, volume, amount,
                 adjust, source, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    code,
                    str(r["date"]),
                    r.get("open"),
                    r.get("high"),
                    r.get("low"),
                    r.get("close"),
                    r.get("volume"),
                    r.get("amount"),
                    adjust,
                    source,
                    now,
                )
                for r in rows
            ],
        )
        conn.commit()
    return len(rows)


def load_daily(
    code: str,
    start: str | None = None,
    end: str | None = None,
    adjust: str = "qfq",
    db_path: Path | None = None,
) -> list[dict]:
    """读取日线，trade_date 升序；start/end 含首尾。无数据返回 []。"""
    init_db(db_path)
    sql = (
        "SELECT * FROM daily_bars WHERE code = ? AND adjust = ?"
    )
    params: list = [code, adjust]
    if start:
        sql += " AND trade_date >= ?"
        params.append(start)
    if end:
        sql += " AND trade_date <= ?"
        params.append(end)
    sql += " ORDER BY trade_date"
    with _connect(db_path) as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def load_bars(
    code: str,
    start: str | None = None,
    end: str | None = None,
    adjust: str = "qfq",
    db_path: Path | None = None,
) -> list[Bar]:
    """读取并适配为引擎消费的 ``list[Bar]``；ts = 窗口内递增序号 0..n-1。"""
    rows = load_daily(code, start=start, end=end, adjust=adjust, db_path=db_path)
    return [
        Bar(
            ts=i,
            o=float(r["open"]),
            h=float(r["high"]),
            l=float(r["low"]),
            c=float(r["close"]),
            vol=float(r["volume"]) if r["volume"] is not None else 0.0,
        )
        for i, r in enumerate(rows)
    ]


def coverage(
    adjust: str = "qfq",
    db_path: Path | None = None,
) -> dict[str, tuple[str, str, int]]:
    """各标的已存范围：{code: (min_date, max_date, count)}，增量续拉依据。"""
    init_db(db_path)
    sql = (
        "SELECT code, MIN(trade_date), MAX(trade_date), COUNT(*) "
        "FROM daily_bars WHERE adjust = ? GROUP BY code"
    )
    with _connect(db_path) as conn:
        return {r[0]: (r[1], r[2], r[3]) for r in conn.execute(sql, (adjust,)).fetchall()}
