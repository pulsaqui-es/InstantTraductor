"""Modo archivo (US2, T037): un fichero de audio o vídeo en inglés → voz en español, textos e informe.

Usa los mismos motores y el mismo pipeline que el modo directo, **a ritmo real** (FR-021): ``FileSource``
entrega el audio según el reloj de sesión y ``TimelineSink`` «reproduce» sobre una pista según ese mismo
reloj. Así el retraso, la aceleración, el resumen y los descartes se comportan como en directo y las métricas
son comparables. Sin dispositivos de audio, autotest ni monitor de eco.

Uso: ``start()`` → ``run()`` → ``finish()`` (salidas e informe) o ``abort()`` (nada en disco). Las salidas se
escriben al final en una carpeta temporal que se mueve a su sitio (FR-022).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from instanttraductor.audio.agc import AutoGain
from instanttraductor.audio.file_outputs import write_outputs
from instanttraductor.audio.file_sink import TimelineSink
from instanttraductor.audio.file_source import FileSource, InputFileError, InputInfo, probe_input
from instanttraductor.config import AppPaths, Settings
from instanttraductor.contracts import Clock, EngineError
from instanttraductor.metrics.report import build_report, report_to_json, report_to_markdown
from instanttraductor.pipeline.clock import SessionClock
from instanttraductor.pipeline.engines import Engines, RealEngines, RecoveryLoop
from instanttraductor.pipeline.segmenter import PauseClauseSegmenter
from instanttraductor.pipeline.session import (
    EXIT_BAD_INPUT,
    EXIT_ERROR,
    EXIT_USAGE,
    Pipeline,
    PipelineParts,
    SessionError,
    Warnings,
    make_scheduler_and_recorder,
    report_components,
    session_id_for,
)

logger = logging.getLogger(__name__)

#: Cada cuánto mira ``run()`` si ha terminado (y avisa del progreso).
POLL_S = 0.2


def default_output_dir(input_path: Path) -> Path:
    """``<carpeta de ENTRADA>/<nombre>_es`` (contracts/cli.md)."""
    return input_path.parent / f"{input_path.stem}_es"


class FileSession:
    """Sesión del modo archivo."""

    def __init__(
        self,
        settings: Settings,
        input_path: Path,
        *,
        output_dir: Path | None = None,
        paths: AppPaths | None = None,
        engines: Engines | None = None,
        clock_factory: Callable[[], Clock] = SessionClock,
        on_progress: Callable[[str], None] | None = None,
    ) -> None:
        self.settings = settings
        self.input_path = Path(input_path)
        self.output_dir = Path(output_dir) if output_dir is not None else default_output_dir(self.input_path)
        self.paths = paths or AppPaths()
        self._progress = on_progress or (lambda text: logger.info(text))
        self._engines = (
            engines if engines is not None else RealEngines(self.paths, on_progress=self._progress)
        )
        self._clock_factory = clock_factory
        self._info: InputInfo | None = None
        self._pipeline: Pipeline | None = None
        self._sink: TimelineSink | None = None
        self._source: FileSource | None = None
        self._started_at = datetime.now().astimezone()

    @property
    def duration_s(self) -> float | None:
        return self._info.duration_s if self._info is not None else None

    def position_s(self) -> float:
        """Segundos de la entrada ya procesados (el reloj de sesión)."""
        return self._pipeline.parts.clock.now() if self._pipeline is not None else 0.0

    # --- arranque --------------------------------------------------------------
    def start(self) -> None:
        """Valida la entrada (código 5) antes de arrancar los motores, que tardan decenas de segundos."""
        t0 = time.perf_counter()
        self._info = _probe(self.input_path)
        _check_output_dir(self.output_dir)  # antes de procesar: no descubrirlo al final de una película
        self._engines.start()
        try:
            clock = self._clock_factory()
            warnings = Warnings(clock)
            # El volumen se aplica una sola vez, en la mezcla (write_outputs); la pista va a ganancia 1.
            sink = TimelineSink(clock, duration_s=self._info.duration_s)
            translator = self._engines.translator(clock)
            scheduler, recorder = make_scheduler_and_recorder(
                clock, sink, translator, self.settings, on_record=warnings.on_record
            )
            source = FileSource(clock, self.input_path)
            parts = PipelineParts(
                clock=clock,
                source=source,
                vad=self._engines.vad(),
                asr=self._engines.asr(clock),
                segmenter=PauseClauseSegmenter(clock, max_untranslated_s=self.settings.max_untranslated_s),
                translator=translator,
                synthesizer=self._engines.synthesizer(),
                sink=sink,
                scheduler=scheduler,
                recorder=recorder,
                agc=AutoGain(),
                child_pids=self._engines.child_pids,
            )
            self._sink, self._source = sink, source
            sink.start(scheduler.on_playback_event)
            source.start()
            recorder.set_startup_s(time.perf_counter() - t0)
            recorder.set_mt_model(self._engines.mt_model_name)
            self._pipeline = Pipeline(parts, warnings=warnings)
            self._pipeline.start()
            self._progress("Traduciendo el fichero a ritmo real…")
        except BaseException as error:
            self.abort()
            if isinstance(error, SessionError | KeyboardInterrupt):
                raise
            if isinstance(error, InputFileError):
                raise SessionError(
                    f"No se puede usar el fichero: {error}", exit_code=EXIT_BAD_INPUT
                ) from error
            raise SessionError(f"No se pudo arrancar: {error}", exit_code=EXIT_ERROR) from error

    # --- en marcha ---------------------------------------------------------------
    def run(
        self, cancel: threading.Event | None = None, *, on_tick: Callable[[float], None] | None = None
    ) -> bool:
        """Espera a que se haya traducido y pronunciado todo. Devuelve False si se canceló con ``cancel``.

        Lanza ``SessionError`` si el pipeline falla o un motor no se recupera (FR-018).
        """
        pipeline = self._pipeline
        assert pipeline is not None and self._sink is not None and self._source is not None
        wait = cancel if cancel is not None else threading.Event()
        recovery = RecoveryLoop(
            self._engines,
            on_warning=pipeline.warnings.add,
            on_restart=pipeline.parts.recorder.count_component_restart,
        )
        recovery.start()
        try:
            while not wait.wait(POLL_S):
                if on_tick is not None:
                    on_tick(pipeline.parts.clock.now())
                if pipeline.stopped:
                    errors = "; ".join(pipeline.errors)
                    raise SessionError(f"Error interno del pipeline: {errors}", exit_code=EXIT_ERROR)
                if recovery.fatal is not None:
                    raise SessionError(recovery.fatal, exit_code=EXIT_ERROR)
                if self._source.failure is not None:  # FR-022: nada de salidas de un fichero a medias
                    raise SessionError(
                        f"No se puede usar el fichero: {self._source.failure}", exit_code=EXIT_BAD_INPUT
                    )
                if self._source.exhausted and pipeline.drained() and self._sink.pending_seconds() == 0:
                    return True
            return False
        finally:
            recovery.stop()

    # --- final --------------------------------------------------------------------------
    def finish(self) -> dict[str, Any]:
        """Para todo, escribe las salidas y devuelve el informe. Si falla, no queda nada a medias (FR-022)."""
        pipeline, sink, info = self._pipeline, self._sink, self._info
        assert pipeline is not None and sink is not None and info is not None
        parts = pipeline.parts
        parts.recorder.sample_memory(parts.clock.now(), self._engines.child_pids(), force=True)
        duration = parts.clock.now()
        pipeline.stop()
        self._engines.stop()
        report = build_report(
            parts.recorder,
            mode="archivo",
            started_at=self._started_at,
            duration_s=duration,
            settings=self.settings,
            session_id=session_id_for(self._started_at),
            input_file=str(self.input_path),
            components=report_components(),
        )
        self._progress("Escribiendo las salidas…")
        try:
            write_outputs(
                self.output_dir,
                input_path=self.input_path,
                track_48k=sink.track(),
                records=parts.recorder.records,
                report_json=report_to_json(report),
                report_md=report_to_markdown(report),
                voice_volume=self.settings.voice_volume,
            )
        except InputFileError as error:
            raise SessionError(f"No se puede usar el fichero: {error}", exit_code=EXIT_BAD_INPUT) from error
        except (EngineError, OSError, ValueError) as error:
            raise SessionError(
                f"No se pudieron escribir las salidas: {error}", exit_code=EXIT_ERROR
            ) from error
        return report

    def abort(self) -> None:
        """Para todo sin escribir nada (idempotente)."""
        if self._pipeline is not None:
            self._pipeline.stop()
        else:
            for part in (self._source, self._sink):
                if part is not None:
                    part.stop()
        self._engines.stop()


def _probe(path: Path) -> InputInfo:
    try:
        return probe_input(path)
    except InputFileError as error:
        raise SessionError(f"No se puede usar el fichero: {error}", exit_code=EXIT_BAD_INPUT) from error
    except EngineError as error:
        raise SessionError(str(error), exit_code=EXIT_ERROR) from error


def _check_output_dir(path: Path) -> None:
    """La carpeta de salida debe ser una carpeta (o no existir) y poder crearse o escribirse."""
    if path.exists() and not path.is_dir():
        raise SessionError(f"La salida «{path}» es un fichero, no una carpeta.", exit_code=EXIT_USAGE)
    existing = path
    while not existing.exists() and existing != existing.parent:
        existing = existing.parent
    if not os.access(existing, os.W_OK):
        raise SessionError(f"No se puede escribir en «{existing}».", exit_code=EXIT_USAGE)
