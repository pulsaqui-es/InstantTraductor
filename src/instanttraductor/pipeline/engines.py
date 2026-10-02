"""Motores de una sesión: voz, traducción, VAD y ASR (comunes a los modos directo y archivo).

Arranque de ``RealEngines`` (parte de los ≤ 60 s de SC-010):
1. servicio de voz (proceso hijo) y, en paralelo, carga del VAD y del ASR;
2. elección del modelo de traducción según la VRAM libre y ``llama-server`` (ADR-0011);
3. calentamiento de la traducción (deja en la caché el prefijo fijo del *prompt*).

Fallos (FR-018): un hijo que falla se apunta desde su hilo de salud y ``recover()`` lo reinicia una vez;
si el reinicio falla, devuelve el motivo y la sesión se detiene.

Las sesiones reciben un ``Engines``: en el PC, ``RealEngines``; en los tests, dobles.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any, Protocol

from instanttraductor.config import AppPaths
from instanttraductor.contracts import (
    AsrEngine,
    Clock,
    EngineError,
    Synthesizer,
    TranslationMode,
    TranslationRequest,
    TranslationUnit,
    Translator,
    Vad,
)
from instanttraductor.pipeline.clock import SessionClock
from instanttraductor.pipeline.session import EXIT_ERROR, EXIT_REQUIREMENTS, SessionError
from instanttraductor.platform.children import stop_all

logger = logging.getLogger(__name__)


class Engines(Protocol):
    """Lo que una sesión necesita de los motores."""

    @property
    def mt_model_name(self) -> str:
        """Modelo de traducción elegido (para el informe)."""
        ...

    def start(self) -> None:
        """Arranca y deja todo listo. Lanza ``SessionError`` con el código de salida si no puede."""
        ...

    def vad(self) -> Vad: ...

    def asr(self, clock: Clock) -> AsrEngine: ...

    def translator(self, clock: Clock) -> Translator: ...

    def synthesizer(self) -> Synthesizer: ...

    def child_pids(self) -> list[int]:
        """PID de los procesos hijos vivos (memoria del informe)."""
        ...

    def recover(self, *, on_warning: Callable[[str], None], on_restart: Callable[[], None]) -> str | None:
        """Reinicia una vez los hijos caídos. Devuelve el motivo si alguno no se recupera (FR-018)."""
        ...

    def stop(self) -> None:
        """Para los hijos en paralelo (idempotente)."""
        ...


class RealEngines:
    """Los motores reales: servicio de voz y ``llama-server`` como hijos; VAD y ASR en este proceso."""

    def __init__(self, paths: AppPaths, *, on_progress: Callable[[str], None] | None = None) -> None:
        self._paths = paths
        self._progress = on_progress or (lambda text: logger.info(text))
        self._tts: Any = None
        self._llama: Any = None
        self._model: Any = None
        self._vad: Any = None
        self._recognizer: Any = None
        self._failed: list[tuple[Any, str]] = []
        self._lock = threading.Lock()

    @property
    def mt_model_name(self) -> str:
        return self._model.value if self._model is not None else ""

    # --- arranque --------------------------------------------------------------
    def start(self) -> None:
        # Importación diferida: los módulos de motores (onnxruntime, sherpa) pesan.
        from instanttraductor.mt.llama_server import LlamaServerProcess
        from instanttraductor.mt.selection import choose_mt_model, free_vram_mb, model_path
        from instanttraductor.tts.service_process import TtsServiceProcess

        try:
            self._progress("Arrancando la voz…")
            self._tts = TtsServiceProcess(
                voices_dir=self._paths.voices, models_dir=self._paths.models, on_failure=self._on_failure
            )
            self._tts.start()
            loaded: dict[str, Any] = {}
            loader = threading.Thread(
                target=_load_listening, args=(loaded,), name="carga-escucha", daemon=True
            )
            loader.start()
            self._tts.wait_ready()

            self._progress("Eligiendo el modelo de traducción según la memoria de la tarjeta…")
            try:
                model = choose_mt_model(free_vram_mb())
            except EngineError as error:
                raise SessionError(str(error), exit_code=EXIT_REQUIREMENTS) from error
            self._model = model
            self._progress(f"Arrancando la traducción ({model.value})…")
            self._llama = LlamaServerProcess(model_path(model), on_failure=self._on_failure)
            self._llama.start()
            self._llama.wait_ready()
            self._warm_translation()

            loader.join()
            if "error" in loaded:
                raise loaded["error"]
            self._vad, self._recognizer = loaded["vad"], loaded["recognizer"]
        except SessionError:
            self.stop()
            raise
        except EngineError as error:
            self.stop()
            raise SessionError(str(error), exit_code=EXIT_ERROR) from error
        except BaseException:
            self.stop()
            raise

    def _warm_translation(self) -> None:
        """Una traducción ficticia: deja en la caché de llama-server el prefijo fijo del prompt."""
        warm = self.translator(SessionClock())
        unit = TranslationUnit(
            unit_id=0, source_text="Hello there.", t_start=0.0, t_end=1.0, is_sentence_end=True, ready_at=0.0
        )
        try:
            warm.translate(
                TranslationRequest(unit=unit, context=(), glossary=(), mode=TranslationMode.NORMAL)
            )
        finally:
            close = getattr(warm, "close", None)
            if callable(close):
                close()

    # --- piezas ---------------------------------------------------------------------
    def vad(self) -> Vad:
        return self._vad  # type: ignore[no-any-return]

    def asr(self, clock: Clock) -> AsrEngine:
        from instanttraductor.asr.sherpa_streaming import NemotronStreamingAsr

        return NemotronStreamingAsr(clock, recognizer=self._recognizer)

    def translator(self, clock: Clock) -> Translator:
        from instanttraductor.mt.hymt2 import HyMt2Translator

        return HyMt2Translator(self._llama.base_url, self._model, clock=clock)

    def synthesizer(self) -> Synthesizer:
        return self._tts.synthesizer()  # type: ignore[no-any-return]

    def child_pids(self) -> list[int]:
        return [pid for pid in (getattr(p, "pid", None) for p in (self._tts, self._llama)) if pid]

    # --- fallos --------------------------------------------------------------------
    def _on_failure(self, child: Any, reason: str) -> None:
        with self._lock:
            self._failed.append((child, reason))

    def recover(self, *, on_warning: Callable[[str], None], on_restart: Callable[[], None]) -> str | None:
        with self._lock:
            failures, self._failed = self._failed, []
        for child, reason in failures:
            on_warning(f"Se ha caído un componente ({reason}); reiniciando…")
            if not child.restart_once():
                return f"No se pudo recuperar un componente: {reason}"
            on_restart()
        return None

    def stop(self) -> None:
        children = [p.child for p in (self._tts, self._llama) if p is not None]
        if children:
            stop_all(children, grace_s=1.0)


def _load_listening(out: dict[str, Any]) -> None:
    try:
        from instanttraductor.asr.sherpa_streaming import create_recognizer
        from instanttraductor.vad.silero import SileroVad

        out["vad"] = SileroVad()
        out["recognizer"] = create_recognizer()
    except Exception as error:  # se relanza en el hilo principal
        out["error"] = error


class RecoveryLoop:
    """Atiende ``engines.recover()`` en un hilo propio mientras la sesión está en marcha.

    Un reinicio espera a que el hijo vuelva a estar listo (decenas de segundos para la voz). Si se hiciera en
    el bucle de la sesión, la orden de parar (tecla ``q``) no se atendería hasta acabar (FR-015).
    """

    def __init__(
        self,
        engines: Engines,
        *,
        on_warning: Callable[[str], None],
        on_restart: Callable[[], None],
        period_s: float = 0.2,
    ) -> None:
        self._engines = engines
        self._on_warning = on_warning
        self._on_restart = on_restart
        self._period_s = period_s
        self._stop = threading.Event()
        self.fatal: str | None = None  # motivo, si un hijo no se pudo recuperar
        self._thread = threading.Thread(target=self._run, name="recuperacion", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        """No espera a un reinicio en curso: la parada de los hijos lo corta."""
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.wait(self._period_s):
            try:
                reason = self._engines.recover(on_warning=self._on_warning, on_restart=self._on_restart)
            except Exception as error:  # un fallo al reiniciar cuenta como no recuperado
                logger.exception("Fallo al recuperar un componente")
                reason = f"No se pudo recuperar un componente: {error}"
            if reason is not None:
                self.fatal = reason
                return
