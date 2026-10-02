"""Diagnostico de la subclase de pyminiaudio para process loopback (plan A del ADR-0005).

Solo emite un pitido de 0,3 s (muy bajo) en la prueba del modo ENDPOINT. Comprueba, en este orden:
1. Versiones (pyminiaudio y el miniaudio de C que lleva dentro).
2. `CapturaProceso` (subclase del boceto de la investigacion) en los tres modos: ENDPOINT (sin PID)
   debe funcionar; EXCLUDE e INCLUDE (con PID) fallan con el codigo de error de miniaudio.
3. La causa: miniaudio, en su ruta "Desktop", llama a `IMMDeviceEnumerator::GetDevice(L"VAD\\Process_Loopback")`
   antes de `Activate()`, y esa llamada devuelve E_INVALIDARG (0x80070057). Se reproduce la llamada.
4. Que Windows SI acepta la activacion del dispositivo virtual por el camino correcto
   (`ActivateAudioInterfaceAsync`, plan B en ctypes/comtypes) con los mismos parametros.

Uso:  uv run python diagnostico_subclase.py
"""

from __future__ import annotations

import os
import sys
import time

import audio_spike  # noqa: F401  (COM en MTA antes de comtypes)
import miniaudio
from _miniaudio import ffi, lib
from audio_spike import banco
from audio_spike.analisis import maximo_tono
from audio_spike.loopback import CapturaProceso
from audio_spike.modos import ModoCaptura
from audio_spike.registro import Registro
from audio_spike.tonos import ReproductorTonos


def main() -> int:
    from comtypes import COMError
    from pycaw.utils import AudioUtilities

    pid = os.getpid()
    resultados: dict = {}
    entorno = banco.info_entorno()
    print("== Diagnostico de la subclase de pyminiaudio ==")
    print("Windows:", entorno["windows"])
    print("pyminiaudio:", entorno["miniaudio"], "| miniaudio (C):", ffi.string(lib.ma_version_string()).decode())
    resultados["versiones"] = {"pyminiaudio": entorno["miniaudio"], "miniaudio_c": ffi.string(lib.ma_version_string()).decode(),
                               "windows": entorno["windows"]}

    print("\n-- 2) CapturaProceso (subclase de miniaudio.CaptureDevice) en cada modo")
    print("   (en ENDPOINT se emite un unico pitido de 0,3 s, muy bajo, para comprobar que llegan datos reales)")
    resultados["subclase"] = {}
    for modo in (ModoCaptura.ENDPOINT, ModoCaptura.EXCLUDE, ModoCaptura.INCLUDE):
        try:
            cap = CapturaProceso(pid=pid if modo is not ModoCaptura.ENDPOINT else 0, modo=modo,
                                 sample_rate=16000, nchannels=1, period_ms=10)
            reg = Registro(16000, modo.value)
            gen = reg.consumidor()
            next(gen)
            cap.start(gen)
            time.sleep(0.5)
            with ReproductorTonos(48000, 2, 20, 3) as rep:
                time.sleep(0.3)
                t0 = banco.ahora_ns()
                rep.tono_y_esperar(1234.0, 0.3, 0.08, cola_s=0.3)
                t1 = banco.ahora_ns()
            x, _ = reg.ventana(t0 - int(0.1e9), t1 + int(0.3e9))
            tono = maximo_tono(x, 16000, 1234.0, ventana_s=0.2)
            n = reg.n_paquetes
            cap.close()
            print(f"   {modo.value:9} OK: dispositivo creado, backend {cap.backend}; paquetes: {n}; "
                  f"tono de 1234 Hz detectado: {'SI' if tono['ratio_db'] >= 15 else 'no'} ({tono['ratio_db']:.0f} dB)")
            resultados["subclase"][modo.value] = {"ok": True, "paquetes": n, "tono_ratio_db": round(tono["ratio_db"], 1)}
        except miniaudio.MiniaudioError as exc:
            print(f"   {modo.value:9} ERROR: {type(exc).__name__}: {exc}")
            resultados["subclase"][modo.value] = {"ok": False, "error": str(exc)}

    print("\n-- 3) Causa: IMMDeviceEnumerator::GetDevice con el ID del dispositivo virtual")
    enumerador = AudioUtilities.GetDeviceEnumerator()
    try:
        enumerador.GetDevice("VAD\\Process_Loopback")
        print("   GetDevice OK (inesperado)")
        resultados["get_device_virtual"] = "ok"
    except COMError as exc:
        print(f"   GetDevice('VAD\\\\Process_Loopback') -> COMError 0x{exc.hresult & 0xFFFFFFFF:08X} ({exc.text})")
        resultados["get_device_virtual"] = f"COMError 0x{exc.hresult & 0xFFFFFFFF:08X}"
    print("   (miniaudio convierte E_INVALIDARG en MA_INVALID_ARGS = -2: es el error de arriba)")

    print("\n-- 4) El plan B: ActivateAudioInterfaceAsync con los mismos parametros")
    from audio_spike.loopback_ctypes import activar_cliente_proceso

    resultados["ctypes"] = {}
    for excluir in (True, False):
        etiqueta = "EXCLUDE" if excluir else "INCLUDE"
        t0 = time.perf_counter()
        try:
            cliente = activar_cliente_proceso(pid, excluir)
            ms = (time.perf_counter() - t0) * 1000
            print(f"   {etiqueta}: IAudioClient obtenido en {ms:.1f} ms")
            resultados["ctypes"][etiqueta.lower()] = {"ok": True, "ms": round(ms, 1)}
            del cliente
        except Exception as exc:
            print(f"   {etiqueta}: ERROR {exc}")
            resultados["ctypes"][etiqueta.lower()] = {"ok": False, "error": str(exc)}
    ruta = banco.guardar_json("diagnostico_subclase.json", resultados)
    print("\nResultados guardados en", ruta)
    return 0


if __name__ == "__main__":
    sys.exit(main())
