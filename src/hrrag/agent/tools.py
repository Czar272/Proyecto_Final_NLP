"""Herramientas del agente con contrato estricto, permisos por rol, validación de parámetros y límites.

- consultar_saldo_vacaciones: SQL parametrizado (dato exacto que el LLM no debe estimar).
- calcular_prestaciones: motor de cálculo determinista (aguinaldo, Bono 14, indemnización, vacaciones).
- registrar_solicitud_vacaciones: acción crítica; exige confirmación humana explícita.
"""
from __future__ import annotations

import os
import sqlite3
import time
from collections import defaultdict, deque
from datetime import date, datetime, timedelta

from pydantic import BaseModel, Field, ValidationError, field_validator

from ..config import settings
from ..schemas import Role, ToolResult, UserContext

MIN_SALARY, MAX_SALARY = 1000.0, 100000.0
RATE_LIMIT_PER_MIN = 10
_calls: dict[str, deque] = defaultdict(deque)


class ToolError(Exception):
    pass


def reference_date() -> date:
    """Fecha de referencia del sistema (configurable para pruebas reproducibles)."""
    raw = os.getenv("REFERENCE_DATE")
    return date.fromisoformat(raw) if raw else date.today()


def _rate_limit(user_id: str) -> None:
    now = time.time()
    q = _calls[user_id]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= RATE_LIMIT_PER_MIN:
        raise ToolError("Límite de invocaciones de herramientas excedido; intente en un minuto")
    q.append(now)


def _service_available() -> None:
    if os.getenv("TOOL_OUTAGE") == "1":
        raise ToolError("Servicio de nómina no disponible")


