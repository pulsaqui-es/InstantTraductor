"""S6 · M2: ¿hasta qué profundidad cubre INCLUDE? Cadena de procesos con el emisor en la hoja.

Lanza una cadena L1 -> L2 -> L3 -> L4 con el intérprete BASE (sin el lanzador del venv) y un emisor de 777 Hz a
-30 dBFS en la hoja (L4). Abre una captura INCLUDE sobre cada eslabón y sobre el proceso que lanza la cadena, y
mide el RMS (nada se guarda). Reproduce y amplía el escenario de S4 (nieto no incluido).

Uso:
    uv run python spikes/captura_app/profundidad.py [--niveles 4] [--duracion 4]
    (con --sin-sesion-cmd se repite lanzando cada eslabón a través de `cmd /c`)
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import sysconfig
import time
from pathlib import Path

import capturar_app as ca
import common as c
import numpy as np
import psutil
from instanttraductor.audio.wasapi_capture import ProcessLoopbackSource

HERE = Path(__file__).resolve().parent
CREATE_NO_WINDOW = 0x08000000
BASE_PY = getattr(sys, "_base_executable", sys.executable)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--niveles", type=int, default=4)
    ap.add_argument("--duracion", type=float, default=4.0)
    ap.add_argument("--via-cmd", action="store_true")
    ap.add_argument(
        "--lanzador-venv",
        action="store_true",
        help="el primer eslabón es el lanzador del venv (el caso real de `uv run`)",
    )
    ap.add_argument(
        "--consola-heredada", action="store_true", help="sin CREATE_NO_WINDOW: la cadena comparte la consola"
    )
    args = ap.parse_args()

    # El intérprete base no ve el venv: se le pasa su site-packages por PYTHONPATH (solo numpy y miniaudio).
    env = {**os.environ, "PYTHONPATH": sysconfig.get_paths()["purelib"]}
    first = [
        sys.executable if args.lanzador_venv else BASE_PY,
        str(HERE / "emisor.py"),
        "--cadena",
        str(args.niveles),
        "--freq",
        "777",
        "--max-s",
        "60",
    ]
    first += ["--via-cmd"] if args.via_cmd else []
    root = subprocess.Popen(
        first,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
        creationflags=0 if args.consola_heredada else CREATE_NO_WINDOW,
    )
    time.sleep(3.0)
    try:
        tree = psutil.Process(root.pid).children(recursive=True)
        chain: list[psutil.Process] = [psutil.Process(root.pid)]
        # ordena por profundidad siguiendo los padres
        by_parent = {p.ppid(): p for p in tree}
        while chain[-1].pid in by_parent:
            chain.append(by_parent[chain[-1].pid])
        me = os.getpid()
        clock = ca.PerfClock()
        ancestors = psutil.Process(me).parents()
        targets = [(f"antepasado {d} de nosotros ({a.name()})", a.pid) for d, a in enumerate(ancestors[:4], 1)]
        targets += [("lanzador (nosotros)", me)] + [
            (f"eslabón {i} (profundidad {i}) {p.name()}", p.pid) for i, p in enumerate(chain, 1)
        ]
        srcs = {pid: ProcessLoopbackSource(clock, include=True, target_pid=pid) for _, pid in targets}
        for s in srcs.values():
            s.start()
        acc = {pid: [0.0, 0] for pid in srcs}
        end = time.perf_counter() + args.duracion
        while time.perf_counter() < end:
            for pid, s in srcs.items():
                chunk = s.read(0.01)
                while chunk is not None:
                    x = chunk.samples.astype(np.float64)
                    acc[pid][0] += float(np.sum(x * x))
                    acc[pid][1] += len(x)
                    chunk = s.read(0.0)
        for s in srcs.values():
            s.stop()
        leaf = chain[-1].pid
        print(f"cadena: {' -> '.join(f'{p.name()}({p.pid})' for p in chain)}  (la hoja {leaf} es el emisor)")
        for label, pid in targets:
            rms = (acc[pid][0] / max(acc[pid][1], 1)) ** 0.5
            print(f"  INCLUDE({pid:>7d}) {label:<44s} rms {c.db(rms):7.1f} dBFS  {'OYE' if rms > 1e-4 else 'silencio'}")
    finally:
        subprocess.run(["taskkill", "/PID", str(root.pid), "/T", "/F"], capture_output=True)


if __name__ == "__main__":
    main()
