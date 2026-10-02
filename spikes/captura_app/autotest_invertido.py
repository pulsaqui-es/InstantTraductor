"""S6 · 3. Autotest invertido: con INCLUDE de OTRA app, la propia voz NO debe aparecer.

Reutiliza `run_echo_selftest(sink, make_source)` de producción sin tocarlo. `make_source(include)` se interpreta
al revés que en 0.1:
  - `make_source(False)` -> la captura de la app: INCLUDE(T), donde T es la app elegida (en 0.1 era EXCLUDE(propio));
  - `make_source(True)`  -> el control positivo: INCLUDE(PID propio) (en 0.1 era el mismo INCLUDE(propio)).
El tono propio (1234 Hz, -30 dBFS, 0,3 s) sale por el `DeviceSink` real y no debe verse en la primera captura y
sí en la segunda. Los escenarios comprueban los casos de la investigación §3.6:

  app_suena     T = un emisor ajeno que suena (777 Hz): debe dar OK.
  app_muda      T = un proceso ajeno sin audio: debe dar OK.
  propio        T = nuestro PID: debe FALLAR (la voz propia entra).
  padre         T = el padre directo (lanzador/venv): debe FALLAR (hijo directo de T).
  abuelo        T = el abuelo: debe dar OK (INCLUDE no cubre nietos).
  inexistente   T = PID que no existe: da OK aunque no capture nada (fallo silencioso: hay que validar el PID).

Uso:
    uv run python spikes/captura_app/autotest_invertido.py [--escenarios app_suena,propio,...] [--repeticiones 1]
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import capturar_app as ca
import common as c
import psutil
from instanttraductor.audio.selftest import run_echo_selftest
from instanttraductor.audio.wasapi_capture import ProcessLoopbackSource
from instanttraductor.audio.wasapi_playback import DeviceSink

HERE = Path(__file__).resolve().parent
CREATE_NO_WINDOW = 0x08000000
EXPECTED = {
    "app_suena": True,
    "app_muda": True,
    "propio": False,
    "padre": False,
    "inexistente": True,
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--escenarios", default=",".join(EXPECTED) + ",ancestros")
    ap.add_argument("--repeticiones", type=int, default=1)
    args = ap.parse_args()

    me = os.getpid()
    parent = psutil.Process(me).ppid()
    clock = ca.PerfClock()
    sink = DeviceSink(clock)
    sink.start(lambda event: None)
    helpers: list[subprocess.Popen] = []
    try:
        emitter = subprocess.Popen(
            [sys.executable, str(HERE / "emisor.py"), "--freq", "777", "--max-s", "300"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
        )
        idle = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(300)"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
        )
        helpers += [emitter, idle]
        time.sleep(2.0)
        targets = {
            "app_suena": emitter.pid,
            "app_muda": idle.pid,
            "propio": me,
            "padre": parent,
            "inexistente": 999999,
        }
        # Antepasados propios por profundidad (1 = padre): cuánto sube la cobertura de INCLUDE desde el emisor.
        ancestors = psutil.Process(me).parents()
        for depth, anc in enumerate(ancestors[:6], 1):
            targets[f"ancestro{depth}"] = anc.pid
            EXPECTED[f"ancestro{depth}"] = None
        print("Antepasados propios:", [(d, a.pid, a.name()) for d, a in enumerate(ancestors[:6], 1)])
        print(f"PID propio {me}, padre {parent} ({c.proc_info(parent).name}); emisor {emitter.pid}")
        print(
            f"{'escenario':<12s} {'T':>7s}  {'esperado':<9s} {'resultado':<9s} {'tono en INCLUDE(T)':>19s} {'tono en control':>16s}  umbral  s"
        )
        all_ok = True
        names = [n for n in args.escenarios.split(",") if n != "ancestros"]
        if "ancestros" in args.escenarios.split(","):
            names += [n for n in targets if n.startswith("ancestro")]
        for name in names:
            pid = targets[name]
            for _ in range(args.repeticiones):
                t0 = time.perf_counter()
                result = run_echo_selftest(
                    sink,
                    lambda control, pid=pid: ProcessLoopbackSource(
                        clock, include=True, target_pid=(me if control else pid)
                    ),
                )
                dt = time.perf_counter() - t0
                expected = EXPECTED[name]
                match = expected is None or result.ok == expected
                all_ok &= match
                tone_t = f"{result.exclude_ratio_db:.1f} dB" if result.exclude_ratio_db is not None else "-"
                tone_c = f"{result.include_ratio_db:.1f} dB" if result.include_ratio_db is not None else "-"
                print(
                    f"{name:<12s} {pid:>7d}  {'(medida)' if expected is None else 'OK' if expected else 'FALLA':<9s} {'OK' if result.ok else 'FALLA':<9s} "
                    f"{tone_t:>19s} {tone_c:>16s}  {result.correlation_threshold:.2f}   {dt:.1f}  "
                    f"{'' if match else '<-- NO COINCIDE'}"
                )
                if not result.ok:
                    print(f"             motivo: {result.reason[:150]}")
        print("\nTodos los escenarios coinciden con lo esperado." if all_ok else "\nHAY ESCENARIOS QUE NO COINCIDEN.")
    finally:
        sink.stop()
        for p in helpers:
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)


if __name__ == "__main__":
    main()
