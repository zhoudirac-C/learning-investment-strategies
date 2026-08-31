"""processed_items 去重 DB 测试（T10）。"""
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from investment_engine.chain_tracker.dedup import ProcessedItemsDB


NOW = datetime(2026, 8, 31, 10, 0, 0)


class TestProcessedItemsDB:
    def setup_method(self):
        self.dir = Path(tempfile.mkdtemp(prefix="chain_dedup_test_"))
        self.db = ProcessedItemsDB(self.dir / "processed_items.db")

    def _record(self, info_id: str, **kw):
        kw.setdefault("source", "report")
        kw.setdefault("title", f"t-{info_id}")
        kw.setdefault("published_at", "2026-08-31")
        kw.setdefault("now", NOW)
        return self.db.record(info_id=info_id, **kw)

    def test_record_then_filter_unprocessed(self):
        self._record("a")
        assert self.db.filter_unprocessed(["a", "b", "c"], now=NOW) == ["b", "c"]

    def test_record_returns_true_only_when_new(self):
        assert self._record("a") is True
        assert self._record("a") is False

    def test_filter_empty_input(self):
        assert self.db.filter_unprocessed([], now=NOW) == []

    def test_ttl_window_expired_item_is_unprocessed_again(self):
        old = NOW - timedelta(hours=49)
        self._record("old", now=old)
        assert self.db.filter_unprocessed(["old"], now=NOW) == ["old"]
        # 48h 内仍算已处理
        recent = NOW - timedelta(hours=47)
        self._record("recent", now=recent)
        assert self.db.filter_unprocessed(["recent"], now=NOW) == []

    def test_cleanup_deletes_only_expired(self):
        self._record("old", now=NOW - timedelta(hours=49))
        self._record("fresh", now=NOW - timedelta(hours=1))
        deleted = self.db.cleanup(now=NOW, ttl_hours=48)
        assert deleted == 1
        assert self.db.get("old") is None
        assert self.db.get("fresh") is not None

    def test_record_stores_chain_and_verdict(self):
        self._record("a", chain_id="ai-pcb-ccl", llm_verdict="strengthening",
                     analysis='{"step1": 1}')
        row = self.db.get("a")
        assert row["chain_id"] == "ai-pcb-ccl"
        assert row["llm_verdict"] == "strengthening"
        assert row["analysis"] == '{"step1": 1}'

    def test_unmatched_item_recorded_with_null_chain(self):
        self._record("noise-1")
        row = self.db.get("noise-1")
        assert row["chain_id"] is None
        assert row["llm_verdict"] is None

    def test_persist_across_instances(self):
        self._record("a")
        db2 = ProcessedItemsDB(self.dir / "processed_items.db")
        assert db2.filter_unprocessed(["a"], now=NOW) == []

    def test_record_many(self):
        n = self.db.record_many(
            [{"info_id": "x", "source": "notice", "title": "t", "published_at": "2026-08-31"},
             {"info_id": "y", "source": "notice", "title": "t", "published_at": "2026-08-31"}],
            now=NOW,
        )
        assert n == 2
        assert self.db.count() == 2
