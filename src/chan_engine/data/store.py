"""chan_bars SQLite 存储：长历史日线 + 分钟滑动窗口本地库（M6-1/M7-1）。

独立于监控 ``kline_cache.db``：后者 ``save_klines`` 为 per-code 覆盖写
（DELETE+INSERT），每日 cron 续拉会销毁长历史；本库幂等 upsert，
行级 ``source``/``adjust`` 溯源。

M7-1 增补 ``minute_bars``（chanlun-m7-multitimeframe-skill.md §4.2）：
60m/30m 滑动窗口快照（单次 260 根 ≈ 60m 2.6 个月 / 30m 1.4 个月，
不做历史回填——能力边界，与日线长历史互补）；盘中未完成 bar 打
``complete=0`` 保留入库，读取默认剔除（§4.3，防用未走完的 bar 确认分型）。
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from chan_engine.data.fetch import VALID_MINUTE_TF
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

CREATE TABLE IF NOT EXISTS minute_bars (
    code       TEXT NOT NULL,
    tf         INTEGER NOT NULL,           -- 60 / 30
    dt         TEXT NOT NULL,              -- 'YYYY-MM-DD HH:MM'
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    complete INTEGER NOT NULL DEFAULT 1,   -- 盘中未完成 bar = 0
    source TEXT NOT NULL,                  -- 'sina' / 'tdx'
    updated_at TEXT,
    PRIMARY KEY (code, tf, dt)
);

CREATE INDEX IF NOT EXISTS idx_minute_bars_code_tf_dt
    ON minute_bars(code, tf, dt);
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
    tf: int | None = None,
    include_partial: bool = False,
) -> list[Bar]:
    """读取并适配为引擎消费的 ``list[Bar]``；ts = 窗口内递增序号 0..n-1。

    ``tf`` 缺省走日线（M6 既有）；tf=60/30 走 minute_bars（M7-1），
    默认剔除盘中未完成 bar（complete=0），``include_partial=True`` 才返回。
    """
    if tf is None:
        rows = load_daily(code, start=start, end=end, adjust=adjust, db_path=db_path)
    else:
        if tf not in VALID_MINUTE_TF:
            raise ValueError(f"不支持的分钟周期 tf={tf}（仅 {VALID_MINUTE_TF}）")
        rows = load_minute(code, tf, start=start, end=end,
                           include_partial=include_partial, db_path=db_path)
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


# ── M7-1 分钟线存储（chanlun-m7-multitimeframe-skill.md §4.2/§4.3） ──

def save_minute(
    code: str,
    tf: int,
    rows: list[dict],
    source: str,
    db_path: Path | None = None,
) -> int:
    """幂等 upsert 分钟线（INSERT OR REPLACE）。返回写入行数。

    rows 每项：``{"dt", "open", "high", "low", "close", "volume", "complete"}``，
    即 fetch.normalize_*_minute_records + mark_complete 的归一输出。
    盘中 complete=0 bar 收盘后重拉自然覆盖为 complete=1（同主键）。
    写入侧防线：缺 dt 或 o/h/l/c 为 None 的行拒绝入库（能存进来的数据
    必须能被 load_bars 读出）；complete 缺键/None 按 1 处理。
    """
    if tf not in VALID_MINUTE_TF:
        raise ValueError(f"不支持的分钟周期 tf={tf}（仅 {VALID_MINUTE_TF}）")
    for r in rows:
        if not r.get("dt") or any(r.get(k) is None for k in ("open", "high", "low", "close")):
            raise ValueError(f"分钟行缺关键字段，拒绝入库: {r!r}")
    if not rows:
        return 0
    init_db(db_path)
    now = datetime.now(_CN_TZ).isoformat()
    with _connect(db_path, write=True) as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO minute_bars
                (code, tf, dt, open, high, low, close, volume,
                 complete, source, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    code,
                    tf,
                    str(r["dt"]),
                    r.get("open"),
                    r.get("high"),
                    r.get("low"),
                    r.get("close"),
                    r.get("volume"),
                    int(r.get("complete") if r.get("complete") is not None else 1),
                    source,
                    now,
                )
                for r in rows
            ],
        )
        conn.commit()
    return len(rows)


def load_minute(
    code: str,
    tf: int,
    start: str | None = None,
    end: str | None = None,
    include_partial: bool = False,
    db_path: Path | None = None,
) -> list[dict]:
    """读取分钟线，dt 升序；start/end 含首尾。

    界口径：start 传纯日期（'2026-08-27'）按前缀比较含当天全部 bar；
    end 传纯日期自动归一为 'YYYY-MM-DD 23:59'（同样含当天，dt 为
    'YYYY-MM-DD HH:MM' 字符串比较，不归一会静默丢当天——评审 Major-1）。
    默认剔除盘中未完成 bar（complete=0）；``include_partial=True`` 才返回。
    无数据返回 []。
    """
    if tf not in VALID_MINUTE_TF:
        raise ValueError(f"不支持的分钟周期 tf={tf}（仅 {VALID_MINUTE_TF}）")
    init_db(db_path)
    sql = "SELECT * FROM minute_bars WHERE code = ? AND tf = ?"
    params: list = [code, tf]
    if not include_partial:
        sql += " AND complete = 1"
    if start:
        sql += " AND dt >= ?"
        params.append(start)
    if end:
        sql += " AND dt <= ?"
        params.append(end + " 23:59" if len(end) == 10 else end)
    sql += " ORDER BY dt"
    with _connect(db_path) as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def coverage_minute(
    db_path: Path | None = None,
) -> dict[tuple[str, int], tuple[str, str, int]]:
    """各标的各周期已存范围：{(code, tf): (min_dt, max_dt, count)}。"""
    init_db(db_path)
    sql = (
        "SELECT code, tf, MIN(dt), MAX(dt), COUNT(*) "
        "FROM minute_bars GROUP BY code, tf"
    )
    with _connect(db_path) as conn:
        return {(r[0], r[1]): (r[2], r[3], r[4]) for r in conn.execute(sql).fetchall()}


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
