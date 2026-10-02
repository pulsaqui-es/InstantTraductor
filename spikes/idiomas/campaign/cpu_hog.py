"""Carga de CPU sintética (como un juego que usa varios núcleos): N procesos ocupados durante ``seconds`` s.

Uso: ``uv run python campaign/cpu_hog.py 12 1500``
"""

from __future__ import annotations

import multiprocessing as mp
import sys
import time


def burn(deadline: float) -> None:
    x = 0.0
    while time.time() < deadline:
        for i in range(200_000):
            x += (i * 1.0001) % 7.0


def main() -> None:
    n = int(sys.argv[1])
    seconds = float(sys.argv[2])
    deadline = time.time() + seconds
    procs = [mp.Process(target=burn, args=(deadline,)) for _ in range(n)]
    for p in procs:
        p.start()
    for p in procs:
        p.join()


if __name__ == "__main__":
    main()
