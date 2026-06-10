"""待审核队列管理模块。

P0 事件驱动管线的核心基础设施。管理两类待审核项：
1. pending_claims: 用户提取的 claims，需审核后才能入库
2. pending_config_updates: 脚本生成的 config 更新建议，需审核后才能写入 YAML

所有数据存储在 SQLite 中，路径: ~/.hermes/pending_review.db

Refs: docs/p0-event-driven-pipeline-design.md v1.0
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = Path.home() / ".hermes" / "pending_review.db"


@dataclass
class PendingClaim:
    """待审核的 claim。"""

    claim_yaml: str
    source_file: str = ""
    batch_id: str = ""
    claim_index: int = 0
    status: str = "pending"  # pending | approved | rejected | modified
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    decided_at: str = ""
    user_decision: str = ""
    id: int = 0


@dataclass
class PendingConfigUpdate:
    """待审核的 config 更新建议。"""

    update_type: str  # 'watchlist' | 'entry_point'
    target_code: str
    current_value: dict[str, Any] = field(default_factory=dict)
    suggested_value: dict[str, Any] = field(default_factory=dict)
    rationale: str = ""
    batch_id: str = ""
    update_index: int = 0
    status: str = "pending"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    decided_at: str = ""
    user_decision: str = ""
    id: int = 0


class PendingReviewQueue:
    """待审核队列管理器。"""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """初始化数据库表。"""
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS pending_claims (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_id TEXT NOT NULL,
                    claim_index INTEGER,
                    claim_yaml TEXT NOT NULL,
                    source_file TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    decided_at TIMESTAMP,
                    user_decision TEXT
                );

                CREATE TABLE IF NOT EXISTS pending_config_updates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_id TEXT NOT NULL,
                    update_index INTEGER,
                    update_type TEXT,
                    target_code TEXT,
                    current_value TEXT,
                    suggested_value TEXT,
                    rationale TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    decided_at TIMESTAMP,
                    user_decision TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_claims_batch ON pending_claims(batch_id);
                CREATE INDEX IF NOT EXISTS idx_claims_status ON pending_claims(status);
                CREATE INDEX IF NOT EXISTS idx_config_batch ON pending_config_updates(batch_id);
                CREATE INDEX IF NOT EXISTS idx_config_status ON pending_config_updates(status);
                """
            )

    # ── Claims 操作 ──

    def add_claims(self, claims: list[PendingClaim]) -> str:
        """批量添加待审核 claims，返回 batch_id。"""
        batch_id = str(uuid.uuid4())[:12]
        with sqlite3.connect(self.db_path) as conn:
            for i, claim in enumerate(claims, 1):
                conn.execute(
                    """
                    INSERT INTO pending_claims
                    (batch_id, claim_index, claim_yaml, source_file, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        batch_id,
                        i,
                        claim.claim_yaml,
                        claim.source_file,
                        claim.status,
                        claim.created_at,
                    ),
                )
        return batch_id

    def get_pending_claims(self, batch_id: str | None = None) -> list[PendingClaim]:
        """获取待审核 claims。"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if batch_id:
                rows = conn.execute(
                    "SELECT * FROM pending_claims WHERE batch_id = ? AND status = 'pending' ORDER BY claim_index",
                    (batch_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM pending_claims WHERE status = 'pending' ORDER BY created_at"
                ).fetchall()

        return [self._row_to_claim(row) for row in rows]

    def get_claim_by_index(self, batch_id: str, index: int) -> PendingClaim | None:
        """获取指定 batch 中指定序号的 claim。"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM pending_claims WHERE batch_id = ? AND claim_index = ?",
                (batch_id, index),
            ).fetchone()
        return self._row_to_claim(row) if row else None

    def approve_claims(self, batch_id: str, indices: list[int] | None = None) -> int:
        """批准 claims。indices=None 表示批准该 batch 全部。"""
        now = datetime.now().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            if indices:
                placeholders = ",".join("?" * len(indices))
                conn.execute(
                    f"""
                    UPDATE pending_claims
                    SET status = 'approved', decided_at = ?, user_decision = 'approved'
                    WHERE batch_id = ? AND claim_index IN ({placeholders}) AND status = 'pending'
                    """,
                    (now, batch_id, *indices),
                )
            else:
                conn.execute(
                    """
                    UPDATE pending_claims
                    SET status = 'approved', decided_at = ?, user_decision = 'approved'
                    WHERE batch_id = ? AND status = 'pending'
                    """,
                    (now, batch_id),
                )
            return conn.total_changes

    def reject_claims(self, batch_id: str, indices: list[int] | None = None) -> int:
        """拒绝 claims。"""
        now = datetime.now().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            if indices:
                placeholders = ",".join("?" * len(indices))
                conn.execute(
                    f"""
                    UPDATE pending_claims
                    SET status = 'rejected', decided_at = ?, user_decision = 'rejected'
                    WHERE batch_id = ? AND claim_index IN ({placeholders}) AND status = 'pending'
                    """,
                    (now, batch_id, *indices),
                )
            else:
                conn.execute(
                    """
                    UPDATE pending_claims
                    SET status = 'rejected', decided_at = ?, user_decision = 'rejected'
                    WHERE batch_id = ? AND status = 'pending'
                    """,
                    (now, batch_id),
                )
            return conn.total_changes

    def modify_claim(self, batch_id: str, index: int, new_yaml: str) -> bool:
        """修改 claim 内容。"""
        now = datetime.now().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE pending_claims
                SET claim_yaml = ?, status = 'modified', decided_at = ?, user_decision = 'modified'
                WHERE batch_id = ? AND claim_index = ? AND status = 'pending'
                """,
                (new_yaml, now, batch_id, index),
            )
            return conn.total_changes > 0

    def get_approved_claims(self, batch_id: str) -> list[PendingClaim]:
        """获取已批准的 claims（用于入库）。"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM pending_claims WHERE batch_id = ? AND status = 'approved' ORDER BY claim_index",
                (batch_id,),
            ).fetchall()
        return [self._row_to_claim(row) for row in rows]

    # ── Config Updates 操作 ──

    def add_config_updates(self, updates: list[PendingConfigUpdate]) -> str:
        """批量添加待审核 config 更新，返回 batch_id。"""
        batch_id = str(uuid.uuid4())[:12]
        with sqlite3.connect(self.db_path) as conn:
            for i, upd in enumerate(updates, 1):
                conn.execute(
                    """
                    INSERT INTO pending_config_updates
                    (batch_id, update_index, update_type, target_code, current_value,
                     suggested_value, rationale, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        batch_id,
                        i,
                        upd.update_type,
                        upd.target_code,
                        json.dumps(upd.current_value, ensure_ascii=False),
                        json.dumps(upd.suggested_value, ensure_ascii=False),
                        upd.rationale,
                        upd.status,
                        upd.created_at,
                    ),
                )
        return batch_id

    def get_pending_config_updates(self, batch_id: str | None = None) -> list[PendingConfigUpdate]:
        """获取待审核 config 更新。"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if batch_id:
                rows = conn.execute(
                    "SELECT * FROM pending_config_updates WHERE batch_id = ? AND status = 'pending' ORDER BY update_index",
                    (batch_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM pending_config_updates WHERE status = 'pending' ORDER BY created_at"
                ).fetchall()

        return [self._row_to_config_update(row) for row in rows]

    def get_config_update_by_index(self, batch_id: str, index: int) -> PendingConfigUpdate | None:
        """获取指定 batch 中指定序号的 config update。"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM pending_config_updates WHERE batch_id = ? AND update_index = ?",
                (batch_id, index),
            ).fetchone()
        return self._row_to_config_update(row) if row else None

    def approve_config_updates(self, batch_id: str, indices: list[int] | None = None) -> int:
        """批准 config updates。"""
        now = datetime.now().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            if indices:
                placeholders = ",".join("?" * len(indices))
                conn.execute(
                    f"""
                    UPDATE pending_config_updates
                    SET status = 'approved', decided_at = ?, user_decision = 'approved'
                    WHERE batch_id = ? AND update_index IN ({placeholders}) AND status = 'pending'
                    """,
                    (now, batch_id, *indices),
                )
            else:
                conn.execute(
                    """
                    UPDATE pending_config_updates
                    SET status = 'approved', decided_at = ?, user_decision = 'approved'
                    WHERE batch_id = ? AND status = 'pending'
                    """,
                    (now, batch_id),
                )
            return conn.total_changes

    def reject_config_updates(self, batch_id: str, indices: list[int] | None = None) -> int:
        """拒绝 config updates。"""
        now = datetime.now().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            if indices:
                placeholders = ",".join("?" * len(indices))
                conn.execute(
                    f"""
                    UPDATE pending_config_updates
                    SET status = 'rejected', decided_at = ?, user_decision = 'rejected'
                    WHERE batch_id = ? AND update_index IN ({placeholders}) AND status = 'pending'
                    """,
                    (now, batch_id, *indices),
                )
            else:
                conn.execute(
                    """
                    UPDATE pending_config_updates
                    SET status = 'rejected', decided_at = ?, user_decision = 'rejected'
                    WHERE batch_id = ? AND status = 'pending'
                    """,
                    (now, batch_id),
                )
            return conn.total_changes

    def modify_config_update(
        self, batch_id: str, index: int, field_path: str, new_value: Any
    ) -> bool:
        """修改 config update 的某个字段。

        field_path: 点分隔路径，如 "odds_analysis.upside_pct"
        """
        upd = self.get_config_update_by_index(batch_id, index)
        if not upd:
            return False

        # 修改 suggested_value
        keys = field_path.split(".")
        target = upd.suggested_value
        for key in keys[:-1]:
            if key not in target:
                target[key] = {}
            target = target[key]
        target[keys[-1]] = new_value

        now = datetime.now().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE pending_config_updates
                SET suggested_value = ?, status = 'modified', decided_at = ?, user_decision = ?
                WHERE batch_id = ? AND update_index = ? AND status = 'pending'
                """,
                (
                    json.dumps(upd.suggested_value, ensure_ascii=False),
                    now,
                    f"modified {field_path}={new_value}",
                    batch_id,
                    index,
                ),
            )
            return conn.total_changes > 0

    def get_approved_config_updates(self, batch_id: str) -> list[PendingConfigUpdate]:
        """获取已批准的 config updates（用于执行）。"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM pending_config_updates WHERE batch_id = ? AND status = 'approved' ORDER BY update_index",
                (batch_id,),
            ).fetchall()
        return [self._row_to_config_update(row) for row in rows]

    # ── 通用操作 ──

    def get_batch_summary(self, batch_id: str) -> dict[str, Any]:
        """获取 batch 的汇总信息。"""
        with sqlite3.connect(self.db_path) as conn:
            claim_counts = conn.execute(
                "SELECT status, COUNT(*) FROM pending_claims WHERE batch_id = ? GROUP BY status",
                (batch_id,),
            ).fetchall()
            config_counts = conn.execute(
                "SELECT status, COUNT(*) FROM pending_config_updates WHERE batch_id = ? GROUP BY status",
                (batch_id,),
            ).fetchall()

        return {
            "batch_id": batch_id,
            "claims": {status: count for status, count in claim_counts},
            "config_updates": {status: count for status, count in config_counts},
        }

    def cleanup_old_entries(self, days: int = 7) -> int:
        """清理超过 N 天的已处理条目。"""
        cutoff = datetime.now().isoformat()[:10]  # 简化：按日期前缀
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                DELETE FROM pending_claims
                WHERE status != 'pending' AND created_at < datetime('now', '-{} days')
                """.format(days)
            )
            conn.execute(
                """
                DELETE FROM pending_config_updates
                WHERE status != 'pending' AND created_at < datetime('now', '-{} days')
                """.format(days)
            )
            return conn.total_changes

    def get_all_pending_batches(self) -> list[dict[str, Any]]:
        """获取所有有待审核项的 batch_id 列表。"""
        with sqlite3.connect(self.db_path) as conn:
            claim_batches = conn.execute(
                "SELECT DISTINCT batch_id, MAX(created_at) as latest FROM pending_claims WHERE status = 'pending' GROUP BY batch_id"
            ).fetchall()
            config_batches = conn.execute(
                "SELECT DISTINCT batch_id, MAX(created_at) as latest FROM pending_config_updates WHERE status = 'pending' GROUP BY batch_id"
            ).fetchall()

        batches = {}
        for batch_id, latest in claim_batches:
            batches[batch_id] = {"latest": latest, "has_claims": True, "has_config": False}
        for batch_id, latest in config_batches:
            if batch_id in batches:
                batches[batch_id]["has_config"] = True
                if latest > batches[batch_id]["latest"]:
                    batches[batch_id]["latest"] = latest
            else:
                batches[batch_id] = {"latest": latest, "has_claims": False, "has_config": True}

        return [
            {"batch_id": bid, **info}
            for bid, info in sorted(batches.items(), key=lambda x: x[1]["latest"], reverse=True)
        ]

    # ── 内部方法 ──

    def _row_to_claim(self, row: sqlite3.Row) -> PendingClaim:
        return PendingClaim(
            id=row["id"],
            batch_id=row["batch_id"],
            claim_index=row["claim_index"],
            claim_yaml=row["claim_yaml"],
            source_file=row["source_file"] or "",
            status=row["status"],
            created_at=row["created_at"],
            decided_at=row["decided_at"] or "",
            user_decision=row["user_decision"] or "",
        )

    def _row_to_config_update(self, row: sqlite3.Row) -> PendingConfigUpdate:
        return PendingConfigUpdate(
            id=row["id"],
            batch_id=row["batch_id"],
            update_index=row["update_index"],
            update_type=row["update_type"] or "",
            target_code=row["target_code"] or "",
            current_value=json.loads(row["current_value"] or "{}"),
            suggested_value=json.loads(row["suggested_value"] or "{}"),
            rationale=row["rationale"] or "",
            status=row["status"],
            created_at=row["created_at"],
            decided_at=row["decided_at"] or "",
            user_decision=row["user_decision"] or "",
        )


# ── CLI 测试 ──

if __name__ == "__main__":
    import sys

    queue = PendingReviewQueue()

    if len(sys.argv) > 1 and sys.argv[1] == "test":
        # 添加测试数据
        test_claims = [
            PendingClaim(
                claim_yaml="id: claim-test-001\ntype: sector-theme\nstatement: 测试claim",
                source_file="test.md",
            ),
            PendingClaim(
                claim_yaml="id: claim-test-002\ntype: operation\nstatement: 测试操作",
                source_file="test.md",
            ),
        ]
        batch_id = queue.add_claims(test_claims)
        print(f"Added test claims, batch_id={batch_id}")

        pending = queue.get_pending_claims(batch_id)
        print(f"Pending claims: {len(pending)}")

        queue.approve_claims(batch_id, [1])
        approved = queue.get_approved_claims(batch_id)
        print(f"Approved claims: {len(approved)}")

        # 测试 config updates
        test_updates = [
            PendingConfigUpdate(
                update_type="watchlist",
                target_code="002353",
                suggested_value={"linked_claims": ["claim-test-001"]},
                rationale="新 claim 提及该标的",
            ),
        ]
        config_batch = queue.add_config_updates(test_updates)
        print(f"Added test config updates, batch_id={config_batch}")

        pending_config = queue.get_pending_config_updates(config_batch)
        print(f"Pending config updates: {len(pending_config)}")

        print("\nAll pending batches:")
        for batch in queue.get_all_pending_batches():
            print(f"  {batch}")

    elif len(sys.argv) > 1 and sys.argv[1] == "cleanup":
        deleted = queue.cleanup_old_entries(days=7)
        print(f"Cleaned up {deleted} old entries")

    else:
        print("Usage: python pending_review_queue.py [test|cleanup]")
