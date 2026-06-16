"""Qdrant client wrapper — remote server mode only.

Connects to a running Qdrant server (host:port).
Local (embedded) mode removed as of 2026-06-16.
"""
from __future__ import annotations

import logging

from qing_investment.agent.config import settings

logger = logging.getLogger(__name__)


class QdrantClientWrapper:
    """Qdrant client — connects to Qdrant server at host:port."""

    def __init__(self):
        from qdrant_client import QdrantClient

        self._client = QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
        logger.info("Qdrant client: %s:%s", settings.qdrant_host, settings.qdrant_port)

    def ensure_collection(self, name: str = "qing_knowledge", vector_size: int = 512):
        from qdrant_client.models import Distance, VectorParams

        collections = self._client.get_collections().collections
        exists = any(c.name == name for c in collections)
        if not exists:
            self._client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
            )
            logger.info("Created Qdrant collection: %s", name)

    def search(self, query_vector, collection: str = "qing_knowledge", limit: int = 5):
        """Semantic search — queries Qdrant server via query_points API.

        Supports qing_knowledge (wiki+raw docs) and qing_claims (structured claims).
        """
        import numpy as np

        if hasattr(query_vector, "ndim"):
            query_vec = np.array(query_vector).flatten()
        else:
            query_vec = np.array(query_vector).flatten()

        resp = self._client.query_points(
            collection_name=collection,
            query=query_vec.tolist(),
            limit=limit,
            with_payload=True,
        )
        return [
            {"id": r.id, "score": r.score, "payload": r.payload or {}}
            for r in resp.points
        ]

    def upsert(self, collection: str, points: list):
        """Upsert points into Qdrant collection."""
        self._client.upsert(collection_name=collection, points=points)

    @property
    def client(self):
        """Expose underlying QdrantClient for direct access."""
        return self._client
