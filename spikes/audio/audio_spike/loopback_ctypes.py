"""Plan B del ADR-0005 en Python: process loopback de WASAPI con ctypes + comtypes.

Como pyminiaudio 1.71 no puede activar el dispositivo virtual `VAD\\Process_Loopback`
(ver `loopback.py`), aqui se llama directamente a `ActivateAudioInterfaceAsync`:

1. Se rellena `AUDIOCLIENT_ACTIVATION_PARAMS` (EXCLUDE/INCLUDE + PID) en un PROPVARIANT VT_BLOB.
2. `ActivateAudioInterfaceAsync(L"VAD\\Process_Loopback", IID_IAudioClient, ...)` con un
   manejador de finalizacion que implementa `IActivateAudioInterfaceCompletionHandler` e
   `IAgileObject` (sin el segundo, el sistema falla con E_ILLEGAL_METHOD_CALL).
3. `IAudioClient::Initialize(SHARED, LOOPBACK | EVENTCALLBACK | AUTOCONVERTPCM |
   SRC_DEFAULT_QUALITY, ..., WAVEFORMATEX elegido)`: este dispositivo virtual no tiene
   *mix format*, asi que se pide 16 kHz mono float32 y Windows convierte.
4. `IAudioCaptureClient` + hilo que espera el evento y lee los paquetes.

Tambien admite el modo ENDPOINT (loopback clasico del dispositivo por defecto) para tener un
control que oye todo, con exactamente el mismo codigo de lectura.
"""

from __future__ import annotations

import ctypes
import threading
import time
from ctypes import HRESULT, POINTER, byref, c_long, c_uint32, c_uint64, c_ubyte, c_ushort, c_ulong
from ctypes import wintypes
from typing import Optional

import comtypes
import numpy as np
from comtypes import CLSCTX_ALL, COMMETHOD, COMError, COMObject, GUID, IUnknown
from pycaw.api.audioclient import IAudioClient
from pycaw.api.audioclient.depend import WAVEFORMATEX
from pycaw.utils import AudioUtilities

from .modos import ModoCaptura
from .registro import Paquete, Registro

# -- constantes de WASAPI ---------------------------------------------------------------
AUDCLNT_SHAREMODE_SHARED = 0
AUDCLNT_STREAMFLAGS_LOOPBACK = 0x00020000
AUDCLNT_STREAMFLAGS_EVENTCALLBACK = 0x00040000
AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM = 0x80000000
AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY = 0x08000000
BUFFERFLAGS_DISCONTINUITY = 0x1
BUFFERFLAGS_SILENT = 0x2
BUFFERFLAGS_TIMESTAMP_ERROR = 0x4
WAVE_FORMAT_IEEE_FLOAT = 3
VT_BLOB = 65
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 0x102

HRESULTS_CONOCIDOS = {
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


def nombre_hresult(hr: int) -> str:
    hr &= 0xFFFFFFFF
    return f"{HRESULTS_CONOCIDOS.get(hr, 'HRESULT')} (0x{hr:08X})"


# -- estructuras de la API de process loopback ----------------------------------------------
class AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS(ctypes.Structure):
    _fields_ = [("TargetProcessId", wintypes.DWORD), ("ProcessLoopbackMode", c_uint32)]


class AUDIOCLIENT_ACTIVATION_PARAMS(ctypes.Structure):
    _fields_ = [("ActivationType", c_uint32), ("ProcessLoopbackParams", AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS)]


class _BLOB(ctypes.Structure):
    _fields_ = [("cbSize", c_ulong), ("pBlobData", POINTER(c_ubyte))]


class _PROPVARIANT_DATOS(ctypes.Union):
    _fields_ = [("blob", _BLOB), ("_relleno", c_ubyte * 16)]


class PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", c_ushort), ("r1", c_ushort), ("r2", c_ushort), ("r3", c_ushort), ("datos", _PROPVARIANT_DATOS)]


# -- interfaces COM ---------------------------------------------------------------------------
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
        COMMETHOD([], HRESULT, "GetNextPacketSize", (["out"], POINTER(c_uint32), "pNumFramesInNextPacket")),
    )


class ManejadorActivacion(COMObject):
    """`IActivateAudioInterfaceCompletionHandler` + `IAgileObject`: solo avisa con un Event."""

    _com_interfaces_ = [IActivateAudioInterfaceCompletionHandler, IAgileObject]

    def __init__(self) -> None:
        super().__init__()
        self.hecho = threading.Event()

    def ActivateCompleted(self, activateOperation):  # noqa: N802 (nombre fijado por COM)
        # No se toca `activateOperation` (puntero prestado): la operacion la recoge el hilo principal.
        self.hecho.set()
        return 0


_mmdevapi = ctypes.WinDLL("Mmdevapi.dll")
_ActivateAudioInterfaceAsync = _mmdevapi.ActivateAudioInterfaceAsync
_ActivateAudioInterfaceAsync.restype = c_long
_ActivateAudioInterfaceAsync.argtypes = [
    wintypes.LPCWSTR,
    POINTER(GUID),
    POINTER(PROPVARIANT),
    POINTER(IActivateAudioInterfaceCompletionHandler),
    POINTER(POINTER(IActivateAudioInterfaceAsyncOperation)),
]

