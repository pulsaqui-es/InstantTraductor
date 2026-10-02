"""Escuchar solo la aplicación elegida: `AppLoopbackSource` (spec 002, ADR-0012, research R4).

Implementa `AudioSource` (16 kHz, mono, float32, chunks contiguos) sobre `ProcessLoopbackSource(include=True)`
y un **vigilante** que sigue a la app por su ejecutable. Se porta el `AppWatcher` del spike S6
(`spikes/captura_app/capturar_app.py`). La identidad que se escucha es la **ruta del ejecutable**; el PID
raíz cambia al reiniciar la app y lo busca el vigilante.

Estados (`AppCaptureState`, data-model.md):

    esperando ──(aparece la app: abre INCLUDE)──▶ sonando
    sonando   ──(muere o cambia el PID)────────▶ esperando
    sonando   ──(la sonda dice que suena y llegan ceros ≥ 4 s)──▶ silencio (aviso)
    silencio  ──(llega audio)──────────────────▶ sonando

- **Vigilante** cada 0,25 s por (PID, `create_time`): si la raíz muere, cierra la captura y vuelve a esperar;
  cuando la app aparece (o reaparece con otro PID) abre una INCLUDE nueva sobre su proceso raíz. La
  reanudación medida en S6 fue de 32-187 ms desde que la app vuelve a sonar.
- **Mientras espera** entrega chunks de ceros de 20 ms a ritmo del `Clock`, para que el pipeline siga vivo y
  no se capte ninguna otra fuente (FR-010). El VAD no abre nada con silencio digital.
- **Continuidad:** los chunks que salen son siempre contiguos (el reloj de audio cuenta las muestras
  entregadas), aunque cambie la captura de debajo: cada `ProcessLoopbackSource` cuenta su propio audio
  desde cero y aquí se vuelve a sellar.
- **Aviso «suena pero llega silencio»:** cuando la captura lleva ≥ 4 s sin audio audible se consulta la
  sonda (por defecto, el medidor de pico de las sesiones de la app, independiente de la captura). Solo si
  dice que la app suena se pasa a `silencio` y se avisa: es el fallo silencioso de un PID equivocado, de
  contenido con DRM o de un modo exclusivo. Con el medidor que copia la mezcla del dispositivo (Discord,
  medido en S6) la sonda no afirma nada.
- `arrival_time` y `current_pid` sirven a las métricas y a la interfaz.

Hilos: uno de **bombeo** (lee la captura o genera ceros y publica los chunks) y uno **vigilante**. Los
callbacks `on_state` y `on_warning` se llaman desde esos hilos: deben volver enseguida y pueden fallar sin
parar la fuente. Los tests sin hilo manejan `_watch_once` y `_pump_once` a mano con un reloj manual.
"""

from __future__ import annotations

import logging
import os
import threading
from collections import deque
from collections.abc import Callable
from enum import StrEnum
from typing import Final

import numpy as np
import numpy.typing as npt

from instanttraductor.audio.app_types import AppIdentity, ProcessTable
from instanttraductor.audio.apps import SystemProcessTable, app_session_peaks, file_description
from instanttraductor.audio.wasapi_capture import ArrivalLog, ProcessLoopbackSource
from instanttraductor.contracts import CAPTURE_RATE, AudioChunk, AudioSource, Clock

logger = logging.getLogger(__name__)

__all__ = [
    "AUDIBLE_PEAK",
    "SILENT_AFTER_S",
    "WATCH_INTERVAL_S",
    "AppCaptureState",
    "AppLoopbackSource",
    "CaptureFactory",
    "SoundProbe",
    "meter_probe",
    "meter_says_sounding",
]

Samples = npt.NDArray[np.float32]

CHUNK_S: Final = 0.02  # tamaño de los chunks de ceros (los de la captura llegan como los dé)
WATCH_INTERVAL_S: Final = 0.25  # periodo del vigilante
AUDIBLE_PEAK: Final = 1e-4  # -80 dBFS: por debajo, silencio digital
SILENT_AFTER_S: Final = 4.0  # sin audio audible durante tanto, y con la sonda diciendo «suena», se avisa
PROBE_INTERVAL_S: Final = 3.0  # entre dos consultas a la sonda mientras la captura sigue muda
OPEN_RETRY_S: Final = 2.0  # espera tras no poder abrir la captura de una app que sí está abierta
SESSION_PEAK: Final = 0.003  # pico de sesión (-50 dBFS) a partir del cual la app «suena» según el medidor
MAX_BACKLOG_S: Final = 60.0  # tope de audio sin leer; por encima se descarta lo más antiguo y se avisa
_PUMP_WAIT_S: Final = 0.01
_EPS: Final = 1e-9
_MAX_DRAIN: Final = 100  # chunks de la captura que se vacían de una vez


