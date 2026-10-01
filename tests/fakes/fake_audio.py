"""Dobles de audio: `FakeAudioSource` (fuente de un array o un WAV) y `FakeAudioSink` (destino simulado).

Ninguno toca dispositivos reales. El sink simula la reproducción sobre un `ManualClock`: el tiempo solo
pasa cuando el test lo mueve.
"""

from __future__ import annotations

import os
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from instanttraductor.contracts import (
    CAPTURE_RATE,
    PLAYBACK_RATE,
    AudioChunk,
    PlaybackEvent,
    PlaybackEventKind,
    SpeechPiece,
)
from instanttraductor.pipeline.clock import ManualClock


def _load_wav(path: str | os.PathLike[str]) -> npt.NDArray[np.float32]:
    """Lee un WAV mono a `CAPTURE_RATE` como float32 en [-1, 1]."""
    import soundfile as sf  # dependencia de desarrollo; import perezoso para no cargarla si no hace falta

    samples, rate = sf.read(path, dtype="float32", always_2d=False)
    if rate != CAPTURE_RATE:
        raise ValueError(f"El WAV {os.fspath(path)!r} está a {rate} Hz y debe estar a {CAPTURE_RATE} Hz.")
    if samples.ndim != 1:
        raise ValueError(f"El WAV {os.fspath(path)!r} no es mono ({samples.shape[1]} canales).")
    return samples


class FakeAudioSource:
    """`AudioSource` que sirve un array o un WAV en chunks contiguos de `chunk_s` segundos (20 ms).

    - `audio`: array 1-D (mono, a `CAPTURE_RATE`) o ruta de un WAV mono a 16 kHz.
    - Los chunks salen tan rápido como se piden, sin esperar al reloj; `read()` no bloquea nunca. El
      primero empieza en `t_start = 0.0` y el último puede ser más corto.
    - `read()` devuelve `None` antes de `start()`, tras `stop()` y cuando se acaba el audio.
    - `exhausted` pasa a True en cuanto se lee el último chunk (no hace falta un `read()` más) o al parar.
    - Cada chunk lleva una copia de sus muestras: modificarlo no altera la fuente.
    """

    sample_rate: int = CAPTURE_RATE

    def __init__(self, audio: npt.ArrayLike | str | os.PathLike[str], *, chunk_s: float = 0.02) -> None:
        if isinstance(audio, (str, os.PathLike)):
            samples = _load_wav(audio)
        else:
            samples = np.asarray(audio, dtype=np.float32)
            if samples.ndim != 1:
                raise ValueError(f"El audio debe ser mono (un array 1-D); forma recibida: {samples.shape}.")
        if chunk_s <= 0:
            raise ValueError("chunk_s debe ser positivo.")
        self._samples = samples
        self._chunk_len = max(1, round(chunk_s * CAPTURE_RATE))
        self._pos = 0
        self._started = False
        self._stopped = False
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            self._started = True

    def read(self, timeout: float = 0.0) -> AudioChunk | None:
        """Siguiente chunk o `None`. `timeout` se ignora: no hay nada que esperar."""
        with self._lock:
            if not self._started or self._stopped or self._pos >= len(self._samples):
                return None
            end = min(self._pos + self._chunk_len, len(self._samples))
            chunk = AudioChunk(
                samples=self._samples[self._pos : end].copy(),
                sample_rate=CAPTURE_RATE,
                t_start=self._pos / CAPTURE_RATE,
            )
            self._pos = end
            return chunk

    @property
    def exhausted(self) -> bool:
        with self._lock:
            return self._stopped or self._pos >= len(self._samples)

    def stop(self) -> None:
        with self._lock:
            self._stopped = True


@dataclass
class _Unit:
    """Unidad que el sink tiene encolada o sonando."""

    unit_id: int
    arrived_at: float  # reloj de sesión: llegada de su primer trozo
    samples: int = 0  # muestras recibidas hasta ahora
    complete: bool = False  # ya llegó el trozo `is_last`
    started_at: float | None = None
    audio_end_at: float = 0.0  # instante simulado en que acaba el audio recibido hasta ahora


