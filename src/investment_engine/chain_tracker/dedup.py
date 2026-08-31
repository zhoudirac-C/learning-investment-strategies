"""processed_items 去重 DB（T10）。

硬规则（见 docs/tasks/m0-chain-industry-tracking.md Phase 2）：
1. 去重键用 info_id 不用标题——同一研报会被多个渠道转载，标题去重会漏。
2. TTL 清理内置在每个 tick——顺手 DELETE 过期记录，不设独立清理任务。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

DEFAULT_TTL_HOURS = 48

_SCHEMA = """
CREATE TABLE IF NOT EXISTS processed_items (
    info_id      TEXT PRIMARY KEY,
    source       TEXT NOT NULL,
    title        TEXT,
    published_at TEXT,
    processed_at TEXT NOT NULL,
    chain_id     TEXT,
    llm_verdict  TEXT,
    analysis     TEXT
);
CREATE INDEX IF NOT EXISTS idx_processed_at ON processed_items(processed_at);
CREATE INDEX IF NOT EXISTS idx_chain ON processed_items(chain_id);
"""

_TS_FMT = "%Y-%m-%dT%H:%M:%S"


def default_db_path() -> Path:
    from qing_investment.paths import repo_root

    return repo_root() / "infra" / "data" / "chain_tracking" / "processed_items.db"


class ProcessedItemsDB:
    """48h 滑窗去重：窗口内处理过的 info_id 跳过，过期的允许重新处理。"""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    @staticmethod
    def _ts(dt: datetime) -> str:
        return dt.strftime(_TS_FMT)

    def filter_unprocessed(self, info_ids: list[str], *, now: datetime,
                           ttl_hours: int = DEFAULT_TTL_HOURS) -> list[str]:
        """返回窗口内未处理过的 info_id（保持入参顺序）。"""
        if not info_ids:
            return []
        cutoff = self._ts(now - timedelta(hours=ttl_hours))
        seen: set[str] = set()
        cur = self._conn.cursor()
        # 分批避免 SQLite 变量数上限（999）
        for i in range(0, len(info_ids), 500):
            chunk = info_ids[i:i + 500]
            marks = ",".join("?" * len(chunk))
            rows = cur.execute(
                f"SELECT info_id FROM processed_items"
                f" WHERE processed_at >= ? AND info_id IN ({marks})",
                [cutoff, *chunk],
            )
            seen.update(r["info_id"] for r in rows)
        return [iid for iid in info_ids if iid not in seen]

    def record(self, *, info_id: str, source: str, title: str | None = None,
               published_at: str | None = None, chain_id: str | None = None,
               llm_verdict: str | None = None, analysis: str | None = None,
               now: datetime | None = None) -> bool:
        """写入处理记录；返回 True 表示是新记录，False 表示覆盖了已有记录。"""
        existed = self.get(info_id) is not None
        self._conn.execute(
            "INSERT OR REPLACE INTO processed_items"
            " (info_id, source, title, published_at, processed_at, chain_id, llm_verdict, analysis)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (info_id, source, title, published_at,
             self._ts(now or datetime.now()), chain_id, llm_verdict, analysis),
        )
        self._conn.commit()
        return not existed

    def record_many(self, rows: list[dict], *, now: datetime | None = None) -> int:
        """批量写入（每行至少含 info_id/source）；返回写入条数。"""
        ts = self._ts(now or datetime.now())
        self._conn.executemany(
            "INSERT OR REPLACE INTO processed_items"
            " (info_id, source, title, published_at, processed_at, chain_id, llm_verdict, analysis)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(r["info_id"], r["source"], r.get("title"), r.get("published_at"),
              ts, r.get("chain_id"), r.get("llm_verdict"), r.get("analysis"))
             for r in rows],
        )
        self._conn.commit()
        return len(rows)

    def get(self, info_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM processed_items WHERE info_id = ?", (info_id,)
        ).fetchone()
        return dict(row) if row else None

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM processed_items").fetchone()[0]

    def cleanup(self, *, now: datetime | None = None,
                ttl_hours: int = DEFAULT_TTL_HOURS) -> int:
        """删除 TTL 之前的记录，返回删除条数。"""
        cutoff = self._ts((now or datetime.now()) - timedelta(hours=ttl_hours))
        cur = self._conn.execute(
            "DELETE FROM processed_items WHERE processed_at < ?", (cutoff,))
        self._conn.commit()
        return cur.rowcount
