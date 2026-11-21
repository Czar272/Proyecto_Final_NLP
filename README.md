# Asistente RAG Agéntico de Recursos Humanos

Proyecto final CC3103 - Procesamiento de Lenguaje Natural (UVG, ciclo 2 2026).

Asistente para colaboradores de una empresa guatemalteca (ficticia: *Comercializadora Altiplano, S.A.*) que responde
consultas sobre políticas internas de Recursos Humanos y el Código de Trabajo de Guatemala **con citas verificables
(fuente, página, chunk_id y versión)**, se **abstiene** cuando no hay evidencia, usa **herramientas** para datos exactos
(saldo de vacaciones en SQL, cálculo de prestaciones) y exige **confirmación humana** para acciones críticas
(registrar solicitudes de vacaciones). Incluye guardrails contra inyección de instrucciones, control de acceso por rol,
validación de salidas y auditoría con PII enmascarada.

## Entregables

| Entregable | Ubicación |
|---|---|
| Documento técnico | [`docs/Informe Tecnico - Proyecto Final CC3103 - Pablo Lopez.pdf`](docs/) |
| Anteproyecto | [`docs/Anteproyecto - Proyecto Final CC3103 - Pablo Lopez.pdf`](docs/) |
| Presentación de apoyo | [`docs/Presentacion - Proyecto Final CC3103 - Pablo Lopez.pdf`](docs/) |
| Código fuente | `src/`, `scripts/`, `app/`, `tests/` |
| Dataset de evaluación | `data/eval/testset.jsonl`, `data/eval/security_cases.jsonl` |
| Resultados comparativos | `results/benchmark_latest.{md,json}`, `results/security_latest.{md,json}`, `results/iteracion1/` |


## Arquitectura

```
Flujo de consulta
Usuario (sesión: user_id + rol)
  -> [Guardrail de entrada] esquema Pydantic, longitud, normalización Unicode, detector de inyección, PII
  -> [Router de intención] reglas auditables + extracción determinista de parámetros
       ├─ consulta_documental ─> Expansión de consulta (glosario) -> Recuperación híbrida (BM25 + E5, RRF)
       │                           -> filtros rol/versión/cuarentena
       │                           -> reranking cross-encoder -> compuerta de permisos -> umbral de abstención
       ├─ saldo_vacaciones ────> consultar_saldo_vacaciones (SQLite, permiso por propietario)
       ├─ calculo_prestaciones > calcular_prestaciones (motor determinista con validación de rangos)
       └─ solicitud_vacaciones > registrar_solicitud_vacaciones (acción crítica: preparar -> confirmar)
  -> [Generación estructurada] LLM (Groq, JSON) con contexto delimitado y citas C1..Cn
  -> [Guardrail de salida] citas válidas, token canario, fuga de documentos restringidos,
                          cifras sin respaldo, PII -> AssistantResponse (Pydantic)
  -> Respuesta + traza de auditoría (logs/audit.jsonl)

Flujo de ingesta
data/sources.json (catálogo con gobernanza) -> carga (PDF/MD) -> extracción por página
  -> limpieza (encabezados, notas al pie, ligaduras, guiones) -> chunking por artículo/sección
  -> metadatos (source, page, chunk_id, version, status, allowed_roles, sensitivity, hash)
  -> cuarentena de fuentes no confiables/envenenadas -> índice BM25 + embeddings E5 (data/index/)
```

| Componente | Archivo |
|---|---|
| Catálogo de fuentes y permisos | `data/sources.json` |
| Ingesta | `src/hrrag/ingest/` (`loader`, `cleaner`, `chunker`, `pipeline`) |
| Recuperación | `src/hrrag/retrieval/retriever.py` |
| Generación | `src/hrrag/generation/` |
| Router, herramientas y orquestador | `src/hrrag/agent/` |
| Guardrails y auditoría | `src/hrrag/security/` |
| Métricas | `src/hrrag/eval/metrics.py` |
| Contrato de salida | `src/hrrag/schemas.py` (`AssistantResponse`) |

## Instalación

