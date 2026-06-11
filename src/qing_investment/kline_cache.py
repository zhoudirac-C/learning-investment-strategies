"""SQLite K线缓存层 —— 日K数据本地存储，支持 WAL 模式多读单写。

设计目标：
- 开盘前预拉取日K写入 SQLite，全天各组件共享
- poll 层和 Agent 层优先读本地，将网络 I/O 转为本地 I/O
- 纯文件数据库，无 Docker/服务依赖，适合云端部署
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# ── 路径配置 ──
_DEFAULT_DB_PATH = (
    Path(__file__).resolve().parents[2] / "infra" / "data" / "kline_cache.db"
)

_CN_TZ = timezone(timedelta(hours=8))


# ── 连接管理 ──
@contextmanager
def _get_conn(write: bool = False, db_path: Path | None = None):
    """获取 SQLite 连接，自动配置 WAL 模式和超时。

    Args:
        write: True 表示写入模式（pre_fetch 使用），False 表示只读模式（poll/Agent 使用）
        db_path: 自定义数据库路径，默认使用 infra/data/kline_cache.db
    """
    path = db_path or _DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    # timeout=30: 等待锁释放的最长时间（秒）
    conn = sqlite3.connect(str(path), timeout=30.0)
    conn.row_factory = sqlite3.Row

    # WAL 模式：支持多读单写，适合"pre_fetch 写 + poll/Agent 读"场景
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA temp_store=MEMORY;")

    if not write:
        # poll/Agent 只读时启用 query_only，防止意外写入
        conn.execute("PRAGMA query_only=ON;")

    try:
        yield conn
    finally:
        conn.close()


# ── 初始化 ──
def init_db(db_path: Path | None = None) -> None:
    """初始化 SQLite 表结构（首次运行时自动创建，幂等）。"""
    with _get_conn(write=True, db_path=db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS stocks_kline (
                code TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL,
                turnover REAL,
                amplitude REAL,
                pct_change REAL,
                updated_at TEXT,
                PRIMARY KEY (code, trade_date)
            );

            CREATE INDEX IF NOT EXISTS idx_kline_code_date
                ON stocks_kline(code, trade_date);

            CREATE TABLE IF NOT EXISTS kline_meta (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            """
        )
        conn.commit()


