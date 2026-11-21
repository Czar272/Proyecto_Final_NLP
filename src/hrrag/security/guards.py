"""Guardrails de entrada y de salida."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..config import settings
from ..generation.prompts import CANARY, SYSTEM_PROMPT
from ..schemas import Chunk, RetrievedChunk, Role, ToolResult
from .patterns import detect_pii, find_injection, mask_pii, normalize_for_matching

NUM_RE = re.compile(r"\d+(?:[.,]\d+)*")


@dataclass
class GuardVerdict:
    allowed: bool = True
    reasons: list[str] = field(default_factory=list)
    sanitized: str = ""
    pii: list[str] = field(default_factory=list)


def check_input(question: str) -> GuardVerdict:
    v = GuardVerdict(sanitized=normalize_for_matching(question).strip())
    if len(v.sanitized) > settings.max_question_chars:
        v.allowed = False
        v.reasons.append("longitud_excedida")
    hits = find_injection(v.sanitized)
    if hits:
        v.allowed = False
        v.reasons.append("posible_inyeccion_de_instrucciones")
    v.pii = detect_pii(v.sanitized)
    return v


@dataclass
class OutputVerdict:
    ok: bool = True
    issues: list[str] = field(default_factory=list)
    answer: str = ""
    force_abstain: bool = False
    needs_review: bool = False


def _restricted_leak(answer: str, restricted: list[Chunk]) -> bool:
    """Detecta si la respuesta reproduce contenido de documentos restringidos (n-gramas de 6 palabras)."""
    words = re.findall(r"\w+", answer.lower())
    grams = {" ".join(words[i:i + 6]) for i in range(len(words) - 5)}
    for c in restricted:
        cw = re.findall(r"\w+", c.text.lower())
        if any(" ".join(cw[i:i + 6]) in grams for i in range(len(cw) - 5)):
            return True
    return False


def _unsupported_numbers(answer: str, evidence: str) -> list[str]:
    """Verificación de fidelidad numérica: toda cifra de la respuesta debe existir en la evidencia."""
    ev = {n.replace(",", "") for n in NUM_RE.findall(evidence)}
    missing = []
    for n in NUM_RE.findall(answer):
        norm = n.replace(",", "")
        if norm not in ev and norm.rstrip("0").rstrip(".") not in ev and len(norm) > 1:
            missing.append(n)
    return missing


def check_output(answer: str, context: list[RetrievedChunk], tool_results: list[ToolResult], role: Role,
                 restricted_chunks: list[Chunk], has_sources: bool, abstained: bool) -> OutputVerdict:
    v = OutputVerdict(answer=answer)
    if CANARY in answer or SYSTEM_PROMPT[:80] in answer or "REGLAS OBLIGATORIAS" in answer:
        v.ok, v.force_abstain = False, True
        v.issues.append("fuga_prompt_sistema")
    if role != Role.RRHH and _restricted_leak(answer, restricted_chunks):
        v.ok, v.force_abstain = False, True
        v.issues.append("fuga_documento_restringido")
    if find_injection(answer):
        v.ok, v.force_abstain = False, True
        v.issues.append("instruccion_en_salida")
    if not abstained:
        if not has_sources and not tool_results:
            v.needs_review = True
            v.issues.append("respuesta_sin_citas")
        evidence = " ".join(rc.chunk.text for rc in context) + " " + " ".join(str(t.data) for t in tool_results)
        evidence += " " + " ".join(f"{rc.chunk.page} {rc.chunk.version}" for rc in context)
        missing = _unsupported_numbers(answer, evidence)
        if missing:
            v.needs_review = True
            v.issues.append(f"cifras_sin_respaldo:{','.join(missing[:5])}")
    v.answer = mask_pii(v.answer)
    return v
