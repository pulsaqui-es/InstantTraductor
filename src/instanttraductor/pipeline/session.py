"""Sesiones de InstantTraductor: une todas las etapas del pipeline (T031; T037 añade el modo archivo).

Flujo (docs/arquitectura.md): captura → AGC → VAD + ASR → segmentador → planificador →
traducción → voz → time-stretch y remuestreo → sink. El planificador (``Scheduler``) es puramente
lógico; aquí viven los hilos que lo alimentan:

- **escucha**: lee la fuente, aplica el AGC, pasa el VAD y alimenta el ASR solo con habla
  (reproduciendo el relleno previo del VAD) y el segmentador en el orden START, parciales, END, FINAL;
- **traducción**: toma la siguiente petición del planificador y la traduce;
- **voz**: sintetiza **bajo demanda** (solo cuando al sink le queda poco audio, recomendación de
  T029) para que la velocidad y el modo lleguen a tiempo;
- **control**: ``scheduler.tick()`` 4 veces por segundo, estado para la interfaz y memoria.

``Pipeline`` recibe las piezas ya construidas (``PipelineParts``), así que los tests de extremo a
extremo usan dobles (T033). ``LiveSession`` construye las piezas reales del modo directo.
"""

from __future__ import annotations

import logging
import threading
import time
import wave
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue

import numpy as np

from instanttraductor.audio.agc import SOURCE_SILENCE_WARNING_S, AutoGain
from instanttraductor.audio.dsp import StreamResampler, StreamTimeStretch
from instanttraductor.config import AppPaths, Settings
from instanttraductor.contracts import (
    PLAYBACK_RATE,
    AsrEngine,
    AsrEvent,
    AudioChunk,
    AudioSink,
    AudioSource,
    Clock,
    DelayPolicy,
    EngineError,
    Outcome,
    Segmenter,
    SpeechPiece,
    SynthesisRequest,
    Synthesizer,
    TranslationUnit,
    Translator,
    UtteranceRecord,
    Vad,
    VadEvent,
    VadEventKind,
    VoiceRef,
)
from instanttraductor.metrics.recorder import MetricsRecorder
from instanttraductor.pipeline.delay import ThresholdDelayController
from instanttraductor.pipeline.scheduler import DROP_REASON_LAG, Scheduler
from instanttraductor.ui.terminal import StatusSnapshot

logger = logging.getLogger(__name__)

#: Audio que se guarda antes del inicio de voz para dárselo al ASR (≥ speech_pad_ms del VAD).
PRE_ROLL_S = 0.5
#: La voz solo sintetiza la frase siguiente cuando al sink le queda menos que esto (T029, nota 3).
TTS_LOOKAHEAD_S = 1.0
#: Periodo del hilo de control (``scheduler.tick()`` 4 veces por segundo).
TICK_S = 0.25
#: Cuánto tiempo se muestra un aviso en la interfaz.
WARNING_TTL_S = 6.0
#: Espera máxima al cerrar cada hilo durante la parada (el total debe quedar en ≤ 2 s).
JOIN_TIMEOUT_S = 0.4

#: Códigos de salida de contracts/cli.md que puede provocar una sesión.
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_SELFTEST = 4
EXIT_BAD_INPUT = 5
EXIT_REQUIREMENTS = 6


