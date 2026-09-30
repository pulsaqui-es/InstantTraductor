"""T1b - Que entiende Windows por "arbol de procesos" en el process loopback (spike S4).

T1 mostro que el audio de un hijo lanzado con `sys.executable` (en un venv de uv es un
redirector que crea el interprete real como hijo) NO queda excluido. Este script averigua por que:

Parte A (ascendentes): el mismo tono de ESTE proceso se mide con capturas INCLUDE y EXCLUDE cuyo
  PID objetivo es cada ascendiente (yo, el redirector del venv, uv.exe, bash.exe...). Si Windows
  recorre el arbol entero, INCLUDE(ascendiente) oira mi tono para todos; si solo cuenta al hijo
  directo, solo para el primero.
Parte B (descendientes): hijos y nietos lanzados con el interprete base (hijo DIRECTO, sin
  redirector) y con `sys.executable` (con redirector), antes y despues de activar la captura.

Uso:  uv run python t1b_arbol.py [--solo-a] [--solo-b]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import audio_spike  # noqa: F401
from audio_spike import banco
from audio_spike.analisis import maximo_tono
from audio_spike.loopback_ctypes import CapturaProcesoCtypes, ErrorCaptura
from audio_spike.modos import ModoCaptura
from audio_spike.procesos import alcanza, cadena_padres, cadena_texto
from audio_spike.registro import Registro
from audio_spike.tonos import AMPLITUD_POR_DEFECTO, ReproductorTonos

TONO_S = 0.6
UMBRAL_RATIO_DB = 15.0
UMBRAL_SOBRE_BASE_DB = 10.0


def detectar(reg: Registro, t0: int, t1: int, base: tuple[int, int], f: float) -> dict:
    x, _ = reg.ventana(t0, t1)
    xb, _ = reg.ventana(*base)
    m = maximo_tono(x, banco.SR_CAPTURA, f)
    mb = maximo_tono(xb, banco.SR_CAPTURA, f)
    det = m["ratio_db"] >= UMBRAL_RATIO_DB and (m["ratio_db"] - mb["ratio_db"]) >= UMBRAL_SOBRE_BASE_DB
    return {"detectado": bool(det), "ratio_db": round(m["ratio_db"], 1), "amp_dbfs": round(m["amp_dbfs"], 1)}


def parte_a(resultados: dict) -> None:
    print("\n== Parte A: mi tono visto desde capturas cuyo PID objetivo es cada ascendiente ==")
    yo = os.getpid()
    cadena = [c for c in cadena_padres(yo) if c["vivo"]]
    print("Cadena:", cadena_texto(cadena))
    caps: dict[tuple[int, str, str], tuple[CapturaProcesoCtypes, Registro]] = {}
    for nivel, c in enumerate(cadena):
        modos = [ModoCaptura.INCLUDE] + ([ModoCaptura.EXCLUDE] if nivel <= 3 else [])
        for modo in modos:
            try:
                cap = CapturaProcesoCtypes(pid=c["pid"], modo=modo, sample_rate=banco.SR_CAPTURA)
            except ErrorCaptura as exc:
                print(f"  nivel {nivel} {c['nombre']}({c['pid']}) {modo.value}: no se pudo abrir: {exc}")
                continue
            reg = Registro(banco.SR_CAPTURA, f"{c['nombre']}({c['pid']})")
            cap.iniciar(reg)
            caps[(nivel, modo.value, f"{c['nombre']}({c['pid']})")] = (cap, reg)
    ctrl = CapturaProcesoCtypes(pid=0, modo=ModoCaptura.ENDPOINT, sample_rate=banco.SR_CAPTURA)
    reg_ctrl = Registro(banco.SR_CAPTURA, "endpoint")
    ctrl.iniciar(reg_ctrl)
    b0 = banco.ahora_ns()
    time.sleep(1.5)
    b1 = banco.ahora_ns()
    f = 1234.0
    rep = ReproductorTonos(48000, 2, 20, 3)
    rep.abrir()
    t0 = banco.ahora_ns()
    rep.tono_y_esperar(f, TONO_S, AMPLITUD_POR_DEFECTO, cola_s=0.3)
    t1 = banco.ahora_ns() + int(0.8e9)
    rep.cerrar()
    time.sleep(0.5)
    filas = []
    print(f"  {'nivel':5} {'proceso objetivo':28} {'modo':8} {'oye mi tono?':>16}")
    det_ctrl = detectar(reg_ctrl, t0 - int(0.15e9), t1, (b0, b1), f)
    print(f"  {'-':5} {'ENDPOINT (control)':28} {'endpoint':8} {'SI' if det_ctrl['detectado'] else 'no':>6} {det_ctrl['ratio_db']:7.1f} dB")
    for (nivel, modo, nombre), (cap, reg) in caps.items():
        d = detectar(reg, t0 - int(0.15e9), t1, (b0, b1), f)
        print(f"  {nivel:5} {nombre:28} {modo:8} {'SI' if d['detectado'] else 'no':>6} {d['ratio_db']:7.1f} dB")
        filas.append({"nivel": nivel, "objetivo": nombre, "modo": modo, **d})
    for cap, _ in caps.values():
        cap.cerrar()
    ctrl.cerrar()
    resultados["parte_a"] = {"cadena": cadena_texto(cadena), "control_endpoint": det_ctrl, "filas": filas}


def parte_b(resultados: dict) -> None:
    print("\n== Parte B: hijos y nietos de este proceso, con y sin redirector del venv ==")
    yo = os.getpid()
    tmp = banco.directorio_temporal("s4_t1b_")
    log = os.path.join(tmp, "w.jsonl")
    # Hijos creados ANTES de activar la captura.
    previos = {
        "directo_previo": banco.Hijo("directo_previo", log, directo=True),
        "lanzador_previo": banco.Hijo("lanzador_previo", log, directo=False),
    }
    for h in previos.values():
        h.orden("abrir")
    cap_ex = CapturaProcesoCtypes(pid=yo, modo=ModoCaptura.EXCLUDE, sample_rate=banco.SR_CAPTURA)
    cap_in = CapturaProcesoCtypes(pid=yo, modo=ModoCaptura.INCLUDE, sample_rate=banco.SR_CAPTURA)
    cap_ep = CapturaProcesoCtypes(pid=0, modo=ModoCaptura.ENDPOINT, sample_rate=banco.SR_CAPTURA)
    regs = {n: Registro(banco.SR_CAPTURA, n) for n in ("exclude", "include", "endpoint")}
    cap_ex.iniciar(regs["exclude"])
    cap_in.iniciar(regs["include"])
    cap_ep.iniciar(regs["endpoint"])
    # Hijos creados DESPUES.
    posteriores = {
        "directo_posterior": banco.Hijo("directo_posterior", log, directo=True),
        "lanzador_posterior": banco.Hijo("lanzador_posterior", log, directo=False),
    }
    directo_nieto_padre = banco.Hijo("directo_padre_de_nieto", log, directo=True)
    # Captura extra: EXCLUDE/INCLUDE con el PID del redirector de un hijo con redirector.
    lanz = posteriores["lanzador_posterior"]
    cap_l_in = CapturaProcesoCtypes(pid=lanz.launcher_pid, modo=ModoCaptura.INCLUDE, sample_rate=banco.SR_CAPTURA)
    cap_l_ex = CapturaProcesoCtypes(pid=lanz.launcher_pid, modo=ModoCaptura.EXCLUDE, sample_rate=banco.SR_CAPTURA)
    regs["incl_lanzador"] = Registro(banco.SR_CAPTURA, "include_redirector")
    regs["excl_lanzador"] = Registro(banco.SR_CAPTURA, "exclude_redirector")
    cap_l_in.iniciar(regs["incl_lanzador"])
    cap_l_ex.iniciar(regs["excl_lanzador"])
    b0 = banco.ahora_ns()
    time.sleep(2.0)
    b1 = banco.ahora_ns()

    escenarios = [
        ("directo_previo", 777.0, previos["directo_previo"], None),
        ("lanzador_previo", 888.0, previos["lanzador_previo"], None),
        ("directo_posterior", 1111.0, posteriores["directo_posterior"], None),
        ("lanzador_posterior", 1222.0, posteriores["lanzador_posterior"], None),
        ("directo_nieto", 1357.0, directo_nieto_padre, "nieto"),
    ]
    filas = []
    for nombre, f, hijo, extra in escenarios:
        print(f"-- {nombre} ({f:.0f} Hz) ...", flush=True)
        if extra == "nieto":
            r = hijo.orden("nieto")
            info_nieto = json.loads(r["listo"])
            pid_emisor = info_nieto["pid"]
            t0 = banco.ahora_ns()
            hijo.orden(f"nieto_tono {f} {TONO_S} {AMPLITUD_POR_DEFECTO} {nombre}")
        else:
            pid_emisor = hijo.pid_real
            t0 = banco.ahora_ns()
            hijo.orden(f"tono {f} {TONO_S} {AMPLITUD_POR_DEFECTO} {nombre}")
        t1 = banco.ahora_ns() + int(0.8e9)
        cadena = cadena_padres(pid_emisor)
        fila = {
            "escenario": nombre,
            "pid_emisor": pid_emisor,
            "cadena": cadena_texto(cadena),
            "niveles_hasta_mi_pid": next((i for i, c in enumerate(cadena) if c["pid"] == yo and c["vivo"]), None),
            "cuelga_de_mi": alcanza(cadena, yo),
        }
        for clave, reg in regs.items():
            fila[clave] = detectar(reg, t0 - int(0.15e9), t1, (b0, b1), f)
        filas.append(fila)
        time.sleep(1.0)

    print(f"\n  {'escenario':20} {'niveles':>7} | {'EXCLUDE(yo)':>13} {'INCLUDE(yo)':>13} {'ENDPOINT':>13} | {'EXCL(redir)':>13} {'INCL(redir)':>13}")
    for fl in filas:
        def c(k):
            d = fl[k]
            return f"{'SI' if d['detectado'] else 'no':>3} {d['ratio_db']:6.1f}"
        print(f"  {fl['escenario']:20} {str(fl['niveles_hasta_mi_pid']):>7} | {c('exclude'):>13} {c('include'):>13} {c('endpoint'):>13} | {c('excl_lanzador'):>13} {c('incl_lanzador'):>13}")
    for fl in filas:
        print(f"    {fl['escenario']}: {fl['cadena']}")
    for cap in (cap_ex, cap_in, cap_ep, cap_l_in, cap_l_ex):
        cap.cerrar()
    for h in (*previos.values(), *posteriores.values(), directo_nieto_padre):
        h.cerrar()
    banco.borrar(tmp)
    resultados["parte_b"] = filas


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--solo-a", action="store_true")
    ap.add_argument("--solo-b", action="store_true")
    ap.add_argument("--nombre", default="t1b_arbol")
    args = ap.parse_args()
    resultados: dict = {"entorno": banco.info_entorno(), "base_python": getattr(sys, "_base_executable", "")}
    if not args.solo_b:
        parte_a(resultados)
    if not args.solo_a:
        parte_b(resultados)
    ruta = banco.guardar_json(f"{args.nombre}.json", resultados)
    print("\nResultados guardados en", ruta)
    return 0


if __name__ == "__main__":
    sys.exit(main())