_k32 = ctypes.WinDLL("kernel32.dll")
_k32.CreateEventW.restype = wintypes.HANDLE
_k32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
_k32.WaitForSingleObject.restype = wintypes.DWORD
_k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_k32.CloseHandle.argtypes = [wintypes.HANDLE]


class ErrorCaptura(RuntimeError):
    """Fallo al activar o inicializar la captura (incluye el HRESULT exacto)."""

    def __init__(self, mensaje: str, hresult: Optional[int] = None) -> None:
        super().__init__(mensaje)
        self.hresult = hresult


def activar_cliente_proceso(pid: int, excluir: bool, timeout_s: float = 5.0):
    """`IAudioClient` del dispositivo virtual de process loopback (EXCLUDE o INCLUDE de `pid`)."""
    params = AUDIOCLIENT_ACTIVATION_PARAMS()
    params.ActivationType = 1  # AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK
    params.ProcessLoopbackParams.TargetProcessId = pid
    params.ProcessLoopbackParams.ProcessLoopbackMode = 1 if excluir else 0
    pv = PROPVARIANT()
    pv.vt = VT_BLOB
    pv.datos.blob.cbSize = ctypes.sizeof(params)
    pv.datos.blob.pBlobData = ctypes.cast(ctypes.pointer(params), POINTER(c_ubyte))

    manejador = ManejadorActivacion()
    operacion = POINTER(IActivateAudioInterfaceAsyncOperation)()
    hr = _ActivateAudioInterfaceAsync(
        "VAD\\Process_Loopback", byref(IAudioClient._iid_), byref(pv), manejador, byref(operacion)
    )
    if hr < 0:
        raise ErrorCaptura(f"ActivateAudioInterfaceAsync fallo: {nombre_hresult(hr)}", hr & 0xFFFFFFFF)
    if not manejador.hecho.wait(timeout_s):
        raise ErrorCaptura("ActivateAudioInterfaceAsync no termino (timeout)")
    hr_activacion, desconocido = operacion.GetActivateResult()
    if hr_activacion < 0:
        raise ErrorCaptura(f"La activacion fallo: {nombre_hresult(hr_activacion)}", hr_activacion & 0xFFFFFFFF)
    return desconocido.QueryInterface(IAudioClient)


def activar_cliente_endpoint():
    """`IAudioClient` del dispositivo de reproduccion por defecto (para el loopback clasico)."""
    altavoces = AudioUtilities.GetSpeakers()
    desconocido = altavoces._dev.Activate(IAudioClient._iid_, CLSCTX_ALL, None)
    return desconocido.QueryInterface(IAudioClient)


