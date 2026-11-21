"""Cliente LLM (API compatible con OpenAI, proveedor Groq) con reintentos, límites y contabilidad de tokens."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

import requests

from ..config import settings


class LLMUnavailable(RuntimeError):
    """El servicio de inferencia no está disponible (sin credenciales, caída o límite de tasa)."""


@dataclass
class Usage:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    errors: int = 0
    latencies: list[float] = field(default_factory=list)

    def add(self, other: "Usage") -> None:
        self.calls += other.calls
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.errors += other.errors
        self.latencies.extend(other.latencies)

    @property
    def cost_usd(self) -> float:
        return (self.prompt_tokens * settings.price_in_per_m + self.completion_tokens * settings.price_out_per_m) / 1e6


class LLMClient:
    def __init__(self, model: str | None = None, provider: str | None = None):
        self.model = model or settings.groq_model
        self.provider = provider or settings.llm_provider
        self.usage = Usage()

    @property
    def available(self) -> bool:
        return self.provider == "groq" and bool(settings.groq_api_key)

    def chat(self, messages: list[dict], json_mode: bool = True, temperature: float = 0.0,
             max_tokens: int = 1200) -> str:
        if not self.available:
            raise LLMUnavailable("Proveedor LLM no configurado (GROQ_API_KEY vacío o LLM_PROVIDER=extractive)")
        payload = {"model": self.model, "messages": messages, "temperature": temperature,
                   "max_tokens": max_tokens}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if "gpt-oss" in self.model:
            # Modelo de razonamiento: esfuerzo bajo para acotar latencia y tokens
            payload["reasoning_effort"] = "low"
        headers = {"Authorization": f"Bearer {settings.groq_api_key}", "Content-Type": "application/json"}
        last_err = None
        for attempt in range(settings.llm_max_retries + 1):
            t0 = time.perf_counter()
            try:
                resp = requests.post(f"{settings.groq_base_url}/chat/completions", headers=headers,
                                     data=json.dumps(payload), timeout=settings.llm_timeout_s)
                if resp.status_code == 429 or resp.status_code >= 500:
                    last_err = f"HTTP {resp.status_code}"
                    wait = float(resp.headers.get("retry-after", 2 ** attempt * 2))
                    self.usage.errors += 1
                    time.sleep(min(wait, 20))
                    continue
                resp.raise_for_status()
                data = resp.json()
                self.usage.calls += 1
                self.usage.latencies.append(time.perf_counter() - t0)
                u = data.get("usage", {})
                self.usage.prompt_tokens += u.get("prompt_tokens", 0)
                self.usage.completion_tokens += u.get("completion_tokens", 0)
                return data["choices"][0]["message"]["content"]
            except requests.RequestException as exc:
                last_err = type(exc).__name__
                self.usage.errors += 1
                time.sleep(2 ** attempt)
        raise LLMUnavailable(f"Servicio LLM no disponible tras reintentos: {last_err}")
