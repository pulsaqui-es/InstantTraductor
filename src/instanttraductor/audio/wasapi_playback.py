"""Reproducción de la voz en español por el dispositivo de salida por defecto: `DeviceSink` (T023).

Implementa `AudioSink` (48 kHz) sobre `miniaudio.PlaybackDevice` (ADR-0010, research R4): sin `device_id`
(sigue al dispositivo por defecto), WASAPI, 48 kHz, float32, estéreo (la voz mono se duplica en los dos
canales) y periodos de 20 ms × 3 (60 ms de búfer: con 10 ms × 2 se pierde audio en cuanto el GIL se ocupa).

Piezas:

- `MiniaudioBackend`: lo único que habla con miniaudio. Abre el dispositivo con una copia adaptada de
  `PlaybackDevice.__init__` que engancha el `notificationCallback` (pyminiaudio 1.71 no lo hace) para
  enterarse de `rerouted` y `stopped`. El *backend* se inyecta en `DeviceSink`, así que todo lo demás se
  prueba sin dispositivo.
- `DeviceSink`: la cola FIFO de unidades, la generación del audio que pide el dispositivo (`_render`, en el
  hilo de audio), los eventos, el volumen, los *underruns* y la recuperación del dispositivo.

Modelo de la cola
-----------------
Cada unidad (`unit_id`) tiene sus trozos en una cola propia y las unidades suenan de una en una, en el orden
en que llegó su primer trozo (FIFO). Una unidad **empieza en cuanto el dispositivo pide audio y ella es la
primera de la cola** (STARTED: su primera muestra se entrega al dispositivo). Acaba (FINISHED) cuando llegó
su trozo `is_last` y se entregó la última muestra. Si el audio recibido se acaba antes de que llegue el
siguiente trozo, la unidad se queda esperando con silencio (un *underrun*) y bloquea a las siguientes: los
trozos de una unidad suenan contiguos y las unidades nunca se mezclan. `cancel_pending()` descarta las que no
han empezado; `stop()` corta la que suena y vacía la cola. Los trozos que lleguen después de una unidad
terminada o cancelada se ignoran.

Hora de los eventos
-------------------
`at` es el reloj de sesión del instante en que el dispositivo recibió esa muestra: la hora de la petición de
datos más su posición dentro del bloque. Nunca decrece (se ajusta si hace falta). No incluye los ~60 ms que
tarda el búfer en llegar al altavoz.

Hilos
-----
- **Hilo de audio** (de miniaudio): ejecuta `_render` cada 20 ms. Solo toma el cerrojo unos microsegundos y
  **nunca llama a código del suscriptor, salvo el gancho `on_rendered`**, que debe volver enseguida.
- **Hilo de eventos** (`reproduccion-eventos`): entrega los `PlaybackEvent` a `on_event`, de uno en uno y en
  orden. Así un `on_event` lento no corta el audio. `stop()` los entrega todos antes de volver.
- **Hilo vigilante** (`reproduccion-vigilante`): reabre el dispositivo cuando miniaudio avisa de `stopped`
  (condición 4 del vigilante de ADR-0010) y reintenta hasta lograrlo. La cola se conserva: al volver el
  dispositivo, la unidad en curso sigue por donde iba.
- `on_warning(texto)` se llama desde el hilo vigilante o desde el de notificaciones de miniaudio: debe volver
  enseguida.

Underruns
---------
`underruns` cuenta los **cortes audibles de la voz**: tramos en los que el dispositivo no recibió a tiempo el
audio de una unidad que estaba sonando, bien porque la cola se quedó sin datos a mitad de unidad, bien porque
la petición de datos llegó más de 60 ms (el búfer entero) después de la anterior. Un tramo continuo es uno
solo. Que no haya nada que reproducir no es un *underrun*.

Gancho `on_rendered`
--------------------
`on_rendered(samples, at)` recibe, desde el hilo de audio, cada bloque que llevó audio de la voz: mono,
float32, a 48 kHz y **ya con el volumen aplicado** (lo que de verdad suena), con la hora (reloj de sesión) de
su primera muestra. Es la entrada «lo reproducido» del `EchoMonitor`. Los bloques en silencio sin voz no se
entregan.
"""

