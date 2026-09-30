"""Generacion de tonos de prueba y reproductor sobre `miniaudio.PlaybackDevice`.

El reproductor abre el dispositivo **sin `device_id`** (dispositivo por defecto, con el
seguimiento automatico de miniaudio) a 48 kHz float32, que es la configuracion del ADR-0005.
"""

from __future__ import annotations

import threading
import time
import wave
from collections import deque
from typing import Callable, Optional

import miniaudio
import numpy as np
from _miniaudio import ffi, lib

AMPLITUD_POR_DEFECTO = 0.15  # volumen bajo: -16,5 dBFS de pico

_NOTIFICACIONES = {
    lib.ma_device_notification_type_started: "started",
    lib.ma_device_notification_type_stopped: "stopped",
    lib.ma_device_notification_type_rerouted: "rerouted",
    lib.ma_device_notification_type_interruption_began: "interruption_began",
    lib.ma_device_notification_type_interruption_ended: "interruption_ended",
}


class PlaybackDeviceConNotificaciones(miniaudio.PlaybackDevice):
    """`miniaudio.PlaybackDevice` (sin device_id) que ademas engancha `notificationCallback`.

    pyminiaudio 1.71 no engancha ese callback, asi que no avisa de `rerouted` (miniaudio siguio al
    nuevo dispositivo por defecto), `stopped` (se perdio el dispositivo) ni `interruption_*`. Aqui se
    replica `PlaybackDevice.__init__` con la unica diferencia del callback (via ffi.callback).
    """

    def __init__(self, output_format: miniaudio.SampleFormat, nchannels: int, sample_rate: int,
                 buffersize_msec: int, callback_periods: int, backends, app_name: str = "",
                 al_notificar: Optional[Callable[[int, str], None]] = None) -> None:
        miniaudio.AbstractDevice.__init__(self)
        self.format = output_format
        self.sample_width = miniaudio.width_from_format(output_format)
        self.nchannels = nchannels
        self.sample_rate = sample_rate
        self.buffersize_msec = buffersize_msec
        self.eventos: list[tuple[int, str]] = []
        self._al_notificar = al_notificar
        self._ffi_handle = ffi.new_handle(self)
        cfg = lib.ma_device_config_init(lib.ma_device_type_playback)
        cfg.sampleRate = sample_rate
        cfg.playback.channels = nchannels
        cfg.playback.format = output_format.value
        cfg.playback.pDeviceID = ffi.NULL  # dispositivo por defecto: miniaudio sigue sus cambios
        cfg.periodSizeInMilliseconds = buffersize_msec
        cfg.pUserData = self._ffi_handle
        cfg.dataCallback = lib._internal_data_callback
        cfg.stopCallback = lib._internal_stop_callback
        cfg.periods = callback_periods
        self._cb_notificacion = ffi.callback("void(ma_device_notification *)", self._notificacion)
        cfg.notificationCallback = self._cb_notificacion
        self._devconfig = cfg
        self.callback_generator = None
        self._context = self._make_context(list(backends or []), miniaudio.ThreadPriority.HIGHEST, app_name)
        resultado = lib.ma_device_init(self._context, ffi.addressof(self._devconfig), self._device)
        if resultado != lib.MA_SUCCESS:
            raise miniaudio.MiniaudioError("failed to init device", resultado)
        self.backend = ffi.string(lib.ma_get_backend_name(self._device.pContext.backend)).decode()

    def _notificacion(self, notif) -> None:
        try:
            nombre = _NOTIFICACIONES.get(notif.type, f"tipo_{notif.type}")
            t_ns = time.perf_counter_ns()
            self.eventos.append((t_ns, nombre))
            if self._al_notificar:
                self._al_notificar(t_ns, nombre)
        except Exception as exc:  # una excepcion en un callback de C solo se imprime
            print(f"[PlaybackDeviceConNotificaciones] error: {exc!r}")


