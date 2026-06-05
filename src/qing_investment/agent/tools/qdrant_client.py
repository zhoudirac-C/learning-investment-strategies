from __future__ import annotations

import logging
from pathlib import Path

import requests

from qing_investment.agent.config import settings

logger = logging.getLogger(__name__)

_QDRANT_BASE = f"http://{settings.qdrant_host}:{settings.qdrant_port}"


class QdrantClientWrapper:
    def __init__(self, local_mode: bool = False):
        # Always use REST API for compatibility with Qdrant server 1.9.7
        self.base_url = _QDRANT_BASE

    def ensure_collection(self, name: str = "qing_knowledge", vector_size: int = 512):
        from qdrant_client.models import Distance, VectorParams
        from qdrant_client import QdrantClient

        # Use raw client only for collection management (these APIs are stable)
        client = QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
        collections = client.get_collections().collections
        exists = any(c.name == name for c in collections)
        if not exists:
            client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
            )
        client.close()

    def search(self, query_vector: list[float], collection: str = "qing_knowledge", limit: int = 5):
        resp = requests.post(
            f"{self.base_url}/collections/{collection}/points/search",
            json={"vector": query_vector, "limit": limit, "with_payload": True},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("result", [])

    def upsert(self, collection: str, points: list):
        from qdrant_client import QdrantClient

        client = QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
        client.upsert(collection_name=collection, points=points)
        client.close()
