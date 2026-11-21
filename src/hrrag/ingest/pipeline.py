"""Pipeline de ingesta reproducible: carga -> extracción -> limpieza -> chunking -> metadatos -> indexación."""
from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timezone

import numpy as np

from ..config import settings
from ..schemas import Chunk
from ..security.patterns import find_injection
from .chunker import build_chunks, embedding_text
from .cleaner import clean_page
from .loader import load_catalog, load_documents

log = logging.getLogger(__name__)


def _quarantine(chunks: list[Chunk]) -> list[Chunk]:
    """Envenenamiento de fuentes: fuentes no confiables o con instrucciones incrustadas
    se marcan en cuarentena y nunca se usan como evidencia."""
    for ch in chunks:
        if not ch.trusted or find_injection(ch.text):
            ch.quarantined = True
    return chunks


def run_ingestion(with_embeddings: bool = True) -> dict:
    t0 = time.perf_counter()
    catalog = load_catalog()
    docs = load_documents(catalog)
    all_chunks: list[Chunk] = []
    stats = []
    for doc in docs:
        pages = [(p.page, p.page_label, clean_page(p.text, doc.meta["format"])) for p in doc.pages]
        chunks = _quarantine(build_chunks(doc.meta, pages))
        all_chunks.extend(chunks)
        stats.append({"doc_id": doc.meta["doc_id"], "version": doc.meta["version"],
                      "pages": len(doc.pages), "chunks": len(chunks),
                      "quarantined": sum(c.quarantined for c in chunks)})
        log.info("%s v%s: %d páginas, %d chunks", doc.meta["doc_id"], doc.meta["version"],
                 len(doc.pages), len(chunks))

    ids = [c.chunk_id for c in all_chunks]
    if len(ids) != len(set(ids)):
        raise RuntimeError("chunk_id duplicados en la ingesta")

    settings.index_dir.mkdir(parents=True, exist_ok=True)
    with open(settings.index_dir / "chunks.jsonl", "w", encoding="utf-8") as fh:
        for c in all_chunks:
            fh.write(c.model_dump_json() + "\n")

    if with_embeddings:
        from ..retrieval.models import embed_passages

        vecs = embed_passages([embedding_text(c) for c in all_chunks])
        np.save(settings.index_dir / "embeddings.npy", vecs)

    catalog_hash = hashlib.sha256(settings.catalog_path.read_bytes()).hexdigest()[:16]
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "catalog_hash": catalog_hash,
        "embedding_model": settings.embedding_model if with_embeddings else None,
        "chunk_max_chars": settings.chunk_max_chars,
        "chunk_overlap_chars": settings.chunk_overlap_chars,
        "n_chunks": len(all_chunks),
        "n_quarantined": sum(c.quarantined for c in all_chunks),
        "documents": stats,
        "elapsed_s": round(time.perf_counter() - t0, 2),
    }
    (settings.index_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False),
                                                      encoding="utf-8")
    return manifest