from __future__ import annotations

import functools
import logging
import math
import threading
from collections import deque
from collections.abc import Callable, Generator, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Protocol

import miniaudio
import numpy as np
import numpy.typing as npt
from _miniaudio import ffi, lib

from instanttraductor.contracts import (
    PLAYBACK_RATE,
    Clock,
    EngineError,
    PlaybackEvent,
    PlaybackEventKind,
    SpeechPiece,
)

logger = logging.getLogger(__name__)

__all__ = [
    "CHANNELS",
    "ENGINE_NAME",
    "LATE_CALLBACK_S",
    "MAX_GAIN",
    "MiniaudioBackend",
    "NotificationCallback",
    "PlaybackBackend",
    "PlaybackStream",
    "RenderCallback",
    "DeviceSink",
]

Samples = npt.NDArray[np.float32]

ENGINE_NAME: Final = "playback"

CHANNELS: Final = 2  # estéreo: la voz mono se duplica
PERIOD_MS: Final = 20  # periodo de miniaudio (research R4)
PERIODS: Final = 3  # 3 periodos: 60 ms de búfer
MAX_GAIN: Final = 2.0  # `set_volume` admite de 0,0 a 2,0
LATE_CALLBACK_S: Final = (
    PERIOD_MS * PERIODS / 1000
)  # una petición de datos más tardía que el búfer entero corta la voz
REOPEN_DELAYS_S: Final = (
    0.1,
    0.5,
    1.0,
    2.0,
    5.0,
)  # espera antes de cada intento de reabrir; el último se repite
_JOIN_TIMEOUT_S: Final = 2.0

# Nombres de las notificaciones de miniaudio (`ma_device_notification_type_*`).
_NOTIFICATION_NAMES: Final = {
    lib.ma_device_notification_type_started: "started",
    lib.ma_device_notification_type_stopped: "stopped",
    lib.ma_device_notification_type_rerouted: "rerouted",
    lib.ma_device_notification_type_interruption_began: "interruption_began",
    lib.ma_device_notification_type_interruption_ended: "interruption_ended",
}

#: `render(frames)`: lo que el dispositivo pide a cada periodo. Devuelve float32 `(frames, CHANNELS)`.
RenderCallback = Callable[[int], Samples]
#: `notify(nombre)`: aviso de un cambio del dispositivo ("started", "stopped", "rerouted"...).
NotificationCallback = Callable[[str], None]


# --------------------------------------------------------------------------------------------------
# Backend: lo único que habla con miniaudio
# --------------------------------------------------------------------------------------------------


class PlaybackStream(Protocol):
    """Un dispositivo de salida abierto y sonando. Lo cumple `miniaudio.PlaybackDevice`."""

    def close(self) -> None:
        """Para el dispositivo y lo libera, cortando en seco lo que quedara en su búfer. Idempotente."""
        ...


class PlaybackBackend(Protocol):
    """Quien abre el dispositivo de salida. `DeviceSink` recibe uno; los tests inyectan uno falso."""

    def open(self, render: RenderCallback, notify: NotificationCallback) -> PlaybackStream:
        """Abre el dispositivo por defecto y empieza a pedir audio a `render`.

        `render(frames)` se llama desde el hilo de audio del dispositivo, a cada periodo. `notify(nombre)`
        avisa de los cambios del dispositivo (puede llamarse desde cualquier hilo). Lanza una excepción si
        no se puede abrir (el sink la convierte en `EngineError`).
        """
        ...


