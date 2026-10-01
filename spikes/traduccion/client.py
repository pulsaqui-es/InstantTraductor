"""Cliente de ``llama-server`` (API compatible con OpenAI) con medición de tiempos.

Una petición se mide de dos formas:

- **Streaming**: tiempo hasta el primer token con contenido (``ttft_ms``) y tiempo
  hasta el final (``total_ms``).
- **Sin streaming**: tiempo de la petición completa (``total_ms``).

Además se guardan las cifras que informa el propio servidor (``timings``): milisegundos
de *prefill* y de generación y tokens por segundo.
"""

from __future__ import annotations

import json
import math
import socket
import time
from dataclasses import asdict, dataclass

import httpx

#: Parámetros de muestreo recomendados por la model card para 1.8B y 7B.
OFFICIAL_SAMPLING = {"temperature": 0.7, "top_p": 0.6, "top_k": 20, "repeat_penalty": 1.05}


@dataclass
class Result:
    text: str
    finish_reason: str | None
    prompt_tokens: int
    completion_tokens: int
    total_ms: float
    ttft_ms: float | None
    server_prompt_ms: float | None
    server_predicted_ms: float | None
    decode_tps: float | None
    prefill_tps: float | None
    stream: bool

    def as_dict(self) -> dict:
        return asdict(self)


def percentile(values: list[float], q: float) -> float:
    """Percentil ``q`` (0-100) con interpolación lineal (igual que numpy por defecto)."""
    if not values:
        return math.nan
    data = sorted(values)
    if len(data) == 1:
        return data[0]
    pos = (len(data) - 1) * q / 100.0
    lo = math.floor(pos)
    hi = math.ceil(pos)
    return data[lo] + (data[hi] - data[lo]) * (pos - lo)


def summarize(values: list[float]) -> dict:
    """Resumen estadístico de una lista de medidas."""
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "min": min(values),
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
        "max": max(values),
        "mean": sum(values) / len(values),
    }


class Translator:
    """Envoltorio mínimo sobre ``/v1/chat/completions`` con un cliente persistente."""

    def __init__(self, base_url: str, timeout: float = 60.0) -> None:
        self.base_url = base_url
        # TCP_NODELAY: sin él, el algoritmo de Nagle puede añadir decenas de ms.
        transport = httpx.HTTPTransport(
            socket_options=[(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)]
        )
        self.client = httpx.Client(base_url=base_url, timeout=timeout, transport=transport)

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> Translator:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def complete(
        self,
        prompt: str | list[dict],
        *,
        stream: bool,
        max_tokens: int,
        temperature: float = OFFICIAL_SAMPLING["temperature"],
        top_p: float = OFFICIAL_SAMPLING["top_p"],
        top_k: int = OFFICIAL_SAMPLING["top_k"],
        repeat_penalty: float = OFFICIAL_SAMPLING["repeat_penalty"],
        seed: int = 42,
        cache_prompt: bool = False,
    ) -> Result:
        """Pide una traducción.

        ``prompt`` puede ser un texto (se envía como único mensaje de usuario) o una lista
        de mensajes de chat (para dar el contexto como turnos previos).
        """
        messages = [{"role": "user", "content": prompt}] if isinstance(prompt, str) else prompt
        body: dict = {
            "messages": messages,
            "temperature": temperature,
            "top_p": top_p,
            "top_k": top_k,
            "repeat_penalty": repeat_penalty,
            "max_tokens": max_tokens,
            "seed": seed,
            "cache_prompt": cache_prompt,
            "stream": stream,
        }
        if stream:
            body["stream_options"] = {"include_usage": True}
        t0 = time.perf_counter()
        if stream:
            return self._stream(body, t0)
        resp = self.client.post("/v1/chat/completions", json=body)
        resp.raise_for_status()
        data = resp.json()
        total_ms = (time.perf_counter() - t0) * 1000
        choice = data["choices"][0]
        return self._result(
            text=choice["message"].get("content") or "",
            finish=choice.get("finish_reason"),
            usage=data.get("usage", {}),
            timings=data.get("timings", {}),
            total_ms=total_ms,
            ttft_ms=None,
            stream=False,
        )

    def _stream(self, body: dict, t0: float) -> Result:
        parts: list[str] = []
        ttft_ms: float | None = None
        finish: str | None = None
        usage: dict = {}
        timings: dict = {}
        with self.client.stream("POST", "/v1/chat/completions", json=body) as resp:
            resp.raise_for_status()
            for raw in resp.iter_lines():
                if not raw.startswith("data:"):
                    continue
                payload = raw[5:].strip()
                if payload == "[DONE]":
                    break
                chunk = json.loads(payload)
                usage = chunk.get("usage") or usage
                timings = chunk.get("timings") or timings
                for choice in chunk.get("choices", []):
                    piece = (choice.get("delta") or {}).get("content")
                    if piece:
                        if ttft_ms is None:
                            ttft_ms = (time.perf_counter() - t0) * 1000
                        parts.append(piece)
                    if choice.get("finish_reason"):
                        finish = choice["finish_reason"]
        total_ms = (time.perf_counter() - t0) * 1000
        return self._result("".join(parts), finish, usage, timings, total_ms, ttft_ms, True)

    @staticmethod
    def _result(
        text: str,
        finish: str | None,
        usage: dict,
        timings: dict,
        total_ms: float,
        ttft_ms: float | None,
        stream: bool,
    ) -> Result:
        return Result(
            text=text,
            finish_reason=finish,
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            total_ms=total_ms,
            ttft_ms=ttft_ms,
            server_prompt_ms=timings.get("prompt_ms"),
            server_predicted_ms=timings.get("predicted_ms"),
            decode_tps=timings.get("predicted_per_second"),
            prefill_tps=timings.get("prompt_per_second"),
            stream=stream,
        )