def _connect() -> sqlite3.Connection:
    _service_available()
    if not settings.db_path.exists():
        raise ToolError("Base de nómina no inicializada (ejecute scripts/seed_db.py)")
    con = sqlite3.connect(f"file:{settings.db_path}?mode=rw", uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    return con


def _employee(con: sqlite3.Connection, employee_id: str) -> sqlite3.Row:
    row = con.execute("SELECT * FROM employees WHERE employee_id = ?", (employee_id,)).fetchone()
    if row is None:
        raise ToolError("Colaborador no encontrado")
    return row


def _can_view(user: UserContext, target: sqlite3.Row) -> bool:
    if user.role == Role.RRHH or user.user_id == target["employee_id"]:
        return True
    return user.role == Role.JEFE and target["jefe_id"] == user.user_id


# ---------------------------------------------------------------- saldo de vacaciones
class SaldoParams(BaseModel):
    employee_id: str = Field(pattern=r"^EMP-\d{3}$")


def consultar_saldo_vacaciones(params: dict, user: UserContext) -> ToolResult:
    name = "consultar_saldo_vacaciones"
    try:
        p = SaldoParams(**params)
        _rate_limit(user.user_id)
        with _connect() as con:
            emp = _employee(con, p.employee_id)
            if not _can_view(user, emp):
                return ToolResult(tool=name, ok=False, error="Acceso denegado: solo puede consultar su propio saldo")
            rows = con.execute(
                "SELECT periodo, dias_asignados, dias_gozados FROM vacation_balance WHERE employee_id = ? "
                "ORDER BY periodo", (p.employee_id,)).fetchall()
            pend = con.execute("SELECT COALESCE(SUM(dias),0) FROM vacation_requests WHERE employee_id = ? "
                               "AND estado LIKE 'pendiente%'", (p.employee_id,)).fetchone()[0]
        periodos = [{"periodo": r["periodo"], "asignados": r["dias_asignados"], "gozados": r["dias_gozados"],
                     "disponibles": r["dias_asignados"] - r["dias_gozados"]} for r in rows]
        disponible = sum(x["disponibles"] for x in periodos)
        return ToolResult(tool=name, ok=True, data={
            "employee_id": p.employee_id, "fecha_ingreso": emp["fecha_ingreso"], "periodos": periodos,
            "dias_disponibles": disponible, "dias_en_solicitudes_pendientes": pend})
    except ValidationError as exc:
        return ToolResult(tool=name, ok=False, error=f"Parámetros inválidos: {exc.errors()[0]['msg']}")
    except (ToolError, sqlite3.Error) as exc:
        return ToolResult(tool=name, ok=False, error=str(exc))


# ---------------------------------------------------------------- cálculo de prestaciones
class CalculoParams(BaseModel):
    tipo: str = Field(pattern=r"^(aguinaldo|bono14|indemnizacion|vacaciones_proporcionales)$")
    salario_mensual: float
    fecha_inicio: date
    fecha_fin: date

    @field_validator("salario_mensual")
    @classmethod
    def salary_range(cls, v: float) -> float:
        if not (MIN_SALARY <= v <= MAX_SALARY):
            raise ValueError(f"salario fuera de rango permitido (Q{MIN_SALARY:,.0f} - Q{MAX_SALARY:,.0f})")
        return v

    @field_validator("fecha_inicio", "fecha_fin")
    @classmethod
    def date_range(cls, v: date) -> date:
        if not (date(1970, 1, 1) <= v <= date(2035, 12, 31)):
            raise ValueError("fecha fuera de rango permitido (1970-2035)")
        return v


def _days(a: date, b: date) -> int:
    return max((b - a).days + 1, 0)


def _period_start(fin: date, month: int, day: int) -> date:
    start = date(fin.year, month, day)
    return start if fin >= start else date(fin.year - 1, month, day)


def calcular_prestaciones(params: dict, user: UserContext) -> ToolResult:
    name = "calcular_prestaciones"
    try:
        p = CalculoParams(**params)
        if p.fecha_inicio > p.fecha_fin:
            raise ToolError("La fecha de inicio no puede ser posterior a la fecha de fin")
        if (p.fecha_fin - p.fecha_inicio).days > 50 * 365:
            raise ToolError("Antigüedad fuera de rango (máximo 50 años)")
        _rate_limit(user.user_id)
        _service_available()
        s = p.salario_mensual
        if p.tipo == "indemnizacion":
            dias = _days(p.fecha_inicio, p.fecha_fin)
            monto = s * dias / 365
            base = "Art. 82 Código de Trabajo: un salario mensual por año de servicio, proporcional por fracción"
        elif p.tipo == "aguinaldo":
            ini = max(p.fecha_inicio, _period_start(p.fecha_fin, 12, 1))
            dias = _days(ini, p.fecha_fin)
            monto = s * min(dias, 365) / 365
            base = "Decreto 76-78 (POL-RH-004): un salario por año, período 1 dic - 30 nov"
        elif p.tipo == "bono14":
            ini = max(p.fecha_inicio, _period_start(p.fecha_fin, 7, 1))
            dias = _days(ini, p.fecha_fin)
            monto = s * min(dias, 365) / 365
            base = "Decreto 42-92 (POL-RH-004): un salario por año, período 1 jul - 30 jun"
        else:
            anniv = date(p.fecha_fin.year, p.fecha_inicio.month, min(p.fecha_inicio.day, 28))
            if anniv > p.fecha_fin:
                anniv = date(p.fecha_fin.year - 1, anniv.month, anniv.day)
            ini = max(p.fecha_inicio, anniv)
            dias = _days(ini, p.fecha_fin)
            monto = (s / 30) * 15 * min(dias, 365) / 365
            base = "Arts. 130 y 133 Código de Trabajo: 15 días hábiles por año, pago proporcional"
        return ToolResult(tool=name, ok=True, data={
            "tipo": p.tipo, "salario_mensual": round(s, 2), "dias_computados": dias,
            "monto_estimado_q": round(monto, 2), "base_legal": base,
            "nota": "Cálculo referencial; el monto definitivo lo confirma Recursos Humanos."})
    except ValidationError as exc:
        err = exc.errors()[0]
        return ToolResult(tool=name, ok=False, error=f"Parámetro fuera de rango o inválido ({err['loc'][0]}): {err['msg']}")
    except ToolError as exc:
        return ToolResult(tool=name, ok=False, error=str(exc))


# ---------------------------------------------------------------- solicitud de vacaciones (acción crítica)
class SolicitudParams(BaseModel):
    employee_id: str = Field(pattern=r"^EMP-\d{3}$")
    fecha_inicio: date
    dias: int = Field(ge=1, le=15)


def _business_days_between(a: date, b: date) -> int:
    n, d = 0, a
    while d < b:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def registrar_solicitud_vacaciones(params: dict, user: UserContext, confirmed: bool = False) -> ToolResult:
    name = "registrar_solicitud_vacaciones"
    try:
        p = SolicitudParams(**params)
        if p.employee_id != user.user_id:
            return ToolResult(tool=name, ok=False,
                              error="Acceso denegado: solo puede registrar solicitudes a su propio nombre")
        today = reference_date()
        anticip = _business_days_between(today, p.fecha_inicio)
        if anticip < 10:
            return ToolResult(tool=name, ok=False, error=(
                f"La solicitud requiere al menos 10 días hábiles de anticipación (POL-RH-002 v2026-01); "
                f"faltan solo {anticip} días hábiles"))
        saldo = consultar_saldo_vacaciones({"employee_id": p.employee_id}, user)
        if not saldo.ok:
            return ToolResult(tool=name, ok=False, error=saldo.error)
        disponible = saldo.data["dias_disponibles"] - saldo.data["dias_en_solicitudes_pendientes"]
        if p.dias > disponible:
            return ToolResult(tool=name, ok=False,
                              error=f"Saldo insuficiente: solicita {p.dias} días y tiene {disponible} disponibles")
        resumen = {"employee_id": p.employee_id, "fecha_inicio": p.fecha_inicio.isoformat(), "dias": p.dias,
                   "saldo_disponible": disponible}
        if not confirmed:
            return ToolResult(tool=name, ok=True, requires_confirmation=True, data=resumen)
        with _connect() as con:
            cur = con.execute(
                "INSERT INTO vacation_requests (employee_id, fecha_inicio, dias, estado, creado_en) "
                "VALUES (?, ?, ?, 'pendiente_aprobacion_jefe', ?)",
                (p.employee_id, p.fecha_inicio.isoformat(), p.dias, datetime.now().isoformat(timespec="seconds")))
            resumen["request_id"] = cur.lastrowid
        resumen["estado"] = "pendiente_aprobacion_jefe"
        return ToolResult(tool=name, ok=True, data=resumen)
    except ValidationError as exc:
        err = exc.errors()[0]
        return ToolResult(tool=name, ok=False, error=f"Parámetro inválido ({err['loc'][0]}): {err['msg']}")
    except (ToolError, sqlite3.Error) as exc:
        return ToolResult(tool=name, ok=False, error=str(exc))


TOOLS = {
    "consultar_saldo_vacaciones": consultar_saldo_vacaciones,
    "calcular_prestaciones": calcular_prestaciones,
    "registrar_solicitud_vacaciones": registrar_solicitud_vacaciones,
}
CRITICAL_TOOLS = {"registrar_solicitud_vacaciones"}
