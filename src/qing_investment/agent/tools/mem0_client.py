from __future__ import annotations

from qing_investment.agent.config import settings


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
        self._ensure_client()
        return self._client.search(
            query=query,
            user_id=user_id,
            filters=filters,
        )

    def add(self, content: str, user_id: str, metadata: dict | None = None):
        self._ensure_client()
        return self._client.add(
            messages=content,
            user_id=user_id,
            metadata=metadata or {},
        )
