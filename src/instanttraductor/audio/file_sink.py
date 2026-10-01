"""Destino de audio del modo archivo: `TimelineSink` (T036), la voz en español sobre una pista en el tiempo.

Implementa `AudioSink` (48 kHz) sin dispositivo: simula la reproducción y, en vez de sonar, coloca cada
unidad en su instante del `Clock` dentro de una pista. Así el modo archivo reproduce el comportamiento
temporal del directo (FR-021): las mismas reglas FIFO y el mismo *underrun* que `DeviceSink`.

Modelo de la simulación
-----------------------
- Cada unidad (`unit_id`) tiene sus trozos; las unidades «suenan» de una en una, en el orden en que llegó su
  primer trozo (FIFO), y nunca se solapan.
- Una unidad **empieza (STARTED) en cuanto llega su primer trozo, si el sink está libre**; si no, cuando
  acaba la que suena. Acaba (FINISHED) cuando llegó su trozo `is_last` y «sonó» todo su audio.
- Si el audio recibido se acaba antes de que llegue el siguiente trozo, la unidad se queda esperando y
  bloquea a las siguientes; el trozo tardío se coloca en cuanto llega (un hueco en la pista).
- `cancel_pending()` descarta las unidades que no han empezado; `stop()` corta la que suena (en la pista
  queda recortada en ese instante) y descarta las demás. Los trozos que lleguen después de una unidad
  terminada o cancelada se ignoran.

Hora de los eventos y entrega
-----------------------------
La simulación sigue al `clock` en un hilo propio que despierta cada pocos milisegundos y en cada llamada
al sink. Los eventos llevan el instante **simulado exacto** (`at`), que puede ser anterior en unos
milisegundos al momento de la entrega, y se entregan siempre desde ese hilo, en orden y sin cerrojos, así
que `on_event` puede llamar al sink. Todo se calcula en muestras de 48 kHz, de modo que las unidades
encadenadas lo están exactamente.

Pista
-----
`track()` devuelve la pista en español: 48 kHz, mono, `float32`, con la duración de la entrada
(`duration_s`); lo que se pase de ahí se recorta. Es dispersa por segmentos: solo guarda los trozos, y el
array completo se construye al pedirlo. `set_volume` (0–2) se aplica al renderizar, a toda la pista.
"""

from __future__ import annotations

import logging
import math
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final

import numpy as np
import numpy.typing as npt

from instanttraductor.contracts import (
    PLAYBACK_RATE,
    Clock,
    PlaybackEvent,
    PlaybackEventKind,
    SpeechPiece,
)

logger = logging.getLogger(__name__)

__all__ = ["MAX_GAIN", "TimelineSink"]

MAX_GAIN: Final = 2.0
_POLL_S: Final = 0.005  # el reloj puede ser manual y no avisar: el hilo mira cada 5 ms
_MIN_WAIT_S: Final = 0.0002

Samples = npt.NDArray[np.float32]


@dataclass(slots=True)
class _Unit:
    """Una unidad encolada o «sonando». Los instantes van en muestras de `PLAYBACK_RATE`."""

    unit_id: int
    arrived_idx: int  # llegada de su primer trozo (reloj de sesión)
    unplaced: list[Samples] = field(default_factory=list)  # trozos recibidos antes de empezar
    samples: int = 0  # muestras recibidas hasta ahora
    complete: bool = False  # ya llegó el trozo `is_last`
    start_idx: int = 0
    end_idx: int = 0  # donde acaba el audio colocado hasta ahora
    segments: list[tuple[int, Samples]] = field(default_factory=list)  # (muestra de inicio, audio)