class FakeAudioSink:
    """`AudioSink` simulado sobre un `ManualClock`.

    Reglas de la simulación (la duración de una unidad es `muestras / PLAYBACK_RATE`):
    - Una unidad empieza en cuanto llega su primer trozo, si el sink está libre; si no, cuando acaba la
      que suena. Las unidades suenan en FIFO y nunca a la vez.
    - Una unidad acaba cuando ha llegado su trozo `is_last` y se ha reproducido todo su audio. Si el audio
      recibido se acaba antes de que llegue el siguiente trozo, la unidad espera (como un *underrun*) y
      bloquea a las siguientes.
    - La reproducción avanza con el reloj, pero de forma perezosa: se procesa en cada llamada pública y en
      `poll()`. Los eventos llevan el instante *simulado* en que ocurren, aunque el test haya saltado el
      reloj de golpe.
    - `cancel_pending()` descarta las unidades que no han empezado y emite CANCELLED por cada una. Los
      trozos que lleguen después de una unidad cancelada, parada o terminada se ignoran (pero se registran).
    - `stop()` emite CANCELLED para la unidad que suena y para las pendientes, y deja el sink parado.
    - Los eventos se entregan a `on_event` sin cerrojos, uno a uno y en orden, desde el hilo que los
      provoca. El callback puede volver a llamar al sink: lo que genere se entrega después.

    Para los tests: `pieces` (todo lo encolado), `events` (todo lo emitido, haya o no callback), `volume`
    (último `set_volume`), `poll()` y `advance(dt)`.
    """

    sample_rate: int = PLAYBACK_RATE

    def __init__(self, clock: ManualClock) -> None:
        self._clock = clock
        self.pieces: list[SpeechPiece] = []
        self.events: list[PlaybackEvent] = []
        self.volume: float = 1.0
        self._on_event: Callable[[PlaybackEvent], None] | None = None
        self._lock = threading.Lock()
        self._queue: deque[_Unit] = deque()  # unidades que aún no han empezado, en orden FIFO
        self._units: dict[int, _Unit] = {}  # las que están en cola o sonando
        self._current: _Unit | None = None
        self._closed: set[int] = set()  # terminadas o canceladas: sus trozos posteriores se ignoran
        self._free_at = 0.0  # instante simulado en que el sink quedó libre
        self._stopped = False
        self._outbox: deque[PlaybackEvent] = deque()
        self._delivering = False

    # --- AudioSink -------------------------------------------------------------------------------

    def start(self, on_event: Callable[[PlaybackEvent], None]) -> None:
        with self._lock:
            self._on_event = on_event

    def enqueue(self, piece: SpeechPiece) -> None:
        with self._lock:
            self.pieces.append(piece)
            if self._stopped or piece.unit_id in self._closed:
                return
            now = self._clock.now()
            self._advance_locked(now)
            unit = self._units.get(piece.unit_id)
            if unit is None:
                unit = _Unit(unit_id=piece.unit_id, arrived_at=now)
                self._units[piece.unit_id] = unit
                self._queue.append(unit)
            unit.samples += len(piece.samples)
            unit.complete = unit.complete or piece.is_last
            if unit.started_at is not None:
                # La unidad ya suena: el audio nuevo va detrás de lo que quedaba por sonar
                # (o desde ahora, si el audio recibido ya se había acabado).
                unit.audio_end_at = max(unit.audio_end_at, now) + len(piece.samples) / PLAYBACK_RATE
            self._advance_locked(now)
        self._deliver()

    def cancel_pending(self) -> list[int]:
        with self._lock:
            now = self._clock.now()
            self._advance_locked(now)
            dropped = [unit.unit_id for unit in self._queue]
            for unit in self._queue:
                self._close_locked(unit, PlaybackEventKind.CANCELLED, now)
            self._queue.clear()
        self._deliver()
        return dropped

    def set_volume(self, gain: float) -> None:
        self.volume = gain

    def pending_seconds(self) -> float:
        with self._lock:
            now = self._clock.now()
            self._advance_locked(now)
            pending = sum(unit.samples for unit in self._queue) / PLAYBACK_RATE
            if self._current is not None:
                pending += max(0.0, self._current.audio_end_at - now)
        self._deliver()
        return pending

    def stop(self) -> None:
        with self._lock:
            if self._stopped:
                return
            now = self._clock.now()
            self._advance_locked(now)
            self._stopped = True
            cut = ([self._current] if self._current is not None else []) + list(self._queue)
            for unit in cut:
                self._close_locked(unit, PlaybackEventKind.CANCELLED, now)
            self._current = None
            self._queue.clear()
        self._deliver()

    # --- Utilidades de test ----------------------------------------------------------------------

    def poll(self) -> None:
        """Reproduce lo que toque hasta `clock.now()` (úsalo tras mover el reloj a mano)."""
        with self._lock:
            self._advance_locked(self._clock.now())
        self._deliver()

    def advance(self, dt: float) -> None:
        """Avanza el reloj `dt` segundos y reproduce lo que toque."""
        self._clock.advance(dt)
        self.poll()

    # --- Simulación ------------------------------------------------------------------------------

    def _advance_locked(self, now: float) -> None:
        """Reproduce hasta `now`: acaba la unidad que suena si le tocaba y arranca las siguientes."""
        while True:
            current = self._current
            if current is not None:
                if not (current.complete and current.audio_end_at <= now):
                    return
                self._close_locked(current, PlaybackEventKind.FINISHED, current.audio_end_at)
                self._free_at = current.audio_end_at
                self._current = None
                continue
            if not self._queue:
                return
            unit = self._queue.popleft()
            unit.started_at = max(unit.arrived_at, self._free_at)
            unit.audio_end_at = unit.started_at + unit.samples / PLAYBACK_RATE
            self._current = unit
            self._emit_locked(PlaybackEvent(unit.unit_id, PlaybackEventKind.STARTED, unit.started_at))

    def _close_locked(self, unit: _Unit, kind: PlaybackEventKind, at: float) -> None:
        self._units.pop(unit.unit_id, None)
        self._closed.add(unit.unit_id)
        self._emit_locked(PlaybackEvent(unit.unit_id, kind, at))

    def _emit_locked(self, event: PlaybackEvent) -> None:
        self.events.append(event)
        self._outbox.append(event)

    def _deliver(self) -> None:
        """Entrega los eventos pendientes sin cerrojos, en orden y de uno en uno.

        Si ya hay un hilo entregando (o el callback volvió a entrar en el sink), los eventos nuevos los
        entrega ese mismo bucle cuando termine el callback en curso.
        """
        with self._lock:
            if self._delivering:
                return
            self._delivering = True
        try:
            while True:
                with self._lock:
                    if not self._outbox:
                        self._delivering = False
                        return
                    event = self._outbox.popleft()
                    callback = self._on_event
                if callback is not None:
                    callback(event)
        except BaseException:
            with self._lock:
                self._delivering = False
            raise
