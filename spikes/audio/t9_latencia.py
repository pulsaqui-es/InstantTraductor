"""T9 - Latencia: desde que un proceso externo empieza a sonar hasta que la muestra llega a la captura.

Un trabajador Python lanzado con `cmd /c start /min` (fuera del arbol de este proceso) mantiene un
PlaybackDevice abierto (ceros) y, al recibir una orden UDP, escribe un tono de 0,25 s. Anota con
`time.perf_counter_ns()` (QPC: el mismo reloj en todos los procesos, comprobado con pings) el instante
en que entrega al dispositivo el primer bloque con tono. Aqui se detecta el inicio del tono en la
captura EXCLUDE (la que usaria la app) y en la ENDPOINT (loopback clasico, de referencia) y se resta:

    latencia = hora estimada de la primera muestra del tono en la captura - hora de escritura en la fuente

La hora de una muestra en la captura se estima como llegada del paquete - (n - i)/fs (los sellos QPC del
process loopback son sinteticos, ver T4). Es una latencia de extremo a extremo de la capa de audio: incluye
el bufer de reproduccion de la FUENTE (periodo x periodos), la mezcla de Windows y el paquete de captura
de 10 ms. Se repite con dos configuraciones de la fuente: 10 ms x 2 y 20 ms x 3 (la del ADR).

Uso:  uv run python t9_latencia.py [--n 10]
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import time

import numpy as np

import audio_spike  # noqa: F401  (COM en MTA antes de comtypes)
from audio_spike import banco
from audio_spike.analisis import inicio_tono, nivel_tono
from audio_spike.modos import ModoCaptura

FRECUENCIA = 1663.0
TONO_S = 0.25
AMPLITUD = 0.15
SR = banco.SR_CAPTURA


def estadisticas(v: list[float]) -> dict:
    a = np.array(v, dtype=float)
    if len(a) == 0:
        return {"n": 0}
    return {"n": int(len(a)), "min_ms": round(float(a.min()), 1), "mediana_ms": round(float(np.median(a)), 1),
            "media_ms": round(float(a.mean()), 1), "p95_ms": round(float(np.percentile(a, 95)), 1),
            "max_ms": round(float(a.max()), 1), "desv_ms": round(float(a.std()), 1)}


def inicio_en_captura(reg, t_fuente_ns: int) -> float | None:
    """Hora (ns) estimada del inicio del tono en la captura, o None si no se detecta."""
    x, t = reg.senal_con_tiempos(t_fuente_ns - int(0.15e9), t_fuente_ns + int(0.8e9))
    if len(x) < SR // 4:
        return None
    _a, _f, ratio = nivel_tono(x, SR, FRECUENCIA)
    if ratio < 15.0:
        return None
    i = inicio_tono(x, SR, FRECUENCIA)
    if i is None or i < 0 or i >= len(t):
        return None
    return float(t[i])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=10, help="pruebas por configuracion")
    ap.add_argument("--configs", default="10x2,20x3", help="periodo_ms x periodos de la fuente, separados por comas")
    args = ap.parse_args()

    pid = os.getpid()
    tmp = banco.directorio_temporal("s4_t9_")
    log = os.path.join(tmp, "trabajadores.jsonl")
    entorno = banco.info_entorno()
    print("== T9 latencia ==")
    print("Dispositivo:", entorno["dispositivo_por_defecto"]["nombre"], "| mezcla:", entorno["formato_mezcla_dispositivo"])
    capt = banco.Capturas(pid, modos=(ModoCaptura.EXCLUDE, ModoCaptura.ENDPOINT))
    capt.iniciar()
    ext = None
    resultados: dict = {"entorno": entorno, "configs": {}}
    try:
        ext = banco.ExternoUDP(log, metodo="cmd")
        print("trabajador externo: pid", ext.pid_real, "| ppid", ext.ppid)
        from audio_spike.procesos import alcanza, cadena_padres, cadena_texto

        cad = cadena_padres(ext.pid_real)
        resultados["cadena_externo"] = cadena_texto(cad)
        resultados["externo_cuelga_de_este_proceso"] = alcanza(cad, pid)
        print("cadena del externo:", cadena_texto(cad), "| cuelga de este proceso:", alcanza(cad, pid))
        # comprobacion de relojes: pings UDP
        offsets, rtts = [], []
        for _ in range(30):
            a = banco.ahora_ns()
            r = ext.orden("ping")
            b = banco.ahora_ns()
            offsets.append((r["t_ns"] - (a + b) / 2) / 1e6)
            rtts.append((b - a) / 1e6)
            time.sleep(0.01)
        resultados["reloj"] = {"desfase_mediano_ms": round(float(np.median(offsets)), 3),
                               "desfase_abs_max_ms": round(float(np.max(np.abs(offsets))), 3),
                               "rtt_mediano_ms": round(float(np.median(rtts)), 3)}
        print("relojes entre procesos (perf_counter):", resultados["reloj"])

        for cfg in args.configs.split(","):
            periodo, periodos = (int(v) for v in cfg.split("x"))
            ext.orden("cerrar")
            ext.orden(f"abrir {periodo} {periodos} 2")
            time.sleep(1.0)
            pruebas = []
            print(f"\n-- fuente {periodo} ms x {periodos} periodos: {args.n} pruebas")
            for i in range(args.n):
                time.sleep(random.uniform(1.2, 2.2))  # fase aleatoria frente a los paquetes de 10 ms
                t_envio = banco.ahora_ns()
                r = ext.orden(f"tono {FRECUENCIA} {TONO_S} {AMPLITUD} t9_{cfg}_{i}")
                time.sleep(0.6)
                pruebas.append({"i": i, "t_envio_ns": t_envio, "t_fuente_ns": r["t_primer_bloque_ns"],
                                "orden_a_fuente_ms": (r["t_primer_bloque_ns"] - t_envio) / 1e6})
            resultados["configs"][cfg] = {"pruebas": pruebas}
        ext.orden("cerrar")
    finally:
        if ext is not None:
            ext.cerrar()
        time.sleep(0.3)
        capt.cerrar()

    # ---- analisis ----------------------------------------------------------------------------------------
    print()
    for cfg, datos in resultados["configs"].items():
        lat = {"exclude": [], "endpoint": []}
        dif = []
        for p in datos["pruebas"]:
            t_ex = inicio_en_captura(capt.registros[ModoCaptura.EXCLUDE], p["t_fuente_ns"])
            t_ep = inicio_en_captura(capt.registros[ModoCaptura.ENDPOINT], p["t_fuente_ns"])
            p["latencia_exclude_ms"] = None if t_ex is None else round((t_ex - p["t_fuente_ns"]) / 1e6, 1)
            p["latencia_endpoint_ms"] = None if t_ep is None else round((t_ep - p["t_fuente_ns"]) / 1e6, 1)
            if t_ex is not None:
                lat["exclude"].append((t_ex - p["t_fuente_ns"]) / 1e6)
            if t_ep is not None:
                lat["endpoint"].append((t_ep - p["t_fuente_ns"]) / 1e6)
            if t_ex is not None and t_ep is not None:
                dif.append((t_ex - t_ep) / 1e6)
        datos["estadisticas"] = {"exclude": estadisticas(lat["exclude"]), "endpoint": estadisticas(lat["endpoint"]),
                                 "exclude_menos_endpoint": estadisticas(dif)}
        print(f"Fuente {cfg} (periodo ms x periodos):")
        print("   pruebas (EXCLUDE ms):", [p["latencia_exclude_ms"] for p in datos["pruebas"]])
        for nombre in ("exclude", "endpoint", "exclude_menos_endpoint"):
            print(f"   {nombre:24}", datos["estadisticas"][nombre])
    ruta = banco.guardar_json("t9_latencia.json", resultados)
    print("\nResultados guardados en", ruta)
    banco.borrar(tmp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
