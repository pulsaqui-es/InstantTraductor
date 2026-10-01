"""Doble de los motores de una sesión (`Engines`): VAD, ASR, traducción y voz falsos, sin procesos hijos."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from instanttraductor.contracts import Clock, Synthesizer, Translator
from instanttraductor.pipeline.session import SessionError
from tests.fakes.fake_speech import FakeAsrEngine, FakeVad, ScriptedAsrEvent
from tests.fakes.fake_synthesis import FakeSynthesizer
from tests.fakes.fake_translation import FakeTranslator


class FakeEngines:
    """Implementa `pipeline.engines.Engines` con dobles.

    - `script`: guion del `FakeAsrEngine`.
    - `start_error`: si se da, `start()` lo lanza (p. ej. un `SessionError` con su código).
    - `failures`: fallos de hijos que `recover()` atiende de uno en uno: `(motivo, se_recupera)`.
    """

    mt_model_name = "fake-mt"

    def __init__(
        self,
        script: Sequence[ScriptedAsrEvent] = (),
        *,
        translator: Translator | None = None,
        synthesizer: Synthesizer | None = None,
        start_error: SessionError | None = None,
        failures: Sequence[tuple[str, bool]] = (),
    ) -> None:
        self._script = list(script)
        self._translator = translator or FakeTranslator(supports_concise=True)
        self._synthesizer = synthesizer or FakeSynthesizer()
        self._start_error = start_error
        self._failures = list(failures)
        self.started = False
        self.stopped = False
        self.restarts = 0

    def start(self) -> None:
        if self._start_error is not None:
            raise self._start_error
        self.started = True

    def vad(self) -> FakeVad:
        return FakeVad()

    def asr(self, clock: Clock) -> FakeAsrEngine:
        return FakeAsrEngine(self._script, clock=clock)

    def translator(self, clock: Clock) -> Translator:
        return self._translator

    def synthesizer(self) -> Synthesizer:
        return self._synthesizer

    def child_pids(self) -> list[int]:
        return []

    def recover(self, *, on_warning: Callable[[str], None], on_restart: Callable[[], None]) -> str | None:
        if not self._failures:
            return None
        reason, recovers = self._failures.pop(0)
        on_warning(f"Se ha caído un componente ({reason}); reiniciando…")
        if not recovers:
            return f"No se pudo recuperar un componente: {reason}"
        self.restarts += 1
        on_restart()
        return None

    def stop(self) -> None:
        self.stopped = True