class AppCaptureState(StrEnum):
    """Estado de la escucha de la app (data-model.md, AppCaptureState). El valor es el texto del estado."""

    WAITING = "esperando"  # la app no está abierta: se entregan ceros a ritmo de reloj
    PLAYING = "sonando"  # captura INCLUDE abierta sobre la app
    SILENT = "silencio"  # la sonda dice que la app suena, pero la captura entrega ceros


# (PID raíz) -> captura INCLUDE sin arrancar. Los tests inyectan una falsa.
CaptureFactory = Callable[[int], AudioSource]
# (identidad de la app) -> ¿suena según una vía independiente de la captura? Los tests inyectan una falsa.
SoundProbe = Callable[[AppIdentity], bool]


def meter_says_sounding(app_peak: float, others_peak: float) -> bool:
    """Decide con los picos de sesión si la app suena (la parte pura de `meter_probe`).

    El medidor de una sesión de Discord copia la mezcla del dispositivo (S6): si el de la app iguala o supera
    al de otra app que también marca, no vale para afirmar nada.
    """
    if app_peak < SESSION_PEAK:
        return False
    return not (others_peak >= SESSION_PEAK and app_peak >= others_peak - 1e-4)


def meter_probe(identity: AppIdentity) -> bool:
    """Sonda real: ¿marca el medidor de pico de las sesiones de la app? Cuesta ~0,4 s (enumera endpoints)."""
    app_peak, others_peak = app_session_peaks(identity.exe_path)
    return meter_says_sounding(app_peak, others_peak)


