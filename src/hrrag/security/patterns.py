"""Patrones compartidos para detección de inyección de instrucciones y PII."""
from __future__ import annotations

import re
import unicodedata

INJECTION_PATTERNS = [
    r"ignor\w*\s+(todas?\s+)?(las\s+|tus\s+)?(instrucciones|reglas|indicaciones|directrices)",
    r"ignore\s+(all\s+|any\s+)?(previous|prior|above)?\s*(instructions|rules)",
    r"olvid\w*\s+(todas?\s+)?(las\s+|tus\s+)?(instrucciones|reglas)",
    r"(revela|muestra|imprime|dime|repite|print|reveal|show)\w*\s+(\w+\s+){0,3}(prompt|instrucciones\s+(del\s+)?sistema|system\s+prompt|mensaje\s+del\s+sistema)",
    r"prompt\s+del\s+sistema|system\s+prompt",
    r"(act[uú]a|actua|comp[oó]rtate|finge|pretend|act)\s+(como|as)\s+(si\s+fueras\s+)?(un\s+)?(administrador|admin|root|desarrollador|developer|dan|rrhh)",
    r"modo\s+(desarrollador|administrador|dios|sin\s+restricciones|developer|jailbreak)",
    r"jailbreak|(?-i:\bDAN\b)",
    r"(nuevas|new)\s+(instrucciones|instructions)\s*:",
    r"(a\s+partir\s+de\s+ahora|from\s+now\s+on)\s*,?\s*(eres|you\s+are|responde|ignora)",
    r"sin\s+(ninguna\s+)?(restricci[oó]n|restricciones|filtros|censura)",
    r"<\s*/?\s*(system|assistant|instrucciones)\s*>",
    r"\[\s*(system|sistema)\s*\]",
    r"(soy|tengo\s+rol\s+de|mi\s+rol\s+es)\s+(de\s+)?(rrhh|recursos\s+humanos|administrador|gerente\s+general)",
    r"(otorga|dame|concede|asigna)\w*\s+(\w+\s+){0,2}(permisos?|acceso|rol)\s+(de\s+)?(rrhh|administrador|admin|total)",
]
_INJECTION_RE = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]

PII_PATTERNS = {
    "DPI": re.compile(r"\b\d{4}\s?\d{5}\s?\d{4}\b"),
    "EMAIL": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    "TELEFONO": re.compile(r"(?<!\d)(?:\+?502[\s-]?)?[2-7]\d{3}[\s-]?\d{4}(?!\d)"),
    "NIT": re.compile(r"\bNIT[:\s]*\d{5,9}-?[\dkK]\b", re.IGNORECASE),
    "TARJETA": re.compile(r"\b(?:\d{4}[\s-]?){3}\d{4}\b"),
}


def normalize_for_matching(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    # Elimina caracteres de ancho cero usados para ofuscar ataques
    return re.sub(r"[​-‏⁠﻿]", "", text)


def find_injection(text: str) -> list[str]:
    norm = normalize_for_matching(text)
    return [p.pattern for p in _INJECTION_RE if p.search(norm)]


def mask_pii(text: str) -> str:
    out = text
    for label in ("TARJETA", "DPI", "NIT", "EMAIL", "TELEFONO"):
        out = PII_PATTERNS[label].sub(f"[{label}]", out)
    return out


def detect_pii(text: str) -> list[str]:
    return [label for label, rx in PII_PATTERNS.items() if rx.search(text)]
