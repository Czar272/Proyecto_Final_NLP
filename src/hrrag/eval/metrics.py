"""Métricas de recuperación, respuesta y operación."""
from __future__ import annotations

import re
import unicodedata

import numpy as np

CLARIFY_RE = re.compile(r"(aclar|especific|te refieres|podr[ií]a referirse|podr[ií]as indicar|ambig|"
                        r"depende de|varias interpretaciones|m[aá]s detalle|a qu[eé] (tipo|plazo|d[ií]as))",
                        re.IGNORECASE)
DENY_RE = re.compile(r"(denegad|no (puedo|es posible)|no se (encuentra|dispone)|no dispongo|no tengo (acceso|permiso)|no encontr|no hay (informaci|evidencia)|"
                     r"no (se )?(menciona|establece|indica|contiene|existe)|no est[aá] (establecid|contemplad))",
                     re.IGNORECASE)


def norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def relevant_pairs(case: dict) -> set[tuple[str, int]]:
    return set(zip(case.get("expected_sources", []), case.get("expected_pages", [])))


def chunk_pair(chunk_id: str, id_to_meta: dict) -> tuple[str, int]:
    m = id_to_meta[chunk_id]
    return (m["source"], m["page"])


def retrieval_metrics(ranked_ids: list[str], case: dict, id_to_meta: dict, k: int = 5) -> dict | None:
    rel = relevant_pairs(case)
    if not rel:
        return None
    pairs = [chunk_pair(cid, id_to_meta) for cid in ranked_ids]
    top = pairs[:k]
    found = {p for p in top if p in rel}
    rr = 0.0
    for pos, p in enumerate(pairs, start=1):
        if p in rel:
            rr = 1.0 / pos
            break
    relevant_in_top = sum(1 for p in top if p in rel)
    return {
        f"recall@{k}": len(found) / len(rel),
        "recall@1": len({p for p in pairs[:1] if p in rel}) / len(rel),
        "recall@3": len({p for p in pairs[:3] if p in rel}) / len(rel),
        "mrr": rr,
        f"precision@{k}": relevant_in_top / max(len(top), 1),
        "noise": 1 - relevant_in_top / max(len(top), 1),
        "redundancy": 1 - len(set(top)) / max(len(top), 1),
    }


def keyword_coverage(answer: str, keywords: list[str]) -> float | None:
    if not keywords:
        return None
    a = norm(answer)
    return sum(1 for k in keywords if norm(k) in a) / len(keywords)


def citation_precision(sources: list[dict], case: dict) -> float | None:
    rel = relevant_pairs(case)
    if not sources or not rel:
        return None
    hits = sum(1 for s in sources if (s["source"], s["page"]) in rel)
    return hits / len(sources)


def behavior_pass(case: dict, resp: dict, extra: dict | None = None) -> bool:
    beh = case["expected_behavior"]
    kw = keyword_coverage(resp["answer"], case.get("expected_keywords", []))
    forbidden = set(case.get("forbidden_sources", []))
    if forbidden and any(s["source"] in forbidden for s in resp["sources"]):
        return False
    if beh == "responder":
        ok = not resp["abstained"] and (kw is None or kw >= 0.5) and bool(resp["sources"])
        if "expected_tool" in case:
            ok = ok and resp["tool_used"] == case["expected_tool"]
        return ok
    if beh == "abstener":
        return resp["abstained"] or bool(DENY_RE.search(resp["answer"]))
    if beh == "aclarar":
        return resp["needs_human_review"] or bool(CLARIFY_RE.search(resp["answer"]))
    if beh == "herramienta":
        return resp["tool_used"] == case["expected_tool"] and (kw is None or kw >= 0.5)
    if beh == "confirmacion":
        return resp["tool_used"] == case["expected_tool"] and resp["needs_human_review"] and \
            not (extra or {}).get("db_write", False)
    if beh == "error_controlado":
        return resp["needs_human_review"] and (kw is None or kw > 0)
    return False


def latency_stats(latencies: list[float]) -> dict:
    if not latencies:
        return {"mean_s": None, "p95_s": None}
    arr = np.array(latencies)
    return {"mean_s": round(float(arr.mean()), 3), "p50_s": round(float(np.percentile(arr, 50)), 3),
            "p95_s": round(float(np.percentile(arr, 95)), 3), "max_s": round(float(arr.max()), 3)}


def mean(values: list) -> float | None:
    vals = [v for v in values if v is not None]
    return round(float(np.mean(vals)), 4) if vals else None
