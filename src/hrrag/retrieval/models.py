"""Carga perezosa (singleton) de los modelos Transformer de embeddings y reranking."""
from __future__ import annotations

from functools import lru_cache

import numpy as np

from ..config import settings


@lru_cache(maxsize=1)
def get_embedder():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(settings.embedding_model, device="cpu")


@lru_cache(maxsize=1)
def get_reranker():
    from sentence_transformers import CrossEncoder

    return CrossEncoder(settings.reranker_model, device="cpu", max_length=512)


def embed_passages(texts: list[str], batch_size: int = 32) -> np.ndarray:
    # Los modelos E5 requieren prefijos "passage:" / "query:"
    model = get_embedder()
    vecs = model.encode([f"passage: {t}" for t in texts], batch_size=batch_size,
                        normalize_embeddings=True, show_progress_bar=True)
    return np.asarray(vecs, dtype=np.float32)


def embed_query(text: str) -> np.ndarray:
    model = get_embedder()
    vec = model.encode([f"query: {text}"], normalize_embeddings=True)
    return np.asarray(vec[0], dtype=np.float32)
