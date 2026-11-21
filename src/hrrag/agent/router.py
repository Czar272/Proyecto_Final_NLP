"""Router de intención: decide entre recuperación documental, herramientas o ambas.

Se usa un enrutador determinista basado en reglas (auditable y sin costo de inferencia) porque las
intenciones transaccionales del dominio son pocas y se expresan con patrones léxicos estables.
La extracción de parámetros también es determinista para evitar que el LLM invente valores.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from ..schemas import UserContext
from .tools import reference_date

QUESTION_START = re.compile(r"^\s*¿?\s*(c[oó]mo|con\s+cu[aá]nta|qu[eé]|cu[aá]l|cu[aá]les|d[oó]nde|por\s+qu[eé]|"
                            r"es\s+cierto|existe|hay)\b", re.IGNORECASE)
SALDO_RE = re.compile(
    r"(saldo|d[ií]as\s+(de\s+vacaciones\s+)?((me|le|te)\s+)?(quedan|tengo|tiene|disponibles|pendientes)|"
    r"vacaciones\s+((me|le|te)\s+)?quedan)",
    re.IGNORECASE)
CALC_TYPES = {
    "aguinaldo": r"aguinaldo",
    "bono14": r"bono\s*14|bonificaci[oó]n\s+anual",
    "indemnizacion": r"indemnizaci[oó]n",
    "vacaciones_proporcionales": r"vacaciones\s+(no\s+gozadas\s+)?proporcional",
}
CALC_TRIGGER = re.compile(
    r"(calcul|cu[aá]nto\s+(me\s+)?(toca|tocar[ií]a|corresponde|corresponder[ií]a|recibir|dar[ií]an|pagar[ií]an|ser[ií]a)|"
    r"monto\s+de\s+mi|estim)", re.IGNORECASE)
REQUEST_TRIGGER = re.compile(
    r"(quiero|deseo|necesito|me\s+gustar[ií]a|registra|reg[ií]strame|solicita|solic[ií]tame|"
    r"tramita|ag[eé]ndame|crea|haz)\w*\s+(\w+\s+){0,4}(solicitud|vacaciones|d[ií]as\s+de\s+vacaciones)",
    re.IGNORECASE)
LEGAL_ADVICE_RE = re.compile(r"(demand\w+|abogad\w+|juicio|denunciar\s+a\s+la\s+empresa|despedir\s+a\s+\w+|"
                             r"me\s+pueden\s+despedir|me\s+van\s+a\s+despedir)", re.IGNORECASE)
OTHER_EMP_RE = re.compile(r"\bEMP-\d{3}\b", re.IGNORECASE)
MONEY_RE = re.compile(r"Q\s?([\d]{1,3}(?:[,\s]?\d{3})*(?:\.\d{1,2})?)", re.IGNORECASE)
ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
DMY_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
DAYS_RE = re.compile(r"\b(\d{1,3})\s+d[ií]as\b", re.IGNORECASE)


@dataclass
class RoutePlan:
    intents: list[str] = field(default_factory=list)
    tool_calls: list[tuple[str, dict]] = field(default_factory=list)
    use_rag: bool = True
    legal_advice: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def primary(self) -> str:
        return self.intents[0] if self.intents else "consulta_documental"


def _dates(text: str) -> list[date]:
    out = []
    for y, m, d in ISO_DATE_RE.findall(text):
        try:
            out.append(date(int(y), int(m), int(d)))
        except ValueError:
            out.append(date(1900, 1, 1))  # fecha inválida explícita -> la herramienta la rechaza
    for d, m, y in DMY_DATE_RE.findall(text):
        try:
            out.append(date(int(y), int(m), int(d)))
        except ValueError:
            out.append(date(1900, 1, 1))
    return out


def _money(text: str) -> float | None:
    m = MONEY_RE.search(text)
    if not m:
        return None
    return float(re.sub(r"[,\s]", "", m.group(1)))


def route(question: str, user: UserContext, db_lookup=None) -> RoutePlan:
    """db_lookup(employee_id) -> dict con salario_base y fecha_ingreso (para completar parámetros propios)."""
    plan = RoutePlan()
    q = question.strip()
    is_info_question = bool(QUESTION_START.match(q))
    target = OTHER_EMP_RE.search(q)
    target_id = target.group(0).upper() if target else user.user_id

    if LEGAL_ADVICE_RE.search(q):
        plan.legal_advice = True
        plan.notes.append("Consulta con componente de asesoría legal: requiere revisión humana")

    # 1) Acción crítica: registrar solicitud de vacaciones
    if REQUEST_TRIGGER.search(q) and not is_info_question:
        dates = _dates(q)
        days = DAYS_RE.search(q)
        params = {"employee_id": target_id}
        if dates:
            params["fecha_inicio"] = dates[0].isoformat()
        if days:
            params["dias"] = int(days.group(1))
        plan.intents.append("solicitud_vacaciones")
        plan.tool_calls.append(("registrar_solicitud_vacaciones", params))
        plan.use_rag = False
        return plan

    # 2) Consulta de saldo (dato transaccional exacto)
    if SALDO_RE.search(q):
        plan.intents.append("saldo_vacaciones")
        plan.tool_calls.append(("consultar_saldo_vacaciones", {"employee_id": target_id}))

    # 3) Cálculo de prestaciones
    calc_type = next((t for t, rx in CALC_TYPES.items() if re.search(rx, q, re.IGNORECASE)), None)
    if calc_type and CALC_TRIGGER.search(q) and not is_info_question:
        params: dict = {"tipo": calc_type}
        salary = _money(q)
        dates = _dates(q)
        own = db_lookup(user.user_id) if db_lookup else None
        if salary is None and own:
            salary = own["salario_base"]
            plan.notes.append("Salario tomado del expediente del propio colaborador")
        if salary is not None:
            params["salario_mensual"] = salary
        if len(dates) >= 2:
            params["fecha_inicio"], params["fecha_fin"] = dates[0].isoformat(), dates[1].isoformat()
        elif len(dates) == 1:
            params["fecha_inicio"], params["fecha_fin"] = dates[0].isoformat(), reference_date().isoformat()
        elif own:
            params["fecha_inicio"], params["fecha_fin"] = own["fecha_ingreso"], reference_date().isoformat()
        plan.intents.append("calculo_prestaciones")
        plan.tool_calls.append(("calcular_prestaciones", params))

    # 4) Recuperación documental: por defecto, o como complemento si la pregunta tiene más partes
    if plan.tool_calls:
        remainder = SALDO_RE.sub("", q)
        for rx in CALC_TYPES.values():
            remainder = re.sub(rx, "", remainder, flags=re.IGNORECASE)
        plan.use_rag = bool(re.search(r"\b(y|adem[aá]s|tambi[eé]n)\b.*\b(c[oó]mo|qu[eé]|cu[aá]nta|cu[aá]l|"
                                      r"plazo|anticipaci[oó]n|requisito|pol[ií]tica|art[ií]culo)", remainder,
                                      re.IGNORECASE))
        if plan.use_rag:
            plan.intents.append("consulta_documental")
    else:
        plan.intents.append("consulta_documental")
    return plan
