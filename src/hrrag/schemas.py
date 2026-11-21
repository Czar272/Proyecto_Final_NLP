"""Contratos de datos del sistema (Pydantic)."""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Role(str, Enum):
    EMPLEADO = "empleado"
    JEFE = "jefe"
    RRHH = "rrhh"


class Chunk(BaseModel):
    """Fragmento indexado con metadatos mínimos de trazabilidad."""

    chunk_id: str
    text: str
    source: str
    doc_id: str
    title: str
    page: int
    page_label: Optional[str] = None
    version: str
    status: str
    section: Optional[str] = None
    allowed_roles: list[str]
    sensitivity: str
    hash: str
    trusted: bool = True
    quarantined: bool = False


class UserContext(BaseModel):
    """Identidad del usuario autenticado (entregada por el sistema, no por el texto de la pregunta)."""

    user_id: str = Field(pattern=r"^EMP-\d{3}$")
    role: Role


class QueryRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    question: str = Field(min_length=3, max_length=800)
    user: UserContext
    confirm_action: bool = False

    @field_validator("question")
    @classmethod
    def no_control_chars(cls, v: str) -> str:
        if any(ord(c) < 32 and c not in "\n\t\r" for c in v):
            raise ValueError("La pregunta contiene caracteres de control no permitidos")
        return v


class SourceRef(BaseModel):
    source: str
    page: int
    chunk_id: str
    version: Optional[str] = None


class AssistantResponse(BaseModel):
    """Formato contractual de salida del asistente."""

    answer: str = Field(min_length=1)
    sources: list[SourceRef] = Field(default_factory=list)
    abstained: bool
    tool_used: Optional[str] = None
    needs_human_review: bool
    intent: Optional[str] = None
    trace_id: Optional[str] = None


class RetrievedChunk(BaseModel):
    chunk: Chunk
    score: float
    rank: int
    stage: Literal["bm25", "dense", "hybrid", "rerank"] = "hybrid"


class ToolResult(BaseModel):
    tool: str
    ok: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    requires_confirmation: bool = False
