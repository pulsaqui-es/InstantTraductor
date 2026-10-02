"""Captura del audio del PC por proceso (*process loopback* de WASAPI): `ProcessLoopbackSource`.

Implementa `AudioSource` (16 kHz, mono, float32, chunks contiguos de 20 ms) con la activación propia de
`ActivateAudioInterfaceAsync` en modo `PROCESS_LOOPBACK` (ADR-0010, research R2 y R3). Windows entrega «todo
el sonido del PC salvo el del proceso objetivo» (`include=False`, EXCLUDE) o «solo el del proceso objetivo»
(`include=True`, INCLUDE: el control positivo del autotest). El objetivo por defecto es el propio núcleo,
que capta y reproduce a la vez: así la voz en español no vuelve a la captura. Windows solo cubre el PID
objetivo y sus hijos directos, no el árbol entero: ningún otro proceso de la app debe reproducir audio.

Piezas, de dentro afuera (todas salvo `_ProcessLoopbackStream` se prueban sin dispositivo):

- `_ProcessLoopbackStream`: el `IAudioClient` de COM y la lectura de sus paquetes (base: el spike S4,
  `spikes/audio/audio_spike/loopback_ctypes.py`). Es lo único que habla con Windows.
- `GapFiller`: red de seguridad que rellena con ceros los huecos de más de 100 ms y se resincroniza con la
  hora de llegada. El audio real nunca se recorta ni se duplica por *jitter*.
- `CaptureWatchdog`: decide cuándo reabrir la captura (más de 0,5 s sin paquetes, error de WASAPI o PID
  objetivo que ya no es el correcto) como máximo una vez cada 10 s.
- `ArrivalLog`: la hora de llegada de cada chunk (reloj de sesión) de los últimos 30 s.
- `ProcessLoopbackSource`: lo une todo en un hilo de captura propio y entrega los chunks por una cola.

Relojes (data-model.md): el reloj de audio cuenta muestras desde la primera que llega y lleva los silencios
rellenados; el de sesión es el `Clock` que recibe la fuente. Los chunks no llevan hora de llegada
(`AudioChunk` está congelado), así que `ProcessLoopbackSource.arrival_time` la da aparte para las métricas.
"""

from __future__ import annotations

import bisect
import contextlib
import ctypes
import functools
import logging
import os
import sys
import threading
from collections import deque
from collections.abc import Callable
from enum import StrEnum
from types import SimpleNamespace
from typing import Final, NamedTuple, Protocol

import numpy as np
import numpy.typing as npt
import psutil

from instanttraductor.contracts import CAPTURE_RATE, AudioChunk, Clock, EngineError

# COM en MTA (ADR-0010). comtypes inicializa COM en el hilo que lo importa y lee este valor en ese momento:
# hay que fijarlo ANTES de que nadie importe comtypes o pycaw. Si otro módulo los importara antes que este,
# el hilo quedaría en STA, que choca con el audio de miniaudio.
sys.coinit_flags = 0

logger = logging.getLogger(__name__)

__all__ = [
    "ARRIVAL_HISTORY_S",
    "ArrivalLog",
    "CaptureWatchdog",
    "GapFiller",
    "Packet",
    "PacketStream",
    "ProcessLoopbackSource",
    "StreamFactory",
    "WatchdogReason",
]

Samples = npt.NDArray[np.float32]

ENGINE_NAME: Final = "capture"

CHUNK_S: Final = 0.02  # tamaño de los chunks que entrega `read` (el recomendado por el contrato)
GAP_THRESHOLD_S: Final = 0.1  # solo se rellenan los huecos de más de 100 ms (R3)
GAP_MARGIN_S: Final = 0.04  # el relleno va 40 ms por detrás del reloj: no inventa ceros antes de un paquete
REANCHOR: Final = 0.02  # fuera de un hueco, la deriva se absorbe moviendo despacio la referencia (2 %)
SILENCE_LIMIT_S: Final = 0.5  # más de 0,5 s sin paquetes: se reabre
MIN_REOPEN_INTERVAL_S: Final = 10.0  # como máximo una reapertura cada 10 s
ARRIVAL_HISTORY_S: Final = 30.0  # histórico de `arrival_time`
MAX_BACKLOG_S: Final = 60.0  # tope de audio sin leer; por encima se descarta lo más antiguo y se avisa

_WAIT_STEP_S: Final = 0.02  # el hilo de captura se despierta al menos cada 20 ms (relleno y vigilante)
_OPEN_TIMEOUT_S: Final = 15.0  # tiempo máximo que `start()` espera a la primera activación
_EPS: Final = 1e-9


# --------------------------------------------------------------------------------------------------
# Paquetes y flujos
# --------------------------------------------------------------------------------------------------


class Packet(NamedTuple):
    """Un paquete leído del dispositivo (en process loopback, 160 muestras cada 10 ms)."""

    arrival: float  # reloj de sesión: instante en que se leyó
    samples: Samples  # mono, float32, a `CAPTURE_RATE`