class _NotifyingPlaybackDevice(miniaudio.PlaybackDevice):
    """`miniaudio.PlaybackDevice` (sin `device_id`) que además engancha el `notificationCallback`.

    pyminiaudio 1.71 no engancha ese callback, así que no avisa de `rerouted` (miniaudio siguió al nuevo
    dispositivo por defecto), `stopped` (se perdió el dispositivo) ni `interruption_*`. Aquí se replica
    `PlaybackDevice.__init__` con la única diferencia del callback, creado con `ffi.callback` (base: el
    spike S4, `spikes/audio/audio_spike/tonos.py`, medido en el PC del usuario).
    """

    def __init__(
        self,
        notify: NotificationCallback,
        *,
        sample_rate: int,
        channels: int,
        period_ms: int,
        periods: int,
        app_name: str,
    ) -> None:
        # No se llama a `PlaybackDevice.__init__`: crearía el dispositivo sin el gancho.
        miniaudio.AbstractDevice.__init__(self)
        self.format = miniaudio.SampleFormat.FLOAT32
        self.sample_width = miniaudio.width_from_format(self.format)
        self.nchannels = channels
        self.sample_rate = sample_rate
        self.buffersize_msec = period_ms
        self._notify = notify
        self._ffi_handle = ffi.new_handle(self)
        config = lib.ma_device_config_init(lib.ma_device_type_playback)
        config.sampleRate = sample_rate
        config.playback.channels = channels
        config.playback.format = self.format.value
        config.playback.pDeviceID = ffi.NULL  # dispositivo por defecto: miniaudio sigue sus cambios
        config.periodSizeInMilliseconds = period_ms
        config.pUserData = self._ffi_handle
        config.dataCallback = lib._internal_data_callback
        config.stopCallback = lib._internal_stop_callback
        config.periods = periods
        self._notification_callback = ffi.callback("void(ma_device_notification *)", self._on_notification)
        config.notificationCallback = self._notification_callback
        self._devconfig = config
        self.callback_generator = None
        self._context = self._make_context(
            [miniaudio.Backend.WASAPI], miniaudio.ThreadPriority.HIGHEST, app_name
        )
        result = lib.ma_device_init(self._context, ffi.addressof(self._devconfig), self._device)
        if result != lib.MA_SUCCESS:
            raise miniaudio.MiniaudioError("failed to init device", result)
        self.backend = ffi.string(lib.ma_get_backend_name(self._device.pContext.backend)).decode()

    def _on_notification(self, notification: Any) -> None:
        try:
            self._notify(_NOTIFICATION_NAMES.get(notification.type, f"type_{notification.type}"))
        except Exception:  # una excepción dentro de un callback de C solo se imprime y se pierde
            logger.exception("Falló el tratamiento de una notificación del dispositivo de audio")


def _frames_generator(render: RenderCallback) -> Generator[Any, int, None]:
    """El generador que `PlaybackDevice.start` espera: recibe los fotogramas pedidos y cede el audio.

    Nunca termina ni lanza: una excepción haría que miniaudio dejara el dispositivo mudo para siempre.
    """
    frames = yield b""
    while True:
        try:
            samples = render(frames)
        except Exception:
            logger.exception("Falló la generación del audio de salida; se envía silencio")
            samples = np.zeros((frames, CHANNELS), dtype=np.float32)
        frames = yield samples


class MiniaudioBackend:
    """`PlaybackBackend` de producción: `miniaudio.PlaybackDevice` (WASAPI) en el dispositivo por defecto."""

    def __init__(
        self,
        *,
        sample_rate: int = PLAYBACK_RATE,
        channels: int = CHANNELS,
        period_ms: int = PERIOD_MS,
        periods: int = PERIODS,
        app_name: str = "InstantTraductor",
    ) -> None:
        self._sample_rate = sample_rate
        self._channels = channels
        self._period_ms = period_ms
        self._periods = periods
        self._app_name = app_name

    def open(self, render: RenderCallback, notify: NotificationCallback) -> PlaybackStream:
        device = _NotifyingPlaybackDevice(
            notify,
            sample_rate=self._sample_rate,
            channels=self._channels,
            period_ms=self._period_ms,
            periods=self._periods,
            app_name=self._app_name,
        )
        try:
            generator = _frames_generator(render)
            next(generator)  # el generador tiene que estar ya arrancado
            device.start(generator)
        except BaseException:
            device.close()
            raise
        logger.info(
            "Salida de audio abierta: %s, %d Hz, %d canales, periodos de %d ms x %d",
            device.backend,
            self._sample_rate,
            self._channels,
            self._period_ms,
            self._periods,
        )
        return device


