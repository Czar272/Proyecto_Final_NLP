"""Generación fundamentada con citas, abstención y degradación controlada."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from ..schemas import RetrievedChunk, SourceRef
from .llm import LLMClient, LLMUnavailable
from .prompts import build_baseline_messages, build_messages, format_context

NO_EVIDENCE_MSG = ("No encontré evidencia suficiente en las fuentes autorizadas para responder esta consulta. "
                   "Te sugiero contactar a Recursos Humanos (rrhh@altiplano.example).")


@dataclass
class GenerationResult:
    answer: str
    sources: list[SourceRef] = field(default_factory=list)
    abstained: bool = False
    needs_human_review: bool = False
    mode: str = "llm"
    error: str | None = None
    invalid_citations: list[str] = field(default_factory=list)


def _to_ref(rc: RetrievedChunk) -> SourceRef:
    c = rc.chunk
    return SourceRef(source=c.source, page=c.page, chunk_id=c.chunk_id, version=c.version)


def _parse_json(raw: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            raise
        return json.loads(m.group(0))


def extractive_answer(question: str, chunks: list[RetrievedChunk], reason: str) -> GenerationResult:
    """Respaldo determinista cuando el LLM no está disponible: muestra el fragmento más relevante citado."""
    if not chunks:
        return GenerationResult(answer=NO_EVIDENCE_MSG, abstained=True, mode="extractive", error=reason)
    top = chunks[0].chunk
    snippet = top.text if len(top.text) <= 600 else top.text[:600].rsplit(" ", 1)[0] + "…"
    answer = ("El servicio de generación no está disponible en este momento. El fragmento más relevante "
              f"encontrado en {top.title} (versión {top.version}, pág. {top.page}) indica:\n\n{snippet}")
    return GenerationResult(answer=answer, sources=[_to_ref(chunks[0])], needs_human_review=True,
                            mode="extractive", error=reason)


def generate(question: str, chunks: list[RetrievedChunk], client: LLMClient, baseline: bool = False,
             tool_note: str | None = None, ambiguous: bool = False) -> GenerationResult:
    if not chunks and not tool_note:
        return GenerationResult(answer=NO_EVIDENCE_MSG, abstained=True, mode="rule")
    context, mapping = format_context(chunks)
    messages = (build_baseline_messages(question, context) if baseline
                else build_messages(question, context, tool_note, ambiguous))
    try:
        raw = client.chat(messages)
        data = _parse_json(raw)
    except LLMUnavailable as exc:
        return extractive_answer(question, chunks, str(exc))
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        res = extractive_answer(question, chunks, f"Salida no conforme del LLM: {type(exc).__name__}")
        res.mode = "fallback_parse"
        return res

    answer = str(data.get("answer", "")).strip()
    cited = data.get("citations") or []
    if not isinstance(cited, list):
        cited = [cited]
    valid, invalid = [], []
    for cid in cited:
        key = str(cid).strip().strip("[]")
        if key in mapping:
            if key not in valid:
                valid.append(key)
        else:
            invalid.append(str(cid))
    return GenerationResult(
        answer=answer or NO_EVIDENCE_MSG,
        sources=[_to_ref(mapping[k]) for k in valid],
        abstained=bool(data.get("abstained", False)) or not answer,
        needs_human_review=bool(data.get("needs_human_review", False)),
        mode="llm",
        invalid_citations=invalid,
    )
