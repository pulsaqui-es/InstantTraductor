"""Captura en Python con el GIL ocupado y coste de CPU (spike S4, riesgo R6 de la investigacion).

La captura del plan B es Python puro (hilo + ctypes/comtypes): si otro hilo Python retiene el GIL, el
hilo de captura llega tarde a vaciar el bufer de WASAPI. Se mide con la fuente en un proceso EXTERNO
(su audio no depende del GIL de este proceso) y una captura EXCLUDE de este PID:

- coste de CPU de una captura (16 kHz mono, paquetes de 10 ms) en reposo;
- con un hilo Python de calculo puro ocupando el GIL: intervalo entre paquetes, flags de discontinuidad
  de WASAPI (AUDCLNT_BUFFERFLAGS_DATA_DISCONTINUITY = se perdieron datos) y huecos en el tono capturado;
- para dos tamanos del bufer de WASAPI: 100 ms (el del spike) y 30 ms.

Uso:  uv run python captura_bajo_gil.py
"""

from __future__ import annotations

import os
import sys
import time

import numpy as np
import psutil

import audio_spike  # noqa: F401  (COM en MTA antes de comtypes)
from audio_spike import banco
from audio_spike.analisis import _envolvente
from audio_spike.loopback_ctypes import CapturaProcesoCtypes
from audio_spike.modos import ModoCaptura
from audio_spike.registro import Registro

SR = banco.SR_CAPTURA
F = 1663.0


def huecos_en_tono(reg: Registro, t0: int, t1: int) -> tuple[int, float]:
    """Numero de huecos y milisegundos en hueco dentro del tono (sin 50 ms en cada extremo)."""
    x, _ = reg.senal_con_tiempos(t0, t1)
    if len(x) < SR // 2:
        return -1, 0.0
    env = _envolvente(x, SR, F, 80)  # ventana de 5 ms
    fuerte = np.nonzero(env > 0.5 * np.percentile(env, 95))[0]
    if len(fuerte) < 100:
        return -1, 0.0
    ini, fin = fuerte[0] + 800, fuerte[-1] - 800
    if fin <= ini:
        return -1, 0.0
    bajo = env[ini:fin] < 0.5 * np.median(env[ini:fin])
    return int(np.sum(np.diff(np.concatenate([[0], bajo.astype(int)])) == 1)), float(bajo.sum()) / SR * 1e3


def main() -> int:
    pid = os.getpid()
    tmp = banco.directorio_temporal("s4_gil_")
    log = os.path.join(tmp, "trabajadores.jsonl")
    entorno = banco.info_entorno()
    resultados: dict = {"entorno": entorno}
    print("== Captura con el GIL ocupado ==")
    ext = banco.ExternoUDP(log, metodo="cmd")
    ext.orden("abrir 20 3 2")
    yo = psutil.Process()
    try:
        # 1) coste de CPU de una captura en reposo
        cap = CapturaProcesoCtypes(pid=pid, modo=ModoCaptura.EXCLUDE, sample_rate=SR, buffer_ms=100)
        reg = Registro(SR, "cpu")
        cap.iniciar(reg)
        time.sleep(1.0)
        c0, t0 = yo.cpu_times(), time.perf_counter()
        time.sleep(10.0)
        c1, t1 = yo.cpu_times(), time.perf_counter()
        cpu = ((c1.user - c0.user) + (c1.system - c0.system)) / (t1 - t0) * 100.0
        cap.cerrar()
        print(f"CPU de una captura en reposo (10 s, 100 paquetes/s): {cpu:.1f} % de un nucleo")
        resultados["cpu_pct_un_nucleo_en_reposo"] = round(cpu, 1)

        # 2) con el GIL ocupado
        resultados["gil"] = {}
        print()
        print(f"{'bufer WASAPI':>12} {'GIL':>8} | {'paq/s':>6} {'int.p99':>8} {'int.max':>8} {'frames/s':>9} | "
              f"{'discont.':>8} {'huecos':>7} {'ms hueco':>9}")
        for buffer_ms in (100, 30):
            for estres in (False, True):
                cap = CapturaProcesoCtypes(pid=pid, modo=ModoCaptura.EXCLUDE, sample_rate=SR, buffer_ms=buffer_ms)
                reg = Registro(SR, f"{buffer_ms}")
                cap.iniciar(reg)
                time.sleep(0.5)
                carga = banco.CargaGIL() if estres else None
                if carga:
                    carga.start()
                t_ini = banco.ahora_ns()
                huecos, ms_huecos, medidos = 0, 0.0, 0
                try:
                    for _ in range(3):
                        ta = banco.ahora_ns()
                        ext.orden(f"tono {F} 1.0 0.10 gil_{buffer_ms}")
                        tb = banco.ahora_ns()
                        h, ms = huecos_en_tono(reg, ta - int(0.1e9), tb + int(0.3e9))
                        if h >= 0:
                            huecos += h
                            ms_huecos += ms
                            medidos += 1
                        time.sleep(0.3)
                finally:
                    t_fin = banco.ahora_ns()
                    if carga:
                        carga.parar = True
                        carga.join(timeout=2)
                ps = [p for p in list(reg.paquetes) if t_ini <= p.t_ns <= t_fin]
                ints = np.diff(np.array([p.t_ns for p in ps], dtype=np.int64)) / 1e6
                dur = (t_fin - t_ini) / 1e9
                fila = {
                    "tonos_medidos": medidos,
                    "paquetes_por_s": round(len(ps) / dur, 1),
                    "intervalo_p99_ms": round(float(np.percentile(ints, 99)), 1),
                    "intervalo_max_ms": round(float(ints.max()), 1),
                    "frames_por_s": round(sum(len(p.muestras) for p in ps) / dur, 0),
                    "discontinuidades": cap.estadisticas["discontinuidades"],
                    "huecos_en_el_tono": huecos,
                    "ms_en_hueco": round(ms_huecos, 1),
                    "error": cap.error,
                }
                resultados["gil"][f"{buffer_ms}ms_{'ocupado' if estres else 'libre'}"] = fila
                print(f"{buffer_ms:>10} ms {'OCUPADO' if estres else 'libre':>8} | {fila['paquetes_por_s']:6.1f} "
                      f"{fila['intervalo_p99_ms']:8.1f} {fila['intervalo_max_ms']:8.1f} {fila['frames_por_s']:9.0f} | "
                      f"{fila['discontinuidades']:8d} {huecos:7d} {ms_huecos:9.1f}")
                cap.cerrar()
    finally:
        ext.cerrar()
    ruta = banco.guardar_json("captura_bajo_gil.json", resultados)
    print("\nResultados guardados en", ruta)
    banco.borrar(tmp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
