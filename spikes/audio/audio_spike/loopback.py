"""Plan A del ADR-0005: subclase de pyminiaudio 1.71 con process loopback.

`CapturaProceso` es la subclase del boceto de la investigacion (docs/investigacion/
2026-09-30-audio-windows.md, 4.1): crea un dispositivo de tipo *loopback* de miniaudio
0.11.25 con `wasapi.loopbackProcessID` y `wasapi.loopbackProcessExclude`.

RESULTADO DEL SPIKE (Windows 11 build 26200, pyminiaudio 1.71 / miniaudio 0.11.25):
- modo ENDPOINT (sin PID): funciona (loopback clasico del dispositivo por defecto).
- modos EXCLUDE/INCLUDE (con PID): `ma_device_init` devuelve MA_INVALID_ARGS (-2).
  Causa: en la ruta "Desktop" de miniaudio, `ma_context_get_IAudioClient_Desktop__wasapi`
  llama a `IMMDeviceEnumerator::GetDevice(L"VAD\\Process_Loopback")`, que devuelve
  E_INVALIDARG (0x80070057), antes de `Activate()`. El dispositivo virtual de process
  loopback solo se puede activar con `ActivateAudioInterfaceAsync`, que miniaudio solo usa
  en la ruta UWP. Se ejecuta `diagnostico_subclase.py` para verlo.
Por eso el plan B (`loopback_ctypes.py`) es el que se usa en el resto del spike.

Usa internals de pyminiaudio (`_miniaudio`, `_make_context`, `_data_callback`), asi que la
version queda fijada en 1.71.
"""

from __future__ import annotations

import time
from typing import Callable, Optional

import miniaudio
from _miniaudio import ffi, lib

from .modos import ModoCaptura

# Nombres legibles de las notificaciones de dispositivo de miniaudio.
NOTIFICACIONES = {
    lib.ma_device_notification_type_started: "started",
    lib.ma_device_notification_type_stopped: "stopped",
    lib.ma_device_notification_type_rerouted: "rerouted",
    lib.ma_device_notification_type_interruption_began: "interruption_began",
    lib.ma_device_notification_type_interruption_ended: "interruption_ended",
}


def nombre_resultado(codigo: int) -> str:
    """Traduce un `ma_result` numerico a su constante MA_* (para informar errores exactos)."""
    nombres = [n for n in dir(lib) if n.startswith("MA_") and getattr(lib, n, None) == codigo]
    return nombres[0] if nombres else f"desconocido({codigo})"


class CapturaProceso(miniaudio.CaptureDevice):
    """Dispositivo de captura 'loopback' con filtro por proceso (ver el docstring del modulo)."""

    def __init__(
        self,
        pid: int = 0,
        modo: ModoCaptura = ModoCaptura.EXCLUDE,
        sample_rate: int = 16000,
        nchannels: int = 1,
        period_ms: int = 10,
        periods: int = 0,
        al_notificar: Optional[Callable[[int, str], None]] = None,
    ) -> None:
        # No se llama a CaptureDevice.__init__ (crearia un dispositivo de captura normal).
        miniaudio.AbstractDevice.__init__(self)
        self.modo = modo
        self.pid = pid
        self.format = miniaudio.SampleFormat.FLOAT32
        self.sample_width = miniaudio.width_from_format(self.format)
        self.nchannels = nchannels
        self.sample_rate = sample_rate
        self.buffersize_msec = period_ms
        self.eventos: list[tuple[int, str]] = []
        self._al_notificar = al_notificar
        self._ffi_handle = ffi.new_handle(self)

        cfg = lib.ma_device_config_init(lib.ma_device_type_loopback)
        cfg.sampleRate = sample_rate
        cfg.capture.format = self.format.value
        cfg.capture.channels = nchannels
        cfg.capture.pDeviceID = ffi.NULL  # obligatorio para el process loopback
        cfg.periodSizeInMilliseconds = period_ms
        cfg.periods = periods
        if modo is ModoCaptura.ENDPOINT:
            cfg.wasapi.loopbackProcessID = 0
        else:
            if not pid:
                raise ValueError("los modos EXCLUDE/INCLUDE necesitan un pid")
            cfg.wasapi.loopbackProcessID = pid
            cfg.wasapi.loopbackProcessExclude = modo is ModoCaptura.EXCLUDE
        cfg.pUserData = self._ffi_handle
        cfg.dataCallback = lib._internal_data_callback
        cfg.stopCallback = lib._internal_stop_callback
        # pyminiaudio no engancha notificationCallback: se hace con ffi.callback (y se
        # guarda la referencia para que el recolector no la libere).
        self._cb_notificacion = ffi.callback("void(ma_device_notification *)", self._notificacion)
        cfg.notificationCallback = self._cb_notificacion
        self._devconfig = cfg

        self._context = self._make_context([miniaudio.Backend.WASAPI])
        resultado = lib.ma_device_init(self._context, ffi.addressof(self._devconfig), self._device)
        if resultado != lib.MA_SUCCESS:
            raise miniaudio.MiniaudioError(
                f"ma_device_init fallo: {nombre_resultado(resultado)} ({resultado}) "
                f"[modo={modo.value}, pid={pid}]",
                resultado,
            )
        self.backend = ffi.string(lib.ma_get_backend_name(self._device.pContext.backend)).decode()

    # -- notificaciones de dispositivo (started/stopped/rerouted/interruption) ----------
    def _notificacion(self, notif) -> None:
        try:
            nombre = NOTIFICACIONES.get(notif.type, f"tipo_{notif.type}")
            t_ns = time.perf_counter_ns()
            self.eventos.append((t_ns, nombre))
            if self._al_notificar:
                self._al_notificar(t_ns, nombre)
        except Exception as exc:  # una excepcion en un callback de C solo se imprime
            print(f"[CapturaProceso] error en notificacion: {exc!r}")
