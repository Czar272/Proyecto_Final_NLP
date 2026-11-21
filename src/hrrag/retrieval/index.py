"""Carga de los índices persistidos (chunks, embeddings y BM25)."""
from __future__ import annotations

from functools import lru_cache

import numpy as np
from rank_bm25 import BM25Okapi

from ..config import settings
from ..ingest.chunker import embedding_text
from ..schemas import Chunk
from .text import tokenize


class CorpusIndex:
    def __init__(self, chunks: list[Chunk], embeddings: np.ndarray | None):
        if not chunks:
            raise RuntimeError("Índice vacío: ejecute scripts/ingest.py")
        self.chunks = chunks
        self.embeddings = embeddings
        self.by_id = {c.chunk_id: i for i, c in enumerate(chunks)}
        self.bm25 = BM25Okapi([tokenize(embedding_text(c)) for c in chunks])

    @classmethod
    def load(cls) -> "CorpusIndex":
        path = settings.index_dir / "chunks.jsonl"
        if not path.exists():
            raise RuntimeError("No existe el índice. Ejecute: python scripts/ingest.py")
        with open(path, encoding="utf-8") as fh:
            chunks = [Chunk.model_validate_json(line) for line in fh if line.strip()]
        emb_path = settings.index_dir / "embeddings.npy"
        embeddings = np.load(emb_path) if emb_path.exists() else None
        if embeddings is not None and len(embeddings) != len(chunks):
            raise RuntimeError("Embeddings desincronizados con chunks: re-ejecute la ingesta")
        return cls(chunks, embeddings)


@lru_cache(maxsize=1)
def get_index() -> CorpusIndex:
    return CorpusIndex.load()
