"""Reproduccion - PlaybackDevice sin device_id a 48 kHz en el dispositivo por defecto (spike S4, ADR-0005).

Comprueba:
1. Que `miniaudio.PlaybackDevice` se abre sin `device_id` (dispositivo por defecto, WASAPI) a 48 kHz
   float32 y que el tono llega de verdad al dispositivo por defecto (lo oye la captura ENDPOINT).
2. Formatos de entrada: 48000/44100/24000/22050 Hz, mono y estereo. Si Windows/miniaudio convierten bien,
   el tono se oye a la frecuencia correcta (un tono de 1234 Hz mal interpretado aparecería en otra) y
   no hace falta remuestrear los segmentos del TTS en Python.
3. Cadencia de las peticiones de datos (callbacks) para varios periodos, en reposo.
4. Cadencia con el GIL ocupado por un hilo Python que hace calculo puro (el riesgo R6 de la investigacion),
   sin GPU: cuantos callbacks se retrasan mas de 1,5 periodos.
5. Cortes reales: tonos de 1 s con el GIL libre y ocupado; se cuentan los huecos en el tono capturado
   (un hueco es un underrun audible) para 10 ms x 2 y 20 ms x 3 periodos.

Uso:  uv run python reproduccion.py
"""

from __future__ import annotations

import os
import sys
import time

import miniaudio
import numpy as np

import audio_spike  # noqa: F401  (COM en MTA antes de comtypes)
from audio_spike import banco
from audio_spike.analisis import maximo_tono
from audio_spike.modos import ModoCaptura
from audio_spike.tonos import ReproductorTonos

SR_CAP = banco.SR_CAPTURA
F = 1234.0


def tono_en(reg_ep, reg_in, rep: ReproductorTonos) -> dict:
    t0 = banco.ahora_ns()
    rep.tono_y_esperar(F, 0.4, 0.15, cola_s=0.4)
    t1 = banco.ahora_ns()
    res = {}
    for nombre, reg in (("endpoint", reg_ep), ("include", reg_in)):
        x, _ = reg.ventana(t0 - int(0.1e9), t1 + int(0.5e9))
        m = maximo_tono(x, SR_CAP, F, ventana_s=0.2)
        res[nombre] = {"detectado": bool(m["ratio_db"] >= 15.0), "ratio_db": round(m["ratio_db"], 1),
                       "amp_dbfs": round(m["amp_dbfs"], 1)}
    return res


def glitches(reg_in, periodo: int, periodos: int, estres: bool, tonos: int = 3) -> dict:
    """Reproduce tonos de 1 s (amplitud 0,10) y cuenta los huecos en la envolvente capturada.

    Un hueco (ventana de 5 ms por debajo de la mitad del nivel estable, sin contar 50 ms en cada extremo
    del tono) es un corte audible: el dispositivo se quedo sin datos (underrun).
    """
    from audio_spike.analisis import _envolvente

    rep = ReproductorTonos(48000, 2, periodo, periodos)
    rep.abrir()
    time.sleep(0.4)
    carga = CargaGIL() if estres else None
    if carga:
        carga.start()
    huecos, ms_huecos, tonos_medidos = 0, 0.0, 0
    try:
        for _ in range(tonos):
            t0 = banco.ahora_ns()
            rep.tono_y_esperar(F, 1.0, 0.10, cola_s=0.4)
            t1 = banco.ahora_ns()
            x, t = reg_in.senal_con_tiempos(t0 - int(0.1e9), t1 + int(0.3e9))
            env = _envolvente(x, SR_CAP, F, 80)  # ventana de 5 ms
            fuerte = env > 0.5 * np.percentile(env, 95)
            idx = np.nonzero(fuerte)[0]
            if len(idx) < 100:
                continue
            ini, fin = idx[0] + 800, idx[-1] - 800  # 50 ms de margen
            if fin <= ini:
                continue
            estable = np.median(env[ini:fin])
            bajo = env[ini:fin] < 0.5 * estable
            huecos += int(np.sum(np.diff(np.concatenate([[0], bajo.astype(int)])) == 1))
            ms_huecos += float(bajo.sum()) / SR_CAP * 1e3
            tonos_medidos += 1
            time.sleep(0.3)
    finally:
        if carga:
            carga.parar = True
            carga.join(timeout=2)
        rep.cerrar()
    return {"tonos_medidos": tonos_medidos, "huecos_en_el_tono": huecos, "ms_en_hueco": round(ms_huecos, 1)}


