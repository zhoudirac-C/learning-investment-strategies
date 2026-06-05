from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

VECTOR_DIM = 512  # ONNX bge-small-zh-v1.5 dimension


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


class OnnxEmbeddingModel:
    """ONNX-based BGE embedding model (bge-small-zh-v1.5, 512-dim).

    Uses transformers tokenizer + onnxruntime inference.
    Performs mean-pooling over token embeddings and L2 normalization.
    """

    _instance: OnnxEmbeddingModel | None = None

    def __new__(cls) -> OnnxEmbeddingModel:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._init_model()
        self._initialized = True

    def _init_model(self):
        from pathlib import Path

        import onnxruntime as ort
        from transformers import AutoTokenizer

        repo_root = Path(__file__).resolve().parents[4]
        model_dir = repo_root / "models" / "onnx"
        model_path = model_dir / "onnx" / "model_quantized.onnx"

        if not model_path.exists():
            raise FileNotFoundError(f"ONNX model not found at {model_path}")

        self.tokenizer = AutoTokenizer.from_pretrained(str(model_dir))
        self.session = ort.InferenceSession(
            str(model_path),
            providers=["CPUExecutionProvider"],
        )
        self.input_names = {inp.name for inp in self.session.get_inputs()}
        logger.info("ONNX embedding model loaded: %s", model_path)

    def encode(self, texts: str | list[str], **kwargs) -> np.ndarray:
        if isinstance(texts, str):
            texts = [texts]

        inputs = self.tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="np",
        )

        feed = {
            "input_ids": inputs["input_ids"],
            "attention_mask": inputs["attention_mask"],
        }
        if "token_type_ids" in self.input_names:
            feed["token_type_ids"] = np.zeros_like(inputs["input_ids"])

        outputs = self.session.run(None, feed)
        last_hidden = outputs[0]  # (batch, seq_len, hidden_dim)

        # Mean pooling with attention mask
        mask = inputs["attention_mask"].astype(np.float32)
        mask_expanded = np.expand_dims(mask, axis=-1)
        sum_embeddings = np.sum(last_hidden * mask_expanded, axis=1)
        mean_embeddings = sum_embeddings / np.clip(
            np.sum(mask, axis=1, keepdims=True), a_min=1e-9, a_max=None
        )

        # L2 normalize
        norms = np.linalg.norm(mean_embeddings, axis=1, keepdims=True)
        return mean_embeddings / norms
