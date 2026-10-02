"""Doble de síntesis de voz: `FakeSynthesizer`, un tono por palabra."""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np

from instanttraductor.contracts import SynthesisRequest, SynthesizedChunk, VoiceInfo

_SAMPLE_RATE = 24_000  # Hz, como Qwen3-TTS
_WORD_S = 0.05  # 50 ms de tono por palabra
_CHUNK_S = 0.1  # trozos de 100 ms
_TONE_HZ = 440.0
_AMPLITUDE = 0.3


class FakeSynthesizer:
    """`Synthesizer` que devuelve un tono senoidal de 50 ms por palabra a 24 kHz.

    - El audio sale en trozos de 100 ms; el último (con `is_last=True`) lleva el resto. Un texto sin
      palabras suena como una (50 ms), para que toda unidad tenga al menos un trozo con audio.
    - El tono es continuo: se genera entero y después se trocea.
    - `supports_speed=False` por defecto: `speed` se ignora y el núcleo aplica el time-stretch. Con
      `supports_speed=True`, el audio dura `1 / speed` de lo normal.
    - `list_voices()` devuelve tres voces de prueba (dos femeninas y una masculina).
    """

    name = "fake-tts"
    sample_rate = _SAMPLE_RATE

    def __init__(self, *, supports_speed: bool = False) -> None:
        self.supports_speed = supports_speed

    def synthesize(self, request: SynthesisRequest) -> Iterator[SynthesizedChunk]:
        words = max(1, len(request.text.split()))
        total = round(words * _WORD_S * _SAMPLE_RATE / (request.speed if self.supports_speed else 1.0))
        total = max(1, total)
        t = np.arange(total) / _SAMPLE_RATE
        tone = (_AMPLITUDE * np.sin(2 * np.pi * _TONE_HZ * t)).astype(np.float32)
        step = round(_CHUNK_S * _SAMPLE_RATE)
        for start in range(0, total, step):
            end = min(start + step, total)
            yield SynthesizedChunk(
                unit_id=request.unit_id,
                samples=tone[start:end].copy(),
                sample_rate=_SAMPLE_RATE,
                is_last=end == total,
            )

    def list_voices(self) -> tuple[VoiceInfo, ...]:
        return (
            VoiceInfo(
                "es-f-fake", "Voz femenina de prueba", "f", "doble de pruebas", "sin licencia: sintética"
            ),
            VoiceInfo(
                "es-f2-fake", "Segunda voz femenina", "f", "doble de pruebas", "sin licencia: sintética"
            ),
            VoiceInfo(
                "es-m-fake", "Voz masculina de prueba", "m", "doble de pruebas", "sin licencia: sintética"
            ),
        )

    def close(self) -> None:
        """No hay nada que liberar; es idempotente."""
