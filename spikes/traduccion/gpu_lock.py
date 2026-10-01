"""Candado de GPU compartido entre los obreros que miden a la vez.

Toda medición que use la GPU (arrancar llama-server, lanzar peticiones, leer
la VRAM) debe ir dentro de ``gpu_lock()``. El candado es un fichero
(``%LOCALAPPDATA%\\InstantTraductor\\gpu.lock``) gestionado con el paquete
``filelock``; se espera hasta 30 minutos.

Uso como biblioteca::

    from gpu_lock import gpu_lock
    with gpu_lock():
        ...  # medir en GPU

Uso como envoltorio de línea de comandos (para pruebas sueltas en GPU)::

    uv run python gpu_lock.py -- <comando> [argumentos...]
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from filelock import FileLock, Timeout

#: Carpeta de datos de la aplicación (fuera del repositorio).
APP_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "InstantTraductor"
LOCK_PATH = APP_DIR / "gpu.lock"
#: Espera máxima para conseguir el candado: 30 minutos.
LOCK_TIMEOUT_S = 30 * 60


@contextmanager
def gpu_lock(timeout: float = LOCK_TIMEOUT_S, quiet: bool = False) -> Iterator[float]:
    """Toma el candado de GPU y lo suelta al salir.

    Devuelve (con ``as``) los segundos que se estuvo esperando el candado.
    """
    APP_DIR.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(LOCK_PATH), timeout=timeout)
    t0 = time.monotonic()
    if not quiet:
        print(f"[gpu_lock] esperando el candado {LOCK_PATH} ...", flush=True)
    try:
        lock.acquire()
    except Timeout:
        raise TimeoutError(
            f"No se consiguió el candado de GPU en {timeout:.0f} s: {LOCK_PATH}"
        ) from None
    waited = time.monotonic() - t0
    if not quiet:
        print(f"[gpu_lock] candado conseguido (espera: {waited:.1f} s)", flush=True)
    try:
        yield waited
    finally:
        lock.release()
        if not quiet:
            print("[gpu_lock] candado liberado", flush=True)


def main(argv: list[str]) -> int:
    """Ejecuta un comando dentro del candado y devuelve su código de salida."""
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    if not argv:
        print(__doc__)
        return 2
    with gpu_lock():
        return subprocess.call(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