class PacketStream(Protocol):
    """Lo que `ProcessLoopbackSource` necesita de un flujo de paquetes. Lo cumple `_ProcessLoopbackStream`.

    Todas las operaciones (crearlo, leer, cerrarlo) las hace el hilo de captura: COM se inicializa en él.
    """

    @property
    def error(self) -> str | None:
        """Texto del último error de WASAPI, o None. Un flujo con error se reabre."""
        ...

    def wait(self, timeout_s: float) -> bool:
        """Espera hasta `timeout_s` a que haya paquetes. True si el dispositivo avisó."""
        ...

    def read_packets(self) -> list[Packet]:
        """Vacía los paquetes disponibles, sin bloquear."""
        ...

    def close(self) -> None:
        """Libera el dispositivo. Idempotente."""
        ...


# (pid objetivo, excluir, reloj de sesión) -> flujo. Los tests inyectan uno falso.
StreamFactory = Callable[[int, bool, Callable[[], float]], PacketStream]


def _current_pid() -> int:
    """PID del proceso actual. Aparte para poder sustituirlo en los tests."""
    return os.getpid()


def _pid_exists(pid: int) -> bool:
    """True si el proceso `pid` está vivo. Aparte para poder sustituirlo en los tests."""
    return psutil.pid_exists(pid)


def _fmt_s(seconds: float) -> str:
    """Segundos con coma decimal, como se escriben en la interfaz."""
    return f"{seconds:.1f}".replace(".", ",")


# --------------------------------------------------------------------------------------------------
# GapFiller: relleno de huecos
# --------------------------------------------------------------------------------------------------


class GapFiller:
    """Convierte las llegadas de paquetes, con posibles huecos, en un flujo continuo alineado con el reloj.

    Política (spike S4, `relleno.py`):

    - El audio real **nunca se recorta ni se duplica por *jitter***: un paquete que llega 25 ms tarde sigue
      siendo continuo con el anterior (en process loopback los paquetes se generan contando fotogramas).
    - Solo se rellena con ceros un **hueco real**: más de `gap_threshold_s` (100 ms) sin paquetes.
    - `tick(ahora)` se llama cada 10-20 ms: si hay un hueco, emite ceros hasta `ahora - margin_s`; el margen
      (40 ms) evita inventar ceros justo antes de que llegue un paquete.
    - Al volver los paquetes tras un hueco se alinea exactamente con el reloj: se añaden los ceros que
      falten o, si el relleno se adelantó, se recorta el principio del paquete.
    - Fuera de un hueco, la deriva entre el reloj de audio y el de pared se corrige moviendo despacio la
      referencia (`covered_until`), sin tocar las muestras.

    En process loopback llegan paquetes de ceros cada 10 ms aunque no suene nada, así que el relleno no suele
    entrar en juego: queda como red de seguridad (suspensión, pérdida del dispositivo).

    `push` y `tick` devuelven las muestras que hay que añadir, en orden. Todo se mide en el reloj de sesión.
    """

    def __init__(
        self,
        sample_rate: int = CAPTURE_RATE,
        *,
        gap_threshold_s: float = GAP_THRESHOLD_S,
        margin_s: float = GAP_MARGIN_S,
        reanchor: float = REANCHOR,
    ) -> None:
        self._rate = sample_rate
        self._gap_threshold_s = gap_threshold_s
        self._margin_s = margin_s
        self._reanchor = reanchor
        self._covered_until: float | None = None  # instante hasta el que la salida ya cubre, según el reloj
        self._in_gap = False
        self.real_samples = 0
        self.filled_samples = 0
        self.trimmed_samples = 0
        self.gaps = 0

    @property
    def in_gap(self) -> bool:
        """True mientras dura un hueco (desde que se detecta hasta que vuelve el audio)."""
        return self._in_gap

    @property
    def covered_until(self) -> float | None:
        """Instante (reloj de sesión) hasta el que cubre la salida; None antes del primer paquete."""
        return self._covered_until

    def push(self, arrival_s: float, samples: Samples) -> list[Samples]:
        """Registra un paquete llegado en `arrival_s` y devuelve lo que se emite (ceros y/o el paquete)."""
        out: list[Samples] = []
        duration = len(samples) / self._rate
        start = arrival_s - duration  # el paquete acaba cuando llega
        if self._covered_until is None:
            self._covered_until = start
        offset = start - self._covered_until
        if self._in_gap:
            # Fin de un hueco: alinear exactamente con el reloj.
            if offset > 0:
                self._zeros(offset, out)
            elif offset < 0:
                trimmed = min(round(-offset * self._rate), len(samples))
                samples = samples[trimmed:]
                self.trimmed_samples += trimmed
            self._in_gap = False
        elif offset > self._gap_threshold_s:
            # Un hueco que `tick` aún no había visto (por ejemplo, no se llamó a `tick`).
            self.gaps += 1
            self._zeros(offset, out)
        else:
            # Jitter y deriva: no se toca el audio; la referencia se mueve despacio.
            self._covered_until += offset * self._reanchor
        if len(samples):
            out.append(samples)
            self.real_samples += len(samples)
            self._covered_until += len(samples) / self._rate
        return out

    def tick(self, now_s: float) -> list[Samples]:
        """Llamar cada 10-20 ms: si hay un hueco, devuelve los ceros que lo cubren hasta `now_s - margen`."""
        out: list[Samples] = []
        if self._covered_until is None:
            return out
        limit = now_s - self._margin_s
        if not self._in_gap and limit - self._covered_until > self._gap_threshold_s:
            self._in_gap = True
            self.gaps += 1
        if self._in_gap and limit > self._covered_until:
            self._zeros(limit - self._covered_until, out)
        return out

    def _zeros(self, duration_s: float, out: list[Samples]) -> None:
        count = round(duration_s * self._rate)
        if count > 0:
            out.append(np.zeros(count, dtype=np.float32))
            self.filled_samples += count
            assert self._covered_until is not None
            self._covered_until += count / self._rate