def cadencia(rep: ReproductorTonos, segundos: float) -> dict:
    rep.t_callbacks.clear()
    rep.frames_por_callback.clear()
    time.sleep(segundos)
    ts = np.array(list(rep.t_callbacks), dtype=np.int64)
    fr = list(rep.frames_por_callback)
    if len(ts) < 3:
        return {"callbacks": int(len(ts))}
    ints = np.diff(ts) / 1e6
    periodo_ms = rep.periodo_ms
    return {
        "callbacks": int(len(ts)),
        "frames_por_callback": sorted(set(fr))[:4],
        "intervalo_med_ms": round(float(ints.mean()), 2),
        "intervalo_p50_ms": round(float(np.median(ints)), 2),
        "intervalo_p99_ms": round(float(np.percentile(ints, 99)), 2),
        "intervalo_max_ms": round(float(ints.max()), 2),
        "mayores_de_1_5_periodos": int(np.sum(ints > 1.5 * periodo_ms)),
        "mayores_de_periodos_x_periodo": int(np.sum(ints > rep.periodos * periodo_ms)),
    }


CargaGIL = banco.CargaGIL


def main() -> int:
    pid = os.getpid()
    entorno = banco.info_entorno()
    resultados: dict = {"entorno": entorno}
    print("== Reproduccion ==")
    print("Dispositivo por defecto (pycaw):", entorno["dispositivo_por_defecto"]["nombre"])
    print("Formato de mezcla del dispositivo:", entorno["formato_mezcla_dispositivo"])
    try:
        devs = miniaudio.Devices(backends=[miniaudio.Backend.WASAPI]).get_playbacks()
        print("Dispositivos de reproduccion segun miniaudio (WASAPI):")
        for d in devs:
            print("   -", d["name"], "| formatos nativos:", d["formats"][:2])
        resultados["dispositivos_miniaudio"] = [{"nombre": d["name"], "formatos": d["formats"][:2]} for d in devs]
    except Exception as exc:
        print("no se pudo enumerar con miniaudio:", exc)

    capt = banco.Capturas(pid, modos=(ModoCaptura.INCLUDE, ModoCaptura.ENDPOINT))
    capt.iniciar()
    reg_in, reg_ep = capt.registros[ModoCaptura.INCLUDE], capt.registros[ModoCaptura.ENDPOINT]
    time.sleep(1.0)
    try:
        # 1) apertura sin device_id a 48 kHz float32 (configuracion del ADR)
        print("\n-- 1) apertura sin device_id, 48 kHz float32, estereo, periodo 20 ms x 3")
        t0 = time.perf_counter()
        rep = ReproductorTonos(48000, 2, 20, 3)
        rep.abrir()
        t_abrir = (time.perf_counter() - t0) * 1000
        print(f"   abierto en {t_abrir:.0f} ms | backend: {rep.dispositivo.backend} | device_id: None")
        time.sleep(0.5)
        r1 = tono_en(reg_ep, reg_in, rep)
        print("   tono 1234 Hz -> captura ENDPOINT (dispositivo por defecto):", r1["endpoint"])
        print("   tono 1234 Hz -> captura INCLUDE (este proceso):", r1["include"])
        resultados["apertura"] = {"ms": round(t_abrir, 1), "backend": rep.dispositivo.backend, "tono": r1}
        # 3) cadencia en reposo
        cad = cadencia(rep, 5.0)
        print("   cadencia de callbacks en reposo (5 s):", cad)
        resultados["cadencia_20x3_reposo"] = cad
        # 4) GIL ocupado
        carga = CargaGIL()
        carga.start()
        cad_gil = cadencia(rep, 5.0)
        carga.parar = True
        carga.join(timeout=2)
        print("   cadencia con un hilo Python de calculo puro ocupando el GIL (5 s):", cad_gil)
        resultados["cadencia_20x3_gil"] = cad_gil
        rep.cerrar()

        # 3b) otros periodos
        print("\n-- 3b) cadencia en reposo con otros periodos")
        resultados["cadencias"] = {}
        for periodo, periodos in ((10, 2), (10, 3), (30, 3)):
            r = ReproductorTonos(48000, 2, periodo, periodos)
            r.abrir()
            time.sleep(0.4)
            c = cadencia(r, 4.0)
            r.cerrar()
            resultados["cadencias"][f"{periodo}x{periodos}"] = c
            print(f"   {periodo} ms x {periodos}: {c}")
        print("\n-- 3c) con el GIL ocupado, periodo 10 ms x 2 y 30 ms x 3")
        resultados["cadencias_gil"] = {}
        for periodo, periodos in ((10, 2), (30, 3)):
            r = ReproductorTonos(48000, 2, periodo, periodos)
            r.abrir()
            time.sleep(0.4)
            carga = CargaGIL()
            carga.start()
            c = cadencia(r, 4.0)
            carga.parar = True
            carga.join(timeout=2)
            r.cerrar()
            resultados["cadencias_gil"][f"{periodo}x{periodos}"] = c
            print(f"   {periodo} ms x {periodos}: {c}")

        # 5) glitches reales (huecos en el tono capturado) con y sin GIL ocupado
        print("\n-- 5) cortes reales: 3 tonos de 1 s con el GIL libre y ocupado (huecos en la envolvente capturada)")
        resultados["glitches"] = {}
        for periodo, periodos in ((10, 2), (20, 3)):
            for estres in (False, True):
                g = glitches(reg_in, periodo, periodos, estres)
                clave = f"{periodo}x{periodos}_{'gil_ocupado' if estres else 'gil_libre'}"
                resultados["glitches"][clave] = g
                print(f"   {periodo} ms x {periodos} | GIL {'OCUPADO' if estres else 'libre  '} | {g}")
                time.sleep(0.3)

        # 2) formatos de entrada
        print("\n-- 2) formatos de entrada (el tono debe oirse a 1234 Hz: conversion correcta)")
        print(f"   {'frecuencia':>10} {'canales':>8} | {'abre':5} {'ENDPOINT':>26}")
        resultados["formatos"] = []
        for sr in (48000, 44100, 24000, 22050):
            for nch in (1, 2):
                fila = {"sample_rate": sr, "canales": nch}
                try:
                    r = ReproductorTonos(sr, nch, 20, 3)
                    r.abrir()
                    time.sleep(0.3)
                    res = tono_en(reg_ep, reg_in, r)
                    r.cerrar()
                    fila.update({"abre": True, **res})
                    e = res["endpoint"]
                    print(f"   {sr:10d} {nch:8d} | {'si':5} {'SI' if e['detectado'] else 'no'} {e['ratio_db']:6.1f} dB  {e['amp_dbfs']:6.1f} dBFS")
                except Exception as exc:
                    fila.update({"abre": False, "error": repr(exc)})
                    print(f"   {sr:10d} {nch:8d} | {'NO':5} {exc!r}")
                resultados["formatos"].append(fila)
                time.sleep(0.3)
    finally:
        capt.cerrar()
    ruta = banco.guardar_json("reproduccion.json", resultados)
    print("\nResultados guardados en", ruta)
    return 0


if __name__ == "__main__":
    sys.exit(main())
