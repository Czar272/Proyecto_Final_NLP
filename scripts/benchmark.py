"""Benchmark reproducible: ablación de recuperación y comparación línea base vs. sistema mejorado.

Uso:
    python scripts/benchmark.py                 # ablación de recuperación + respuestas de ambos sistemas
    python scripts/benchmark.py --retrieval-only
    python scripts/benchmark.py --judge         # agrega LLM-as-a-judge de fidelidad/relevancia
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("REFERENCE_DATE", "2026-11-20")

from hrrag.agent.orchestrator import HRAssistant, baseline_answer  # noqa: E402
from hrrag.config import settings  # noqa: E402
from hrrag.eval import metrics as M  # noqa: E402
from hrrag.generation.llm import LLMClient, LLMUnavailable  # noqa: E402
from hrrag.retrieval.index import get_index  # noqa: E402
from hrrag.retrieval.retriever import RetrievalConfig, retrieve  # noqa: E402
from hrrag.schemas import Role, UserContext  # noqa: E402
from seed_db import seed  # noqa: E402

ABLATIONS = {
    "bm25_sin_filtros (línea base)": RetrievalConfig(mode="bm25", rerank=False, access_filter=False,
                                                     version_filter=False, exclude_quarantined=False, expand=False),
    "bm25 + filtros": RetrievalConfig(mode="bm25", rerank=False, expand=False),
    "denso_e5 + filtros": RetrievalConfig(mode="dense", rerank=False, expand=False),
    "híbrido_rrf + filtros": RetrievalConfig(mode="hybrid", rerank=False, expand=False),
    "híbrido_rrf + filtros + rerank": RetrievalConfig(mode="hybrid", rerank=True, expand=False),
    "híbrido_rrf + filtros + rerank + expansión (mejorado)": RetrievalConfig(mode="hybrid", rerank=True),
}

JUDGE_PROMPT = """Eres un evaluador estricto. Dada una PREGUNTA, una RESPUESTA y la EVIDENCIA citada, devuelve JSON:
{"faithfulness": x, "relevance": y}
- faithfulness (0 a 1): proporción de afirmaciones de la respuesta respaldadas por la evidencia.
- relevance (0 a 1): qué tan bien la respuesta atiende la pregunta.
Solo JSON."""


def load_cases(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def count_requests() -> int:
    con = sqlite3.connect(settings.db_path)
    n = con.execute("SELECT COUNT(*) FROM vacation_requests").fetchone()[0]
    con.close()
    return n


def run_ablation(cases: list[dict], id_meta: dict) -> dict:
    out = {}
    for name, cfg in ABLATIONS.items():
        per_case, lat = [], []
        for c in cases:
            if not M.relevant_pairs(c):
                continue
            t0 = time.perf_counter()
            res, _ = retrieve(c["question"], Role(c["role"]), cfg)
            lat.append(time.perf_counter() - t0)
            m = M.retrieval_metrics([r.chunk.chunk_id for r in res], c, id_meta)
            per_case.append({"id": c["id"], **m})
        out[name] = {k: M.mean([p[k] for p in per_case]) for k in per_case[0] if k != "id"}
        out[name]["latency"] = M.latency_stats(lat)
        out[name]["per_case"] = per_case
        print(f"  {name}: recall@5={out[name]['recall@5']} mrr={out[name]['mrr']}")
    return out


def judge(client: LLMClient, question: str, answer: str, evidence: str) -> dict:
    try:
        raw = client.chat([{"role": "system", "content": JUDGE_PROMPT},
                           {"role": "user", "content": f"PREGUNTA: {question}\nRESPUESTA: {answer}\n"
                                                       f"EVIDENCIA:\n{evidence[:6000]}"}], max_tokens=60)
        d = json.loads(raw)
        return {"faithfulness": float(d.get("faithfulness")), "relevance": float(d.get("relevance"))}
    except (LLMUnavailable, ValueError, TypeError, json.JSONDecodeError):
        return {"faithfulness": None, "relevance": None}


def run_system(name: str, cases: list[dict], id_meta: dict, use_judge: bool, pause: float) -> dict:
    llm = LLMClient()
    judge_client = LLMClient(model=os.getenv("JUDGE_MODEL", "qwen/qwen3.8-27b")) if use_judge else None
    assistant = HRAssistant(llm=llm, audit=True)
    index = get_index()
    rows = []
    for c in cases:
        seed()
        old_env = {k: os.environ.get(k) for k in c.get("env", {})}
        os.environ.update(c.get("env", {}))
        before = count_requests()
        user = UserContext(user_id=c["user"], role=Role(c["role"]))
        try:
            if name == "baseline":
                resp, trace = baseline_answer(c["question"], user.role, llm)
            else:
                resp, trace = assistant.ask(c["question"], user, confirm_action=c.get("confirm", False))
        finally:
            for k, v in old_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        r = resp.model_dump()
        ctx_ids = trace.get("retrieval", {}).get("context", [])
        extra = {"db_write": count_requests() > before}
        row = {
            "id": c["id"], "category": c["category"], "question": c["question"], "response": r,
            "context_ids": ctx_ids, "latency_s": trace["latency_s"], "llm_calls": trace["llm_calls"],
            "prompt_tokens": trace["prompt_tokens"], "completion_tokens": trace["completion_tokens"],
            "events": trace.get("events", []), "guard_issues": trace.get("guard_issues", []),
            "retrieval": M.retrieval_metrics(ctx_ids, c, id_meta) if ctx_ids else None,
            "keyword_coverage": M.keyword_coverage(r["answer"], c.get("expected_keywords", [])),
            "citation_precision": M.citation_precision(r["sources"], c),
            "abstention_correct": r["abstained"] == (not c["answerable"]),
            "behavior_pass": M.behavior_pass(c, r, extra),
            "db_write": extra["db_write"],
        }
        if judge_client and not r["abstained"] and r["sources"]:
            ev = "\n".join(index.chunks[index.by_id[s["chunk_id"]]].text for s in r["sources"]
                           if s["chunk_id"] in index.by_id)
            row.update(judge(judge_client, c["question"], r["answer"], ev))
        rows.append(row)
        status = "OK " if row["behavior_pass"] else "FAIL"
        print(f"  [{name}] {c['id']} {status} abst={r['abstained']} tool={r['tool_used']} "
              f"rev={r['needs_human_review']} {trace['latency_s']}s")
        if pause:
            time.sleep(pause)
    return {"summary": summarize(rows, cases, llm.usage.errors), "rows": rows}


def summarize(rows: list[dict], cases: list[dict], llm_errors: int) -> dict:
    answerable_retr = [x["retrieval"] for x in rows if x["retrieval"]]
    summary = {
        "n_cases": len(rows),
        "behavior_accuracy": M.mean([float(x["behavior_pass"]) for x in rows]),
        "recall@5": M.mean([x["recall@5"] for x in answerable_retr]),
        "mrr": M.mean([x["mrr"] for x in answerable_retr]),
        "noise": M.mean([x["noise"] for x in answerable_retr]),
        "keyword_coverage": M.mean([x["keyword_coverage"] for x in rows]),
        "citation_precision": M.mean([x["citation_precision"] for x in rows]),
        "abstention_accuracy_unanswerable": M.mean(
            [float(x["response"]["abstained"]) for x, c in zip(rows, cases) if not c["answerable"]]),
        "false_abstention_rate": M.mean(
            [float(x["response"]["abstained"]) for x, c in zip(rows, cases)
             if c["answerable"] and c["expected_behavior"] == "responder"]),
        "faithfulness_judge": M.mean([x.get("faithfulness") for x in rows]),
        "relevance_judge": M.mean([x.get("relevance") for x in rows]),
        "latency": M.latency_stats([x["latency_s"] for x in rows]),
        "llm_calls": sum(x["llm_calls"] for x in rows),
        "prompt_tokens": sum(x["prompt_tokens"] for x in rows),
        "completion_tokens": sum(x["completion_tokens"] for x in rows),
        "refusal_rate_unanswerable": M.mean(
            [float(x["response"]["abstained"] or bool(M.DENY_RE.search(x["response"]["answer"])))
             for x, c in zip(rows, cases) if not c["answerable"]]),
        "confidential_citations_to_non_rrhh": sum(
            1 for x, c in zip(rows, cases) if c["role"] != "rrhh"
            and any("CONFIDENCIAL" in s["source"] for s in x["response"]["sources"])),
        "llm_errors_retries": llm_errors,
        "fallback_responses": sum(1 for x in rows if any("extractive" in e or "fallback" in e for e in x["events"])),
    }
    summary["est_cost_usd"] = round((summary["prompt_tokens"] * settings.price_in_per_m +
                                     summary["completion_tokens"] * settings.price_out_per_m) / 1e6, 5)
    summary["cost_per_query_usd"] = round(summary["est_cost_usd"] / max(len(rows), 1), 6)
    by_cat: dict[str, list] = {}
    for x in rows:
        by_cat.setdefault(x["category"], []).append(float(x["behavior_pass"]))
    summary["behavior_by_category"] = {k: M.mean(v) for k, v in by_cat.items()}
    return summary


def rescore(path: Path, cases: list[dict]) -> dict:
    """Recalcula métricas de respuesta sobre salidas guardadas (sin nuevas llamadas al LLM)."""
    report = json.loads(path.read_text(encoding="utf-8"))
    by_id = {c["id"]: c for c in cases}
    for name, sysrep in report.get("systems", {}).items():
        ordered = [by_id[r["id"]] for r in sysrep["rows"]]
        for r, c in zip(sysrep["rows"], ordered):
            resp = r["response"]
            r["keyword_coverage"] = M.keyword_coverage(resp["answer"], c.get("expected_keywords", []))
            r["citation_precision"] = M.citation_precision(resp["sources"], c)
            r["behavior_pass"] = M.behavior_pass(c, resp, {"db_write": r.get("db_write", False)})
        sysrep["summary"] = summarize(sysrep["rows"], ordered, sysrep["summary"].get("llm_errors_retries", 0))
    return report


def write_markdown(report: dict, path: Path) -> None:
    lines = [f"# Resultados del benchmark ({report['timestamp']})", "",
             f"Modelo LLM: `{report['llm_model']}` | Embeddings: `{report['embedding_model']}` | "
             f"Reranker: `{report['reranker_model']}`", "", "## Ablación de recuperación (casos con evidencia esperada)", "",
             "| Configuración | Recall@1 | Recall@3 | Recall@5 | MRR | Precision@5 | Ruido | Latencia media (s) |",
             "|---|---|---|---|---|---|---|---|"]
    for name, m in report.get("retrieval_ablation", {}).items():
        lines.append(f"| {name} | {m['recall@1']} | {m['recall@3']} | {m['recall@5']} | {m['mrr']} | "
                     f"{m['precision@5']} | {m['noise']} | {m['latency']['mean_s']} |")
    if "systems" in report:
        lines += ["", "## Línea base vs. sistema mejorado (extremo a extremo)", "",
                  "| Métrica | Línea base | Mejorado |", "|---|---|---|"]
        b, i = report["systems"]["baseline"]["summary"], report["systems"]["mejorado"]["summary"]
        for key in ["behavior_accuracy", "recall@5", "mrr", "noise", "keyword_coverage", "citation_precision",
                    "abstention_accuracy_unanswerable", "false_abstention_rate", "faithfulness_judge",
                    "relevance_judge", "llm_calls", "prompt_tokens", "completion_tokens", "est_cost_usd",
                    "cost_per_query_usd", "fallback_responses"]:
            lines.append(f"| {key} | {b.get(key)} | {i.get(key)} |")
        lines.append(f"| latencia media (s) | {b['latency']['mean_s']} | {i['latency']['mean_s']} |")
        lines.append(f"| latencia P95 (s) | {b['latency']['p95_s']} | {i['latency']['p95_s']} |")
        lines += ["", "### Exactitud de comportamiento por categoría", "", "| Categoría | Línea base | Mejorado |",
                  "|---|---|---|"]
        for cat in i["behavior_by_category"]:
            lines.append(f"| {cat} | {b['behavior_by_category'].get(cat)} | {i['behavior_by_category'][cat]} |")
        lines += ["", "### Detalle por caso (sistema mejorado)", "", "| ID | Categoría | Pasa | Abstuvo | Herramienta | "
                  "Revisión humana | Recall@5 | Citas OK | Latencia (s) |", "|---|---|---|---|---|---|---|---|---|"]
        for x in report["systems"]["mejorado"]["rows"]:
            r = x["response"]
            rec = x["retrieval"]["recall@5"] if x["retrieval"] else "-"
            lines.append(f"| {x['id']} | {x['category']} | {'✔' if x['behavior_pass'] else '✘'} | {r['abstained']} | "
                         f"{r['tool_used'] or '-'} | {r['needs_human_review']} | {rec} | "
                         f"{x['citation_precision'] if x['citation_precision'] is not None else '-'} | {x['latency_s']} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--retrieval-only", action="store_true")
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--rescore", action="store_true",
                    help="Recalcula métricas sobre results/benchmark_latest.json sin volver a consultar el LLM")
    ap.add_argument("--pause", type=float, default=float(os.getenv("BENCH_PAUSE", "2")),
                    help="Pausa entre casos para respetar límites de tasa de la API")
    ap.add_argument("--cases", default=str(ROOT / "data" / "eval" / "testset.jsonl"))
    args = ap.parse_args()

    cases = load_cases(Path(args.cases))
    if args.rescore:
        report = rescore(settings.results_dir / "benchmark_latest.json", cases)
        (settings.results_dir / "benchmark_latest.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        write_markdown(report, settings.results_dir / "benchmark_latest.md")
        print("Métricas recalculadas")
        return
    index = get_index()
    # Precalentamiento: carga de modelos fuera de la medición de latencia
    from hrrag.retrieval.models import get_embedder, get_reranker
    get_embedder(), get_reranker()
    retrieve("precalentamiento", Role.EMPLEADO)
    id_meta = {c.chunk_id: {"source": c.source, "page": c.page} for c in index.chunks}
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report = {"timestamp": ts, "llm_model": settings.groq_model, "embedding_model": settings.embedding_model,
              "reranker_model": settings.reranker_model, "n_cases": len(cases)}
    print("Ablación de recuperación...")
    report["retrieval_ablation"] = run_ablation(cases, id_meta)
    if not args.retrieval_only:
        report["systems"] = {}
        for name in ("baseline", "mejorado"):
            print(f"Sistema: {name}")
            report["systems"][name] = run_system(name, cases, id_meta, args.judge, args.pause)
    settings.results_dir.mkdir(exist_ok=True)
    (settings.results_dir / "benchmark_latest.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    write_markdown(report, settings.results_dir / "benchmark_latest.md")
    seed()
    print(f"Resultados en {settings.results_dir}")


if __name__ == "__main__":
    main()
