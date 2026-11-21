"""Orquestador con estado explícito.

Usuario -> guardrails de entrada -> router -> herramientas / recuperación -> validación de permisos ->
evidencia -> generación estructurada -> guardrails de salida -> respuesta + trazabilidad.
"""
from __future__ import annotations

import sqlite3
import time
import uuid
from dataclasses import dataclass, field

from pydantic import ValidationError

from ..config import settings
from ..generation.generator import NO_EVIDENCE_MSG, GenerationResult, generate
from ..generation.llm import LLMClient
from ..retrieval.index import get_index
from ..retrieval.retriever import BASELINE, IMPROVED, RetrievalConfig, check_permissions, retrieve
from ..schemas import AssistantResponse, QueryRequest, RetrievedChunk, Role, SourceRef, ToolResult, UserContext
from ..security.audit import pseudonymize, write_audit
from ..security.guards import check_input, check_output
from ..security.patterns import mask_pii
from .router import RoutePlan, route
from .tools import CRITICAL_TOOLS, TOOLS

BLOCKED_MSG = ("No puedo procesar esta solicitud porque contiene instrucciones no permitidas o intenta "
               "modificar mis reglas de operación. Reformula tu consulta sobre políticas de Recursos Humanos.")
SAFE_FALLBACK = ("No es posible entregar una respuesta verificada para esta consulta. "
                 "El caso fue marcado para revisión de Recursos Humanos.")


@dataclass
class AgentState:
    trace_id: str
    request: QueryRequest
    plan: RoutePlan | None = None
    tool_results: list[ToolResult] = field(default_factory=list)
    retrieved: list[RetrievedChunk] = field(default_factory=list)
    retrieval_trace: dict = field(default_factory=dict)
    generation: GenerationResult | None = None
    events: list[str] = field(default_factory=list)
    guard_issues: list[str] = field(default_factory=list)
    timings: dict = field(default_factory=dict)


def _db_lookup(employee_id: str) -> dict | None:
    try:
        con = sqlite3.connect(f"file:{settings.db_path}?mode=ro", uri=True)
        row = con.execute("SELECT salario_base, fecha_ingreso FROM employees WHERE employee_id = ?",
                          (employee_id,)).fetchone()
        con.close()
        return {"salario_base": row[0], "fecha_ingreso": row[1]} if row else None
    except sqlite3.Error:
        return None


def _tool_text(tr: ToolResult) -> str:
    d = tr.data
    if not tr.ok:
        return f"No fue posible completar la operación ({tr.tool}): {tr.error}."
    if tr.tool == "consultar_saldo_vacaciones":
        detalle = "; ".join(f"período {p['periodo']}: {p['disponibles']} disponibles de {p['asignados']}"
                            for p in d["periodos"]) or "sin períodos registrados"
        txt = f"Según el sistema de nómina, tienes {d['dias_disponibles']} días de vacaciones disponibles ({detalle})."
        if d.get("dias_en_solicitudes_pendientes"):
            txt += f" Hay {d['dias_en_solicitudes_pendientes']} días en solicitudes pendientes de aprobación."
        return txt
    if tr.tool == "calcular_prestaciones":
        etiqueta = {"aguinaldo": "aguinaldo", "bono14": "Bono 14", "indemnizacion": "indemnización",
                    "vacaciones_proporcionales": "vacaciones proporcionales"}[d["tipo"]]
        return (f"Cálculo referencial de {etiqueta}: Q{d['monto_estimado_q']:,.2f} "
                f"({d['dias_computados']} días computados). Base: {d['base_legal']}. {d['nota']}")
    if tr.tool == "registrar_solicitud_vacaciones":
        if tr.requires_confirmation:
            return (f"Se preparó una solicitud de {d['dias']} días de vacaciones a partir del {d['fecha_inicio']} "
                    f"(saldo disponible: {d['saldo_disponible']} días). Esta es una acción que requiere tu "
                    "confirmación explícita: confirma para registrarla. Luego deberá aprobarla tu jefe inmediato.")
        return (f"Solicitud #{d['request_id']} registrada: {d['dias']} días desde el {d['fecha_inicio']}. "
                "Estado: pendiente de aprobación del jefe inmediato (POL-RH-002 v2026-01).")
    return str(d)


TOOL_LEGAL_BASIS = {
    "aguinaldo": ("POL-RH-004", "Aguinaldo"),
    "bono14": ("POL-RH-004", "Bono 14"),
    "indemnizacion": ("CT-GT-1441", "ARTÍCULO 82"),
    "vacaciones_proporcionales": ("CT-GT-1441", "ARTÍCULO 133"),
    "registrar_solicitud_vacaciones": ("POL-RH-002", "diez días hábiles"),
}


