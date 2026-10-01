"""Modo directo con las piezas reales (US1, T031).

Arranque (≤ 60 s, SC-010):
1. servicio de voz (proceso hijo) y, en paralelo, carga del VAD y del ASR;
2. elección del modelo de traducción según la VRAM libre y ``llama-server`` (ADR-0011);
3. calentamiento de la traducción;
4. autotest contra la realimentación (ADR-0010; si falla, código 4);
5. reloj de sesión, captura, sink y pipeline.

Parada (≤ 2 s, FR-015): último muestreo de memoria → pipeline → hijos en paralelo → informe.
Los fallos de un hijo se reintentan una vez (FR-018); si el reinicio falla, la sesión se detiene.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from instanttraductor.asr.sherpa_streaming import NemotronStreamingAsr, create_recognizer
from instanttraductor.audio.agc import AutoGain
from instanttraductor.audio.echo_monitor import EchoMonitor
from instanttraductor.audio.selftest import run_echo_selftest
from instanttraductor.audio.wasapi_capture import ProcessLoopbackSource
from instanttraductor.audio.wasapi_playback import DeviceSink
from instanttraductor.config import AppPaths, Settings
from instanttraductor.contracts import EngineError, TranslationMode, TranslationRequest, TranslationUnit
from instanttraductor.metrics.report import build_report, write_report
from instanttraductor.mt.hymt2 import HyMt2Translator
from instanttraductor.mt.llama_server import LlamaServerProcess
from instanttraductor.mt.selection import choose_mt_model, free_vram_mb, model_path
from instanttraductor.pipeline.clock import SessionClock
from instanttraductor.pipeline.segmenter import PauseClauseSegmenter
from instanttraductor.pipeline.session import (
    Pipeline,
    PipelineParts,
    SessionError,
    Warnings,
    make_scheduler_and_recorder,
    report_dir_for,
    session_id_for,
)
from instanttraductor.platform.children import stop_all
from instanttraductor.setup.manifest import COMPONENTS
from instanttraductor.tts.service_process import TtsServiceProcess
from instanttraductor.ui.terminal import StatusSnapshot
from instanttraductor.vad.silero import SileroVad

logger = logging.getLogger(__name__)

EXIT_SELFTEST = 4
EXIT_REQUIREMENTS = 6
EXIT_ERROR = 1


class LiveSession:
    """Sesión del modo directo. Uso: ``start()``, ``run_until(evento)``, ``stop()`` → informe."""

    def __init__(
        self,
        settings: Settings,
        *,
        paths: AppPaths | None = None,
        report_dir: Path | None = None,
        on_status: Callable[[StatusSnapshot], None] | None = None,
        on_progress: Callable[[str], None] | None = None,
    ) -> None:
        self.settings = settings
        self.paths = paths or AppPaths()
        self._report_dir = report_dir
        self._on_status = on_status
        self._progress = on_progress or (lambda text: logger.info(text))
        self._tts: TtsServiceProcess | None = None
        self._llama: LlamaServerProcess | None = None
        self._pipeline: Pipeline | None = None
        self._failed_children: list[tuple[Any, str]] = []
        self._failures_lock = threading.Lock()
        self._fatal: SessionError | None = None
        self._started_at = datetime.now().astimezone()
        self._mt_model = None

    # --- arranque --------------------------------------------------------------
    def start(self) -> None:
        t0 = time.perf_counter()
        settings = self.settings
        try:
            self._progress("Arrancando la voz…")
            self._tts = TtsServiceProcess(
                voices_dir=self.paths.voices, models_dir=self.paths.models, on_failure=self._on_child_failure
            )
            self._tts.start()
            loaded: dict[str, Any] = {}
            loader = threading.Thread(target=self._load_listening, args=(loaded,), name="carga-escucha")
            loader.start()
            self._tts.wait_ready()

            self._progress("Eligiendo el modelo de traducción según la memoria de la tarjeta…")
            try:
                model = choose_mt_model(free_vram_mb())
            except EngineError as error:
                raise SessionError(str(error), exit_code=EXIT_REQUIREMENTS) from error
            self._mt_model = model
            self._progress(f"Arrancando la traducción ({model.value})…")
            self._llama = LlamaServerProcess(model_path(model), on_failure=self._on_child_failure)
            self._llama.start()
            self._llama.wait_ready()
            self._warm_translation(model)

            loader.join()
            if "error" in loaded:
                raise loaded["error"]

            self._progress("Comprobando que no se oye a sí mismo…")
            threshold = self._selftest()

            clock = SessionClock()
            warnings = Warnings(clock)
            echo = _make_echo_monitor(threshold, warnings)
            sink = _make_device_sink(clock, warnings, echo)
            translator = HyMt2Translator(self._llama.base_url, model, clock=clock)
            scheduler, recorder = make_scheduler_and_recorder(
                clock, sink, translator, settings, on_record=warnings.on_record
            )
            source = ProcessLoopbackSource(clock, on_reopen=self._on_capture_reopen, on_warning=warnings.add)
            save_path = None
            if settings.save_audio:
                save_path = self._report_path() / "audio_captado.wav"
            parts = PipelineParts(
                clock=clock,
                source=source,
                vad=loaded["vad"],
                asr=NemotronStreamingAsr(clock, recognizer=loaded["recognizer"]),
                segmenter=PauseClauseSegmenter(clock, max_untranslated_s=settings.max_untranslated_s),
                translator=translator,
                synthesizer=self._tts.synthesizer(),
                sink=sink,
                scheduler=scheduler,
                recorder=recorder,
                agc=AutoGain(),
                echo_monitor=echo,
                on_status=self._on_status,
                child_pids=self._child_pids,
                save_audio_path=save_path,
            )
            sink.start(scheduler.on_playback_event)
            sink.set_volume(settings.voice_volume)
            source.start()
            recorder.set_startup_s(time.perf_counter() - t0)
            recorder.set_mt_model(model.value)
            self._pipeline = Pipeline(parts, warnings=warnings)
            self._pipeline.start()
            self._progress("Escuchando.")
        except SessionError:
            self._stop_children()
            raise
        except EngineError as error:
            self._stop_children()
            raise SessionError(str(error), exit_code=EXIT_ERROR) from error

    def _load_listening(self, out: dict[str, Any]) -> None:
        try:
            out["vad"] = SileroVad()
            out["recognizer"] = create_recognizer()
        except Exception as error:  # se relanza en el hilo principal
            out["error"] = error

    def _warm_translation(self, model: Any) -> None:
        """Una traducción ficticia: deja en la caché de llama-server el prefijo fijo del prompt."""
        assert self._llama is not None
        warm = HyMt2Translator(self._llama.base_url, model, clock=SessionClock())
        unit = TranslationUnit(
            unit_id=0, source_text="Hello there.", t_start=0.0, t_end=1.0, is_sentence_end=True, ready_at=0.0
        )
        try:
            warm.translate(
                TranslationRequest(unit=unit, context=(), glossary=(), mode=TranslationMode.NORMAL)
            )
        finally:
            warm.close()

    def _selftest(self) -> float:
        temp_clock = SessionClock()
        temp_sink = DeviceSink(temp_clock)
        try:
            result = run_echo_selftest(
                temp_sink, lambda include: ProcessLoopbackSource(temp_clock, include=include)
            )
        finally:
            temp_sink.stop()
        if not result.ok:
            raise SessionError(
                f"Falla la comprobación contra la realimentación: {result.reason}", exit_code=EXIT_SELFTEST
            )
        return result.correlation_threshold

    # --- en marcha ---------------------------------------------------------------
    def run_until(self, stop_event: threading.Event) -> None:
        """Espera a ``stop_event`` (Ctrl+C o tecla q) atendiendo los fallos de los procesos hijos."""
        assert self._pipeline is not None
        while not stop_event.wait(0.2):
            if self._pipeline.stopped:
                self._fatal = self._fatal or SessionError(
                    "Error interno del pipeline: " + "; ".join(self._pipeline.errors), exit_code=EXIT_ERROR
                )
            if self._fatal is not None:
                return
            self._handle_child_failures()

    def set_volume(self, gain: float) -> None:
        if self._pipeline is not None:
            self._pipeline.parts.sink.set_volume(gain)

    @property
    def fatal_error(self) -> SessionError | None:
        return self._fatal

    def _on_child_failure(self, child: Any, reason: str) -> None:
        with self._failures_lock:
            self._failed_children.append((child, reason))

    def _handle_child_failures(self) -> None:
        with self._failures_lock:
            failures, self._failed_children = self._failed_children, []
        for child, reason in failures:
            warnings = self._pipeline.warnings if self._pipeline else None
            if warnings is not None:
                warnings.add(f"Se ha caído un componente ({reason}); reiniciando…")
            if child.restart_once():
                if self._pipeline is not None:
                    self._pipeline.parts.recorder.count_component_restart()
            else:
                self._fatal = SessionError(
                    f"No se pudo recuperar un componente: {reason}", exit_code=EXIT_ERROR
                )

    def _on_capture_reopen(self) -> None:
        """ADR-0010: tras reabrir la captura se repite el autotest, en otro hilo (el callback vuelve ya)."""

        def check() -> None:
            try:
                self._selftest()
            except SessionError as error:
                self._fatal = error

        threading.Thread(target=check, name="autotest-reapertura", daemon=True).start()

    def _child_pids(self) -> list[int | None]:
        return [self._tts.pid if self._tts else None, self._llama.pid if self._llama else None]

    # --- parada --------------------------------------------------------------------
    def stop(self) -> dict[str, Any] | None:
        """Parada en ≤ 2 s. Devuelve el informe (o None si la sesión no llegó a arrancar)."""
        pipeline = self._pipeline
        if pipeline is None:
            self._stop_children()
            return None
        parts = pipeline.parts
        parts.recorder.sample_memory(
            parts.clock.now(), [pid for pid in self._child_pids() if pid], force=True
        )
        underruns = getattr(parts.sink, "underruns", None)
        if underruns is not None:
            parts.recorder.set_underruns(int(underruns))
        pipeline.stop()
        self._stop_children()
        report = build_report(
            parts.recorder,
            mode="directo",
            started_at=self._started_at,
            duration_s=parts.clock.now(),
            settings=self.settings,
            session_id=session_id_for(self._started_at),
            components=[c for c in COMPONENTS if not c.optional],
        )
        write_report(report, self._report_path())
        return report

    def _report_path(self) -> Path:
        if self._report_dir is not None:
            return self._report_dir / session_id_for(self._started_at)
        return report_dir_for(self.paths, session_id_for(self._started_at))

    def _stop_children(self) -> None:
        children = [p.child for p in (self._tts, self._llama) if p is not None]
        if children:
            stop_all(children, grace_s=1.0)


# --- piezas de la ola 2 (obrero D): constructores aislados para ajustar su API en un solo sitio ---
def _make_echo_monitor(threshold: float, warnings: Warnings) -> EchoMonitor:
    return EchoMonitor(threshold=threshold, on_echo=lambda: warnings.add("Eco: se oye la propia voz."))


def _make_device_sink(clock: SessionClock, warnings: Warnings, echo: EchoMonitor) -> DeviceSink:
    return DeviceSink(clock, on_warning=warnings.add, on_rendered=echo.feed_played)