# --------------------------------------------------------------------------------------------------
# CaptureWatchdog: cuándo reabrir
# --------------------------------------------------------------------------------------------------


class WatchdogReason(StrEnum):
    """Por qué hay que reabrir la captura (las tres condiciones de T015)."""

    NO_PACKETS = "no_packets"  # más de 0,5 s sin paquetes
    WASAPI_ERROR = "wasapi_error"  # error de WASAPI al leer
    PID_CHANGED = "pid_changed"  # el PID objetivo ya no es el correcto: la captura seguiría viva sin excluir


class CaptureWatchdog:
    """Vigilante de la captura: decide **cuándo** reabrirla; reabrir lo hace `ProcessLoopbackSource`.

    Prioridad si se dan varias condiciones: PID, error de WASAPI y falta de paquetes. Una vez
    registrada una reapertura (`note_reopen`) no concede otra hasta que pasen `min_reopen_interval_s` (10 s),
    aunque la condición siga dándose: así un fallo persistente no provoca un bucle de reaperturas.
    """

    def __init__(
        self,
        *,
        silence_limit_s: float = SILENCE_LIMIT_S,
        min_reopen_interval_s: float = MIN_REOPEN_INTERVAL_S,
    ) -> None:
        self._silence_limit_s = silence_limit_s
        self._min_reopen_interval_s = min_reopen_interval_s
        self._last_reopen_at: float | None = None

    def check(
        self, now: float, *, last_packet_at: float, error: str | None, target_ok: bool
    ) -> WatchdogReason | None:
        """Motivo para reabrir ahora, o None si todo va bien o aún no toca (límite de 10 s)."""
        reason: WatchdogReason | None = None
        if not target_ok:
            reason = WatchdogReason.PID_CHANGED
        elif error is not None:
            reason = WatchdogReason.WASAPI_ERROR
        elif now - last_packet_at > self._silence_limit_s:
            reason = WatchdogReason.NO_PACKETS
        if reason is None:
            return None
        if self._last_reopen_at is not None and now - self._last_reopen_at < self._min_reopen_interval_s:
            return None
        return reason

    def note_reopen(self, now: float) -> None:
        """Anota un intento de reapertura (haya salido bien o no)."""
        self._last_reopen_at = now


# --------------------------------------------------------------------------------------------------
# ArrivalLog: hora de llegada de cada chunk
# --------------------------------------------------------------------------------------------------


class ArrivalLog:
    """Hora de llegada (reloj de sesión) de los chunks de los últimos `history_s` segundos de audio.

    `lookup(t)` da la llegada del chunk que contiene el instante de audio `t`, con la convención
    `(t_start, t_end]`: un instante justo en la frontera pertenece al chunk que acaba ahí, que es el que
    contiene el final de la frase (`t_end_audio`). Seguro entre hilos.
    """

    def __init__(self, history_s: float = ARRIVAL_HISTORY_S) -> None:
        self._history_s = history_s
        # (t_start, t_end, llegada) de cada chunk, por t_end creciente
        self._items: deque[tuple[float, float, float]] = deque()
        self._lock = threading.Lock()

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def record(self, t_start: float, t_end: float, arrival: float) -> None:
        with self._lock:
            self._items.append((t_start, t_end, arrival))
            horizon = t_end - self._history_s
            while self._items[0][1] < horizon:
                self._items.popleft()

    def lookup(self, t_audio: float) -> float | None:
        """Llegada del chunk que contiene `t_audio`; None si es futuro o más antiguo que el histórico."""
        with self._lock:
            index = bisect.bisect_left(self._items, t_audio - _EPS, key=lambda item: item[1])
            if index >= len(self._items):
                return None
            t_start, _t_end, arrival = self._items[index]
            return arrival if t_audio >= t_start - _EPS else None


# --------------------------------------------------------------------------------------------------
# Capa de Windows: process loopback con ctypes + comtypes
# --------------------------------------------------------------------------------------------------

_HRESULT_NAMES: Final = {
    0x88890004: "AUDCLNT_E_DEVICE_INVALIDATED",
    0x88890018: "AUDCLNT_E_BUFFER_ERROR",
    0x88890010: "AUDCLNT_E_SERVICE_NOT_RUNNING",
    0x88890026: "AUDCLNT_E_RESOURCES_INVALIDATED",
    0x8889000A: "AUDCLNT_E_DEVICE_IN_USE",
    0x88890008: "AUDCLNT_E_UNSUPPORTED_FORMAT",
    0x80070057: "E_INVALIDARG",
    0x80004001: "E_NOTIMPL",
    0x8000000E: "E_ILLEGAL_METHOD_CALL",
}

