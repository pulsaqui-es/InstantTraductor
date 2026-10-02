"""Modo directo (US1, T031): lo que suena en el PC, hablado en español por los auriculares.

Arranque (≤ 60 s, SC-010):
1. motores (``Engines``): voz, traducción, VAD y ASR;
2. autotest contra la realimentación (ADR-0010; si falla, código 4);
3. reloj de sesión, captura, sink y pipeline.

Parada (≤ 2 s, FR-015): último muestreo de memoria → pipeline → hijos en paralelo → informe.
Los fallos de un hijo se reintentan una vez (FR-018); si el reinicio falla, la sesión se detiene.

Los dispositivos (captura, reproducción, autotest y monitor de eco) llegan por ``LiveDevices`` y los
motores por ``Engines``: en el PC, ``WasapiDevices`` y ``RealEngines``; en los tests, dobles (T033).
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from instanttraductor.audio.agc import AutoGain
from instanttraductor.config import AppPaths, Settings
from instanttraductor.contracts import AudioSink, AudioSource, Clock
from instanttraductor.metrics.report import build_report, write_report
from instanttraductor.pipeline.clock import SessionClock
from instanttraductor.pipeline.engines import Engines, RealEngines, RecoveryLoop
from instanttraductor.pipeline.segmenter import PauseClauseSegmenter
from instanttraductor.pipeline.session import (
    EXIT_ERROR,
    EXIT_SELFTEST,
    Pipeline,
    PipelineParts,
    SessionError,
    Warnings,
    make_scheduler_and_recorder,
    report_components,
    report_dir_for,
    session_id_for,
)
from instanttraductor.ui.terminal import StatusSnapshot

logger = logging.getLogger(__name__)


class LiveDevices(Protocol):
    """Los dispositivos de audio del modo directo."""

    def selftest(self) -> float:
        """Autotest contra la realimentación: devuelve el umbral del monitor de eco.

        Si falla, lanza ``SessionError`` con el código 4.
        """
        ...

    def echo_monitor(self, threshold: float, warnings: Warnings) -> Any:
        """Monitor de eco: ``feed_captured(chunk, arrival)``, ``feed_played(...)`` y ``echo_events``."""
        ...

    def sink(self, clock: Clock, warnings: Warnings, echo: Any) -> AudioSink: ...

    def source(
        self, clock: Clock, *, on_reopen: Callable[[], None], on_warning: Callable[[str], None]
    ) -> AudioSource: ...


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
        engines: Engines | None = None,
        devices: LiveDevices | None = None,
        clock_factory: Callable[[], Clock] = SessionClock,
    ) -> None:
        self.settings = settings
        self.paths = paths or AppPaths()
        self._report_dir = report_dir
        self._on_status = on_status
        self._progress = on_progress or (lambda text: logger.info(text))
        self._engines = (
            engines
            if engines is not None
            else RealEngines(
                self.paths,
                language=settings.source_language,
                max_segment_s=settings.max_untranslated_s,
                on_progress=self._progress,
            )
        )
        self._devices = devices if devices is not None else WasapiDevices(capture_app=settings.capture_app)
        self._clock_factory = clock_factory
        self._pipeline: Pipeline | None = None
        self._fatal: SessionError | None = None
        self._started_at = datetime.now().astimezone()

    # --- arranque --------------------------------------------------------------
    def start(self) -> None:
        t0 = time.perf_counter()
        settings = self.settings
        self._engines.start()  # lanza SessionError y deja los hijos parados si falla
        sink: AudioSink | None = None
        source: AudioSource | None = None
        try:
            self._progress("Comprobando que no se oye a sí mismo…")
            threshold = self._devices.selftest()

            clock = self._clock_factory()
            warnings = Warnings(clock)
            echo = self._devices.echo_monitor(threshold, warnings)
            sink = self._devices.sink(clock, warnings, echo)
            translator = self._engines.translator(clock)
            scheduler, recorder = make_scheduler_and_recorder(
                clock, sink, translator, settings, on_record=warnings.on_record
            )
            source = self._devices.source(clock, on_reopen=self._on_capture_reopen, on_warning=warnings.add)
            save_path = self._report_path() / "audio_captado.wav" if settings.save_audio else None
            parts = PipelineParts(
                clock=clock,
                source=source,
                vad=self._engines.vad(),
                asr=self._engines.asr(clock),
                segmenter=PauseClauseSegmenter(clock, max_untranslated_s=settings.max_untranslated_s),
                translator=translator,
                synthesizer=self._engines.synthesizer(),
                sink=sink,
                scheduler=scheduler,
                recorder=recorder,
                agc=AutoGain(),
                echo_monitor=echo,
                on_status=self._on_status,
                child_pids=self._engines.child_pids,
                save_audio_path=save_path,
                language_verifier=self._engines.language_verifier(),
            )
            sink.start(scheduler.on_playback_event)
            sink.set_volume(settings.voice_volume)
            source.start()
            recorder.set_startup_s(time.perf_counter() - t0)
            recorder.set_mt_model(self._engines.mt_model_name)
            self._pipeline = Pipeline(parts, warnings=warnings)
            self._pipeline.start()
            self._progress("Escuchando.")
        except BaseException as error:
            if self._pipeline is not None:
                self._pipeline.stop()
                self._pipeline = None
            for part in (
                source,
                sink,
            ):  # si falla antes de existir el pipeline, el dispositivo quedaba abierto
                if part is not None:
                    with contextlib.suppress(Exception):
                        part.stop()
            self._engines.stop()
            if isinstance(error, SessionError | KeyboardInterrupt):
                raise
            raise SessionError(f"No se pudo arrancar: {error}", exit_code=EXIT_ERROR) from error

    # --- en marcha ---------------------------------------------------------------
    def run_until(self, stop_event: threading.Event) -> None:
        """Espera a ``stop_event`` (Ctrl+C o tecla q) atendiendo los fallos de los procesos hijos."""
        pipeline = self._pipeline
        assert pipeline is not None
        recovery = RecoveryLoop(
            self._engines,
            on_warning=pipeline.warnings.add,
            on_restart=pipeline.parts.recorder.count_component_restart,
        )
        recovery.start()
        try:
            while not stop_event.wait(0.2):
                if pipeline.stopped:
                    self._fatal = self._fatal or SessionError(
                        "Error interno del pipeline: " + "; ".join(pipeline.errors), exit_code=EXIT_ERROR
                    )
                if self._fatal is None and recovery.fatal is not None:
                    self._fatal = SessionError(recovery.fatal, exit_code=EXIT_ERROR)
                if self._fatal is not None:
                    return
        finally:
            recovery.stop()

    def set_volume(self, gain: float) -> None:
        if self._pipeline is not None:
            self._pipeline.parts.sink.set_volume(gain)

    @property
    def fatal_error(self) -> SessionError | None:
        return self._fatal

    def _on_capture_reopen(self) -> None:
        """ADR-0010: tras reabrir la captura se repite el autotest, en otro hilo (el callback vuelve ya)."""

        def check() -> None:
            try:
                self._devices.selftest()
            except SessionError as error:
                self._fatal = error
            except Exception as error:
                self._fatal = SessionError(
                    f"Falla el autotest tras reabrir la captura: {error}", exit_code=EXIT_SELFTEST
                )

        threading.Thread(target=check, name="autotest-reapertura", daemon=True).start()

    # --- parada --------------------------------------------------------------------
    def stop(self) -> dict[str, Any] | None:
        """Parada en ≤ 2 s. Devuelve el informe (o None si la sesión no llegó a arrancar)."""
        pipeline = self._pipeline
        if pipeline is None:
            self._engines.stop()
            return None
        parts = pipeline.parts
        parts.recorder.sample_memory(parts.clock.now(), self._engines.child_pids(), force=True)
        underruns = getattr(parts.sink, "underruns", None)
        if underruns is not None:
            parts.recorder.set_underruns(int(underruns))
        pipeline.stop()
        self._engines.stop()
        report = build_report(
            parts.recorder,
            mode="directo",
            started_at=self._started_at,
            duration_s=parts.clock.now(),
            settings=self.settings,
            session_id=session_id_for(self._started_at),
            components=report_components(),
        )
        write_report(report, self._report_path())
        return report

    def _report_path(self) -> Path:
        if self._report_dir is not None:
            return self._report_dir / session_id_for(self._started_at)
        return report_dir_for(self.paths, session_id_for(self._started_at))


class WasapiDevices:
    """Los dispositivos reales: reproducción WASAPI, autotest y la captura *process loopback*.

    - `capture_app` vacío: todo el PC salvo la propia app (EXCLUDE, ADR-0010).
    - `capture_app` = ruta de un .exe: solo esa aplicación (INCLUDE, ADR-0012), con su vigilante que espera y
      reabre cuando la app se cierra o se reinicia. El autotest va con el cableado invertido: la captura de la
      app no debe oír nuestro tono y una INCLUDE propia sí (research.md de la 002, R5).
    """

    def __init__(
        self, *, capture_app: str = "", on_app_state: Callable[[str, str], None] | None = None
    ) -> None:
        self.capture_app = capture_app
        self._on_app_state = on_app_state

    def selftest(self) -> float:
        from instanttraductor.audio.selftest import run_echo_selftest
        from instanttraductor.audio.wasapi_capture import ProcessLoopbackSource
        from instanttraductor.audio.wasapi_playback import DeviceSink

        temp_clock = SessionClock()
        make_source = lambda include: ProcessLoopbackSource(temp_clock, include=include)  # noqa: E731
        if self.capture_app:
            from instanttraductor.audio.apps import resolve_root

            root = resolve_root(self.capture_app)
            if root is None:
                # La app aún no está abierta: no hay a quién probar. La lista ya oculta la propia app y sus
                # antepasados, que son los únicos casos en que la voz propia entraría en una INCLUDE.
                logger.info("Autotest omitido: la app elegida aún no está abierta (%s).", self.capture_app)
                return _default_echo_threshold()

            def make_source(include: bool) -> AudioSource:  # type: ignore[misc]
                if include:
                    return ProcessLoopbackSource(temp_clock, include=True)  # INCLUDE propia: debe oír el tono
                return ProcessLoopbackSource(temp_clock, include=True, target_pid=root.root_pid)

        temp_sink = DeviceSink(temp_clock)
        temp_sink.start(lambda event: None)  # sus eventos no van al planificador
        try:
            result = run_echo_selftest(temp_sink, make_source)
        finally:
            temp_sink.stop()
        if not result.ok:
            raise SessionError(
                f"Falla la comprobación contra la realimentación: {result.reason}", exit_code=EXIT_SELFTEST
            )
        return float(result.correlation_threshold)

    def echo_monitor(self, threshold: float, warnings: Warnings) -> Any:
        from instanttraductor.audio.echo_monitor import EchoMonitor

        # El aviso a la persona lo da el pipeline al ver crecer `echo_events`; aquí solo se registra.
        return EchoMonitor(threshold=threshold, on_echo=logger.warning)

    def sink(self, clock: Clock, warnings: Warnings, echo: Any) -> AudioSink:
        from instanttraductor.audio.wasapi_playback import DeviceSink

        return DeviceSink(clock, on_warning=warnings.add, on_rendered=echo.feed_played)

    def source(
        self, clock: Clock, *, on_reopen: Callable[[], None], on_warning: Callable[[str], None]
    ) -> AudioSource:
        if self.capture_app:
            from instanttraductor.audio.app_source import AppLoopbackSource

            def on_state(state: Any, name: str) -> None:
                if str(state) == "esperando":
                    on_warning(f"Esperando a que suene {name}…")
                if self._on_app_state is not None:
                    self._on_app_state(str(state), name)

            return AppLoopbackSource(clock, self.capture_app, on_state=on_state, on_warning=on_warning)
        from instanttraductor.audio.wasapi_capture import ProcessLoopbackSource

        return ProcessLoopbackSource(clock, on_reopen=on_reopen, on_warning=on_warning)


def _default_echo_threshold() -> float:
    from instanttraductor.audio.echo_monitor import DEFAULT_THRESHOLD

    return float(DEFAULT_THRESHOLD)
