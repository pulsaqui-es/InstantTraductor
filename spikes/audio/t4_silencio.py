"""T4 - Silencio: llegan paquetes cuando no suena nada? (spike S4, ADR-0005).

Mide, con las tres capturas a la vez (EXCLUDE y INCLUDE sobre este PID + ENDPOINT de control),
que entrega Windows en cada situacion de silencio y evalua el relleno por reloj propuesto.

Fases (la captura sigue viva todo el rato):
  ambiente              nada suena desde este proceso
  reproductor_en_ceros  PlaybackDevice abierto y alimentado con ceros (como audio_io en reposo)
  rafagas               3 tonos de 0,3 s separados por 1,5 s de silencio, con el reproductor abierto
  reproductor_cerrado   se cierra el PlaybackDevice; nada suena
  ffplay_silencio       app externa con una sesion de audio ACTIVA que reproduce ceros (WAV mudo)
  deriva                tramo largo en reposo, con instancias de captura extra, para medir la deriva

Por fase y captura se mide: paquetes/s, frames/s frente a 16000, fraccion de paquetes con muestras
distintas de cero, intervalo entre llegadas (medio, p99, maximo) y flags de WASAPI. Ademas: regularidad
de los sellos QPC, deriva del reloj de audio frente a QPC y evaluacion del relleno por reloj
(audio_spike/relleno.py) sobre las llegadas reales.

IMPORTANTE: la fase `ambiente` solo vale como "silencio del sistema" si ninguna otra app tiene una
sesion activa (aunque sea muda): el loopback de dispositivo (ENDPOINT) entrega paquetes mientras haya
alguna sesion activa. El script lista las sesiones activas al empezar.

Uso:  uv run python t4_silencio.py [--fase-s 8] [--deriva-s 60]
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import numpy as np

import audio_spike  # noqa: F401  (COM en MTA antes de comtypes)
from audio_spike import banco
from audio_spike.analisis import rms_dbfs
from audio_spike.loopback_ctypes import CapturaProcesoCtypes
from audio_spike.modos import ModoCaptura
from audio_spike.registro import Registro
from audio_spike.relleno import simular
from audio_spike.tonos import AMPLITUD_POR_DEFECTO, ReproductorTonos

SR = banco.SR_CAPTURA


def estadisticas(reg, t0: int, t1: int) -> dict:
    """Estadisticas de los paquetes de `reg` que llegan en [t0, t1] (ns)."""
    ps = [p for p in list(reg.paquetes) if t0 <= p.t_ns <= t1]
    dur_s = (t1 - t0) / 1e9
    if not ps:
        return {"paquetes": 0, "paquetes_por_s": 0.0, "frames_por_s": 0.0, "pct_con_señal": 0.0,
                "intervalo_med_ms": None, "intervalo_p99_ms": None, "intervalo_max_ms": None,
                "rms_dbfs": None, "flags": []}
    ts = np.array([p.t_ns for p in ps], dtype=np.int64)
    ints = np.diff(ts) / 1e6
    frames = sum(len(p.muestras) for p in ps)
    con_señal = sum(1 for p in ps if np.any(np.abs(p.muestras) > 1e-5))  # > -100 dBFS
    return {
        "paquetes": len(ps),
        "paquetes_por_s": round(len(ps) / dur_s, 1),
        "frames_por_s": round(frames / dur_s, 0),
        "pct_con_señal": round(100.0 * con_señal / len(ps), 1),
        "intervalo_med_ms": round(float(ints.mean()), 2) if len(ints) else None,
        "intervalo_p99_ms": round(float(np.percentile(ints, 99)), 2) if len(ints) else None,
        "intervalo_max_ms": round(float(ints.max()), 2) if len(ints) else None,
        "rms_dbfs": round(float(rms_dbfs(np.concatenate([p.muestras for p in ps]))), 1),
        "flags": sorted({p.flags for p in ps if p.flags is not None}),
    }


def regularidad_qpc(reg, t0: int = 0, t1: int = 1 << 62) -> dict:
    """Regularidad de los sellos QPC y deriva del reloj de audio frente a QPC (tasa efectiva)."""
    ps = [p for p in list(reg.paquetes) if p.qpc_ns and t0 <= p.t_ns <= t1]
    if len(ps) < 50:
        return {}
    q = np.array([p.qpc_ns for p in ps], dtype=np.float64)
    n = np.array([len(p.muestras) for p in ps], dtype=np.float64)
    t = np.array([p.t_ns for p in ps], dtype=np.float64)
    paso = np.diff(q) / 1e6
    desv = paso - n[:-1] / SR * 1e3  # diferencia entre el paso del sello y la duracion del paquete
    tasa_sellos = (n[:-1].sum()) / ((q[-1] - q[0]) / 1e9)  # frames/s entre el primer y el ultimo sello
    tasa_llegada = (n[1:].sum()) / ((t[-1] - t[0]) / 1e9)  # frames/s por hora de llegada (reloj de pared)
    llegada = (t - q) / 1e6
    salto_idx = np.nonzero(np.abs(desv) > 5.0)[0]
    return {
        "saltos": [{"t_llegada_ns": int(t[i + 1]), "paso_ms": round(float(paso[i]), 2)} for i in salto_idx],
        "paquetes": len(ps),
        "duracion_s": round(float((t[-1] - t[0]) / 1e9), 1),
        "pasos_de_sello_exactos_pct": round(float(100.0 * np.mean(np.abs(desv) < 1e-3)), 2),
        "desviacion_sello_std_ms": round(float(desv.std()), 3),
        "desviacion_sello_absmax_ms": round(float(np.abs(desv).max()), 3),
        "saltos_de_sello_mayores_de_5ms": int(np.sum(np.abs(desv) > 5.0)),
        "tasa_por_sellos_hz": round(float(tasa_sellos), 2),
        "deriva_sellos_ppm": round(float((tasa_sellos / SR - 1.0) * 1e6), 0),
        "tasa_por_llegada_hz": round(float(tasa_llegada), 2),
        "deriva_llegada_ppm": round(float((tasa_llegada / SR - 1.0) * 1e6), 0),
        "llegada_menos_sello_med_ms": round(float(np.median(llegada)), 2),
        "llegada_menos_sello_p99_ms": round(float(np.percentile(llegada, 99)), 2),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fase-s", type=float, default=8.0, help="duracion de las fases de espera (s)")
    ap.add_argument("--deriva-s", type=float, default=60.0, help="duracion del tramo de deriva (0 = omitir)")
    ap.add_argument("--nombre", default="t4_silencio")
    args = ap.parse_args()

    pid = os.getpid()
    tmp = banco.directorio_temporal("s4_t4_")
    entorno = banco.info_entorno()
    print("== T4 silencio ==")
    print("Windows:", entorno["windows"], "| dispositivo:", entorno["dispositivo_por_defecto"]["nombre"])
    ses = banco.sesiones_activas()
    activas = [s for s in ses if s["estado"] == "activa"]
    print("Sesiones del dispositivo por defecto:", len(ses), "| ACTIVAS:", activas if activas else "ninguna")
    capt = banco.Capturas(pid)
    # instancias extra para comparar la deriva entre capturas simultaneas
    extra: list[tuple[str, CapturaProcesoCtypes, Registro]] = []
    if args.deriva_s > 0:
        for nombre, modo in (("exclude_2", ModoCaptura.EXCLUDE), ("include_2", ModoCaptura.INCLUDE),
                             ("endpoint_2", ModoCaptura.ENDPOINT)):
            c = CapturaProcesoCtypes(pid=pid, modo=modo, sample_rate=SR)
            extra.append((nombre, c, Registro(SR, nombre)))
    capt.iniciar()
    for _n, c, r in extra:
        c.iniciar(r)
    time.sleep(0.5)
    fases: dict[str, tuple[int, int]] = {}
    extras: dict = {"sesiones_al_empezar": ses}
    rep = None
    try:
        # A) ambiente
        t0 = banco.ahora_ns()
        time.sleep(args.fase_s)
        fases["ambiente"] = (t0, banco.ahora_ns())
        # B) reproductor abierto, alimentado con ceros
        rep = ReproductorTonos(48000, 2, 20, 3)
        rep.abrir()
        time.sleep(0.5)
        t0 = banco.ahora_ns()
        time.sleep(args.fase_s)
        fases["reproductor_en_ceros"] = (t0, banco.ahora_ns())
        # C) rafagas de tono con el reproductor abierto
        t0 = banco.ahora_ns()
        for _ in range(3):
            time.sleep(1.5)
            rep.tono_y_esperar(1234.0, 0.3, AMPLITUD_POR_DEFECTO, cola_s=0.0)
        time.sleep(1.5)
        fases["rafagas"] = (t0, banco.ahora_ns())
        # D) reproductor cerrado
        rep.cerrar()
        rep = None
        time.sleep(0.5)
        t0 = banco.ahora_ns()
        time.sleep(args.fase_s * 0.5)
        fases["reproductor_cerrado"] = (t0, banco.ahora_ns())
        # E) app externa con una sesion ACTIVA que reproduce ceros (WAV mudo de 4 s)
        wav = banco.wav_tono(tmp, "s4_t4_mudo.wav", 1000.0, 0.05, amplitud=0.0, cola_s=4.0)
        ej = banco.lanzar_ffplay(wav, "cmd")
        time.sleep(0.8)
        extras["sesiones_con_ffplay"] = banco.sesiones_activas()
        t0 = banco.ahora_ns()
        banco.esperar_ffplay(ej, 8.0)
        fases["ffplay_silencio"] = (t0, banco.ahora_ns())
        time.sleep(0.5)
        # F) tramo largo de deriva, sin sonido
        if args.deriva_s > 0:
            t0 = banco.ahora_ns()
            time.sleep(args.deriva_s)
            fases["deriva"] = (t0, banco.ahora_ns())
    finally:
        if rep is not None:
            rep.cerrar()
        capt.cerrar()
        for _n, c, _r in extra:
            c.cerrar()

    # ---- informe --------------------------------------------------------------------------
    resultados: dict = {"fases": {}}
    print()
    print(f"{'fase':22} {'captura':9} {'paq/s':>6} {'frames/s':>9} {'%con señal':>10} {'int.med':>8} {'p99':>7} {'max ms':>8} {'RMS dBFS':>9} flags")
    for nombre, (t0, t1) in fases.items():
        resultados["fases"][nombre] = {"duracion_s": round((t1 - t0) / 1e9, 2)}
        for modo in (ModoCaptura.EXCLUDE, ModoCaptura.INCLUDE, ModoCaptura.ENDPOINT):
            s = estadisticas(capt.registros[modo], t0, t1)
            resultados["fases"][nombre][modo.value] = s
            rms = "-inf" if s["rms_dbfs"] is None else f"{s['rms_dbfs']:.1f}"
            print(f"{nombre:22} {modo.value:9} {s['paquetes_por_s']:6.1f} {s['frames_por_s']:9.0f} {s['pct_con_señal']:10.1f} "
                  f"{str(s['intervalo_med_ms']):>8} {str(s['intervalo_p99_ms']):>7} {str(s['intervalo_max_ms']):>8} {rms:>9} {s['flags']}")
    amb = resultados["fases"]["ambiente"]["exclude"]["rms_dbfs"]
    resultados["ambiente_silencioso"] = bool(amb is not None and amb < -90 and not activas)
    print()
    print("Ambiente: EXCLUDE %s dBFS, sesiones activas ajenas: %s -> %s" % (
        amb, len(activas), "sistema en silencio real" if resultados["ambiente_silencioso"]
        else "el sistema NO estaba en silencio: la referencia de silencio es INCLUDE"))

    # ---- sellos QPC y deriva -----------------------------------------------------------------------------
    print()
    print("Sellos QPC y deriva del reloj de audio frente a QPC (toda la ejecucion, una fila por captura):")
    todos = [(m.value, capt.registros[m]) for m in (ModoCaptura.EXCLUDE, ModoCaptura.INCLUDE, ModoCaptura.ENDPOINT)]
    todos += [(n, r) for n, _c, r in extra]
    for nombre, reg in todos:
        q = regularidad_qpc(reg)
        resultados.setdefault("qpc", {})[nombre] = q
        print(f"  {nombre:11} { {k: v for k, v in q.items() if k != 'saltos'} }")
    print("Saltos de sello (> 5 ms respecto a la duracion del paquete) y la fase en que ocurren:")
    for nombre, reg in todos[:2]:
        for s in regularidad_qpc(reg).get("saltos", []):
            fase = next((n for n, (a, b) in fases.items() if a <= s["t_llegada_ns"] <= b), "entre fases")
            cerca = min(((abs(s['t_llegada_ns'] - lim) / 1e9, f"{'inicio' if i == 0 else 'fin'} de {n}")
                         for n, par in fases.items() for i, lim in enumerate(par)), key=lambda c: c[0])
            print(f"  {nombre:9} paso de sello {s['paso_ms']:6.2f} ms | fase '{fase}' | "
                  f"{cerca[0]:.2f} s del {cerca[1]}")
    if "deriva" in fases:
        print("Solo el tramo de deriva (sin sonido):")
        t0d, t1d = fases["deriva"]
        for nombre, reg in todos:
            q = regularidad_qpc(reg, t0d, t1d)
            resultados.setdefault("qpc_deriva", {})[nombre] = q
            if q:
                print(f"  {nombre:11} {q['duracion_s']:6.1f} s | deriva por llegada {q['deriva_llegada_ppm']:+.0f} ppm | "
                      f"por sellos {q['deriva_sellos_ppm']:+.0f} ppm | sellos exactos {q['pasos_de_sello_exactos_pct']} % "
                      f"(saltos > 5 ms: {q['saltos_de_sello_mayores_de_5ms']}) | llegada-sello med {q['llegada_menos_sello_med_ms']} "
                      f"p99 {q['llegada_menos_sello_p99_ms']} ms")
            else:
                print(f"  {nombre:11} sin paquetes suficientes")

    # ---- evaluacion del relleno por reloj sobre llegadas reales --------------------------------------------
    print()
    print("Relleno por reloj (audio_spike/relleno.py) sobre las llegadas reales de toda la ejecucion:")
    for nombre, reg in todos[:3]:
        llegadas = [(p.t_ns, len(p.muestras)) for p in list(reg.paquetes)]
        m = simular(llegadas, SR)
        resultados.setdefault("relleno", {})[nombre] = m
        if m:
            print(f"  {nombre:9} reales {m['paquetes_reales_s']:6.2f} s | rellenadas {m['rellenadas_s']:6.2f} s | "
                  f"huecos {m['huecos']:3d} | recortadas {m['recortadas_ms']:.1f} ms | "
                  f"retraso de la salida {m['retraso_medio_ms']:.1f} ms (max {m['retraso_max_ms']:.1f})")
        else:
            print(f"  {nombre:9} sin paquetes")

    ruta = banco.guardar_json(f"{args.nombre}.json", {"entorno": entorno, **resultados, "extras": extras})
    print("\nResultados guardados en", ruta)
    banco.borrar(tmp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