# Constantes de WASAPI.
_AUDCLNT_SHAREMODE_SHARED: Final = 0
_STREAMFLAGS_LOOPBACK: Final = 0x00020000
_STREAMFLAGS_EVENTCALLBACK: Final = 0x00040000
_STREAMFLAGS_AUTOCONVERTPCM: Final = 0x80000000
_STREAMFLAGS_SRC_DEFAULT_QUALITY: Final = 0x08000000
_BUFFERFLAGS_SILENT: Final = 0x2
_WAVE_FORMAT_IEEE_FLOAT: Final = 3
_VT_BLOB: Final = 65
_ACTIVATION_TYPE_PROCESS_LOOPBACK: Final = 1
_LOOPBACK_MODE_INCLUDE: Final = 0  # solo el proceso objetivo (control positivo)
_LOOPBACK_MODE_EXCLUDE: Final = 1  # todo salvo el proceso objetivo
_WAIT_OBJECT_0: Final = 0
_WAIT_TIMEOUT: Final = 0x102
_MAX_PACKETS_PER_READ: Final = 200  # tope de seguridad por llamada (2 s de audio de 10 ms)


def hresult_name(hresult: int) -> str:
    """Nombre legible de un HRESULT (con el valor en hexadecimal)."""
    hresult &= 0xFFFFFFFF
    return f"{_HRESULT_NAMES.get(hresult, 'HRESULT')} (0x{hresult:08X})"


