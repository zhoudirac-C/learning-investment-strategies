from __future__ import annotations

import json
from pathlib import Path

from qing_investment.agent.config import settings

_REPO_ROOT = Path(__file__).resolve().parents[4]
_LOCAL_MEMORY_PATH = _REPO_ROOT / "infra" / "data" / "local_memories.json"


class Mem0ClientWrapper:
    def __init__(self):
        self._client = None
        try:
            from mem0 import MemoryClient
            self._client = MemoryClient(
                api_key=settings.mem0_api_key or "local",
                host=settings.mem0_base_url,
            )
        except Exception:
            pass

    def _ensure_client(self):
        if self._client is None:
            raise RuntimeError("Mem0 client not available")

    def search(self, query: str, user_id: str, filters: dict | None = None):
        """Search memories. Falls back to local JSON if Mem0 server unavailable."""
        try:
            self._ensure_client()
            return self._client.search(
                query=query,
                user_id=user_id,
                filters=filters,
            )
        except Exception:
            return self._local_search(query)

    def add(self, content: str, user_id: str, metadata: dict | None = None):
        self._ensure_client()
        return self._client.add(
            messages=content,
            user_id=user_id,
            metadata=metadata or {},
        )

    def _local_search(self, query: str) -> list[dict]:
        """Fallback: simple keyword-match over local memory JSON."""
        if not _LOCAL_MEMORY_PATH.exists():
            return []
        try:
            memories = json.loads(_LOCAL_MEMORY_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []

        query_words = set(query.lower().split())
        scored = []
        for mem in memories:
            content = mem.get("content", "").lower()
            score = sum(1 for w in query_words if w in content)
            if score > 0:
                scored.append((score, mem))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in scored[:5]]
