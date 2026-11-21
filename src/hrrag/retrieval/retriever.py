"""Recuperación: léxica (BM25), semántica (E5), híbrida (RRF), filtros de metadatos y reranking."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

import numpy as np

from ..config import settings
from ..ingest.chunker import embedding_text
from ..schemas import Chunk, RetrievedChunk, Role
from .index import CorpusIndex, get_index
from .text import tokenize

HISTORICAL_RE = re.compile(
    r"\b(2025|anterior|antes|derogad\w*|vieja|previa|pasad\w*|cambi\w*|diferencia\w*)\b", re.IGNORECASE
)


@dataclass
class RetrievalConfig:
    mode: Literal["bm25", "dense", "hybrid"] = "hybrid"
    rerank: bool = True
    access_filter: bool = True
    version_filter: bool = True
    exclude_quarantined: bool = True
    top_k: int = settings.top_k_context
    candidates: int = settings.top_k_candidates


# Línea base: búsqueda léxica pura sin filtros de metadatos ni reranking
BASELINE = RetrievalConfig(mode="bm25", rerank=False, access_filter=False, version_filter=False,
                           exclude_quarantined=False)
IMPROVED = RetrievalConfig()


@dataclass
class RetrievalTrace:
    filters: dict = field(default_factory=dict)
    candidates: list[tuple[str, float]] = field(default_factory=list)
    reranked: list[tuple[str, float]] = field(default_factory=list)
    denied_by_role: int = 0


def wants_history(question: str) -> bool:
    return bool(HISTORICAL_RE.search(question))


def allowed_mask(index: CorpusIndex, role: Role, cfg: RetrievalConfig, question: str) -> np.ndarray:
    include_hist = wants_history(question)
    mask = np.ones(len(index.chunks), dtype=bool)
    for i, c in enumerate(index.chunks):
        if cfg.access_filter and role.value not in c.allowed_roles:
            mask[i] = False
        if cfg.exclude_quarantined and c.quarantined:
            mask[i] = False
        if cfg.version_filter and c.status != "vigente" and not (include_hist and c.status == "derogado"):
            mask[i] = False
    return mask


def _bm25(index: CorpusIndex, question: str, mask: np.ndarray, n: int) -> list[tuple[int, float]]:
    scores = index.bm25.get_scores(tokenize(question))
    scores = np.where(mask, scores, -np.inf)
    order = np.argsort(-scores)[:n]
    return [(int(i), float(scores[i])) for i in order if np.isfinite(scores[i]) and scores[i] > 0]


def _dense(index: CorpusIndex, question: str, mask: np.ndarray, n: int) -> list[tuple[int, float]]:
    from .models import embed_query

    if index.embeddings is None:
        raise RuntimeError("Índice vectorial no disponible")
    sims = index.embeddings @ embed_query(question)
    sims = np.where(mask, sims, -np.inf)
    order = np.argsort(-sims)[:n]
    return [(int(i), float(sims[i])) for i in order if np.isfinite(sims[i])]


def _rrf(rankings: list[list[tuple[int, float]]], k: int) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion: combina rankings sin calibrar escalas de score."""
    fused: dict[int, float] = {}
    for ranking in rankings:
        for pos, (idx, _) in enumerate(ranking, start=1):
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (k + pos)
    return sorted(fused.items(), key=lambda x: -x[1])


def _dedupe(items: list[tuple[int, float]], index: CorpusIndex) -> list[tuple[int, float]]:
    seen, out = set(), []
    for idx, s in items:
        h = index.chunks[idx].hash
        if h not in seen:
            seen.add(h)
            out.append((idx, s))
    return out


def retrieve(question: str, role: Role, cfg: RetrievalConfig = IMPROVED,
             index: CorpusIndex | None = None) -> tuple[list[RetrievedChunk], RetrievalTrace]:
    index = index or get_index()
    trace = RetrievalTrace()
    mask = allowed_mask(index, role, cfg, question)
    if cfg.access_filter:
        trace.denied_by_role = int(sum(role.value not in c.allowed_roles for c in index.chunks))
    trace.filters = {"role": role.value, "access_filter": cfg.access_filter,
                     "version_filter": cfg.version_filter, "include_historical": wants_history(question),
                     "exclude_quarantined": cfg.exclude_quarantined, "eligible_chunks": int(mask.sum())}
    if not mask.any():
        return [], trace

    if cfg.mode == "bm25":
        ranked, stage = _bm25(index, question, mask, cfg.candidates), "bm25"
    elif cfg.mode == "dense":
        ranked, stage = _dense(index, question, mask, cfg.candidates), "dense"
    else:
        ranked = _rrf([_bm25(index, question, mask, cfg.candidates),
                       _dense(index, question, mask, cfg.candidates)], settings.rrf_k)
        stage = "hybrid"
    ranked = _dedupe(ranked, index)[: cfg.candidates]
    trace.candidates = [(index.chunks[i].chunk_id, round(s, 4)) for i, s in ranked]

    if cfg.rerank and ranked:
        from .models import get_reranker

        pairs = [(question, embedding_text(index.chunks[i])) for i, _ in ranked]
        scores = get_reranker().predict(pairs, batch_size=16)
        ranked = sorted(zip([i for i, _ in ranked], [float(s) for s in scores]), key=lambda x: -x[1])
        stage = "rerank"
        trace.reranked = [(index.chunks[i].chunk_id, round(s, 4)) for i, s in ranked]

    top = ranked[: cfg.top_k]
    results = [RetrievedChunk(chunk=index.chunks[i], score=s, rank=r, stage=stage)
               for r, (i, s) in enumerate(top, start=1)]
    return results, trace


def check_permissions(results: list[RetrievedChunk], role: Role) -> tuple[list[RetrievedChunk], int]:
    """Segunda compuerta de permisos (defensa en profundidad) previa a la generación."""
    ok = [r for r in results if role.value in r.chunk.allowed_roles and not r.chunk.quarantined]
    return ok, len(results) - len(ok)


def chunk_label(c: Chunk) -> str:
    return f"{c.title} (v{c.version}, {c.section or ''}, pág. {c.page})"
