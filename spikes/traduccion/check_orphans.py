"""Comprueba que llama-server NO queda huérfano si el proceso que lo lanzó muere de golpe.

Un proceso hijo lanza llama-server (con el *Job Object* de ``llama_server.py``) y el
script lo MATA a la fuerza (``TerminateProcess``: no se ejecutan ni ``finally`` ni
``atexit``). Si el mecanismo funciona, Windows cierra el Job Object y mata también a
llama-server. Usa la GPU unos segundos, así que va dentro del candado.

Uso::

    uv run python check_orphans.py
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import gpu_info
from gpu_lock import gpu_lock

HERE = Path(__file__).resolve().parent

CHILD = """
import time
from llama_server import LlamaServer

srv = LlamaServer()
srv.start()
print(srv.pid, flush=True)
time.sleep(600)
"""


def main() -> int:
    with gpu_lock():
        child = subprocess.Popen(  # noqa: S603
            [sys.executable, "-c", CHILD], cwd=str(HERE), stdout=subprocess.PIPE, text=True
        )
        try:
            assert child.stdout is not None
            line = child.stdout.readline().strip()
            server_pid = int(line)
            print(f"[orphans] proceso hijo {child.pid} lanzó llama-server (pid {server_pid})")
            print(f"[orphans] llama-server vivo antes de matar al padre: {gpu_info.process_exists(server_pid)}")
            child.kill()  # muerte abrupta: no corre ningún finally ni atexit
            child.wait(timeout=10)
            t0 = time.perf_counter()
            while gpu_info.process_exists(server_pid) and time.perf_counter() - t0 < 15:
                time.sleep(0.1)
            gone = not gpu_info.process_exists(server_pid)
            print(f"[orphans] llama-server desaparecido tras matar al padre: {gone} "
                  f"({time.perf_counter() - t0:.1f} s)")
        finally:
            if child.poll() is None:
                child.kill()
        gpu_info.settle(1.0)
        print(f"[orphans] VRAM usada tras la prueba: {gpu_info.vram_used_mib()} MiB")
    return 0 if gone else 1


if __name__ == "__main__":
    sys.exit(main())