def generar_tono(
    frecuencia: float,
    duracion_s: float,
    amplitud: float = AMPLITUD_POR_DEFECTO,
    sample_rate: int = 48000,
    fundido_ms: float = 5.0,
) -> np.ndarray:
    """Seno mono float32 con fundidos de coseno elevado (sin clics de banda ancha)."""
    n = int(round(duracion_s * sample_rate))
    t = np.arange(n) / sample_rate
    x = amplitud * np.sin(2 * np.pi * frecuencia * t)
    nf = min(int(round(fundido_ms * 1e-3 * sample_rate)), n // 2)
    if nf > 0:
        rampa = 0.5 * (1 - np.cos(np.pi * np.arange(nf) / nf))
        x[:nf] *= rampa
        x[n - nf :] *= rampa[::-1]
    return x.astype(np.float32)


def escribir_wav(ruta: str, mono: np.ndarray, sample_rate: int = 48000) -> None:
    """Guarda un WAV PCM16 mono (para lanzar ffplay como app externa). Solo en ficheros temporales."""
    pcm = np.clip(mono, -1.0, 1.0)
    pcm = (pcm * 32767.0).astype("<i2")
    with wave.open(ruta, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())


def silencio(duracion_s: float, sample_rate: int = 48000) -> np.ndarray:
    return np.zeros(int(round(duracion_s * sample_rate)), dtype=np.float32)


class ReproductorTonos:
    """PlaybackDevice por defecto que reproduce ceros y, bajo demanda, tonos.

    El generador se ejecuta en el hilo de audio de miniaudio (con el GIL); solo copia trozos
    de un array ya preparado. Cada tono devuelve un dict con las marcas de tiempo
    (`time.perf_counter_ns`) del primer y el ultimo bloque no nulo entregados al dispositivo.
    """

    def __init__(
        self,
        sample_rate: int = 48000,
        nchannels: int = 2,
        periodo_ms: int = 20,
        periodos: int = 3,
        nombre_app: str = "",
        al_notificar: Optional[Callable[[int, str], None]] = None,
    ) -> None:
        self.sample_rate = sample_rate
        self.nchannels = nchannels
        self.periodo_ms = periodo_ms
        self.periodos = periodos
        self.nombre_app = nombre_app
        self.al_notificar = al_notificar
        self.dispositivo: Optional[PlaybackDeviceConNotificaciones] = None
        self._pendientes: deque = deque()  # (mono, info, evento)
        self._actual: Optional[np.ndarray] = None
        self._info: Optional[dict] = None
        self._evento: Optional[threading.Event] = None
        self._pos = 0
        self.t_callbacks: list[int] = []  # llegada de cada peticion de datos (para medir cadencia)
        self.frames_por_callback: list[int] = []

    # -- ciclo de vida --------------------------------------------------------------
    def abrir(self) -> None:
        """Crea e inicia el dispositivo (sin device_id: dispositivo por defecto)."""
        self.dispositivo = PlaybackDeviceConNotificaciones(
            output_format=miniaudio.SampleFormat.FLOAT32,
            nchannels=self.nchannels,
            sample_rate=self.sample_rate,
            buffersize_msec=self.periodo_ms,
            callback_periods=self.periodos,
            backends=[miniaudio.Backend.WASAPI],
            app_name=self.nombre_app,
            al_notificar=self.al_notificar,
        )
        gen = self._generador()
        next(gen)
        self.dispositivo.start(gen)

    def cerrar(self) -> None:
        if self.dispositivo is not None:
            self.dispositivo.close()
            self.dispositivo = None

    def __enter__(self) -> "ReproductorTonos":
        self.abrir()
        return self

    def __exit__(self, *exc) -> None:
        self.cerrar()

    # -- API de tonos -----------------------------------------------------------------
    def tono(self, frecuencia: float, duracion_s: float, amplitud: float = AMPLITUD_POR_DEFECTO) -> dict:
        """Encola un tono; devuelve el dict de marcas y un Event en info['_hecho']."""
        mono = generar_tono(frecuencia, duracion_s, amplitud, self.sample_rate)
        info = {
            "frecuencia": frecuencia,
            "duracion_s": duracion_s,
            "amplitud": amplitud,
            "t_encolado_ns": time.perf_counter_ns(),
            "t_primer_bloque_ns": None,
            "t_ultimo_bloque_ns": None,
        }
        evento = threading.Event()
        info["_hecho"] = evento
        self._pendientes.append((mono, info, evento))
        return info

    def tono_y_esperar(self, frecuencia: float, duracion_s: float, amplitud: float = AMPLITUD_POR_DEFECTO,
                       cola_s: float = 0.25) -> dict:
        """Reproduce un tono y espera a que termine (mas `cola_s` de margen para el dispositivo)."""
        info = self.tono(frecuencia, duracion_s, amplitud)
        info["_hecho"].wait(timeout=duracion_s + 5.0)
        time.sleep(cola_s)
        return info

    # -- generador que alimenta al dispositivo (hilo de audio) ----------------------------
    def _generador(self):
        frames = yield b""
        while True:
            t_ns = time.perf_counter_ns()
            if len(self.t_callbacks) < 100000:
                self.t_callbacks.append(t_ns)
                self.frames_por_callback.append(frames)
            salida = np.zeros((frames, self.nchannels), dtype=np.float32)
            if self._actual is None and self._pendientes:
                self._actual, self._info, self._evento = self._pendientes.popleft()
                self._pos = 0
                self._info["t_primer_bloque_ns"] = t_ns
            if self._actual is not None:
                trozo = self._actual[self._pos : self._pos + frames]
                salida[: len(trozo), :] = trozo[:, None]
                self._pos += len(trozo)
                if self._pos >= len(self._actual):
                    self._info["t_ultimo_bloque_ns"] = t_ns
                    self._evento.set()
                    self._actual = None
            frames = yield salida