# --------------------------------------------------------------------------------------------------
# La cola de unidades
# --------------------------------------------------------------------------------------------------


@dataclass(slots=True)
class _Unit:
    """Una unidad en el sink: sus trozos aún sin reproducir y su estado."""

    unit_id: int
    pieces: deque[Samples] = field(default_factory=deque)
    head_pos: int = 0  # muestras ya entregadas del primer trozo
    available: int = 0  # muestras recibidas y todavía sin entregar
    complete: bool = False  # ya llegó el trozo `is_last`

    def take_into(self, out: Samples, pos: int, limit: int) -> int:
        """Copia en `out[pos:]` hasta `limit` muestras de la unidad y devuelve cuántas copió."""
        copied = 0
        while copied < limit and self.pieces:
            head = self.pieces[0]
            count = min(len(head) - self.head_pos, limit - copied)
            out[pos + copied : pos + copied + count] = head[self.head_pos : self.head_pos + count]
            copied += count
            self.head_pos += count
            if self.head_pos >= len(head):
                self.pieces.popleft()
                self.head_pos = 0
        self.available -= copied
        return copied


# --------------------------------------------------------------------------------------------------
# DeviceSink
# --------------------------------------------------------------------------------------------------


def _close_quietly(stream: PlaybackStream) -> None:
    try:
        stream.close()
    except Exception:
        logger.exception("Error al cerrar la salida de audio")


