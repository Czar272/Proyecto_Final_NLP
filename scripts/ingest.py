"""Ejecuta el pipeline de ingesta completo y construye los índices léxico y vectorial."""
import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hrrag.ingest.pipeline import run_ingestion  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-embeddings", action="store_true", help="Solo índice léxico")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    manifest = run_ingestion(with_embeddings=not args.no_embeddings)
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