# ── 写入 ──
def save_klines(
    code: str,
    klines: list[dict[str, Any]],
    db_path: Path | None = None,
) -> None:
    """保存单只股票的日K线（覆盖写入该股票的历史数据）。

    Args:
        code: 股票代码，如 "600378"
        klines: K线数据列表，每项为 dict，至少包含 date, open, high, low, close
        db_path: 自定义数据库路径
    """
    with _get_conn(write=True, db_path=db_path) as conn:
        # 先删除该股票旧数据，再插入新数据（覆盖策略）
        conn.execute("DELETE FROM stocks_kline WHERE code = ?", (code,))

        if klines:
            conn.executemany(
                """INSERT INTO stocks_kline
                    (code, trade_date, open, high, low, close,
                     volume, turnover, amplitude, pct_change, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        code,
                        str(d.get("date", d.get("trade_date", ""))),
                        float(d.get("open", 0)) if d.get("open") is not None else None,
                        float(d.get("high", 0)) if d.get("high") is not None else None,
                        float(d.get("low", 0)) if d.get("low") is not None else None,
                        float(d.get("close", 0)) if d.get("close") is not None else None,
                        float(d.get("volume", 0)) if d.get("volume") is not None else None,
                        float(d.get("turnover", 0)) if d.get("turnover") is not None else None,
                        float(d.get("amplitude", 0)) if d.get("amplitude") is not None else None,
                        float(d.get("pct_change", 0)) if d.get("pct_change") is not None else None,
                        d.get("updated_at", datetime.now(_CN_TZ).isoformat()),
                    )
                    for d in klines
                ],
            )
        conn.commit()


# ── 读取 ──
def get_klines(
    code: str,
    days: int = 30,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    """读取最近 N 日 K线，按 trade_date 升序（旧→新）返回。

    返回格式与 API 原始格式兼容：
    - date: 交易日期（兼容 API 的 date 字段）
    - open/high/low/close/volume/turnover/amplitude/pct_change

    Args:
        code: 股票代码
        days: 读取最近多少个交易日
        db_path: 自定义数据库路径

    Returns:
        K线数据列表，正序排列。无数据时返回空列表。
    """
    with _get_conn(write=False, db_path=db_path) as conn:
        cursor = conn.execute(
            """SELECT * FROM stocks_kline
                WHERE code = ?
                ORDER BY trade_date DESC
                LIMIT ?""",
            (code, days),
        )
        rows = cursor.fetchall()

        result = []
        for row in reversed(rows):
            d = dict(row)
            # 字段名兼容性映射：trade_date → date（与 API 返回格式一致）
            if "trade_date" in d:
                d["date"] = d.pop("trade_date")
            result.append(d)
        return result


def get_ma(
    code: str,
    days: int = 20,
    db_path: Path | None = None,
) -> float | None:
    """计算最近 N 日收盘价的移动平均。

    Args:
        code: 股票代码
        days: 均线周期
        db_path: 自定义数据库路径

    Returns:
        均线值，K线不足时返回 None。
    """
    klines = get_klines(code, days=days, db_path=db_path)
    if len(klines) < days:
        return None
    return sum(d["close"] for d in klines) / days


def get_latest_price(
    code: str,
    db_path: Path | None = None,
) -> dict[str, Any] | None:
    """获取某只股票最新一根 K线数据。

    Returns:
        最新 K线 dict，无数据时返回 None。
    """
    klines = get_klines(code, days=1, db_path=db_path)
    return klines[-1] if klines else None


# ── 预拉取标记 ──
def is_cache_ready(date: str | None = None, db_path: Path | None = None) -> bool:
    """检查某交易日 K线是否已预拉取完成。

    Args:
        date: 日期字符串 "YYYY-MM-DD"，默认今天
        db_path: 自定义数据库路径

    Returns:
        True 表示已预拉取，False 表示未预拉取或数据不存在。
    """
    if date is None:
        date = datetime.now(_CN_TZ).strftime("%Y-%m-%d")

    with _get_conn(write=False, db_path=db_path) as conn:
        cursor = conn.execute(
            "SELECT value FROM kline_meta WHERE key = ?",
            (f"ready_{date}",),
        )
        row = cursor.fetchone()
        return row is not None


def mark_cache_ready(
    date: str | None = None,
    db_path: Path | None = None,
) -> None:
    """标记某交易日预拉取已完成。

    Args:
        date: 日期字符串 "YYYY-MM-DD"，默认今天
        db_path: 自定义数据库路径
    """
    if date is None:
        date = datetime.now(_CN_TZ).strftime("%Y-%m-%d")

    with _get_conn(write=True, db_path=db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO kline_meta (key, value) VALUES (?, ?)",
            (f"ready_{date}", date),
        )
        conn.commit()


def clear_cache_ready(
    date: str | None = None,
    db_path: Path | None = None,
) -> None:
    """清除某交易日的预拉取标记（用于重试或测试）。"""
    if date is None:
        date = datetime.now(_CN_TZ).strftime("%Y-%m-%d")

    with _get_conn(write=True, db_path=db_path) as conn:
        conn.execute(
            "DELETE FROM kline_meta WHERE key = ?",
            (f"ready_{date}",),
        )
        conn.commit()


# ── 诊断工具 ──
def get_cache_stats(db_path: Path | None = None) -> dict[str, Any]:
    """获取缓存统计信息（用于调试和监控）。"""
    with _get_conn(write=False, db_path=db_path) as conn:
        # 总股票数
        cursor = conn.execute(
            "SELECT COUNT(DISTINCT code) as stock_count FROM stocks_kline"
        )
        stock_count = cursor.fetchone()["stock_count"]

        # 总 K线数
        cursor = conn.execute("SELECT COUNT(*) as kline_count FROM stocks_kline")
        kline_count = cursor.fetchone()["kline_count"]

        # 最近更新日期
        cursor = conn.execute(
            "SELECT MAX(updated_at) as last_update FROM stocks_kline"
        )
        last_update = cursor.fetchone()["last_update"]

        # 预拉取标记
        cursor = conn.execute("SELECT key, value FROM kline_meta")
        meta = {row["key"]: row["value"] for row in cursor.fetchall()}

        return {
            "stock_count": stock_count,
            "kline_count": kline_count,
            "last_update": last_update,
            "meta": meta,
        }