class DeviceSink:
    """`AudioSink` sobre el dispositivo de salida por defecto (ver el docstring del módulo).

    - `clock`: reloj de sesión, para la hora de los eventos.
    - `on_warning(texto)`: avisos para la persona, en español (cambio de dispositivo, reapertura...).
    - `on_rendered(samples, at)`: gancho con lo que se reproduce (ver el módulo). También se puede fijar o
      quitar después con la propiedad `on_rendered`.
    - `backend` y `reopen_delays_s`: solo para pruebas (un dispositivo falso y esperas cortas).

    `start(on_event)` abre el dispositivo y lanza `EngineError` si no se puede. `stop()` es terminal e
    idempotente: corta lo que suena, emite CANCELLED por todo lo que quedaba, cierra el dispositivo y entrega
    los eventos pendientes antes de volver. Tras `stop()`, `enqueue` no hace nada.
    """

    sample_rate: int = PLAYBACK_RATE

    def __init__(
        self,
        clock: Clock,
        *,
        on_warning: Callable[[str], None] | None = None,
        on_rendered: Callable[[Samples, float], None] | None = None,
        backend: PlaybackBackend | None = None,
        reopen_delays_s: Sequence[float] = REOPEN_DELAYS_S,
    ) -> None:
        if not reopen_delays_s or any(delay < 0 for delay in reopen_delays_s):
            raise ValueError("reopen_delays_s debe tener al menos una espera y ninguna negativa.")
        self._clock = clock
        self._on_warning = on_warning
        self._on_rendered = on_rendered
        self._backend: PlaybackBackend = backend if backend is not None else MiniaudioBackend()
        self._reopen_delays_s = tuple(float(delay) for delay in reopen_delays_s)

        # Estado de la cola, bajo `_lock`. El hilo de audio y los de la API lo comparten.
        self._lock = threading.Lock()
        self._queue: deque[_Unit] = deque()  # unidades que aún no han empezado, en orden FIFO
        self._current: _Unit | None = None  # la que suena
        self._by_id: dict[int, _Unit] = {}  # la que suena y las que esperan
        self._closed: set[int] = set()  # terminadas o canceladas: sus trozos posteriores se ignoran
        self._pending_samples = 0
        self._last_event_at = 0.0
        self._underruns = 0
        self._in_glitch = False
        self._last_render_at: float | None = None
        self._started = False
        self._stopped = False
        self._stream: PlaybackStream | None = None
        self._generation = 0  # cada dispositivo abierto tiene la suya: los avisos de uno viejo no cuentan
        self._lost = False  # miniaudio avisó de `stopped`: hay que reabrir
        self._reopens = 0
        self._reroutes = 0
        self._hook_failures = 0

        # El volumen lo escribe cualquier hilo (asignación atómica); `_applied_gain` solo el hilo de audio.
        self._gain = 1.0
        self._applied_gain = 1.0

        # Salida de eventos hacia `on_event`.
        self._on_event: Callable[[PlaybackEvent], None] | None = None
        self._outbox: deque[PlaybackEvent] = deque()
        self._outbox_cv = threading.Condition()
        self._outbox_closed = False
        self._posted = 0
        self._delivered = 0

        self._stop_event = threading.Event()
        self._wake = threading.Event()  # despierta al hilo vigilante: hay que reabrir o parar
        self._dispatcher: threading.Thread | None = None
        self._supervisor: threading.Thread | None = None

    # --- AudioSink -------------------------------------------------------------------------------

    def start(self, on_event: Callable[[PlaybackEvent], None]) -> None:
        """Abre el dispositivo y arranca los hilos. Lanza `EngineError` si no se puede abrir el dispositivo.

        Llamarlo otra vez solo cambia el destino de los eventos. Tras `stop()` no hace nada.
        """
        with self._lock:
            self._on_event = on_event
            if self._started or self._stopped:
                return
            self._started = True
        try:
            self._open_stream()
        except BaseException:
            with self._lock:
                self._started = False
            raise
        self._dispatcher = threading.Thread(
            target=self._dispatch_loop, name="reproduccion-eventos", daemon=True
        )
        self._supervisor = threading.Thread(
            target=self._supervise, name="reproduccion-vigilante", daemon=True
        )
        self._dispatcher.start()
        self._supervisor.start()

    def enqueue(self, piece: SpeechPiece) -> None:
        """Encola un trozo sin bloquear. Los de una unidad ya terminada o cancelada se ignoran."""
        samples = np.asarray(piece.samples, dtype=np.float32)
        if samples.ndim != 1:
            raise ValueError(
                f"El audio del trozo debe ser mono (un array 1-D); forma recibida: {samples.shape}."
            )
        with self._lock:
            if self._stopped or piece.unit_id in self._closed:
                return
            unit = self._by_id.get(piece.unit_id)
            if unit is None:
                unit = _Unit(piece.unit_id)
                self._by_id[piece.unit_id] = unit
                self._queue.append(unit)
            if len(samples):
                unit.pieces.append(samples)
                unit.available += len(samples)
                self._pending_samples += len(samples)
            if piece.is_last:
                unit.complete = True

    def cancel_pending(self) -> list[int]:
        """Descarta las unidades que no han empezado (un CANCELLED por cada una) y devuelve sus `unit_id`."""
        with self._lock:
            at = self._stamp_locked(self._clock.now())
            cancelled = [unit.unit_id for unit in self._queue]
            for unit in self._queue:
                self._drop_locked(unit, at)
            self._queue.clear()
        return cancelled

    def set_volume(self, gain: float) -> None:
        """Volumen de la voz en español, de 0,0 a 2,0 (fuera de rango se acota). No toca el del sistema.

        El cambio se aplica con una rampa dentro del siguiente bloque, sin chasquido. `ValueError` si el valor
        no es un número finito.
        """
        if not math.isfinite(gain):
            raise ValueError(f"El volumen debe ser un número finito (recibido: {gain}).")
        self._gain = min(MAX_GAIN, max(0.0, float(gain)))

    def pending_seconds(self) -> float:
        """Audio encolado aún sin entregar al dispositivo (incluido lo que queda de la unidad en curso)."""
        with self._lock:
            return max(0, self._pending_samples) / PLAYBACK_RATE

    def stop(self) -> None:
        """Corta lo que suena, vacía la cola con CANCELLED por unidad y cierra el dispositivo. Idempotente."""
        # Primero se cancela todo bajo el cerrojo; luego se paran los hilos y se cierra el dispositivo.
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            at = self._stamp_locked(self._clock.now())
            units = ([self._current] if self._current is not None else []) + list(self._queue)
            for unit in units:
                self._drop_locked(unit, at)
            self._current = None
            self._queue.clear()
        self._stop_event.set()
        self._wake.set()
        current = threading.current_thread()
        supervisor = self._supervisor
        if supervisor is not None and supervisor is not current:
            supervisor.join(timeout=_JOIN_TIMEOUT_S)
        with self._lock:
            stream, self._stream = self._stream, None
            self._generation += 1
        if stream is not None:
            _close_quietly(stream)
        with self._outbox_cv:
            self._outbox_closed = True
            self._outbox_cv.notify_all()
        dispatcher = self._dispatcher
        if dispatcher is not None and dispatcher is not current:
            dispatcher.join(timeout=_JOIN_TIMEOUT_S)

    # --- Extras (fuera del contrato) -----------------------------------------------------------------

    @property
    def underruns(self) -> int:
        """Cortes audibles de la voz hasta ahora (ver «Underruns» en el módulo)."""
        with self._lock:
            return self._underruns

    @property
    def reopens(self) -> int:
        """Veces que se reabrió el dispositivo tras un `stopped`."""
        with self._lock:
            return self._reopens

    @property
    def reroutes(self) -> int:
        """Veces que miniaudio siguió al dispositivo por defecto a otro (`rerouted`)."""
        with self._lock:
            return self._reroutes

    @property
    def volume(self) -> float:
        """El volumen pedido con `set_volume` (1,0 al empezar)."""
        return self._gain

    @property
    def on_rendered(self) -> Callable[[Samples, float], None] | None:
        """El gancho de lo reproducido; se puede cambiar con el sink en marcha."""
        return self._on_rendered

    @on_rendered.setter
    def on_rendered(self, hook: Callable[[Samples, float], None] | None) -> None:
        self._on_rendered = hook

    def flush_events(self, timeout_s: float = 2.0) -> bool:
        """Espera a que `on_event` haya recibido todo lo emitido hasta ahora. False si pasa `timeout_s`.

        Desde el propio hilo de eventos (un `on_event` que llama a esto) devuelve True sin esperar.
        """
        if threading.current_thread() is self._dispatcher:
            return True
        with self._outbox_cv:
            target = self._posted
            return self._outbox_cv.wait_for(lambda: self._delivered >= target, timeout=timeout_s)

    # --- Hilo de audio ---------------------------------------------------------------------------------

    def _render(self, frames: int) -> Samples:
        """Genera el audio de un periodo (`frames` fotogramas). Lo llama el hilo de audio del dispositivo."""
        now = self._clock.now()
        mono = np.zeros(frames, dtype=np.float32)
        with self._lock:
            if self._stopped:
                return np.zeros((frames, CHANNELS), dtype=np.float32)
            played = self._fill_locked(mono, now)
        target = self._gain
        if played:
            mono = self._apply_gain(mono, target)
            hook = self._on_rendered
            if hook is not None:
                self._call_hook(hook, mono, now)
        self._applied_gain = target
        out = np.empty((frames, CHANNELS), dtype=np.float32)
        out[:] = mono[:, None]
        return out

    def _fill_locked(self, mono: Samples, now: float) -> int:
        """Copia en `mono` el audio de las unidades en curso y emite sus eventos.

        Devuelve cuántas muestras de voz copió (0 si no sonaba nada en este bloque).
        """
        frames = len(mono)
        was_playing = self._current is not None
        late = (
            was_playing and self._last_render_at is not None and now - self._last_render_at > LATE_CALLBACK_S
        )
        self._last_render_at = now
        pos = played = 0
        starved = False
        while pos < frames:
            unit = self._current
            if unit is None:
                unit = self._next_startable_locked()
                if unit is None:
                    break
                self._current = unit
                self._post(unit.unit_id, PlaybackEventKind.STARTED, now + pos / PLAYBACK_RATE)
            taken = unit.take_into(mono, pos, frames - pos)
            pos += taken
            played += taken
            self._pending_samples -= taken
            if unit.complete and unit.available == 0:
                self._post(unit.unit_id, PlaybackEventKind.FINISHED, now + pos / PLAYBACK_RATE)
                self._current = None
                self._by_id.pop(unit.unit_id, None)
                self._closed.add(unit.unit_id)
                continue
            if pos < frames:
                starved = True  # la unidad que suena se quedó sin datos: silencio hasta el siguiente trozo
                break
        glitch = starved or late
        if glitch and not self._in_glitch:
            self._underruns += 1
        self._in_glitch = glitch
        return played

    def _next_startable_locked(self) -> _Unit | None:
        """Saca de la cola la primera unidad si ya tiene audio (o es una unidad vacía ya completa)."""
        if self._queue:
            head = self._queue[0]
            if head.available > 0 or head.complete:
                return self._queue.popleft()
        return None

    def _apply_gain(self, mono: Samples, target: float) -> Samples:
        """Aplica el volumen (con rampa si cambió desde el bloque anterior) y limita a [-1, 1]."""
        applied = self._applied_gain
        if target != applied:
            mono *= np.linspace(applied, target, len(mono) + 1, dtype=np.float32)[1:]
        elif target != 1.0:
            mono *= np.float32(target)
        if target > 1.0 or applied > 1.0:
            np.clip(mono, -1.0, 1.0, out=mono)
        return mono

    def _call_hook(self, hook: Callable[[Samples, float], None], mono: Samples, at: float) -> None:
        try:
            hook(mono, at)
        except Exception:
            self._hook_failures += 1
            if self._hook_failures == 1:  # una vez: un gancho roto se llamaría 50 veces por segundo
                logger.exception("Falló el gancho on_rendered; el audio sigue sonando")

    # --- Eventos ---------------------------------------------------------------------------------------

    def _stamp_locked(self, at: float) -> float:
        """Hora del evento: nunca anterior a la del último emitido."""
        if at < self._last_event_at:
            return self._last_event_at
        self._last_event_at = at
        return at

    def _post(self, unit_id: int, kind: PlaybackEventKind, at: float) -> None:
        """Deja un evento en la salida. Se llama con `_lock` tomado: así el orden es el de los cambios."""
        event = PlaybackEvent(unit_id, kind, self._stamp_locked(at))
        with self._outbox_cv:
            self._outbox.append(event)
            self._posted += 1
            self._outbox_cv.notify_all()

    def _drop_locked(self, unit: _Unit, at: float) -> None:
        """Descarta una unidad que no terminó: libera su audio y emite CANCELLED."""
        self._pending_samples -= unit.available
        unit.pieces.clear()
        unit.available = 0
        self._by_id.pop(unit.unit_id, None)
        self._closed.add(unit.unit_id)
        self._post(unit.unit_id, PlaybackEventKind.CANCELLED, at)

    def _dispatch_loop(self) -> None:
        """Entrega los eventos a `on_event`, de uno en uno y en orden, fuera de todo cerrojo del sink."""
        while True:
            with self._outbox_cv:
                while not self._outbox and not self._outbox_closed:
                    self._outbox_cv.wait()
                if not self._outbox:
                    return  # cerrado y vacío
                event = self._outbox.popleft()
                callback = self._on_event
            try:
                if callback is not None:
                    callback(event)
            except Exception:
                logger.exception("Falló el callback de eventos de reproducción (unidad %s)", event.unit_id)
            finally:
                with self._outbox_cv:
                    self._delivered += 1
                    self._outbox_cv.notify_all()

    # --- Dispositivo: abrir, avisos y recuperación -------------------------------------------------------

    def _open_stream(self) -> None:
        """Abre el dispositivo y lo instala. Lanza `EngineError` si no se puede."""
        with self._lock:
            self._generation += 1
            generation = self._generation
        notify = functools.partial(self._on_notification, generation)
        try:
            stream = self._backend.open(self._render, notify)
        except EngineError:
            raise
        except Exception as exc:
            raise EngineError(f"No se pudo abrir la salida de audio: {exc}", engine=ENGINE_NAME) from exc
        with self._lock:
            late = self._stopped  # `stop()` llegó mientras se abría
            if not late:
                self._stream = stream
                self._last_render_at = None  # la primera petición del dispositivo nuevo no es «tardía»
                self._in_glitch = False
        if late:
            _close_quietly(stream)

    def _on_notification(self, generation: int, name: str) -> None:
        """Aviso de miniaudio (desde cualquiera de sus hilos). Solo anota y despierta al vigilante."""
        with self._lock:
            if self._stopped or generation != self._generation:
                return  # el dispositivo ya se cerró o se sustituyó: sus avisos no cuentan
            if name == "stopped":
                self._lost = True
            elif name == "rerouted":
                self._reroutes += 1
        if name == "stopped":
            logger.warning("El dispositivo de salida de audio se detuvo; se reabrirá.")
            self._wake.set()
        elif name == "rerouted":
            logger.info("La salida de audio siguió al nuevo dispositivo por defecto.")
            self._warn("La salida de audio cambió de dispositivo.")
        else:
            logger.debug("Notificación del dispositivo de audio: %s", name)

    def _supervise(self) -> None:
        """Hilo vigilante: cuando miniaudio avisa de `stopped`, reabre el dispositivo."""
        while True:
            self._wake.wait()
            self._wake.clear()
            if self._stopped:
                return
            with self._lock:
                lost = self._lost
            if lost:
                self._recover()

    def _recover(self) -> None:
        """Cierra el dispositivo perdido y reintenta abrir otro, con esperas crecientes, hasta lograrlo."""
        with self._lock:
            old, self._stream = self._stream, None
            self._generation += 1  # los avisos del dispositivo viejo ya no cuentan
        if old is not None:
            _close_quietly(old)
        self._warn("La salida de audio se detuvo: reabriendo el dispositivo.")
        attempt = 0
        while True:
            delay = self._reopen_delays_s[min(attempt, len(self._reopen_delays_s) - 1)]
            if self._stop_event.wait(delay):
                return
            try:
                self._open_stream()
            except Exception as exc:
                attempt += 1
                if attempt == 1:
                    self._warn(f"No se pudo reabrir la salida de audio ({exc}). Se sigue intentando.")
                else:
                    logger.warning("Reapertura de la salida de audio fallida (intento %d): %s", attempt, exc)
                continue
            if self._stopped:
                return  # `stop()` llegó mientras se abría: `_open_stream` ya cerró el dispositivo nuevo
            with self._lock:
                self._lost = False
                self._reopens += 1
            self._warn("La salida de audio se ha reabierto.")
            return

    def _warn(self, message: str) -> None:
        logger.warning(message)
        callback = self._on_warning
        if callback is None:
            return
        try:
            callback(message)
        except Exception:
            logger.exception("Falló el callback on_warning de la reproducción")
