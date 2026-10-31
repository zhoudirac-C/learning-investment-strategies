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

    def search(
        self,
        query_vector,
        collection: str = "qing_knowledge",
        limit: int = 5,
        schools: list[str] | None = None,
        include_superseded: bool = False,
    ):
        """Semantic search — queries Qdrant server via query_points API.

        Supports qing_knowledge (wiki+raw docs) and qing_claims (structured claims).

        Args:
            schools: 学派过滤（2026-10-15 双学派架构）。None = 不过滤（现状兼容）；
                     ["qing"] / ["gator"] / ["qing","gator","shared"] 等。
                     过滤字段为 payload.school（存量无该字段的点不会被匹配）。
            include_superseded: 默认 False —— 检索时排除 status=superseded 的 claim。
                     claim 合并后旧碎片仍留在库中（可追溯），若不过滤会与新合并 claim
                     同时命中并抢占排名，导致「合并了但检索还是碎片」（2026-10-31 实测）。
        """
        import numpy as np

        if hasattr(query_vector, "ndim"):
            query_vec = np.array(query_vector).flatten()
        else:
            query_vec = np.array(query_vector).flatten()

        query_filter = None
        must: list = []
        must_not: list = []
        if schools:
            from qdrant_client.models import FieldCondition, MatchAny

            must.append(FieldCondition(key="school", match=MatchAny(any=list(schools))))
        if not include_superseded:
            from qdrant_client.models import FieldCondition, MatchValue

            must_not.append(FieldCondition(key="status", match=MatchValue(value="superseded")))
        if must or must_not:
            from qdrant_client.models import Filter

            query_filter = Filter(must=must or None, must_not=must_not or None)

        resp = self._client.query_points(
            collection_name=collection,
            query=query_vec.tolist(),
            limit=limit,
            with_payload=True,
            query_filter=query_filter,
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