if sys.platform == "win32":
    from ctypes import (
        HRESULT,
        POINTER,
        byref,
        c_long,
        c_ubyte,
        c_uint32,
        c_uint64,
        c_ulong,
        c_ushort,
        wintypes,
    )

    import comtypes
    from comtypes import COMMETHOD, GUID, COMError, COMObject, IUnknown
    from pycaw.api.audioclient import IAudioClient
    from pycaw.api.audioclient.depend import WAVEFORMATEX

    # -- estructuras de la API de process loopback --------------------------------------------
    class AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS(ctypes.Structure):
        _fields_ = [("TargetProcessId", wintypes.DWORD), ("ProcessLoopbackMode", c_uint32)]

    class AUDIOCLIENT_ACTIVATION_PARAMS(ctypes.Structure):
        _fields_ = [
            ("ActivationType", c_uint32),
            ("ProcessLoopbackParams", AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS),
        ]

    class _BLOB(ctypes.Structure):
        _fields_ = [("cbSize", c_ulong), ("pBlobData", POINTER(c_ubyte))]

    class _PROPVARIANT_DATA(ctypes.Union):
        _fields_ = [("blob", _BLOB), ("_padding", c_ubyte * 16)]

    class PROPVARIANT(ctypes.Structure):
        _fields_ = [
            ("vt", c_ushort),
            ("r1", c_ushort),
            ("r2", c_ushort),
            ("r3", c_ushort),
            ("data", _PROPVARIANT_DATA),
        ]

    # -- interfaces COM -----------------------------------------------------------------------
    class IActivateAudioInterfaceAsyncOperation(IUnknown):
        _iid_ = GUID("{72A22D78-CDE4-431D-B8CC-843A71199B6D}")
        _methods_ = (
            COMMETHOD(
                [],
                HRESULT,
                "GetActivateResult",
                (["out"], POINTER(c_long), "activateResult"),
                (["out"], POINTER(POINTER(IUnknown)), "activatedInterface"),
            ),
        )

    class IActivateAudioInterfaceCompletionHandler(IUnknown):
        _iid_ = GUID("{41D949AB-9862-444A-80F6-C261334DA5EB}")
        _methods_ = (
            COMMETHOD(
                [],
                HRESULT,
                "ActivateCompleted",
                (["in"], POINTER(IActivateAudioInterfaceAsyncOperation), "activateOperation"),
            ),
        )

    class IAgileObject(IUnknown):
        _iid_ = GUID("{94EA2B94-E9CC-49E0-C0FF-EE64CA8F5B90}")
        _methods_ = ()

    class IAudioCaptureClient(IUnknown):
        _iid_ = GUID("{C8ADBD64-E71E-48A0-A4DE-185C395CD317}")
        _methods_ = (
            COMMETHOD(
                [],
                HRESULT,
                "GetBuffer",
                (["out"], POINTER(POINTER(c_ubyte)), "ppData"),
                (["out"], POINTER(c_uint32), "pNumFramesToRead"),
                (["out"], POINTER(c_uint32), "pdwFlags"),
                (["out"], POINTER(c_uint64), "pu64DevicePosition"),
                (["out"], POINTER(c_uint64), "pu64QPCPosition"),
            ),
            COMMETHOD([], HRESULT, "ReleaseBuffer", (["in"], c_uint32, "NumFramesRead")),
            COMMETHOD(
                [], HRESULT, "GetNextPacketSize", (["out"], POINTER(c_uint32), "pNumFramesInNextPacket")
            ),
        )

    class _ActivationHandler(COMObject):
        """`IActivateAudioInterfaceCompletionHandler` + `IAgileObject` (sin el segundo, falla con
        E_ILLEGAL_METHOD_CALL): solo avisa con un `Event` de que terminó la activación."""

        _com_interfaces_ = [IActivateAudioInterfaceCompletionHandler, IAgileObject]

        def __init__(self) -> None:
            super().__init__()
            self.done = threading.Event()

        def ActivateCompleted(self, activateOperation):  # noqa: N802 - el nombre lo fija COM
            # No se toca `activateOperation` (puntero prestado): el resultado lo recoge el hilo que activa.
            self.done.set()
            return 0

    # Manejadores de activaciones que se pasaron de tiempo: Windows podría llamar a `ActivateCompleted` más
    # tarde y el objeto COM tiene que seguir vivo. Solo crece en ese fallo.
    _late_handlers: list[_ActivationHandler] = []

    @functools.cache
    def _win_api() -> SimpleNamespace:
        """Funciones de `Mmdevapi` y `kernel32` con sus prototipos (se cargan al primer uso)."""
        activate = ctypes.WinDLL("Mmdevapi.dll").ActivateAudioInterfaceAsync
        activate.restype = c_long
        activate.argtypes = [
            wintypes.LPCWSTR,
            POINTER(GUID),
            POINTER(PROPVARIANT),
            POINTER(IActivateAudioInterfaceCompletionHandler),
            POINTER(POINTER(IActivateAudioInterfaceAsyncOperation)),
        ]
        kernel32 = ctypes.WinDLL("kernel32.dll")
        kernel32.CreateEventW.restype = wintypes.HANDLE
        kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        return SimpleNamespace(
            activate=activate,
            create_event=kernel32.CreateEventW,
            wait=kernel32.WaitForSingleObject,
            close_handle=kernel32.CloseHandle,
        )

    def _activate_process_client(pid: int, exclude: bool, timeout_s: float):
        """`IAudioClient` del dispositivo virtual de process loopback (EXCLUDE o INCLUDE de `pid`)."""
        try:
            api = _win_api()
        except (OSError, AttributeError) as exc:
            raise EngineError(
                "Este Windows no admite la captura por proceso (hace falta la build 20348 o posterior).",
                engine=ENGINE_NAME,
                recoverable=False,
            ) from exc
        params = AUDIOCLIENT_ACTIVATION_PARAMS()
        params.ActivationType = _ACTIVATION_TYPE_PROCESS_LOOPBACK
        params.ProcessLoopbackParams.TargetProcessId = pid
        params.ProcessLoopbackParams.ProcessLoopbackMode = (
            _LOOPBACK_MODE_EXCLUDE if exclude else _LOOPBACK_MODE_INCLUDE
        )
        variant = PROPVARIANT()
        variant.vt = _VT_BLOB
        variant.data.blob.cbSize = ctypes.sizeof(params)
        variant.data.blob.pBlobData = ctypes.cast(ctypes.pointer(params), POINTER(c_ubyte))

        handler = _ActivationHandler()  # debe seguir vivo hasta que Windows llame a `ActivateCompleted`
        operation = POINTER(IActivateAudioInterfaceAsyncOperation)()
        hr = api.activate(
            "VAD\\Process_Loopback", byref(IAudioClient._iid_), byref(variant), handler, byref(operation)
        )
        if hr < 0:
            raise EngineError(f"ActivateAudioInterfaceAsync falló: {hresult_name(hr)}", engine=ENGINE_NAME)
        if not handler.done.wait(timeout_s):
            _late_handlers.append(handler)  # Windows aún puede llamarlo: que no se libere (fuga mínima)
            raise EngineError("La activación de la captura no terminó a tiempo.", engine=ENGINE_NAME)
        activation_hr, unknown = operation.GetActivateResult()
        if activation_hr < 0:
            raise EngineError(
                f"La activación de la captura falló: {hresult_name(activation_hr)}", engine=ENGINE_NAME
            )
        return unknown.QueryInterface(IAudioClient)

    class _ProcessLoopbackStream:
        """Un `IAudioClient` de process loopback ya activo y la lectura de sus paquetes (16 kHz, float32).

        Pide 16 kHz mono directamente (este dispositivo virtual no tiene *mix format*: Windows convierte).
        Si Windows no acepta mono, pide estéreo y lo mezcla a mono. Crear, leer y cerrar tiene que hacerlo
        el mismo hilo: aquí se inicializa COM (MTA) y aquí se deshace.
        """

        def __init__(
            self,
            pid: int,
            exclude: bool,
            now: Callable[[], float],
            *,
            sample_rate: int = CAPTURE_RATE,
            buffer_ms: int = 100,
            activation_timeout_s: float = 5.0,
        ) -> None:
            self._now = now
            self._sample_rate = sample_rate
            self._error: str | None = None
            self._client = None
            self._capture = None
            self._event = None
            self._channels = 1
            self._com_initialized = False
            comtypes.CoInitializeEx()  # usa sys.coinit_flags (MTA)
            self._com_initialized = True
            try:
                self._open(pid, exclude, buffer_ms, activation_timeout_s)
            except BaseException:
                self.close()
                raise

        @property
        def error(self) -> str | None:
            return self._error

        def _wave_format(self, channels: int) -> WAVEFORMATEX:
            fmt = WAVEFORMATEX()
            fmt.wFormatTag = _WAVE_FORMAT_IEEE_FLOAT
            fmt.nChannels = channels
            fmt.nSamplesPerSec = self._sample_rate
            fmt.wBitsPerSample = 32
            fmt.nBlockAlign = channels * 4
            fmt.nAvgBytesPerSec = self._sample_rate * fmt.nBlockAlign
            fmt.cbSize = 0
            return fmt

        def _open(self, pid: int, exclude: bool, buffer_ms: int, timeout_s: float) -> None:
            flags = (
                _STREAMFLAGS_LOOPBACK
                | _STREAMFLAGS_EVENTCALLBACK
                | _STREAMFLAGS_AUTOCONVERTPCM
                | _STREAMFLAGS_SRC_DEFAULT_QUALITY
            )
            rejected: list[str] = []
            for channels in (1, 2):
                client = _activate_process_client(pid, exclude, timeout_s)  # un cliente nuevo por intento
                try:
                    # Búfer de `buffer_ms` (unidades de 100 ns); en modo compartido la periodicidad es 0.
                    client.Initialize(
                        _AUDCLNT_SHAREMODE_SHARED,
                        flags,
                        buffer_ms * 10_000,
                        0,
                        ctypes.pointer(self._wave_format(channels)),
                        None,
                    )
                except COMError as exc:
                    rejected.append(f"{channels} canal(es): {hresult_name(exc.hresult)}")
                    continue
                self._client = client
                self._channels = channels
                break
            if self._client is None:
                raise EngineError(
                    "No se pudo inicializar la captura (" + "; ".join(rejected) + ").", engine=ENGINE_NAME
                )
            api = _win_api()
            self._event = api.create_event(None, False, False, None)
            if not self._event:
                raise EngineError("No se pudo crear el evento de la captura.", engine=ENGINE_NAME)
            self._client.SetEventHandle(self._event)
            unknown = self._client.GetService(byref(IAudioCaptureClient._iid_))
            self._capture = unknown.QueryInterface(IAudioCaptureClient)
            self._client.Start()

        def wait(self, timeout_s: float) -> bool:
            result = _win_api().wait(self._event, max(0, int(timeout_s * 1000)))
            if result == _WAIT_OBJECT_0:
                return True
            if result != _WAIT_TIMEOUT:
                self._error = f"WaitForSingleObject devolvió {result}"
            return False

        def read_packets(self) -> list[Packet]:
            packets: list[Packet] = []
            capture = self._capture
            if capture is None:
                return packets
            channels = self._channels
            try:
                for _ in range(_MAX_PACKETS_PER_READ):
                    if capture.GetNextPacketSize() == 0:
                        break
                    data, frames, flags, _position, _qpc = capture.GetBuffer()
                    arrival = self._now()
                    try:
                        if frames == 0:
                            break
                        if flags & _BUFFERFLAGS_SILENT:
                            # Según WASAPI el contenido del búfer es indefinido: se trata como ceros.
                            samples = np.zeros(frames, dtype=np.float32)
                        else:
                            raw = (ctypes.c_float * (frames * channels)).from_address(
                                ctypes.addressof(data.contents)
                            )
                            samples = np.frombuffer(raw, dtype=np.float32).copy()
                            if channels > 1:
                                samples = samples.reshape(frames, channels).mean(axis=1).astype(np.float32)
                    finally:
                        capture.ReleaseBuffer(frames)
                    packets.append(Packet(arrival, samples))
            except COMError as exc:
                self._error = hresult_name(exc.hresult)
            return packets

        def close(self) -> None:
            client, self._client = self._client, None
            self._capture = None
            if client is not None:
                with contextlib.suppress(COMError):
                    client.Stop()
            del client  # suelta el puntero COM antes de deshacer COM
            event, self._event = self._event, None
            if event:
                _win_api().close_handle(event)
            if self._com_initialized:
                self._com_initialized = False
                comtypes.CoUninitialize()


