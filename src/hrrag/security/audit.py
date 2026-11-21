"""Registro de auditoría en JSONL con enmascaramiento de PII y seudonimización del usuario."""
from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from typing import Any

from ..config import settings
from .patterns import mask_pii

_lock = threading.Lock()


def pseudonymize(user_id: str) -> str:
    return "usr_" + hashlib.sha256(f"hrrag::{user_id}".encode()).hexdigest()[:10]


def _scrub(obj: Any) -> Any:
    if isinstance(obj, str):
        return mask_pii(obj)
    if isinstance(obj, dict):
        return {k: _scrub(v) for k, v in obj.items() if k not in ("salario_mensual", "salario_base")}
    if isinstance(obj, (list, tuple)):
        return [_scrub(x) for x in obj]
    return obj


def write_audit(record: dict, filename: str = "audit.jsonl") -> None:
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    rec = _scrub(record)
    rec["ts"] = datetime.now(timezone.utc).isoformat()
    with _lock, open(settings.log_dir / filename, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
