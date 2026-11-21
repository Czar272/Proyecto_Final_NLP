"""Configuración central leída desde variables de entorno (.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    root: Path = ROOT_DIR
    data_dir: Path = ROOT_DIR / "data"
    index_dir: Path = ROOT_DIR / "data" / "index"
    catalog_path: Path = ROOT_DIR / "data" / "sources.json"
    db_path: Path = ROOT_DIR / "data" / "hr.db"
    log_dir: Path = ROOT_DIR / "logs"
    results_dir: Path = ROOT_DIR / "results"

    llm_provider: str = os.getenv("LLM_PROVIDER", "groq")
    groq_api_key: str = field(default_factory=lambda: os.getenv("GROQ_API_KEY", ""), repr=False)
    groq_model: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    groq_base_url: str = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
    llm_timeout_s: int = _int("LLM_TIMEOUT_S", 30)
    llm_max_retries: int = _int("LLM_MAX_RETRIES", 2)

    embedding_model: str = os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-small")
    reranker_model: str = os.getenv("RERANKER_MODEL", "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1")

    chunk_max_chars: int = 1200
    chunk_overlap_chars: int = 150
    top_k_candidates: int = 20
    top_k_context: int = 5
    rrf_k: int = 60
    abstain_rerank_threshold: float = -2.0

    max_tool_calls: int = _int("MAX_TOOL_CALLS", 3)
    max_question_chars: int = _int("MAX_QUESTION_CHARS", 800)

    # Precios de referencia USD por millón de tokens (Groq, llama-3.3-70b-versatile)
    price_in_per_m: float = 0.59
    price_out_per_m: float = 0.79


settings = Settings()
