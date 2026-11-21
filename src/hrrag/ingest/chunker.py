"""Fase 4 y 5: segmentación por unidades semánticas del dominio y enriquecimiento con metadatos.

Estrategia:
- Código de Trabajo: un chunk por artículo (unidad normativa citable). Los artículos que
  continúan en otra página generan un chunk de continuación con la misma etiqueta, de modo
  que la página citada siempre es exacta. Artículos largos se dividen por párrafos con solape.
- Políticas internas: un chunk por sección "##" (cada sección regula un tema).
"""
from __future__ import annotations

import hashlib
import re

from ..config import settings
from ..schemas import Chunk

ARTICLE_RE = re.compile(r"(?=^ART[ÍI]CULO\s+\d+)", re.MULTILINE)
ARTICLE_NUM_RE = re.compile(r"^ART[ÍI]CULO\s+(\d+)", re.IGNORECASE)
SECTION_RE = re.compile(r"(?=^##\s)", re.MULTILINE)
MIN_CHARS = 120


def _split_long(text: str, max_chars: int, overlap: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    paras = [p for p in re.split(r"\n+", text) if p.strip()]
    pieces, current = [], ""
    for p in paras:
        if current and len(current) + len(p) + 1 > max_chars:
            pieces.append(current)
            current = current[-overlap:] + "\n" + p if overlap else p
        else:
            current = f"{current}\n{p}" if current else p
        while len(current) > max_chars * 1.5:
            pieces.append(current[:max_chars])
            current = current[max_chars - overlap:]
    if current.strip():
        pieces.append(current)
    return pieces


def _merge_small(segments: list[tuple[str, str]]) -> list[tuple[str, str]]:
    merged: list[tuple[str, str]] = []
    for section, text in segments:
        if merged and len(merged[-1][1]) < MIN_CHARS:
            prev_section, prev_text = merged[-1]
            merged[-1] = (prev_section or section, prev_text + "\n" + text)
        else:
            merged.append((section, text))
    return merged


def segment_code_page(text: str, carry_article: str | None) -> tuple[list[tuple[str, str]], str | None]:
    parts = [p.strip() for p in ARTICLE_RE.split(text) if p.strip()]
    segments: list[tuple[str, str]] = []
    current = carry_article
    for part in parts:
        m = ARTICLE_NUM_RE.match(part)
        if m:
            current = f"Artículo {m.group(1)}"
            segments.append((current, part))
        else:
            label = f"{current} (continuación)" if current else "Preámbulo"
            segments.append((label, part))
    return _merge_small(segments), current


def segment_policy_page(text: str, carry_section: str | None) -> tuple[list[tuple[str, str]], str | None]:
    parts = [p.strip() for p in SECTION_RE.split(text) if p.strip()]
    segments: list[tuple[str, str]] = []
    current = carry_section
    for part in parts:
        if part.startswith("## "):
            current = part.splitlines()[0].lstrip("# ").strip()
        elif part.startswith("# "):
            current = "Encabezado"
        segments.append((current or "Encabezado", part))
    return _merge_small(segments), current


def build_chunks(meta: dict, pages: list[tuple[int, str | None, str]]) -> list[Chunk]:
    chunks: list[Chunk] = []
    carry: str | None = None
    for page_num, page_label, text in pages:
        if not text.strip():
            continue
        if meta["format"] == "pdf":
            segments, carry = segment_code_page(text, carry)
        else:
            segments, carry = segment_policy_page(text, carry)
        n = 0
        for section, seg_text in segments:
            for piece in _split_long(seg_text, settings.chunk_max_chars, settings.chunk_overlap_chars):
                n += 1
                chunk_id = f"{meta['doc_id']}-v{meta['version']}-p{page_num}-c{n}"
                chunks.append(
                    Chunk(
                        chunk_id=chunk_id,
                        text=piece.strip(),
                        source=meta["path"].split("/")[-1],
                        doc_id=meta["doc_id"],
                        title=meta["title"],
                        page=page_num,
                        page_label=page_label,
                        version=meta["version"],
                        status=meta["status"],
                        section=section,
                        allowed_roles=meta["allowed_roles"],
                        sensitivity=meta["sensitivity"],
                        hash=hashlib.sha256(piece.encode("utf-8")).hexdigest()[:16],
                        trusted=meta.get("trusted", True),
                    )
                )
    return chunks


def embedding_text(chunk: Chunk) -> str:
    """Texto enriquecido con el contexto del documento para indexar (encabezado contextual)."""
    return f"{chunk.title} | {chunk.section or ''} | versión {chunk.version}\n{chunk.text}"
