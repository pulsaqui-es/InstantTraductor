"""T1c - Que pasa con la captura cuando muere el proceso objetivo (spike S4, ADR-0005).

Un hijo directo A suena y se excluye con EXCLUDE(pid A) (y se incluye con INCLUDE(pid A)). Luego se
mata A: se observa si la captura sigue entregando paquetes o falla. Despues se lanza un hijo nuevo B
(otro PID) y se comprueba si su audio ya NO queda excluido por la captura antigua: si la app reinicia el
proceso que suena, hay que reactivar la captura con el PID nuevo (el ADR lo da por hecho).

Uso:  uv run python t1c_pid_objetivo_muere.py
"""

from __future__ import annotations

import os
import sys
import time

import audio_spike  # noqa: F401  (COM en MTA antes de comtypes)
from audio_spike import banco
from audio_spike.analisis import maximo_tono
from audio_spike.loopback_ctypes import CapturaProcesoCtypes
from audio_spike.modos import ModoCaptura
from audio_spike.registro import Registro

SR = banco.SR_CAPTURA
TONO_S = 0.5
AMP = 0.15


def detecta(reg, t0: int, t1: int, f: float) -> dict:
    x, _ = reg.ventana(t0, t1)
    m = maximo_tono(x, SR, f)
    return {"detectado": bool(m["ratio_db"] >= 15.0), "ratio_db": round(m["ratio_db"], 1)}


def estado(cap: CapturaProcesoCtypes, reg: Registro, ventana_s: float = 1.0) -> dict:
    ahora = banco.ahora_ns()
    recientes = [p for p in list(reg.paquetes) if ahora - p.t_ns <= ventana_s * 1e9]
    return {"paquetes_ultimo_s": len(recientes), "error": cap.error}


def main() -> int:
    tmp = banco.directorio_temporal("s4_t1c_")
    log = os.path.join(tmp, "w.jsonl")
    resultados: dict = {}
    hijo_a = banco.Hijo("objetivo_A", log, directo=True)
    pid_a = hijo_a.pid_real
    print("== T1c: el proceso objetivo muere ==")
    print("hijo A (directo) pid", pid_a)
    caps = {m: CapturaProcesoCtypes(pid=pid_a, modo=m, sample_rate=SR)
            for m in (ModoCaptura.EXCLUDE, ModoCaptura.INCLUDE)}
    regs = {m: Registro(SR, m.value) for m in caps}
    for m, c in caps.items():
        c.iniciar(regs[m])
    time.sleep(1.0)
    hijo_b = None
    try:
        # 1) A suena: excluido por EXCLUDE(A), visto por INCLUDE(A)
        t0 = banco.ahora_ns()
        hijo_a.orden(f"tono 1111 {TONO_S} {AMP} A")
        t1 = banco.ahora_ns() + int(0.8e9)
        r1 = {m.value: detecta(regs[m], t0, t1, 1111.0) for m in caps}
        print("1) A suena (1111 Hz):", r1)
        resultados["1_A_suena"] = r1
        # 2) se mata A
        banco.ahora_ns()
        pid_real = hijo_a.pid_real
        import psutil

        for p in (psutil.Process(pid_real), psutil.Process(hijo_a.launcher_pid)) if hijo_a.launcher_pid != pid_real else (psutil.Process(pid_real),):
            try:
                p.kill()
            except psutil.NoSuchProcess:
                pass
        time.sleep(0.3)
        print("2) A muerto. Estado de las capturas en los 3 s siguientes:")
        estados = []
        for _ in range(3):
            time.sleep(1.0)
            e = {m.value: estado(caps[m], regs[m]) for m in caps}
            estados.append(e)
            print("   ", e)
        resultados["2_estado_tras_morir_A"] = estados
        # 3) B (PID nuevo) suena: EXCLUDE(A muerto) ya no lo excluye
        hijo_b = banco.Hijo("objetivo_B", log, directo=True)
        print("3) hijo B (directo) pid", hijo_b.pid_real, "suena a 1222 Hz")
        t0 = banco.ahora_ns()
        hijo_b.orden(f"tono 1222 {TONO_S} {AMP} B")
        t1 = banco.ahora_ns() + int(0.8e9)
        r3 = {m.value: detecta(regs[m], t0, t1, 1222.0) for m in caps}
        print("   B suena:", r3, "(si EXCLUDE(A) lo oye -> la captura antigua ya no excluye nada)")
        resultados["3_B_suena"] = r3
        resultados["conclusion"] = {
            "captura_sigue_viva_tras_morir_el_objetivo": all(
                e[m.value]["paquetes_ultimo_s"] > 50 and not e[m.value]["error"] for e in estados[-1:] for m in caps),
            "exclude_del_pid_muerto_excluye_al_pid_nuevo": not r3["exclude"]["detectado"],
        }
        print("Conclusion:", resultados["conclusion"])
    finally:
        for c in caps.values():
            c.cerrar()
        if hijo_b is not None:
            hijo_b.cerrar()
        hijo_a.cerrar()
    ruta = banco.guardar_json("t1c_pid_objetivo_muere.json", resultados)
    print("Resultados guardados en", ruta)
    banco.borrar(tmp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
