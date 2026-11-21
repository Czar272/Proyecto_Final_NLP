# Resultados del benchmark (20261120_193907)

Modelo LLM: `openai/gpt-oss-120b` | Embeddings: `intfloat/multilingual-e5-small` | Reranker: `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`

## Ablación de recuperación (casos con evidencia esperada)

| Configuración | Recall@1 | Recall@3 | Recall@5 | MRR | Precision@5 | Ruido | Latencia media (s) |
|---|---|---|---|---|---|---|---|
| bm25_sin_filtros (línea base) | 0.5 | 0.7895 | 0.8684 | 0.7237 | 0.3474 | 0.6526 | 0.002 |
| bm25 + filtros | 0.6579 | 0.8684 | 0.8684 | 0.8333 | 0.3579 | 0.6421 | 0.003 |
| denso_e5 + filtros | 0.5263 | 0.8158 | 0.8158 | 0.7281 | 0.3684 | 0.6316 | 0.089 |
| híbrido_rrf + filtros | 0.5526 | 0.7632 | 0.8158 | 0.7237 | 0.3895 | 0.6105 | 0.125 |
| híbrido_rrf + filtros + rerank | 0.7368 | 0.8947 | 0.9211 | 0.886 | 0.3895 | 0.6105 | 2.197 |
| híbrido_rrf + filtros + rerank + expansión (mejorado) | 0.7895 | 0.9474 | 0.9737 | 0.9386 | 0.4105 | 0.5895 | 0.943 |

## Línea base vs. sistema mejorado (extremo a extremo)

| Métrica | Línea base | Mejorado |
|---|---|---|
| behavior_accuracy | 0.6296 | 1.0 |
| recall@5 | 0.8684 | 0.9722 |
| mrr | 0.7237 | 0.9352 |
| noise | 0.6526 | 0.5778 |
| keyword_coverage | 0.7174 | 1.0 |
| citation_precision | 0.8824 | 0.9474 |
| abstention_accuracy_unanswerable | 0.0 | 1.0 |
| false_abstention_rate | 0.0588 | 0.0 |
| faithfulness_judge | 0.9348 | 0.9636 |
| relevance_judge | 0.9609 | 0.9682 |
| llm_calls | 27 | 21 |
| prompt_tokens | 27659 | 28442 |
| completion_tokens | 2945 | 2399 |
| est_cost_usd | 0.00592 | 0.00571 |
| cost_per_query_usd | 0.000219 | 0.000211 |
| fallback_responses | 0 | 1 |
| latencia media (s) | 2.711 | 4.743 |
| latencia P95 (s) | 6.876 | 9.93 |

### Exactitud de comportamiento por categoría

| Categoría | Línea base | Mejorado |
|---|---|---|
| directa | 1.0 | 1.0 |
| parafrasis | 0.3333 | 1.0 |
| lexica | 1.0 | 1.0 |
| compuesta | 1.0 | 1.0 |
| ambigua | 0.0 | 1.0 |
| sin_respuesta | 1.0 | 1.0 |
| version | 1.0 | 1.0 |
| herramienta_nominal | 0.0 | 1.0 |
| herramienta_seleccion | 1.0 | 1.0 |
| herramienta_rango | 0.0 | 1.0 |
| herramienta_confirmacion | 0.0 | 1.0 |
| herramienta_indisponible | 0.0 | 1.0 |
| herramienta_compuesta | 0.0 | 1.0 |

### Detalle por caso (sistema mejorado)

| ID | Categoría | Pasa | Abstuvo | Herramienta | Revisión humana | Recall@5 | Citas OK | Latencia (s) |
|---|---|---|---|---|---|---|---|---|
| D01 | directa | ✔ | False | - | True | 1.0 | 1.0 | 6.38 |
| D02 | directa | ✔ | False | - | False | 1.0 | 1.0 | 1.891 |
| D03 | directa | ✔ | False | - | False | 1.0 | 1.0 | 2.645 |
| D04 | directa | ✔ | False | - | False | 1.0 | 1.0 | 5.894 |
| D05 | directa | ✔ | False | - | False | 1.0 | 1.0 | 9.898 |
| P01 | parafrasis | ✔ | False | - | True | 1.0 | 0.5 | 8.033 |
| P02 | parafrasis | ✔ | False | - | False | 1.0 | 1.0 | 8.176 |
| P03 | parafrasis | ✔ | False | - | True | 0.5 | 1.0 | 9.586 |
| L01 | lexica | ✔ | False | - | False | 1.0 | 1.0 | 1.473 |
| L02 | lexica | ✔ | False | - | False | 1.0 | 1.0 | 1.643 |
| L03 | lexica | ✔ | False | - | False | 1.0 | 1.0 | 3.675 |
| M01 | compuesta | ✔ | False | - | True | 1.0 | 1.0 | 2.89 |
| M02 | compuesta | ✔ | False | - | False | 1.0 | 1.0 | 7.794 |
| M03 | compuesta | ✔ | False | - | True | 1.0 | 1.0 | 10.18 |
| A01 | ambigua | ✔ | False | - | True | - | - | 7.342 |
| A02 | ambigua | ✔ | False | - | True | - | - | 7.285 |
| N01 | sin_respuesta | ✔ | True | - | False | - | - | 7.056 |
| N02 | sin_respuesta | ✔ | True | - | False | - | - | 9.944 |
| V01 | version | ✔ | False | - | False | 1.0 | 1.0 | 6.701 |
| V02 | version | ✔ | False | - | False | 1.0 | 1.0 | 5.429 |
| T01 | herramienta_nominal | ✔ | False | consultar_saldo_vacaciones | False | - | - | 0.003 |
| T02 | herramienta_nominal | ✔ | False | calcular_prestaciones | False | - | 1.0 | 0.004 |
| T03 | herramienta_seleccion | ✔ | False | - | False | 1.0 | 0.5 | 1.951 |
| T04 | herramienta_rango | ✔ | False | calcular_prestaciones | True | - | - | 0.007 |
| T05 | herramienta_confirmacion | ✔ | False | registrar_solicitud_vacaciones | True | - | - | 0.003 |
| T06 | herramienta_indisponible | ✔ | False | consultar_saldo_vacaciones | True | - | - | 0.0 |
| T07 | herramienta_compuesta | ✔ | False | consultar_saldo_vacaciones | False | 1.0 | 1.0 | 2.166 |
