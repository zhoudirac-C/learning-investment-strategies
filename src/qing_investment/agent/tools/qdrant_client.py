from __future__ import annotations

import logging
from pathlib import Path

from qing_investment.agent.config import settings

logger = logging.getLogger(__name__)


class QdrantClientWrapper:
    """Qdrant client wrapper — supports both local file mode and remote server mode.

    Local mode (default): uses QdrantClient(path=...) — embedded, no server needed.
    Remote mode: uses QdrantClient(host=..., port=...) — connects to a running server.
    """

    def __init__(self, local_mode: bool = True):
        from qdrant_client import QdrantClient

        self.local_path = settings.qdrant_local_path
        self._is_local = local_mode and bool(self.local_path)

        if self._is_local:
            self._client = QdrantClient(path=self.local_path)
            logger.info(f"Qdrant local mode: {self.local_path}")
        else:
            self._client = QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
            logger.info(f"Qdrant remote mode: {settings.qdrant_host}:{settings.qdrant_port}")

    def _enable_wal_mode(self):
        """Enable SQLite WAL mode for better concurrent write stability."""
        try:
            path = Path(self.local_path)
            db_files = list(path.rglob("storage.sqlite"))
            if db_files:
                import sqlite3
                db_path = str(db_files[0])
                conn = sqlite3.connect(db_path)
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.commit()
                conn.close()
                logger.info("Qdrant SQLite WAL mode enabled: %s", db_path)
        except Exception as e:
            logger.warning("Failed to enable WAL mode (non-fatal): %s", e)

    def ensure_collection(self, name: str = "qing_knowledge", vector_size: int = 512):
        from qdrant_client.models import Distance, VectorParams

        collections = self._client.get_collections().collections
        exists = any(c.name == name for c in collections)
        if not exists:
            self._client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
            )
            logger.info(f"Created Qdrant collection: {name}")
            # Enable WAL mode after collection creation (SQLite file now exists)
            if self._is_local:
                self._enable_wal_mode()

    def search(self, query_vector, collection: str = "qing_knowledge", limit: int = 5):
        """Semantic search — compatible with both local and remote Qdrant modes.
        
        Supports qing_knowledge (wiki+raw docs) and qing_claims (structured claims).
        Falls back to manual cosine similarity for local mode if query_points fails.
        """
        import numpy as np
        
        # Ensure query_vector is 1D numpy array
        if hasattr(query_vector, 'ndim'):
            query_vec = np.array(query_vector).flatten()
        else:
            query_vec = np.array(query_vector).flatten()
        
        if self._is_local:
            try:
                # Try query_points first
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
            except Exception:
                # Fallback: manual cosine similarity via scroll
                return self._search_manual(query_vec, collection, limit)
        else:
            # Remote mode uses search() via REST
            results = self._client.search(
                collection_name=collection,
                query_vector=query_vec.tolist(),
                limit=limit,
                with_payload=True,
            )
            return [
                {"id": r.id, "score": r.score, "payload": r.payload or {}}
                for r in results
            ]
    
    def _search_manual(self, query_vec: np.ndarray, collection: str, limit: int):
        """Manual cosine similarity search for local mode fallback."""
        import numpy as np
        
        all_points = []
        offset = None
        while True:
            resp = self._client.scroll(
                collection_name=collection,
                limit=100,
                offset=offset,
                with_payload=True,
                with_vectors=True,
            )
            points = resp[0]
            if not points:
                break
            all_points.extend(points)
            offset = resp[1]
            if offset is None:
                break
        
        # Calculate cosine similarity
        scores = []
        query_norm = np.linalg.norm(query_vec)
        for p in all_points:
            vec = np.array(p.vector).flatten()
            score = np.dot(query_vec, vec) / (query_norm * np.linalg.norm(vec))
            scores.append((score, p))
        
        # Sort and return top-k
        scores.sort(key=lambda x: -x[0])
        return [
            {"id": p.id, "score": score, "payload": p.payload or {}}
            for score, p in scores[:limit]
        ]

    def upsert(self, collection: str, points: list):
        # Local mode requires UUID point IDs — convert string IDs to deterministic UUIDs
        if self._is_local:
            import uuid as _uuid
            for p in points:
                if not isinstance(p.id, _uuid.UUID):
                    try:
                        p.id = _uuid.UUID(str(p.id))
                    except ValueError:
                        p.id = _uuid.uuid5(_uuid.NAMESPACE_DNS, str(p.id))
        self._client.upsert(collection_name=collection, points=points)
