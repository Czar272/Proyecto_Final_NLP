"""Fase 1 y 2: carga del repositorio de origen y extracción de texto por página."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from ..config import settings

PAGE_MARKER = re.compile(r"^---\s*página\s+(\d+)\s*---\s*$", re.IGNORECASE | re.MULTILINE)


@dataclass
class RawPage:
    page: int
    text: str
    page_label: str | None = None


@dataclass
class RawDocument:
    meta: dict
    pages: list[RawPage]


def load_catalog(path: Path | None = None) -> list[dict]:
    path = path or settings.catalog_path
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)["sources"]


def extract_pdf(path: Path) -> list[RawPage]:
    reader = PdfReader(str(path))
    pages = []
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        label = None
        first = text.strip().splitlines()[:1]
        if first and first[0].strip().isdigit():
            label = first[0].strip()
        pages.append(RawPage(page=i, text=text, page_label=label))
    return pages


def extract_markdown(path: Path) -> list[RawPage]:
    content = path.read_text(encoding="utf-8")
    parts = PAGE_MARKER.split(content)
    pages = [RawPage(page=1, text=parts[0])]
    for j in range(1, len(parts), 2):
        pages.append(RawPage(page=int(parts[j]), text=parts[j + 1]))
    return pages


def load_documents(catalog: list[dict] | None = None) -> list[RawDocument]:
    catalog = catalog or load_catalog()
    docs = []
    for meta in catalog:
        path = settings.data_dir / meta["path"]
        if not path.exists():
            raise FileNotFoundError(f"Fuente declarada en el catálogo no encontrada: {path}")
        if meta["format"] == "pdf":
            pages = extract_pdf(path)
        elif meta["format"] in ("md", "txt"):
            pages = extract_markdown(path)
        else:
            raise ValueError(f"Formato no soportado: {meta['format']}")
        docs.append(RawDocument(meta=meta, pages=pages))
    return docs
