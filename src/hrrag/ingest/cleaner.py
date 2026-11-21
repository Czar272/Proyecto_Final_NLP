"""Fase 3: limpieza y normalización del texto extraído."""
from __future__ import annotations

import re
import unicodedata

HEADER_RE = re.compile(r"^C[óo]digo de Trabajo\s*•\s*Edici[óo]n Conmemorativa.*$", re.MULTILINE)
FOOTNOTE_LINE_RE = re.compile(r"^\d{1,3}\s+[A-ZÁÉÍÓÚÑ\"“(]")
INLINE_FOOTNOTE_RE = re.compile(r"(?<=[a-záéíóúñ\.,;:\)])(\d{1,3})(?=[\s,;:\.]|$)")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("­", "")
    text = re.sub(r"[ \t]+", " ", text)
    return text


def strip_pdf_noise(text: str) -> str:
    """Quita encabezados repetidos, número de página y notas al pie del PDF del Código."""
    text = HEADER_RE.sub("", text)
    lines = [ln.rstrip() for ln in text.splitlines()]
    while lines and (not lines[0].strip() or lines[0].strip().isdigit()):
        lines.pop(0)
    # Las notas al pie aparecen al final de la página; se cortan desde la primera línea
    # con formato "NN Texto" ubicada en el último 40% de la página.
    cut = len(lines)
    start = int(len(lines) * 0.6)
    for idx in range(start, len(lines)):
        if FOOTNOTE_LINE_RE.match(lines[idx].strip()) and not lines[idx].strip().upper().startswith("ART"):
            cut = idx
            break
    lines = lines[:cut]
    text = "\n".join(lines)
    text = INLINE_FOOTNOTE_RE.sub("", text)
    return text


def join_lines(text: str) -> str:
    """Une líneas cortadas por el maquetado conservando párrafos e incisos."""
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    lines = text.splitlines()
    out: list[str] = []
    for ln in lines:
        s = ln.strip()
        if not s:
            out.append("")
            continue
        new_block = (
            not out
            or out[-1] == ""
            or out[-1].startswith("#")
            or re.match(r"^(ART[ÍI]CULO\s+\d+|#|[a-zñ]\)|\d+\)|[A-ZÁÉÍÓÚ ]{6,}$|T[ÍI]TULO|CAP[ÍI]TULO)", s)
            or out[-1].endswith((".", ":", ";"))
        )
        if new_block:
            out.append(s)
        else:
            out[-1] = out[-1] + " " + s
    text = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def clean_page(text: str, fmt: str) -> str:
    text = normalize(text)
    if fmt == "pdf":
        text = strip_pdf_noise(text)
    return join_lines(text)
