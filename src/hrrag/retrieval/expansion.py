"""Expansión de consulta con un glosario del dominio laboral.

Corrige el desajuste léxico entre lenguaje coloquial y terminología normativa (p. ej. «me caso» frente a
«contraer matrimonio»), detectado en el análisis de fallas de la primera iteración del benchmark.
"""
from __future__ import annotations

import re

GLOSSARY: list[tuple[str, str]] = [
    (r"\b(me\s+caso|casarme|boda|me\s+voy\s+a\s+casar)\b", "contraer matrimonio permiso"),
    (r"\b(d[ií]as?\s+libres?\s+pagados?|d[ií]as?\s+libres?\s+con\s+pago|libre\s+pagado)\b",
     "permisos con goce de salario"),
    (r"\b(me\s+corren|me\s+corre|correr(me)?|me\s+echan)\b", "despido injustificado"),
    (r"\b(compu|computadora|laptop)\b", "computadora portátil equipo"),
    (r"\b(internet|wifi)\b", "auxilio de conectividad"),
    (r"\b(trabajo\s+desde\s+(mi\s+)?casa|home\s*office|trabajar\s+desde\s+casa)\b", "teletrabajo"),
    (r"\b(naci[oó]\s+mi\s+(hijo|beb[eé])|nacimiento|ser\s+pap[aá])\b", "licencia de paternidad nacimiento de hijo"),
    (r"\b(se\s+muri[oó]|falleci[oó]|muerte)\b", "fallecimiento permiso"),
    (r"\b(llegar\s+tarde|tardanza|impuntual)\b", "llegada tardía puntualidad"),
    (r"\b(regalo|obsequio|detalle)\b", "regalos y atenciones"),
]
_COMPILED = [(re.compile(p, re.IGNORECASE), exp) for p, exp in GLOSSARY]


def expand_query(question: str) -> str:
    extra = [exp for rx, exp in _COMPILED if rx.search(question)]
    return f"{question} ({'; '.join(extra)})" if extra else question
