from __future__ import annotations

import hashlib

import numpy as np

VECTOR_DIM = 1024


def simple_hash_embedding(text: str, dim: int = VECTOR_DIM) -> list[float]:
    """Character-bigram hashing embedding fallback.

    Zero-dependency deterministic embedding where similar texts
    have higher cosine similarity. Used when sentence-transformers
    is unavailable.
    """
    vec = np.zeros(dim, dtype=np.float32)
    text = text.strip()
    if not text:
        return vec.tolist()
    for i in range(len(text) - 1):
        bigram = text[i : i + 2]
        idx = int(hashlib.md5(bigram.encode("utf-8")).hexdigest(), 16) % dim
        vec[idx] += 1.0
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    return vec.tolist()


class FallbackEmbeddingModel:
    """Wraps simple_hash_embedding to expose a sentence-transformers-like API."""

    def encode(self, texts: str | list[str], **kwargs) -> np.ndarray:
        if isinstance(texts, str):
            return np.array(simple_hash_embedding(texts), dtype=np.float32)
        return np.array([simple_hash_embedding(t) for t in texts], dtype=np.float32)