class TimelineSink:
    """`AudioSink` que coloca la voz en una pista, a la hora del `Clock`, sin dispositivo.

    - `clock`: el reloj de sesión; la simulación lo sigue.
    - `duration_s`: duración de la entrada, que es la de la pista; None para que sea lo justo para lo
      que sonó.
    - `track()`: la pista renderizada (48 kHz, mono, `float32`).
    """

    sample_rate: int = PLAYBACK_RATE

    def __init__(self, clock: Clock, *, duration_s: float | None) -> None:
        if duration_s is not None and (not math.isfinite(duration_s) or duration_s < 0):
            raise ValueError(f"duration_s debe ser un número finito no negativo (recibido: {duration_s}).")
        self._clock = clock
        self._length = None if duration_s is None else round(duration_s * PLAYBACK_RATE)
        self._gain = 1.0
        self._on_event: Callable[[PlaybackEvent], None] | None = None
        self._cond = threading.Condition()  # protege todo el estado de la simulación
        self._queue: deque[_Unit] = deque()  # unidades que aún no han empezado, en orden FIFO
        self._units: dict[int, _Unit] = {}  # las que están en cola o sonando
        self._current: _Unit | None = None
        self._closed: set[int] = set()  # terminadas o canceladas: sus trozos posteriores se ignoran
        self._placed: list[tuple[int, Samples]] = []  # segmentos de las unidades ya cerradas
        self._free_idx = 0  # muestra en que el sink quedó libre
        self._stopped = False
        self._outbox: deque[PlaybackEvent] = deque()
        self._thread: threading.Thread | None = None

    # --- AudioSink -------------------------------------------------------------------------------

    def start(self, on_event: Callable[[PlaybackEvent], None]) -> None:
        """Registra el receptor de eventos y arranca el hilo de la simulación."""
        with self._cond:
            self._on_event = on_event
            if self._thread is not None or self._stopped:
                return
            self._thread = threading.Thread(target=self._run, name="timeline-sink", daemon=True)
            self._thread.start()

    def enqueue(self, piece: SpeechPiece) -> None:
        with self._cond:
            if self._stopped or piece.unit_id in self._closed:
                return
            now = self._now_samples()
            self._advance_locked(now)
            unit = self._units.get(piece.unit_id)
            if unit is None:
                unit = _Unit(unit_id=piece.unit_id, arrived_idx=round(now))
                self._units[piece.unit_id] = unit
                self._queue.append(unit)
            samples = np.asarray(piece.samples, dtype=np.float32)
            unit.samples += len(samples)
            unit.complete = unit.complete or piece.is_last
            if unit is self._current:
                # Ya suena: el audio nuevo va detrás de lo colocado, o desde ahora si ya se había acabado.
                at = max(unit.end_idx, round(now))
                unit.segments.append((at, samples))
                unit.end_idx = at + len(samples)
            else:
                unit.unplaced.append(samples)
            self._advance_locked(now)
            self._cond.notify_all()

    def cancel_pending(self) -> list[int]:
        with self._cond:
            now = self._now_samples()
            self._advance_locked(now)
            dropped = [unit.unit_id for unit in self._queue]
            for unit in self._queue:
                self._close_locked(unit, PlaybackEventKind.CANCELLED, round(now))
            self._queue.clear()
            if dropped:
                self._cond.notify_all()
            return dropped

    def set_volume(self, gain: float) -> None:
        """Volumen de la voz de 0,0 a 2,0 (fuera de rango se acota); se aplica al renderizar `track()`."""
        if not math.isfinite(gain):
            raise ValueError(f"El volumen debe ser un número finito (recibido: {gain}).")
        with self._cond:
            self._gain = min(MAX_GAIN, max(0.0, float(gain)))

    def pending_seconds(self) -> float:
        """Audio encolado aún sin «sonar» (incluido lo que queda de la unidad en curso)."""
        with self._cond:
            now = self._now_samples()
            self._advance_locked(now)
            pending = sum(unit.samples for unit in self._queue)
            if self._current is not None:
                pending += max(0.0, self._current.end_idx - now)
            self._cond.notify_all()  # lo que acabe de generar la simulación lo entrega el hilo
            return pending / PLAYBACK_RATE

    def stop(self) -> None:
        """Corta la unidad que suena, descarta las demás y emite CANCELLED. Idempotente."""
        with self._cond:
            if not self._stopped:
                now = self._now_samples()
                self._advance_locked(now)
                self._stopped = True
                cut_idx = round(now)
                current = self._current
                cut = ([current] if current is not None else []) + list(self._queue)
                for unit in cut:
                    self._close_locked(unit, PlaybackEventKind.CANCELLED, cut_idx)
                if current is not None:
                    self._truncate(current, cut_idx)
                    self._placed.extend(current.segments)
                self._current = None
                self._queue.clear()
            thread = self._thread
            self._cond.notify_all()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5.0)

    # --- Pista -----------------------------------------------------------------------------------

    def track(self) -> Samples:
        """La pista en español: 48 kHz, mono, `float32`, con la duración de la entrada.

        Cada unidad está en su instante simulado de inicio; el volumen de `set_volume` va aplicado. Se
        puede pedir en cualquier momento, también durante la sesión.
        """
        with self._cond:
            segments = list(self._placed)
            if self._current is not None:
                segments.extend(self._current.segments)
            gain = self._gain
            length = self._length
        if length is None:
            length = max((idx + len(audio) for idx, audio in segments), default=0)
        out = np.zeros(length, dtype=np.float32)
        for idx, audio in segments:
            count = min(len(audio), length - idx)
            if count > 0:
                out[idx : idx + count] += audio[:count]
        if gain != 1.0:
            out *= np.float32(gain)
        return out

    # --- Simulación ------------------------------------------------------------------------------

    def _now_samples(self) -> float:
        return self._clock.now() * PLAYBACK_RATE

    def _advance_locked(self, now: float) -> None:
        """Hace «sonar» hasta `now`: acaba la unidad actual si le tocaba y arranca las siguientes."""
        while True:
            current = self._current
            if current is not None:
                if not (current.complete and current.end_idx <= now):
                    return
                self._close_locked(current, PlaybackEventKind.FINISHED, current.end_idx)
                self._placed.extend(current.segments)
                self._free_idx = current.end_idx
                self._current = None
                continue
            if not self._queue:
                return
            unit = self._queue.popleft()
            unit.start_idx = max(unit.arrived_idx, self._free_idx)
            position = unit.start_idx
            for audio in unit.unplaced:  # los trozos de una unidad suenan contiguos
                unit.segments.append((position, audio))
                position += len(audio)
            unit.unplaced.clear()
            unit.end_idx = position
            self._current = unit
            self._emit_locked(unit.unit_id, PlaybackEventKind.STARTED, unit.start_idx)

    def _close_locked(self, unit: _Unit, kind: PlaybackEventKind, at_idx: int) -> None:
        self._units.pop(unit.unit_id, None)
        self._closed.add(unit.unit_id)
        self._emit_locked(unit.unit_id, kind, at_idx)

    def _emit_locked(self, unit_id: int, kind: PlaybackEventKind, at_idx: int) -> None:
        self._outbox.append(PlaybackEvent(unit_id, kind, at_idx / PLAYBACK_RATE))

    @staticmethod
    def _truncate(unit: _Unit, cut_idx: int) -> None:
        """Recorta lo que de la unidad suena después de `cut_idx` (la parada)."""
        kept: list[tuple[int, Samples]] = []
        for idx, audio in unit.segments:
            if idx >= cut_idx:
                continue
            kept.append((idx, audio[: cut_idx - idx]))
        unit.segments = kept

    # --- Hilo de la simulación -------------------------------------------------------------------

    def _run(self) -> None:
        while True:
            with self._cond:
                if not self._stopped:
                    self._advance_locked(self._now_samples())
                events = list(self._outbox)
                self._outbox.clear()
                callback = self._on_event
                if not events:
                    if self._stopped:
                        return
                    self._cond.wait(self._next_wait_locked())
                    continue
            for event in events:
                if callback is None:
                    continue
                try:
                    callback(event)
                except Exception:
                    logger.exception("Falló el receptor de eventos del sink de la línea de tiempo.")

    def _next_wait_locked(self) -> float:
        wait = _POLL_S
        current = self._current
        if current is not None and current.complete:
            remaining = (current.end_idx - self._now_samples()) / PLAYBACK_RATE
            wait = min(wait, max(_MIN_WAIT_S, remaining))
        return wait
