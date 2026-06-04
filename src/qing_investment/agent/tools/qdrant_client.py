from __future__ import annotations

from qdrant_client import QdrantClient

from qing_investment.agent.config import settings


class QdrantClientWrapper:
    def __init__(self):
        self.client = QdrantClient(
            host=settings.qdrant_host,
            port=settings.qdrant_port,
        )

    def ensure_collection(self, name: str = "qing_knowledge", vector_size: int = 1024):
        from qdrant_client.models import Distance, VectorParams

        collections = self.client.get_collections().collections
        exists = any(c.name == name for c in collections)
        if not exists:
            self.client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
            )

    def search(self, query_vector: list[float], collection: str = "qing_knowledge", limit: int = 5):
        return self.client.query_points(
            collection_name=collection,
            query=query_vector,
            limit=limit,
            with_payload=True,
        ).points

    def upsert(self, collection: str, points: list):
        self.client.upsert(collection_name=collection, points=points)