class AppLoopbackSource:
    """`AudioSource` en vivo con el audio de una sola aplicación, por su ejecutable.

    - `clock`: reloj de sesión; marca el ritmo de los ceros y la hora de llegada de los chunks.
    - `exe_path`: ruta del ejecutable de la app (`AppIdentity.exe_path`).
    - `process_table`: sistema de procesos (por defecto `SystemProcessTable`, con psutil).
    - `capture_factory`: crea la captura INCLUDE de un PID (por defecto `ProcessLoopbackSource` con el mismo
      reloj, y sus avisos van a `on_warning`).
    - `probe`: sonda del aviso de silencio (por defecto `meter_probe`).
    - `on_state(estado, nombre)`: cada cambio de estado, con el nombre visible de la app. También el inicial.
    - `on_warning(texto)`: avisos para la persona, en español.

    `start()` no falla porque la app no esté abierta: queda en `esperando`. Un fallo al abrir la captura de
    una app abierta solo avisa y se reintenta cada 2 s. `stop()` es idempotente; desde entonces `exhausted`
    es True.
    """

    sample_rate: int = CAPTURE_RATE

    def __init__(
        self,
        clock: Clock,
        exe_path: str,
        *,
        process_table: ProcessTable | None = None,
        capture_factory: CaptureFactory | None = None,
        probe: SoundProbe | None = None,
        on_state: Callable[[AppCaptureState, str], None] | None = None,
        on_warning: Callable[[str], None] | None = None,
    ) -> None:
        self._clock = clock
        self._exe_path = exe_path
        self._table: ProcessTable = process_table or SystemProcessTable()
        self._factory: CaptureFactory = capture_factory or self._default_capture
        self._probe: SoundProbe = probe or meter_probe
        self._on_state = on_state
        self._on_warning = on_warning
        self._chunk_len = round(CHUNK_S * CAPTURE_RATE)
        self._max_backlog = round(MAX_BACKLOG_S / CHUNK_S)

        # Estado compartido entre el hilo de bombeo y el vigilante, bajo `_lock`.
        self._lock = threading.Lock()
        self._state = AppCaptureState.WAITING
        self._name = file_description(exe_path) or os.path.splitext(os.path.basename(exe_path))[0] or exe_path
        self._identity: AppIdentity | None = None
        self._capture: AudioSource | None = None
        self._opened_at = 0.0
        self._last_audible_at = 0.0

        # Solo los toca el hilo de bombeo (o el test, a mano).
        self._origin = 0.0
        self._emitted = 0  # muestras publicadas: el reloj de audio
        self._overflowed = False

        # Solo los toca el vigilante (o el test, a mano).
        self._next_open_at = 0.0
        self._last_probe_at: float | None = None
        self._silent_since = 0.0

        # Cola hacia `read`.
        self._cond = threading.Condition()
        self._queue: deque[AudioChunk] = deque()
        self._stopped = False
        self._started = False

        self._arrivals = ArrivalLog()
        self._stop_event = threading.Event()
        self._threads: list[threading.Thread] = []

    # --- AudioSource -----------------------------------------------------------------------------

    def start(self) -> None:
        """Busca la app (una vez, enseguida) y lanza los hilos. No falla si la app no está. Idempotente."""
        with self._cond:
            if self._started or self._stopped:
                return
            self._started = True
        self._origin = self._clock.now()
        self._notify_state()
        try:
            self._watch_once()
        except Exception:
            logger.exception("Falló la primera búsqueda de la app")
        for name, target in (("app-bombeo", self._pump_loop), ("app-vigilante", self._watch_loop)):
            thread = threading.Thread(target=target, name=name, daemon=True)
            self._threads.append(thread)
            thread.start()

    def read(self, timeout: float) -> AudioChunk | None:
        """Siguiente chunk. Espera hasta `timeout` s; None si no llega ninguno o la fuente está parada."""
        with self._cond:
            self._cond.wait_for(lambda: bool(self._queue) or self._stopped, timeout=max(0.0, timeout))
            if self._stopped or not self._queue:
                return None
            self._overflowed = False  # el consumidor sigue vivo: un nuevo desbordamiento volverá a avisar
            return self._queue.popleft()

    @property
    def exhausted(self) -> bool:
        """True tras `stop()`: ya no llegarán más datos."""
        with self._cond:
            return self._stopped

    def stop(self) -> None:
        """Detiene los hilos y la captura y descarta lo que no se haya leído. Idempotente."""
        with self._cond:
            self._stopped = True
            self._queue.clear()
            self._cond.notify_all()
        self._stop_event.set()
        for thread in self._threads:
            if thread is not threading.current_thread():
                thread.join(timeout=2.0)
        self._close_capture()

    # --- Lo que se consulta desde fuera ----------------------------------------------------------

    @property
    def state(self) -> AppCaptureState:
        with self._lock:
            return self._state

    @property
    def app_name(self) -> str:
        """Nombre visible de la app (el de su ejecutable hasta que se la encuentra)."""
        with self._lock:
            return self._name

    @property
    def current_pid(self) -> int | None:
        """PID raíz sobre el que hay una captura abierta ahora, o None si está esperando."""
        with self._lock:
            identity = self._identity if self._capture is not None else None
        return identity.root_pid if identity is not None else None

    def arrival_time(self, t_audio: float) -> float | None:
        """Hora de llegada (reloj de sesión) del chunk que contiene el instante de audio `t_audio`.

        Los chunks de ceros llegan cuando toca por el reloj; los de la captura, cuando los dio Windows. None
        si ese audio aún no se ha entregado o es más antiguo que los últimos 30 s.
        """
        return self._arrivals.lookup(t_audio)

    # --- Hilo de bombeo --------------------------------------------------------------------------

    def _pump_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                with self._lock:
                    capturing = self._capture is not None
                if not capturing:
                    self._stop_event.wait(_PUMP_WAIT_S)
                self._pump_once(wait_s=_PUMP_WAIT_S if capturing else 0.0)
            except Exception:
                logger.exception("Error inesperado en el hilo de bombeo de la app")
                self._stop_event.wait(_PUMP_WAIT_S)

    def _pump_once(self, *, wait_s: float = 0.0) -> None:
        """Un paso: pasa a la cola lo que dio la captura o, sin captura, los ceros que toquen. No bloquea."""
        with self._lock:
            capture = self._capture
        now = self._clock.now()
        if capture is None:
            self._fill_zeros(now)
            return
        chunk = capture.read(wait_s)
        count = 0
        while chunk is not None:
            self._forward(capture, chunk)
            count += 1
            chunk = capture.read(0.0) if count < _MAX_DRAIN else None

    def _fill_zeros(self, now: float) -> None:
        """Ceros hasta alcanzar el reloj: los chunks de 20 ms salen contiguos y a su ritmo."""
        elapsed = now - self._origin
        while (self._emitted + self._chunk_len) / CAPTURE_RATE <= elapsed + _EPS:
            self._publish(np.zeros(self._chunk_len, dtype=np.float32), now)

    def _forward(self, capture: AudioSource, chunk: AudioChunk) -> None:
        samples = np.asarray(chunk.samples, dtype=np.float32)
        if not len(samples):
            return
        now = self._clock.now()
        arrival = now
        arrival_of = getattr(capture, "arrival_time", None)
        if arrival_of is not None:
            arrival = arrival_of(chunk.t_end)
            arrival = now if arrival is None else arrival
        if float(np.max(np.abs(samples))) >= AUDIBLE_PEAK:
            with self._lock:
                self._last_audible_at = now
        self._publish(samples, arrival)

    def _publish(self, samples: Samples, arrival: float) -> None:
        chunk = AudioChunk(samples=samples, sample_rate=CAPTURE_RATE, t_start=self._emitted / CAPTURE_RATE)
        self._emitted += len(samples)
        self._arrivals.record(chunk.t_start, chunk.t_end, arrival)
        overflow = False
        with self._cond:
            if self._stopped:
                return
            self._queue.append(chunk)
            dropped = False
            while len(self._queue) > self._max_backlog:
                self._queue.popleft()  # se pierde audio, pero la memoria no crece sin límite
                dropped = True
            if dropped and not self._overflowed:
                self._overflowed = overflow = True
            self._cond.notify()
        if overflow:
            self._warn("El consumidor del audio no da abasto: se descarta el audio más antiguo de la app.")

    # --- Vigilante -------------------------------------------------------------------------------

    def _watch_loop(self) -> None:
        while not self._stop_event.wait(WATCH_INTERVAL_S):
            try:
                self._watch_once()
            except Exception:
                logger.exception("Error inesperado en el vigilante de la app")

    def _watch_once(self) -> None:
        """Un sondeo del vigilante: ¿sigue viva la raíz?, ¿hay que abrir la captura?, ¿llega silencio?"""
        now = self._clock.now()
        with self._lock:
            capture, identity = self._capture, self._identity
        if capture is not None and identity is not None:
            if not self._table.is_alive(identity.root_pid, identity.create_time):
                logger.info("%s se ha cerrado: se espera a que vuelva a abrirse", identity.display_name)
                self._close_capture()
                self._set_state(AppCaptureState.WAITING)
                capture = None
            elif capture.exhausted and not self._stop_event.is_set():
                self._warn(f"La captura de {identity.display_name} se detuvo: se vuelve a abrir.")
                self._close_capture()
                self._next_open_at = now
                capture = None
        if capture is None:
            self._open_if_running(now)
        else:
            self._check_silence(now, identity)

    def _open_if_running(self, now: float) -> None:
        if now < self._next_open_at or self._stop_event.is_set():
            return
        roots = self._table.find_roots(self._exe_path)
        if not roots:
            return
        identity = min(roots, key=lambda root: root.create_time)  # varias instancias: la más antigua
        try:
            capture = self._factory(identity.root_pid)
            capture.start()
        except Exception as exc:
            self._next_open_at = now + OPEN_RETRY_S
            self._warn(f"No se pudo abrir la captura de {identity.display_name}: {exc}. Se reintenta.")
            return
        with self._lock:
            if self._stop_event.is_set():
                stale = capture
            else:
                stale = None
                self._capture, self._identity, self._name = capture, identity, identity.display_name
                self._opened_at = self._last_audible_at = now
        if stale is not None:
            stale.stop()
            return
        self._last_probe_at = None
        logger.info("Escuchando %s (PID %s)", identity.display_name, identity.root_pid)
        self._set_state(AppCaptureState.PLAYING)

    def _check_silence(self, now: float, identity: AppIdentity | None) -> None:
        with self._lock:
            state, last_audible = self._state, max(self._last_audible_at, self._opened_at)
        if state is AppCaptureState.SILENT:
            if last_audible > self._silent_since:  # llegó audio desde que se avisó
                self._set_state(AppCaptureState.PLAYING)
            return
        if state is not AppCaptureState.PLAYING or identity is None:
            return
        if now - last_audible < SILENT_AFTER_S:
            self._last_probe_at = None
            return
        if self._last_probe_at is not None and now - self._last_probe_at < PROBE_INTERVAL_S:
            return
        self._last_probe_at = now
        try:
            sounding = self._probe(identity)
        except Exception:
            logger.exception("Falló la sonda del aviso de silencio")
            return
        if sounding:
            self._silent_since = now
            self._set_state(AppCaptureState.SILENT)
            self._warn(
                f"{identity.display_name} suena, pero la captura llega en silencio desde hace "
                f"{now - last_audible:.0f} s (¿contenido protegido o audio por otro proceso?)."
            )

    def _close_capture(self) -> None:
        with self._lock:
            capture, self._capture = self._capture, None
        if capture is not None:
            try:
                capture.stop()
            except Exception:
                logger.exception("Error al cerrar la captura de la app")

    # --- Estado y callbacks ----------------------------------------------------------------------

    def _set_state(self, state: AppCaptureState) -> None:
        with self._lock:
            if state is self._state:
                return
            self._state = state
        self._notify_state()

    def _notify_state(self) -> None:
        with self._lock:
            state, name = self._state, self._name
        logger.info("Escucha de la app: %s (%s)", state.value, name)
        self._call(self._on_state, state, name)

    def _warn(self, message: str) -> None:
        logger.warning(message)
        self._call(self._on_warning, message)

    @staticmethod
    def _call(callback: Callable[..., None] | None, *args: object) -> None:
        """Llama a un callback del suscriptor sin dejar que su fallo pare la fuente."""
        if callback is None:
            return
        try:
            callback(*args)
        except Exception:
            logger.exception("Falló un callback de la fuente de la app")

    def _default_capture(self, pid: int) -> AudioSource:
        return ProcessLoopbackSource(self._clock, include=True, target_pid=pid, on_warning=self._warn)