Requisitos: Python 3.11, ~2 GB de disco para modelos (se descargan de Hugging Face la primera vez).

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   |   Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # completar GROQ_API_KEY (https://console.groq.com/keys)
```

Sin `GROQ_API_KEY` el sistema funciona en **modo extractivo** (degradación controlada): devuelve el fragmento más
relevante citado y marca la respuesta para revisión humana.

## Uso

```bash
python scripts/seed_db.py                       # base SQLite sintética de nómina
python scripts/ingest.py                        # pipeline de ingesta + índices (BM25 y embeddings)
python scripts/ask.py "¿Cuántos días de vacaciones me corresponden?" --user EMP-001 --role empleado
python scripts/ask.py "Quiero solicitar 3 días de vacaciones a partir del 2026-12-21" --confirm
streamlit run app/streamlit_app.py              # demo interactiva
```

Usuarios ficticios: `EMP-001` (empleado), `EMP-002` (jefe), `EMP-003` (rrhh), `EMP-004`, `EMP-005` (empleados).

## Evaluación

```bash
python -m pytest -q tests                       # pruebas unitarias (sin red)
python scripts/benchmark.py --retrieval-only    # ablación de recuperación (sin LLM)
python scripts/benchmark.py --judge             # línea base vs. mejorado + LLM-as-a-judge
python scripts/security_suite.py                # suite adversaria
```

- `data/eval/testset.jsonl`: 27 casos (5 directas, 3 paráfrasis, 3 identificadores exactos, 3 compuestas,
  2 ambiguas, 2 sin respuesta, 2 de versión y 7 de herramientas: nominal, selección errónea, fuera de rango,
  confirmación humana, indisponibilidad y compuesta). Campos: `id, question, expected_behavior, expected_sources,
  expected_pages, answerable, risk_level` (+ `expected_keywords`, `expected_tool`, `forbidden_sources`).
- `data/eval/security_cases.jsonl`: 17 casos adversarios (inyección directa/indirecta/ofuscada, escalamiento de rol,
  evasión de permisos en documentos y herramientas, acciones críticas, alucinación forzada, PII en logs, salidas no
  conformes, fuga de prompt, citas inventadas, entradas fuera de especificación).
- Resultados: `results/benchmark_latest.{md,json}` y `results/security_latest.{md,json}`.

Fecha de referencia reproducible para las herramientas: `REFERENCE_DATE=2026-11-20` (la fijan los scripts de evaluación).

## Fuentes y gobernanza

| Fuente | Formato | Propietario | Versión | Estado | Sensibilidad | Roles |
|---|---|---|---|---|---|---|
| Código de Trabajo de Guatemala (Decreto 1441, ed. MINTRAB 2007) | PDF | MINTRAB / Congreso | 2007 | vigente | pública | todos |
| POL-RH-001 Reglamento Interior de Trabajo | MD | RRHH (ficticio) | 2026-01 | vigente | interna | todos |
| POL-RH-002 Vacaciones y Permisos | MD | RRHH (ficticio) | 2025-01 | derogado | interna | todos |
| POL-RH-002 Vacaciones y Permisos | MD | RRHH (ficticio) | 2026-01 | vigente | interna | todos |
| POL-RH-003 Teletrabajo | MD | RRHH (ficticio) | 2026-01 | vigente | interna | todos |
| POL-RH-004 Beneficios y Prestaciones | MD | RRHH (ficticio) | 2026-01 | vigente | interna | todos |
| POL-RH-005 Código de Ética | MD | Cumplimiento (ficticio) | 2026-01 | vigente | interna | todos |
| POL-RH-006 Bandas salariales y disciplina | MD | RRHH (ficticio) | 2026-01 | vigente | confidencial | rrhh |
| FORO-001 Publicación de foro | MD | desconocido | 2026-03 | no oficial | interna | cuarentena |

Las políticas internas, empleados y montos son **sintéticos** y fueron redactados por el equipo; no se usan datos
personales reales. El Código de Trabajo es una norma pública. Las credenciales se leen solo desde `.env` (ignorado por git).

## Estructura

```
app/            demo Streamlit
data/           catálogo, fuentes, banco de pruebas (index/ y hr.db se generan)
results/        reportes de benchmark y seguridad
scripts/        ingesta, base de datos, CLI, benchmark, suite adversaria
src/hrrag/      paquete principal
tests/          pruebas unitarias
```

## Referencias técnicas

- Lewis et al. (2020). *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks*. NeurIPS.
- Robertson & Zaragoza (2009). *The Probabilistic Relevance Framework: BM25 and Beyond*.
- Wang et al. (2024). *Multilingual E5 Text Embeddings: A Technical Report*. `intfloat/multilingual-e5-small`.
- Cormack, Clarke & Büttcher (2009). *Reciprocal Rank Fusion outperforms Condorcet and individual rank learning methods*. SIGIR.
- Nogueira & Cho (2019). *Passage Re-ranking with BERT*; Bonifacio et al. (2021) *mMARCO* (`cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`).
- Greshake et al. (2023). *Not what you've signed up for: Compromising Real-World LLM-Integrated Applications with Indirect Prompt Injection*.
- OWASP (2025). *Top 10 for LLM Applications*.
- Es et al. (2023). *RAGAS: Automated Evaluation of Retrieval Augmented Generation*.
- Librerías: sentence-transformers, rank_bm25, pypdf, pydantic, streamlit, requests. LLM generador: openai/gpt-oss-120b vía Groq API; juez: qwen/qwen3.8-27b.
