"""Doble de traducción: `FakeTranslator`, determinista y con latencia y fallos configurables."""

from __future__ import annotations

import threading
import time

from instanttraductor.contracts import (
    Clock,
    EngineError,
    TranslationMode,
    TranslationRequest,
    TranslationResult,
)
from instanttraductor.pipeline.clock import ManualClock


class FakeTranslator:
    """`Translator` determinista: `"ES: " + texto`.

    - **CONCISE** (solo si `supports_concise`): recorta a la mitad de las palabras del original (mínimo una),
      y el resultado lleva `mode=CONCISE`. Sin soporte, traduce normalmente y devuelve `mode=NORMAL`; en
      `calls` queda constancia de lo que se pidió, para comprobar que el planificador no pide resumir.
    - **Latencia** (`latency_s`): la traducción «tarda» ese tiempo en el reloj. Con un `ManualClock` lo
      adelanta (`advance`), sin esperar de verdad; con cualquier otro reloj, duerme con `time.sleep`.
      `started_at` y `finished_at` salen del reloj antes y después de esa espera.
    - **Fallos** (`fail_times`): las primeras `fail_times` llamadas lanzan `EngineError` (recuperable,
      `engine="fake-mt"`); las siguientes funcionan.
    - Registra en `calls` cada petición recibida, incluidas las que fallan.
    - `clock` por defecto es un `ManualClock` propio.
    """

    name = "fake-mt"

    def __init__(
        self,
        *,
        clock: Clock | None = None,
        supports_concise: bool = True,
        latency_s: float = 0.0,
        fail_times: int = 0,
    ) -> None:
        if latency_s < 0:
            raise ValueError("latency_s no puede ser negativa.")
        if fail_times < 0:
            raise ValueError("fail_times no puede ser negativo.")
        self._clock: Clock = clock if clock is not None else ManualClock()
        self.supports_concise = supports_concise
        self._latency_s = latency_s
        self._failures_left = fail_times
        self.calls: list[TranslationRequest] = []
        self._lock = threading.Lock()

    def translate(self, request: TranslationRequest) -> TranslationResult:
        with self._lock:
            self.calls.append(request)
            if self._failures_left > 0:
                self._failures_left -= 1
                raise EngineError("Fallo simulado del traductor.", engine=self.name)
        started_at = self._clock.now()
        self._wait(self._latency_s)
        finished_at = self._clock.now()

        mode = request.mode
        if mode is TranslationMode.CONCISE and not self.supports_concise:
            mode = TranslationMode.NORMAL
        words = request.unit.source_text.split()
        if mode is TranslationMode.CONCISE:
            words = words[: max(1, len(words) // 2)]
        return TranslationResult(
            unit_id=request.unit.unit_id,
            text="ES: " + " ".join(words),
            mode=mode,
            started_at=started_at,
            finished_at=finished_at,
        )

    def close(self) -> None:
        """No hay nada que liberar; es idempotente."""

    def _wait(self, seconds: float) -> None:
        if seconds <= 0:
            return
        if isinstance(self._clock, ManualClock):
            self._clock.advance(seconds)
        else:
            time.sleep(seconds)
