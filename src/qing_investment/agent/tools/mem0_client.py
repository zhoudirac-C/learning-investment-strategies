from __future__ import annotations

from mem0 import MemoryClient

from qing_investment.agent.config import settings


class Mem0ClientWrapper:
    def __init__(self):
        self.client = MemoryClient(
            api_key=settings.mem0_api_key or "local",
            host=settings.mem0_base_url,
        )

    def search(self, query: str, user_id: str, filters: dict | None = None):
        return self.client.search(
            query=query,
            user_id=user_id,
            filters=filters,
        )

    def add(self, content: str, user_id: str, metadata: dict | None = None):
        return self.client.add(
            messages=content,
            user_id=user_id,
            metadata=metadata or {},
        )