def _tool_sources(results: list[ToolResult]) -> list[SourceRef]:
    """Asocia cada resultado de herramienta con el fragmento normativo que fundamenta su regla."""
    index = get_index()
    refs: list[SourceRef] = []
    for tr in results:
        if not tr.ok:
            continue
        key = tr.data.get("tipo") if tr.tool == "calcular_prestaciones" else tr.tool
        basis = TOOL_LEGAL_BASIS.get(key)
        if not basis:
            continue
        for c in index.chunks:
            if c.doc_id == basis[0] and c.status == "vigente" and basis[1] in c.text:
                refs.append(SourceRef(source=c.source, page=c.page, chunk_id=c.chunk_id, version=c.version))
                break
    return refs


class HRAssistant:
    def __init__(self, llm: LLMClient | None = None, retrieval_cfg: RetrievalConfig = IMPROVED,
                 audit: bool = True):
        self.llm = llm or LLMClient()
        self.cfg = retrieval_cfg
        self.audit = audit

    # ------------------------------------------------------------------ pasos
    def _run_tools(self, st: AgentState) -> None:
        for n, (name, params) in enumerate(st.plan.tool_calls):
            if n >= settings.max_tool_calls:
                st.events.append("limite_herramientas_alcanzado")
                break
            fn = TOOLS.get(name)
            if fn is None:
                st.events.append(f"herramienta_desconocida:{name}")
                continue
            if name in CRITICAL_TOOLS:
                res = fn(params, st.request.user, confirmed=st.request.confirm_action)
            else:
                res = fn(params, st.request.user)
            st.tool_results.append(res)
            st.events.append(f"tool:{name}:{'ok' if res.ok else 'error'}")

    def _retrieve(self, st: AgentState) -> None:
        q, role = st.request.question, st.request.user.role
        results, tr = retrieve(q, role, self.cfg)
        allowed, denied = check_permissions(results, role) if self.cfg.access_filter else (results, 0)
        st.retrieved = allowed
        st.retrieval_trace = {"filters": tr.filters, "candidates": tr.candidates[:20],
                              "reranked": tr.reranked[:10], "denied_post_filter": denied,
                              "context": [r.chunk.chunk_id for r in allowed]}

    # ------------------------------------------------------------------ flujo principal
    def ask(self, question: str, user: UserContext, confirm_action: bool = False) -> tuple[AssistantResponse, dict]:
        t0 = time.perf_counter()
        trace_id = uuid.uuid4().hex[:12]
        llm_calls_before = self.llm.usage.calls
        tok_before = (self.llm.usage.prompt_tokens, self.llm.usage.completion_tokens)
        try:
            req = QueryRequest(question=question, user=user, confirm_action=confirm_action)
        except ValidationError as exc:
            resp = AssistantResponse(answer=f"Solicitud inválida: {exc.errors()[0]['msg']}", abstained=True,
                                     needs_human_review=False, intent="entrada_invalida", trace_id=trace_id)
            return resp, self._finish(None, resp, t0, ["entrada_invalida"], llm_calls_before, tok_before,
                                      question, user)
        st = AgentState(trace_id=trace_id, request=req)

        # 1. Guardrails de entrada
        gin = check_input(req.question)
        if not gin.allowed:
            st.guard_issues.extend(gin.reasons)
            resp = AssistantResponse(answer=BLOCKED_MSG, abstained=True, needs_human_review=True,
                                     intent="bloqueado_por_guardrail", trace_id=trace_id)
            return resp, self._finish(st, resp, t0, gin.reasons, llm_calls_before, tok_before)
        if gin.pii:
            st.events.append(f"pii_en_entrada:{','.join(gin.pii)}")

        # 2. Router
        st.plan = route(req.question, req.user, _db_lookup)
        st.events.append(f"intents:{','.join(st.plan.intents)}")

        # 3. Herramientas
        if st.plan.tool_calls:
            self._run_tools(st)

        tool_used = st.tool_results[0].tool if st.tool_results else None
        tool_text = " ".join(_tool_text(t) for t in st.tool_results) if st.tool_results else None
        needs_review = st.plan.legal_advice or any(t.requires_confirmation for t in st.tool_results)
        needs_review = needs_review or any(not t.ok for t in st.tool_results)

        # 4. Solo herramientas: respuesta determinista (sin LLM) para no alterar datos exactos
        if not st.plan.use_rag:
            resp = AssistantResponse(answer=tool_text or SAFE_FALLBACK, sources=_tool_sources(st.tool_results),
                                     abstained=False,
                                     tool_used=tool_used, needs_human_review=needs_review,
                                     intent=st.plan.primary, trace_id=trace_id)
            return resp, self._finish(st, resp, t0, [], llm_calls_before, tok_before)

        # 5. Recuperación + compuerta de abstención
        self._retrieve(st)
        top_score = st.retrieved[0].score if st.retrieved else None
        low_evidence = (not st.retrieved) or (self.cfg.rerank and top_score is not None
                                              and top_score < settings.abstain_rerank_threshold)
        if low_evidence and not st.tool_results:
            st.events.append("abstencion_por_baja_evidencia")
            resp = AssistantResponse(answer=NO_EVIDENCE_MSG, abstained=True, tool_used=None,
                                     needs_human_review=st.plan.legal_advice, intent=st.plan.primary,
                                     trace_id=trace_id)
            return resp, self._finish(st, resp, t0, [], llm_calls_before, tok_before)

        # 6. Generación estructurada
        context = [] if low_evidence else st.retrieved
        st.generation = generate(req.question, context, self.llm, tool_note=tool_text)
        gen = st.generation
        if gen.invalid_citations:
            st.guard_issues.append("citas_invalidas")
        st.events.append(f"generacion:{gen.mode}")

        # 7. Guardrails de salida
        index = get_index()
        restricted = [c for c in index.chunks if req.user.role.value not in c.allowed_roles]
        gout = check_output(gen.answer, context, st.tool_results, req.user.role, restricted,
                            bool(gen.sources), gen.abstained)
        st.guard_issues.extend(gout.issues)
        answer, abstained, sources = gout.answer, gen.abstained, list(gen.sources)
        for ref in _tool_sources(st.tool_results):
            if ref.chunk_id not in {s.chunk_id for s in sources}:
                sources.append(ref)
        if gout.force_abstain:
            answer, abstained, sources = SAFE_FALLBACK, True, []
        if abstained and not gout.force_abstain:
            sources = []
            if tool_text:
                answer = tool_text + " " + answer
        needs_review = needs_review or gen.needs_human_review or gout.needs_review or gen.mode != "llm"
        needs_review = needs_review or bool(gen.invalid_citations) or gout.force_abstain
        try:
            resp = AssistantResponse(answer=answer, sources=sources, abstained=abstained, tool_used=tool_used,
                                     needs_human_review=needs_review, intent=st.plan.primary, trace_id=trace_id)
        except ValidationError:
            resp = AssistantResponse(answer=SAFE_FALLBACK, abstained=True, needs_human_review=True,
                                     intent=st.plan.primary, trace_id=trace_id)
        return resp, self._finish(st, resp, t0, [], llm_calls_before, tok_before)

    def _finish(self, st: AgentState | None, resp: AssistantResponse, t0: float, extra: list[str],
                calls_before: int, tok_before: tuple[int, int], question: str | None = None,
                user: UserContext | None = None) -> dict:
        latency = time.perf_counter() - t0
        u = self.llm.usage
        trace = {
            "trace_id": resp.trace_id,
            "user": pseudonymize((st.request.user.user_id if st else user.user_id) if (st or user) else "anon"),
            "role": (st.request.user.role.value if st else (user.role.value if user else None)),
            "question": mask_pii(st.request.question if st else (question or "")),
            "intent": resp.intent,
            "plan": st.plan.__dict__ if st and st.plan else None,
            "tools": [t.model_dump() for t in st.tool_results] if st else [],
            "retrieval": st.retrieval_trace if st else {},
            "events": (st.events if st else []) + extra,
            "guard_issues": st.guard_issues if st else extra,
            "response": resp.model_dump(),
            "latency_s": round(latency, 3),
            "llm_calls": u.calls - calls_before,
            "prompt_tokens": u.prompt_tokens - tok_before[0],
            "completion_tokens": u.completion_tokens - tok_before[1],
        }
        if self.audit:
            write_audit(trace)
        return trace


def baseline_answer(question: str, role: Role, llm: LLMClient) -> tuple[AssistantResponse, dict]:
    """Línea base: BM25 top-5 sin filtros, prompt simple, sin herramientas ni guardrails."""
    t0 = time.perf_counter()
    calls, pt, ct = llm.usage.calls, llm.usage.prompt_tokens, llm.usage.completion_tokens
    results, tr = retrieve(question, role, BASELINE)
    gen = generate(question, results, llm, baseline=True)
    resp = AssistantResponse(answer=gen.answer, sources=gen.sources, abstained=gen.abstained, tool_used=None,
                             needs_human_review=gen.needs_human_review, intent="baseline")
    trace = {"retrieval": {"candidates": tr.candidates, "context": [r.chunk.chunk_id for r in results]},
             "latency_s": round(time.perf_counter() - t0, 3), "llm_calls": llm.usage.calls - calls,
             "prompt_tokens": llm.usage.prompt_tokens - pt, "completion_tokens": llm.usage.completion_tokens - ct,
             "events": [f"generacion:{gen.mode}"], "guard_issues": []}
    return resp, trace
