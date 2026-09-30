"""T1 - Autoexclusion del process loopback EXCLUDE (spike S4, ADR-0005).

Comprueba que, con una captura EXCLUDE sobre el PID de este proceso, NO aparece el audio de este
proceso ni el de sus descendientes (lo que asume el ADR), y SI aparece el de un proceso externo.

Cada tono (frecuencia poco comun, 0,6 s, amplitud 0,15) se mide en tres capturas a la vez:
- EXCLUDE(pid): lo que usara la app.
- INCLUDE(pid): control positivo (debe oir lo que EXCLUDE no oye, y al reves).
- ENDPOINT: loopback clasico del dispositivo por defecto; debe oirlo todo. Sin este control, un
  "no aparece" no probaria nada (el sonido podria no haber salido).
La deteccion es por pico espectral relativo (audio_spike/analisis.py), robusta a que el humano
este oyendo otras cosas.

"Hijo directo" = proceso cuyo PPID es este proceso. Con un venv de uv, `sys.executable` es un
redirector que crea el interprete real como hijo: el que suena queda a dos niveles ("redirector").

Uso:  uv run python t1_autoexclusion.py [--rondas 1] [--sin-wmi] [--solo ID ...]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Optional

import audio_spike  # noqa: F401  (COM en MTA antes de comtypes)
from audio_spike import banco
from audio_spike.analisis import maximo_tono, rms_dbfs
from audio_spike.procesos import alcanza, cadena_padres, cadena_texto
from audio_spike.tonos import AMPLITUD_POR_DEFECTO, ReproductorTonos

TONO_S = 0.6
UMBRAL_RATIO_DB = 15.0  # relacion tono/fondo minima para dar el tono por presente
UMBRAL_SOBRE_BASE_DB = 10.0  # y debe superar en tanto a la misma medida sin tono


@dataclass
class Escenario:
    id: str
    descripcion: str
    frecuencia: float
    adr_excluido: bool  # lo que asumen la investigacion y el ADR: True = debe quedar excluido
    profundidad: Optional[int]  # niveles por debajo de este proceso (0 = el propio); None = externo
    solo_con: str = ""


ESCENARIOS = [
    Escenario("propio_nuevo", "este proceso; PlaybackDevice creado tras iniciar la captura", 1234.0, True, 0),
    Escenario("propio_previo", "este proceso; PlaybackDevice abierto (con ceros) antes de la captura", 1321.0, True, 0),
    Escenario("hijo_directo_previo", "hijo directo creado y con el dispositivo abierto ANTES de la captura", 777.0, True, 1),
    Escenario("hijo_directo_posterior", "hijo directo creado DESPUES de iniciar la captura", 1111.0, True, 1),
    Escenario("hijo_redirector", "hijo lanzado con sys.executable (redirector del venv): suena a 2 niveles", 1222.0, True, 2),
    Escenario("nieto_directo", "nieto (hijo directo del hijo directo), sin redirectores", 1357.0, True, 2),
    Escenario("nieto_redirector", "nieto lanzado con sys.executable desde un hijo con redirector", 1471.0, True, 4),
    Escenario("ffplay_hijo_directo", "ffplay lanzado con Popen directo (hijo directo, sin python)", 1579.0, True, 1),
    Escenario("ffplay_via_cmd", "ffplay lanzado con `cmd /c ffplay` (cmd.exe vivo de intermedio)", 1888.0, True, 2),
    Escenario("externo_ffplay_cmd", "ffplay lanzado con `cmd /c start` (su cmd.exe muere)", 1999.0, False, None),
    Escenario("externo_python_cmd", "trabajador Python lanzado con `cmd /c start` (pythonw)", 1663.0, False, None),
    Escenario("externo_ffplay_wmi", "ffplay lanzado con Win32_Process.Create (padre WmiPrvSE)", 1777.0, False, None, "wmi"),
]


class Contexto:
    def __init__(self, tmp: str) -> None:
        self.tmp = tmp
        self.log = os.path.join(tmp, "trabajadores.jsonl")
        self.capturas: Optional[banco.Capturas] = None
        self.propio_persistente: Optional[ReproductorTonos] = None
        self.hijos: dict[str, banco.Hijo] = {}
        self.pid_nietos: dict[str, int] = {}
        self.pid = os.getpid()


def anotar_emisor(datos: dict, pid: int, yo: int) -> None:
    cadena = cadena_padres(pid)
    datos["emisores"].append({
        "pid": pid,
        "cadena": cadena_texto(cadena),
        "cuelga_de_este_proceso": alcanza(cadena, yo),
        "nivel": next((i for i, c in enumerate(cadena) if c["pid"] == yo and c["vivo"]), None),
    })


def tono_en_hijo(ctx: Contexto, datos: dict, nombre_hijo: str, esc: Escenario, nieto: bool = False) -> None:
    f = esc.frecuencia
    hijo = ctx.hijos[nombre_hijo]
    if nieto:
        r = hijo.orden("nieto")
        if r.get("listo"):  # primera vez: el nieto acaba de crearse (queda vivo para las rondas siguientes)
            ctx.pid_nietos[nombre_hijo] = json.loads(r["listo"])["pid"]
        pid_nieto = ctx.pid_nietos[nombre_hijo]
        datos["t_ini_ns"] = banco.ahora_ns()
        datos["respuesta"] = hijo.orden(f"nieto_tono {f} {TONO_S} {AMPLITUD_POR_DEFECTO} {esc.id}")
        anotar_emisor(datos, pid_nieto, ctx.pid)
    else:
        datos["t_ini_ns"] = banco.ahora_ns()
        datos["respuesta"] = hijo.orden(f"tono {f} {TONO_S} {AMPLITUD_POR_DEFECTO} {esc.id}")
        anotar_emisor(datos, hijo.pid_real, ctx.pid)


def tono_ffplay(ctx: Contexto, datos: dict, esc: Escenario, metodo: str) -> None:
    wav = banco.wav_tono(ctx.tmp, f"s4_{esc.id}_{int(esc.frecuencia)}.wav", esc.frecuencia, TONO_S, AMPLITUD_POR_DEFECTO)
    ej = banco.lanzar_ffplay(wav, metodo)
    datos["t_ini_ns"] = ej.t_lanzamiento_ns
    if ej.pid:
        datos["emisores"].append({
            "pid": ej.pid,
            "cadena": cadena_texto(ej.cadena),
            "cuelga_de_este_proceso": alcanza(ej.cadena, ctx.pid),
            "nivel": next((i for i, c in enumerate(ej.cadena) if c["pid"] == ctx.pid and c["vivo"]), None),
        })
    else:
        datos["emisores"].append({"pid": 0, "cadena": "(no se encontro el proceso ffplay)",
                                  "cuelga_de_este_proceso": None, "nivel": None})
    banco.esperar_ffplay(ej, 12.0)


def ejecutar(ctx: Contexto, esc: Escenario) -> dict:
    """Emite el tono del escenario. Devuelve la ventana temporal y los datos de procesos."""
    f = esc.frecuencia
    datos: dict = {"emisores": []}
    datos["t_ini_ns"] = banco.ahora_ns()
    if esc.id == "propio_nuevo":
        rep = ReproductorTonos(48000, 2, 20, 3)
        rep.abrir()
        rep.tono_y_esperar(f, TONO_S, AMPLITUD_POR_DEFECTO, cola_s=0.3)
        rep.cerrar()
        anotar_emisor(datos, ctx.pid, ctx.pid)
    elif esc.id == "propio_previo":
        ctx.propio_persistente.tono_y_esperar(f, TONO_S, AMPLITUD_POR_DEFECTO, cola_s=0.3)
        anotar_emisor(datos, ctx.pid, ctx.pid)
    elif esc.id == "hijo_directo_previo":
        tono_en_hijo(ctx, datos, "directo_previo", esc)
    elif esc.id == "hijo_directo_posterior":
        tono_en_hijo(ctx, datos, "directo_posterior", esc)
    elif esc.id == "hijo_redirector":
        tono_en_hijo(ctx, datos, "redirector", esc)
    elif esc.id == "nieto_directo":
        tono_en_hijo(ctx, datos, "padre_nieto_directo", esc, nieto=True)
    elif esc.id == "nieto_redirector":
        tono_en_hijo(ctx, datos, "padre_nieto_redirector", esc, nieto=True)
    elif esc.id == "ffplay_hijo_directo":
        tono_ffplay(ctx, datos, esc, "popen")
    elif esc.id == "ffplay_via_cmd":
        tono_ffplay(ctx, datos, esc, "cmd_hijo")
    elif esc.id == "externo_ffplay_cmd":
        tono_ffplay(ctx, datos, esc, "cmd")
    elif esc.id == "externo_ffplay_wmi":
        tono_ffplay(ctx, datos, esc, "wmi")
    elif esc.id == "externo_python_cmd":
        ext = banco.ExternoUDP(ctx.log, metodo="cmd")
        try:
            datos["t_ini_ns"] = banco.ahora_ns()
            datos["respuesta"] = ext.orden(f"tono {f} {TONO_S} {AMPLITUD_POR_DEFECTO} {esc.id}")
            anotar_emisor(datos, ext.pid_real, ctx.pid)
        finally:
            ext.cerrar()
    else:
        raise ValueError(esc.id)
    time.sleep(0.4)
    return {"t_ini_ns": datos["t_ini_ns"], "t_fin_ns": banco.ahora_ns(), "datos": datos}


def medir(ctx: Contexto, esc: Escenario, ventana: dict, base: tuple[int, int]) -> dict:
    """Mide el tono en cada captura, frente a la misma medida en el tramo base (sin tonos)."""
    resultado = {}
    for modo, reg in ctx.capturas.registros.items():
        x, ps = reg.ventana(ventana["t_ini_ns"] - int(0.15e9), ventana["t_fin_ns"] + int(0.8e9))
        xb, _ = reg.ventana(*base)
        m = maximo_tono(x, banco.SR_CAPTURA, esc.frecuencia)
        mb = maximo_tono(xb, banco.SR_CAPTURA, esc.frecuencia)
        detectado = m["ratio_db"] >= UMBRAL_RATIO_DB and (m["ratio_db"] - mb["ratio_db"]) >= UMBRAL_SOBRE_BASE_DB
        resultado[modo.value] = {
            "ratio_db": round(m["ratio_db"], 1),
            "amp_dbfs": round(m["amp_dbfs"], 1),
            "ratio_base_db": round(mb["ratio_db"], 1),
            "detectado": bool(detectado),
            "paquetes": len(ps),
            "rms_dbfs": round(rms_dbfs(x), 1),
        }
    return resultado


def esperado(esc: Escenario) -> dict:
    """Lo que asumen la investigacion y el ADR: excluido = no sale en EXCLUDE y si en INCLUDE."""
    if esc.adr_excluido:
        return {"exclude": False, "include": True, "endpoint": True}
    return {"exclude": True, "include": False, "endpoint": True}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rondas", type=int, default=1)
    ap.add_argument("--sin-wmi", action="store_true", help="omite el escenario lanzado por WMI")
    ap.add_argument("--solo", nargs="*", default=None, help="ids de escenario a ejecutar")
    ap.add_argument("--nombre", default="t1_autoexclusion", help="nombre del JSON de resultados")
    args = ap.parse_args()

    tmp = banco.directorio_temporal("s4_t1_")
    ctx = Contexto(tmp)
    entorno = banco.info_entorno()
    print("== T1 autoexclusion ==")
    print("Windows:", entorno["windows"])
    print("Dispositivo por defecto:", entorno["dispositivo_por_defecto"]["nombre"])
    print("PID de este proceso:", ctx.pid, "| cadena:", entorno["cadena_propia"])

    escenarios = [e for e in ESCENARIOS if not (e.solo_con == "wmi" and args.sin_wmi)]
    if args.solo:
        escenarios = [e for e in escenarios if e.id in args.solo]
    ids = {e.id for e in escenarios}

    filas: list[dict] = []
    rms_base: dict = {}
    try:
        # 1) Antes de activar la captura: hijo directo y dispositivo propio ya abiertos.
        if "hijo_directo_previo" in ids:
            ctx.hijos["directo_previo"] = banco.Hijo("directo_previo", ctx.log, directo=True)
            ctx.hijos["directo_previo"].orden("abrir")
        if "propio_previo" in ids:
            ctx.propio_persistente = ReproductorTonos(48000, 2, 20, 3)
            ctx.propio_persistente.abrir()
        # 2) Capturas.
        ctx.capturas = banco.Capturas(ctx.pid)
        ctx.capturas.iniciar()
        t_base0 = banco.ahora_ns()
        time.sleep(2.0)
        t_base1 = banco.ahora_ns()
        rms_base = {m.value: round(float(rms_dbfs(r.ventana(t_base0, t_base1)[0])), 1)
                    for m, r in ctx.capturas.registros.items()}
        print("Nivel de fondo durante la base (dBFS RMS):", rms_base,
              "(-180 = silencio digital; valores mayores = el sistema tenia audio)")
        # 3) Hijos creados con la captura ya activa.
        if "hijo_directo_posterior" in ids:
            ctx.hijos["directo_posterior"] = banco.Hijo("directo_posterior", ctx.log, directo=True)
        if "hijo_redirector" in ids:
            ctx.hijos["redirector"] = banco.Hijo("redirector", ctx.log, directo=False)
        if "nieto_directo" in ids:
            ctx.hijos["padre_nieto_directo"] = banco.Hijo("padre_nieto_directo", ctx.log, directo=True)
        if "nieto_redirector" in ids:
            ctx.hijos["padre_nieto_redirector"] = banco.Hijo("padre_nieto_redirector", ctx.log, directo=False)
        # 4) Escenarios.
        for ronda in range(1, args.rondas + 1):
            for esc in escenarios:
                print(f"-- ronda {ronda}: {esc.id} ({esc.frecuencia:.0f} Hz) ...", flush=True)
                ventana = ejecutar(ctx, esc)
                mediciones = medir(ctx, esc, ventana, (t_base0, t_base1))
                filas.append({
                    "ronda": ronda, "escenario": esc.id, "descripcion": esc.descripcion,
                    "frecuencia": esc.frecuencia, "profundidad_esperada": esc.profundidad,
                    "esperado_segun_adr": esperado(esc), "mediciones": mediciones, **ventana["datos"],
                })
                time.sleep(1.0)
    finally:
        if ctx.capturas:
            ctx.capturas.cerrar()
        for h in ctx.hijos.values():
            h.cerrar()
        if ctx.propio_persistente:
            ctx.propio_persistente.cerrar()

    # 5) Informe.
    print()
    print(f"{'escenario':24} {'nivel':>5} | {'EXCLUDE':>20} | {'INCLUDE':>20} | {'ENDPOINT':>20} | segun ADR")
    fallos = 0
    for fila in filas:
        celdas, ok_fila = [], True
        esp = fila["esperado_segun_adr"]
        for modo in ("exclude", "include", "endpoint"):
            m = fila["mediciones"][modo]
            txt = f"{'SI' if m['detectado'] else 'no'} {m['ratio_db']:6.1f} dB"
            if esp[modo] == m["detectado"]:
                txt += " ok"
            else:
                txt += " MAL"
                ok_fila = False
            celdas.append(f"{txt:>20}")
        nivel = "-"
        if fila["emisores"]:
            n = fila["emisores"][-1].get("nivel")
            nivel = "ext" if n is None else str(n)
        if not ok_fila:
            fallos += 1
        print(f"{fila['escenario']:24} {nivel:>5} | " + " | ".join(celdas) + f" | {'cumple' if ok_fila else 'NO CUMPLE'}")
    print()
    for fila in filas:
        for e in fila["emisores"]:
            print(f"  {fila['escenario']}: pid {e['pid']} cadena: {e['cadena']}")
    print(f"\nEscenarios que no cumplen lo que asume el ADR: {fallos} de {len(filas)}")

    log_txt = open(ctx.log, encoding="utf-8").read() if os.path.exists(ctx.log) else ""
    ruta = banco.guardar_json(f"{args.nombre}.json", {
        "entorno": entorno, "nivel_fondo_dbfs": rms_base, "filas": filas,
        "umbral_ratio_db": UMBRAL_RATIO_DB, "umbral_sobre_base_db": UMBRAL_SOBRE_BASE_DB,
        "log_trabajadores": log_txt.splitlines()[-60:],
    })
    print("Resultados guardados en", ruta)
    banco.borrar(tmp)
    return 0 if fallos == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
