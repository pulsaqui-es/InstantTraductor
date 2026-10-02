"""Prueba de parada (SC-006, quickstart §5.6): arranca `directo` N veces y lo detiene con Ctrl+Break.

Por cada vuelta: lanza `python -m instanttraductor directo` en su propio grupo de procesos, espera a que
escuche, anota sus procesos hijos, envía Ctrl+Break y mide el tiempo hasta que sale. Después comprueba que
no queda vivo ninguno de sus hijos. Solo Windows. Suena el tono del autotest en cada arranque.

    uv run python scripts/stop_test.py --veces 20
"""

from __future__ import annotations

import argparse
import os
import signal
import statistics
import subprocess
import sys
import threading
import time

import psutil

READY_TEXT = "Escuchando."
START_TIMEOUT_S = 120.0
STOP_LIMIT_S = 2.0
SETTLE_S = 5.0  # escuchando un poco antes de parar


def one_run(index: int) -> tuple[float, list[str], int]:
    """Devuelve (segundos hasta salir, hijos que siguen vivos, código de salida)."""
    process = subprocess.Popen(
        [sys.executable, "-m", "instanttraductor", "directo"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONUNBUFFERED": "1"},  # sin búfer: «Escuchando.» llega al momento
    )
    ready = threading.Event()
    lines: list[str] = []

    def pump() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            lines.append(line.rstrip())
            if READY_TEXT in line:
                ready.set()

    threading.Thread(target=pump, daemon=True).start()
    if not ready.wait(START_TIMEOUT_S):
        process.kill()
        raise RuntimeError(f"Vuelta {index}: no llegó a escuchar. Salida:\n" + "\n".join(lines[-20:]))
    time.sleep(SETTLE_S)
    children = psutil.Process(process.pid).children(recursive=True)
    t0 = time.perf_counter()
    os.kill(process.pid, signal.CTRL_BREAK_EVENT)
    code = process.wait(30)
    elapsed = time.perf_counter() - t0
    time.sleep(0.5)
    alive = [f"{c.pid} {c.name()}" for c in children if c.is_running() and c.status() != psutil.STATUS_ZOMBIE]
    return elapsed, alive, code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--veces", type=int, default=20)
    args = parser.parse_args()
    times: list[float] = []
    failures = 0
    for index in range(1, args.veces + 1):
        elapsed, alive, code = one_run(index)
        times.append(elapsed)
        ok = elapsed <= STOP_LIMIT_S and not alive and code == 0
        failures += not ok
        print(
            f"{index:2d}: parada en {elapsed:.2f} s · código {code} · hijos vivos: {alive or 'ninguno'}"
            + ("" if ok else "  ← FALLA"),
            flush=True,
        )
    print(
        f"\n{args.veces - failures}/{args.veces} correctas · mediana {statistics.median(times):.2f} s, "
        f"máxima {max(times):.2f} s"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