def _default_stream_factory(pid: int, exclude: bool, now: Callable[[], float]) -> PacketStream:
    if sys.platform != "win32":
        raise EngineError(
            "La captura por proceso solo existe en Windows.", engine=ENGINE_NAME, recoverable=False
        )
    return _ProcessLoopbackStream(pid, exclude, now)


# --------------------------------------------------------------------------------------------------
# ProcessLoopbackSource
# --------------------------------------------------------------------------------------------------


class ProcessLoopbackSource:
    """`AudioSource` en vivo con el audio del PC: 16 kHz, mono, float32 y chunks contiguos de 20 ms.

    - `include=False` (por defecto): modo EXCLUDE, todo el sonido salvo el del proceso objetivo.
      `include=True`: modo INCLUDE, solo el del proceso objetivo (control positivo del autotest).
    - `target_pid`: por defecto el propio proceso (`os.getpid()`), que capta y reproduce a la vez.
    - Un hilo propio vacía el dispositivo, rellena los huecos de más de 100 ms, cuenta el reloj de audio y
      vigila la captura. `read` solo espera en una cola: el consumidor puede tardar sin perder audio.
    - **Vigilante:** reabre la captura, como máximo una vez cada 10 s, si pasan más de 0,5 s sin paquetes, si
      WASAPI da un error o si el PID objetivo ya no es el correcto (el propio proceso cambió de PID; o, en
      EXCLUDE con un `target_pid` explícito, ese proceso murió). En INCLUDE con un `target_pid` explícito no
      se vigila el PID: quien lo eligió (`AppLoopbackSource`) es quien lo cambia, y reabrir sobre un PID
      muerto no arreglaría nada (ADR-0012). Al reabrir llama a `on_reopen()` para que la sesión repita el
      autotest. **`on_reopen` y `on_warning` se llaman desde el hilo de captura: deben volver enseguida**
      (el autotest, en otro hilo). Si la reapertura falla, solo hay `on_warning`; se reintenta a los 10 s.
    - `on_warning(texto)`: avisos para la persona, en español (hueco en la captura, reapertura, audio sin
      consumir...). Los dos callbacks pueden fallar sin parar la captura.

    `start()` lanza `EngineError` si no se puede abrir el dispositivo. `stop()` es idempotente y desde
    entonces `exhausted` es True. Parámetros de solo prueba: `stream_factory`, `chunk_s` y `max_backlog_s`.
    """

    sample_rate: int = CAPTURE_RATE

    def __init__(
        self,
        clock: Clock,
        *,
        include: bool = False,
        target_pid: int | None = None,
        on_reopen: Callable[[], None] | None = None,
        on_warning: Callable[[str], None] | None = None,
        chunk_s: float = CHUNK_S,
        max_backlog_s: float = MAX_BACKLOG_S,
        stream_factory: StreamFactory | None = None,
    ) -> None:
        self._clock = clock
        self._include = include
        self._follow_process = target_pid is None
        self._target_pid = _current_pid() if target_pid is None else int(target_pid)
        self._on_reopen = on_reopen
        self._on_warning = on_warning
        self._factory: StreamFactory = stream_factory or _default_stream_factory
        self._chunk_len = max(1, round(chunk_s * CAPTURE_RATE))
        self._max_backlog = max(1, round(max_backlog_s / chunk_s))

        # Estado del hilo de captura (solo lo toca ese hilo; los tests sin hilo lo manejan a mano).
        self._stream: PacketStream | None = None
        self._filler = GapFiller(CAPTURE_RATE)
        self._watchdog = CaptureWatchdog()
        self._last_packet_at = 0.0
        self._parts: list[Samples] = []
        self._buffered = 0
        self._emitted = 0  # muestras publicadas: el reloj de audio
        self._reported_gaps = 0

        # Cola hacia `read`.
        self._cond = threading.Condition()
        self._queue: deque[AudioChunk] = deque()
        self._stopped = False
        self._started = False
        self._overflowed = False

        self._arrivals = ArrivalLog()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._opened = threading.Event()
        self._open_error: EngineError | None = None

    # --- AudioSource -----------------------------------------------------------------------------

    def start(self) -> None:
        """Abre la captura y lanza el hilo. Lanza `EngineError` si no se puede. Idempotente."""
        with self._cond:
            if self._started or self._stopped:
                return
            self._started = True
        thread = threading.Thread(target=self._run, name="captura-loopback", daemon=True)
        self._thread = thread
        thread.start()
        if not self._opened.wait(_OPEN_TIMEOUT_S):
            self.stop()
            raise EngineError("La captura de audio no arrancó a tiempo.", engine=ENGINE_NAME)
        if self._open_error is not None:
            raise self._open_error

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
        """True tras `stop()` (o si el hilo de captura murió): ya no llegarán más datos."""
        with self._cond:
            return self._stopped

    def stop(self) -> None:
        """Detiene la captura y descarta lo que no se haya leído. Idempotente."""
        self._mark_stopped()
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)

    def _mark_stopped(self) -> None:
        with self._cond:
            self._stopped = True
            self._queue.clear()
            self._cond.notify_all()

    # --- Hora de llegada -------------------------------------------------------------------------

    def arrival_time(self, t_audio: float) -> float | None:
        """Hora de llegada (reloj de sesión) del chunk que contiene el instante de audio `t_audio`.

        Un instante justo en la frontera entre dos chunks pertenece al que acaba ahí (el de `t_end_audio`).
        Devuelve None si ese audio aún no se ha captado o es más antiguo que los últimos 30 s. Sirve para
        `StageTimings.captured_at`, que `AudioChunk` no puede llevar.
        """
        return self._arrivals.lookup(t_audio)

    # --- Hilo de captura -------------------------------------------------------------------------

    def _run(self) -> None:
        try:
            try:
                self._open_stream(self._clock.now())
            except Exception as exc:
                error = (
                    exc
                    if isinstance(exc, EngineError)
                    else EngineError(f"No se pudo iniciar la captura de audio: {exc}", engine=ENGINE_NAME)
                )
                if error is not exc:
                    error.__cause__ = exc
                self._open_error = error
                self._mark_stopped()  # antes de avisar a `start()`: al volver de su excepción ya está parada
                return
            finally:
                self._opened.set()
            while not self._stop_event.is_set():
                try:
                    stream = self._stream
                    if stream is not None:
                        stream.wait(_WAIT_STEP_S)
                    else:
                        self._stop_event.wait(_WAIT_STEP_S)
                    self._pump_once()
                except Exception:
                    # Un fallo inesperado no debe matar la captura: se anota y se sigue en el paso siguiente.
                    logger.exception("Error inesperado en el hilo de captura")
                    self._stop_event.wait(_WAIT_STEP_S)
        finally:
            self._close_stream()
            self._mark_stopped()  # el hilo ya no produce: nadie debe esperar más datos

    def _open_stream(self, now: float) -> None:
        """Crea el flujo con el PID objetivo actual. Lanza si no se puede (y entonces no hay flujo)."""
        self._stream = self._factory(self._target_pid, not self._include, self._clock.now)
        self._last_packet_at = now  # los 0,5 s sin paquetes se cuentan desde la apertura
        logger.info(
            "Captura de audio abierta: PID objetivo %s, modo %s",
            self._target_pid,
            "INCLUDE" if self._include else "EXCLUDE",
        )

    def _close_stream(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.close()
            except Exception:
                logger.exception("Error al cerrar el flujo de captura")

    def _pump_once(self) -> None:
        """Un paso del hilo: vaciar paquetes, rellenar huecos, publicar chunks y vigilar. No bloquea."""
        stream = self._stream
        error: str | None = None
        if stream is not None:
            self._feed_packets(stream.read_packets())
            error = stream.error
        now = self._clock.now()
        self._feed(self._filler.tick(now), now)
        if self._filler.gaps > self._reported_gaps:
            self._reported_gaps = self._filler.gaps
            self._warn("Hueco en la captura de audio: se rellena con silencio.")
        self._check_watchdog(now, error)

    def _feed_packets(self, packets: list[Packet]) -> None:
        """Pasa al relleno los paquetes leídos de una vez (una ráfaga) y publica los chunks completos.

        Los paquetes de una ráfaga son consecutivos y el último se acaba de leer: el relleno ve la ráfaga
        como audio continuo que termina en ese instante. Así, una lectura retrasada (el hilo no tuvo la CPU
        durante más de 100 ms) no es un hueco mientras WASAPI no haya perdido datos; si los perdió, la parte
        que falta sí se rellena. La llegada de cada chunk es la de la lectura real: incluye ese retraso.
        """
        if not packets:
            return
        end = packets[-1].arrival
        stamps: list[float] = []
        after = 0.0  # duración del audio de los paquetes posteriores
        for packet in reversed(packets):
            stamps.append(end - after)
            after += len(packet.samples) / CAPTURE_RATE
        for packet, stamp in zip(packets, reversed(stamps), strict=True):
            self._last_packet_at = max(self._last_packet_at, packet.arrival)
            self._feed(self._filler.push(stamp, packet.samples), packet.arrival)

    def _feed(self, arrays: list[Samples], arrival: float) -> None:
        """Acumula muestras y publica los chunks completos; `arrival` es cuándo llegaron."""
        for array in arrays:
            if len(array):
                self._parts.append(np.asarray(array, dtype=np.float32))
                self._buffered += len(array)
        if self._buffered < self._chunk_len:
            return
        data = np.concatenate(self._parts) if len(self._parts) > 1 else self._parts[0]
        size = self._chunk_len
        count = len(data) // size
        for i in range(count):
            chunk = AudioChunk(
                samples=data[i * size : (i + 1) * size].copy(),
                sample_rate=CAPTURE_RATE,
                t_start=self._emitted / CAPTURE_RATE,
            )
            self._emitted += size
            self._arrivals.record(chunk.t_start, chunk.t_end, arrival)
            self._publish(chunk)
        rest = data[count * size :].copy()
        self._parts = [rest] if len(rest) else []
        self._buffered = len(rest)

    def _publish(self, chunk: AudioChunk) -> None:
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
            self._warn(
                "El consumidor del audio no da abasto: se descarta el audio más antiguo de la captura."
            )

    # --- Vigilante -------------------------------------------------------------------------------

    def _target_ok(self) -> bool:
        """False si el PID objetivo ya no es el correcto (condición 3 del vigilante)."""
        if self._follow_process:
            return _current_pid() == self._target_pid  # el proceso cambió de PID (fork/spawn)
        if self._include:
            return True  # INCLUDE de un PID explícito: lo vigila quien lo eligió (`AppLoopbackSource`)
        return _pid_exists(self._target_pid)  # EXCLUDE de un PID explícito: sigue vivo

    def _check_watchdog(self, now: float, stream_error: str | None) -> None:
        reason = self._watchdog.check(
            now, last_packet_at=self._last_packet_at, error=stream_error, target_ok=self._target_ok()
        )
        if reason is not None:
            self._reopen(reason, now, stream_error)

    def _reopen(self, reason: WatchdogReason, now: float, stream_error: str | None) -> None:
        if reason is WatchdogReason.NO_PACKETS:
            why = f"no llegan paquetes desde hace {_fmt_s(now - self._last_packet_at)} s"
        elif reason is WatchdogReason.WASAPI_ERROR:
            why = f"error de WASAPI ({stream_error})"
        else:
            why = "el proceso objetivo ya no es el de la captura"
        self._warn(f"Reabriendo la captura de audio: {why}.")
        if self._stop_event.is_set():  # el aviso pudo parar la fuente
            return
        self._watchdog.note_reopen(now)
        self._close_stream()
        if self._follow_process:
            self._target_pid = _current_pid()
        try:
            self._open_stream(now)
        except Exception as exc:
            self._warn(f"No se pudo reabrir la captura de audio: {exc}")
            return
        self._call(self._on_reopen)

    # --- Callbacks -------------------------------------------------------------------------------

    def _warn(self, message: str) -> None:
        logger.warning(message)
        self._call(self._on_warning, message)

    @staticmethod
    def _call(callback: Callable[..., None] | None, *args: object) -> None:
        """Llama a un callback del suscriptor sin dejar que su fallo pare la captura."""
        if callback is None:
            return
        try:
            callback(*args)
        except Exception:
            logger.exception("Falló un callback de la captura de audio")