class CapturaProcesoCtypes:
    """Captura loopback (EXCLUDE/INCLUDE por proceso, o ENDPOINT) con el plan B en ctypes.

    Entrega paquetes float32 mono (o estereo mezclado a mono si Windows no admite mono)
    a un `Registro`, con la hora de llegada, los flags de WASAPI y el sello QPC.
    """

    def __init__(
        self,
        pid: int = 0,
        modo: ModoCaptura = ModoCaptura.EXCLUDE,
        sample_rate: int = 16000,
        nchannels: int = 1,
        buffer_ms: int = 100,
        espera_ms: int = 20,
    ) -> None:
        if modo is not ModoCaptura.ENDPOINT and not pid:
            raise ValueError("los modos EXCLUDE/INCLUDE necesitan un pid")
        self.pid = pid
        self.modo = modo
        self.sample_rate = sample_rate
        self.nchannels = nchannels  # canales pedidos a Windows (puede bajar a estereo + mezcla)
        self.buffer_ms = buffer_ms
        self.espera_ms = espera_ms
        self.registro: Optional[Registro] = None
        self.estadisticas = {
            "despertares_evento": 0,
            "despertares_timeout": 0,
            "paquetes": 0,
            "frames": 0,
            "silent": 0,
            "discontinuidades": 0,
            "error_sello": 0,
        }
        self.error: Optional[str] = None
        self.formato_pedido = ""
        self._hilo: Optional[threading.Thread] = None
        self._parar = threading.Event()
        self._cliente = None
        self._captura = None
        self._evento = None
        self._canales_reales = nchannels
        self._abrir()

    # -- apertura ----------------------------------------------------------------------
    def _formato(self, canales: int) -> WAVEFORMATEX:
        f = WAVEFORMATEX()
        f.wFormatTag = WAVE_FORMAT_IEEE_FLOAT
        f.nChannels = canales
        f.nSamplesPerSec = self.sample_rate
        f.wBitsPerSample = 32
        f.nBlockAlign = canales * 4
        f.nAvgBytesPerSec = self.sample_rate * f.nBlockAlign
        f.cbSize = 0
        return f

    def _activar(self):
        if self.modo is ModoCaptura.ENDPOINT:
            return activar_cliente_endpoint()
        return activar_cliente_proceso(self.pid, excluir=self.modo is ModoCaptura.EXCLUDE)

    def _abrir(self) -> None:
        flags = (
            AUDCLNT_STREAMFLAGS_LOOPBACK
            | AUDCLNT_STREAMFLAGS_EVENTCALLBACK
            | AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM
            | AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY
        )
        ultimo_error: Optional[COMError] = None
        intentos = (self.nchannels, 2) if self.nchannels != 2 else (2,)
        for canales in intentos:
            cliente = self._activar()
            fmt = self._formato(canales)
            try:
                # Buffer de `buffer_ms` (unidades de 100 ns); en modo compartido la periodicidad es 0.
                cliente.Initialize(
                    AUDCLNT_SHAREMODE_SHARED, flags, self.buffer_ms * 10000, 0, ctypes.pointer(fmt), None
                )
            except COMError as exc:
                ultimo_error = exc
                self.formato_pedido = (
                    f"{canales} canal(es) {self.sample_rate} Hz float32 -> rechazado "
                    f"{nombre_hresult(exc.hresult)}"
                )
                continue
            self._cliente = cliente
            self._canales_reales = canales
            self.formato_pedido = f"{canales} canal(es) {self.sample_rate} Hz float32 -> aceptado"
            break
        if self._cliente is None:
            raise ErrorCaptura(
                f"IAudioClient::Initialize fallo: {self.formato_pedido}",
                (ultimo_error.hresult & 0xFFFFFFFF) if ultimo_error else None,
            )
        self._evento = _k32.CreateEventW(None, False, False, None)
        self._cliente.SetEventHandle(self._evento)
        desconocido = self._cliente.GetService(byref(IAudioCaptureClient._iid_))
        self._captura = desconocido.QueryInterface(IAudioCaptureClient)

    # -- ciclo de vida -----------------------------------------------------------------
    def iniciar(self, registro: Registro) -> None:
        self.registro = registro
        self._parar.clear()
        self._cliente.Start()
        self._hilo = threading.Thread(target=self._bucle, name=f"captura-{self.modo.value}", daemon=True)
        self._hilo.start()
        registro.evento("start")

    def detener(self) -> None:
        self._parar.set()
        if self._hilo is not None:
            self._hilo.join(timeout=2.0)
            self._hilo = None
        if self._cliente is not None:
            try:
                self._cliente.Stop()
            except COMError:
                pass

    def cerrar(self) -> None:
        self.detener()
        self._captura = None
        self._cliente = None
        if self._evento:
            _k32.CloseHandle(self._evento)
            self._evento = None

    def __enter__(self) -> "CapturaProcesoCtypes":
        return self

    def __exit__(self, *exc) -> None:
        self.cerrar()

    # -- hilo de captura -----------------------------------------------------------------
    def _bucle(self) -> None:
        comtypes.CoInitializeEx()  # usa sys.coinit_flags (MTA)
        est = self.estadisticas
        nch = self._canales_reales
        registro = self.registro
        try:
            while not self._parar.is_set():
                r = _k32.WaitForSingleObject(self._evento, self.espera_ms)
                despertar = time.perf_counter_ns()
                if r == WAIT_OBJECT_0:
                    est["despertares_evento"] += 1
                elif r == WAIT_TIMEOUT:
                    est["despertares_timeout"] += 1
                else:
                    self.error = f"WaitForSingleObject devolvio {r}"
                    registro.evento(f"error: {self.error}")
                    return
                while not self._parar.is_set():
                    try:
                        siguiente = self._captura.GetNextPacketSize()
                        if siguiente == 0:
                            break
                        datos, nframes, flags, _pos, qpc = self._captura.GetBuffer()
                        t_ns = time.perf_counter_ns()
                        if nframes == 0:
                            break
                        if flags & BUFFERFLAGS_SILENT:
                            # Segun WASAPI el contenido del bufer es indefinido: se trata como ceros.
                            muestras = np.zeros(nframes, dtype=np.float32)
                            est["silent"] += 1
                        else:
                            bruto = (ctypes.c_float * (nframes * nch)).from_address(
                                ctypes.addressof(datos.contents)
                            )
                            muestras = np.frombuffer(bruto, dtype=np.float32).copy()
                            if nch > 1:
                                muestras = muestras.reshape(nframes, nch).mean(axis=1).astype(np.float32)
                        self._captura.ReleaseBuffer(nframes)
                    except COMError as exc:
                        self.error = nombre_hresult(exc.hresult)
                        registro.evento(f"error: {self.error}")
                        return
                    est["paquetes"] += 1
                    est["frames"] += nframes
                    if flags & BUFFERFLAGS_DISCONTINUITY:
                        est["discontinuidades"] += 1
                    if flags & BUFFERFLAGS_TIMESTAMP_ERROR:
                        est["error_sello"] += 1
                    registro.anadir(Paquete(t_ns, muestras, flags, int(qpc) * 100, despertar))
        finally:
            comtypes.CoUninitialize()