class SessionError(RuntimeError):
    """Error de la sesión con el código de salida que corresponde (contracts/cli.md)."""

    def __init__(self, message: str, *, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


@dataclass
class PipelineParts:
    """Piezas ya construidas que une el pipeline. Todas cumplen sus contratos."""

    clock: Clock
    source: AudioSource
    vad: Vad
    asr: AsrEngine
    segmenter: Segmenter
    translator: Translator
    synthesizer: Synthesizer
    sink: AudioSink
    scheduler: Scheduler
    recorder: MetricsRecorder
    agc: AutoGain | None = None
    #: Monitor de eco opcional: ``feed_captured(chunk, arrival)`` y ``echo_events``.
    echo_monitor: object | None = None
    #: Recibe el estado para la interfaz (desde el hilo de control).
    on_status: Callable[[StatusSnapshot], None] | None = None
    #: PID de los procesos hijos, para la memoria del informe.
    child_pids: Callable[[], Sequence[int | None]] = field(default=lambda: ())
    #: Si existe, se escribe aquí el audio captado (FR-030: solo si se pide).
    save_audio_path: Path | None = None


class Warnings:
    """Avisos recientes para la interfaz (cada uno se muestra unos segundos)."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._items: deque[tuple[float, str]] = deque(maxlen=20)

    def add(self, text: str) -> None:
        logger.warning(text)
        with self._lock:
            self._items.append((self._clock.now(), text))

    def current(self) -> tuple[str, ...]:
        now = self._clock.now()
        with self._lock:
            return tuple(dict.fromkeys(t for at, t in self._items if now - at <= WARNING_TTL_S))

    def on_record(self, record: UtteranceRecord) -> None:
        """Para ``Scheduler(on_record=...)``: avisa en la terminal de cada descarte por retraso (FR-014)."""
        if record.outcome is Outcome.DROPPED and record.reason == DROP_REASON_LAG:
            self.add("Retraso excesivo: se ha descartado una frase pendiente.")


class Pipeline:
    """Hilos del pipeline sobre unas ``PipelineParts``."""

    def __init__(
        self,
        parts: PipelineParts,
        *,
        warnings: Warnings | None = None,
        tts_lookahead_s: float = TTS_LOOKAHEAD_S,
    ) -> None:
        self.parts = parts
        self.tts_lookahead_s = tts_lookahead_s
        self.warnings = warnings if warnings is not None else Warnings(parts.clock)
        self._echo_seen = 0
        self.errors: list[str] = []
        self._stop = threading.Event()  # «hilos, parad»: lo pone stop() o un hilo que muere (_guard)
        self._closed = False  # stop() ya paró las piezas (su idempotencia no depende de _stop)
        self._work = threading.Event()  # despierta al hilo de traducción
        self._synth_queue: Queue[SynthesisRequest] = Queue()
        self._threads: list[threading.Thread] = []
        self._listening_done = threading.Event()
        self._last_source = None
        self._last_translation = None
        self._wav: wave.Wave_write | None = None

    # --- ciclo de vida -------------------------------------------------------
    def start(self) -> None:
        if self.parts.save_audio_path is not None:
            self.parts.save_audio_path.parent.mkdir(parents=True, exist_ok=True)
            self._wav = wave.open(str(self.parts.save_audio_path), "wb")  # noqa: SIM115 (se cierra en stop())
            self._wav.setnchannels(1)
            self._wav.setsampwidth(2)
            self._wav.setframerate(self.parts.source.sample_rate)
        for name, target in (
            ("escucha", self._listen_loop),
            ("traduccion", self._translate_loop),
            ("voz", self._voice_loop),
            ("control", self._control_loop),
        ):
            thread = threading.Thread(target=self._guard(target), name=f"pipeline-{name}", daemon=True)
            self._threads.append(thread)
            thread.start()

    def stop(self) -> None:
        """Parada rápida: corta lo que suena y descarta lo pendiente (idempotente).

        Para las piezas aunque un hilo ya haya puesto `_stop` al morir: si no, quedarían el sink sonando,
        la fuente abierta y las frases abiertas sin registro (FR-018).
        """
        if self._closed:
            return
        self._closed = True
        self._stop.set()
        self._work.set()
        self.parts.scheduler.stop()
        self.parts.sink.stop()
        self.parts.source.stop()
        for thread in self._threads:
            thread.join(JOIN_TIMEOUT_S)
        if self._wav is not None:
            self._wav.close()
            self._wav = None

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def drained(self) -> bool:
        """Fuente agotada, todo escuchado y ninguna frase abierta (modo archivo)."""
        return self._listening_done.is_set() and self.parts.scheduler.open_count == 0

    def _guard(self, target: Callable[[], None]) -> Callable[[], None]:
        def run() -> None:
            try:
                target()
            except Exception as error:  # un hilo que muere no debe dejar la app colgada
                logger.exception("Fallo inesperado en %s", threading.current_thread().name)
                self.errors.append(f"{threading.current_thread().name}: {error}")
                self.warnings.add(f"Error interno ({threading.current_thread().name}): {error}")
                self._stop.set()

        return run

    # --- escucha -------------------------------------------------------------
    def _listen_loop(self) -> None:
        parts = self.parts
        pre_roll: deque[AudioChunk] = deque()
        in_speech = False
        last_asr_at: float | None = None

        def feed_asr(chunk: AudioChunk) -> list[TranslationUnit]:
            nonlocal last_asr_at
            units: list[TranslationUnit] = []
            try:
                events = parts.asr.accept(chunk)
            except EngineError as error:
                self.warnings.add(f"Fallo del reconocimiento de voz: {error}")
                return units
            for event in events:
                last_asr_at = event.emitted_at
                units.extend(parts.segmenter.accept(event))
            return units

        def flush_asr() -> list[TranslationUnit]:
            nonlocal last_asr_at
            units: list[TranslationUnit] = []
            try:
                finals: list[AsrEvent] = parts.asr.flush()
            except EngineError as error:
                self.warnings.add(f"Fallo del reconocimiento de voz: {error}")
                finals = []
            for event in finals:
                last_asr_at = event.emitted_at
                units.extend(parts.segmenter.accept(event))
            return units

        while not self._stop.is_set():
            chunk = parts.source.read(0.1)
            if chunk is None:
                if parts.source.exhausted:
                    break
                continue
            self._save(chunk)
            if parts.agc is not None:
                chunk = parts.agc.process(chunk)
            if parts.echo_monitor is not None:
                arrival = self._arrival(chunk.t_end)
                parts.echo_monitor.feed_captured(chunk, arrival)  # type: ignore[attr-defined]

            pre_roll.append(chunk)
            while pre_roll and pre_roll[-1].t_end - pre_roll[0].t_start > PRE_ROLL_S:
                pre_roll.popleft()

            units: list[TranslationUnit] = []
            fed = False
            events: list[VadEvent] = parts.vad.accept(chunk)
            for event in events:
                if event.kind is VadEventKind.SPEECH_START:
                    in_speech = True
                    units.extend(parts.segmenter.accept(event))
                    for buffered in pre_roll:  # incluye el chunk actual
                        piece = _trim_start(buffered, event.t)
                        if piece is not None:
                            units.extend(feed_asr(piece))
                    fed = True
                elif event.kind is VadEventKind.SPEECH_END:
                    if in_speech and not fed:
                        units.extend(feed_asr(chunk))  # la cola de silencio que confirma el fin
                        fed = True
                    units.extend(parts.segmenter.accept(event))
                    units.extend(flush_asr())
                    in_speech = False
            if in_speech and not fed:
                units.extend(feed_asr(chunk))
            self._add_units(units, last_asr_at)

        # Fin de la fuente (fichero) o parada: se cierra lo que quede.
        if not self._stop.is_set():
            units = flush_asr() if in_speech else []
            units.extend(parts.segmenter.flush())
            self._add_units(units, last_asr_at)
        self._listening_done.set()
        self._work.set()

    def _add_units(self, units: list[TranslationUnit], asr_final_at: float | None) -> None:
        for unit in units:
            self.parts.scheduler.add_unit(
                unit, asr_final_at=asr_final_at, captured_at=self._arrival(unit.t_end)
            )
        if units:
            self._work.set()

    def _arrival(self, t_audio: float) -> float | None:
        arrival_time = getattr(self.parts.source, "arrival_time", None)
        return arrival_time(t_audio) if callable(arrival_time) else None

    def _save(self, chunk: AudioChunk) -> None:
        if self._wav is not None:
            pcm = np.clip(chunk.samples, -1.0, 1.0)
            self._wav.writeframes((pcm * 32767.0).astype("<i2").tobytes())

    # --- traducción ----------------------------------------------------------
    def _translate_loop(self) -> None:
        parts = self.parts
        while not self._stop.is_set():
            request = parts.scheduler.next_translation()
            if request is None:
                self._work.wait(0.05)
                self._work.clear()
                continue
            try:
                result = parts.translator.translate(request)
            except EngineError as error:
                parts.scheduler.on_failure(request.unit.unit_id, f"traducción: {error}")
                self.warnings.add(f"Fallo de la traducción: {error}")
                continue
            if not result.rejected:
                self._last_source, self._last_translation = request.unit.source_text, result.text
            synthesis = parts.scheduler.on_translation(result)
            if synthesis is not None:
                self._synth_queue.put(synthesis)

    # --- voz -----------------------------------------------------------------
    def _voice_loop(self) -> None:
        parts = self.parts
        while not self._stop.is_set():
            try:
                request = self._synth_queue.get(timeout=0.05)
            except Empty:
                continue
            # Bajo demanda: no se adelanta más de tts_lookahead_s de audio al sink.
            while not self._stop.is_set() and parts.sink.pending_seconds() > self.tts_lookahead_s:
                time.sleep(0.02)
            if self._stop.is_set() or not parts.scheduler.is_open(request.unit_id):
                continue
            self._speak(request)

    def _speak(self, request: SynthesisRequest) -> None:
        parts = self.parts
        rate = parts.synthesizer.sample_rate
        stretch = StreamTimeStretch(
            speed=request.speed if not parts.synthesizer.supports_speed else 1.0, sample_rate=rate
        )
        resampler = StreamResampler(rate, PLAYBACK_RATE)
        parts.scheduler.on_tts_started(request.unit_id)
        first = True
        delivered = False
        try:
            for chunk in parts.synthesizer.synthesize(request):
                if self._stop.is_set() or not parts.scheduler.is_open(request.unit_id):
                    break
                out = resampler.process(stretch.process(chunk.samples)) if chunk.samples.size else _EMPTY
                if chunk.is_last:
                    tail = resampler.process(stretch.flush())
                    out = np.concatenate([out, tail, resampler.flush()]).astype(np.float32)
                if out.size == 0 and not chunk.is_last:
                    continue
                if first:
                    parts.scheduler.on_tts_first_audio(request.unit_id)
                    first = False
                if chunk.is_last:
                    parts.scheduler.on_tts_finished(request.unit_id)
                parts.sink.enqueue(SpeechPiece(request.unit_id, out.astype(np.float32), chunk.is_last))
                delivered = True
                if chunk.is_last:
                    return
        except EngineError as error:
            parts.scheduler.on_failure(request.unit_id, f"voz: {error}")
            self.warnings.add(f"Fallo de la voz: {error}")
        # Cortada o fallida a medias: se cierra la unidad en el sink para no bloquear el FIFO (T029, nota 5).
        if delivered:
            parts.sink.enqueue(SpeechPiece(request.unit_id, _EMPTY, True))

    # --- control -------------------------------------------------------------
    def _control_loop(self) -> None:
        parts = self.parts
        while not self._stop.wait(TICK_S):
            decision = parts.scheduler.tick()
            now = parts.clock.now()
            pids = [pid for pid in parts.child_pids() if pid]
            parts.recorder.sample_memory(now, pids)
            if parts.agc is not None and parts.agc.source_silent_for_s > SOURCE_SILENCE_WARNING_S:
                self.warnings.add("No llega audio del origen (¿app silenciada o contenido protegido?).")
            if parts.echo_monitor is not None:
                total = int(getattr(parts.echo_monitor, "echo_events", 0))
                if total > self._echo_seen:
                    parts.recorder.count_echo_event(total - self._echo_seen)
                    self._echo_seen = total
                    self.warnings.add("Se ha detectado la propia voz en la captura (eco).")
            if parts.on_status is not None:
                parts.on_status(
                    StatusSnapshot(
                        state=self._state(),
                        lag_s=parts.scheduler.lag(),
                        speed=decision.speed,
                        mode=decision.mode,
                        warnings=self.warnings.current(),
                        last_source=self._last_source,
                        last_translation=self._last_translation,
                    )
                )

    def _state(self) -> str:
        if self._stop.is_set():
            return "stopped"
        if self.parts.sink.pending_seconds() > 0:
            return "speaking"
        if self.parts.scheduler.open_count > 0:
            return "translating"
        return "listening"


_EMPTY = np.zeros(0, dtype=np.float32)


def _trim_start(chunk: AudioChunk, t: float) -> AudioChunk | None:
    """El tramo de ``chunk`` desde el instante ``t`` (None si acaba antes)."""
    if chunk.t_end <= t:
        return None
    if chunk.t_start >= t:
        return chunk
    skip = int(round((t - chunk.t_start) * chunk.sample_rate))
    return AudioChunk(chunk.samples[skip:], chunk.sample_rate, chunk.t_start + skip / chunk.sample_rate)


def make_scheduler_and_recorder(
    clock: Clock,
    sink: AudioSink,
    translator: Translator,
    settings: Settings,
    *,
    on_record: Callable[[UtteranceRecord], None] | None = None,
) -> tuple[Scheduler, MetricsRecorder]:
    """Planificador y recorder con la política de retraso de los ajustes (``allow_concise`` del traductor)."""
    recorder = MetricsRecorder(drop_after_s=settings.drop_after_s)
    policy = DelayPolicy(
        accelerate_after_s=settings.accelerate_after_s,
        max_speed=settings.max_speed,
        concise_after_s=settings.concise_after_s,
        drop_after_s=settings.drop_after_s,
        allow_concise=translator.supports_concise,
    )

    def record(item: UtteranceRecord) -> None:
        recorder.add_record(item)
        if on_record is not None:
            on_record(item)

    scheduler = Scheduler(
        clock,
        ThresholdDelayController(policy),
        sink,
        voice=VoiceRef(settings.voice),
        context_utterances=settings.context_utterances,
        glossary=settings.glossary,
        on_record=record,
        on_lag_sample=recorder.add_lag_sample,
    )
    return scheduler, recorder


def report_components() -> list[object]:
    """Componentes del manifiesto que usa una sesión, para el informe: los obligatorios, sin las voces."""
    from instanttraductor.setup.manifest import COMPONENTS

    return [c for c in COMPONENTS if not c.optional and c.kind != "voz"]


def session_id_for(started: datetime) -> str:
    return started.strftime("%Y%m%d-%H%M%S")


def report_dir_for(paths: AppPaths, session_id: str) -> Path:
    return paths.reports / session_id
