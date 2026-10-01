"""Lecturas de GPU (``nvidia-smi``) y de memoria del proceso en Windows.

Todas estas funciones solo LEEN el estado de la GPU; aun así, quien las llama debe
estar dentro del candado de GPU cuando el objetivo sea medir.

En Windows (modo WDDM) ``nvidia-smi --query-compute-apps`` devuelve ``[N/A]`` como
memoria por proceso. Por eso se mide la VRAM de dos formas:

1. Diferencia de ``memory.used`` global antes y después de cargar el modelo.
2. Contador de rendimiento de Windows ``\\GPU Process Memory(pid_N*)\\Dedicated Usage``,
   que sí da la memoria dedicada de un proceso concreto.
"""

from __future__ import annotations

import contextlib
import json
import re
import subprocess
import threading
import time

_SMI_FIELDS = (
    "name,driver_version,pstate,clocks.sm,clocks.max.sm,clocks.mem,power.draw,"
    "temperature.gpu,utilization.gpu,memory.used,memory.total"
)


def _run(cmd: list[str], timeout: float = 30.0) -> str:
    r = subprocess.run(  # noqa: S603 - comandos fijos
        cmd, capture_output=True, timeout=timeout, check=False
    )
    return r.stdout.decode("utf-8", errors="replace").strip()


def gpu_snapshot() -> dict:
    """Estado de la GPU en este instante (nombre, reloj, potencia, VRAM...)."""
    out = _run(["nvidia-smi", f"--query-gpu={_SMI_FIELDS}", "--format=csv,noheader,nounits"])
    values = [v.strip() for v in out.splitlines()[0].split(",")]
    keys = _SMI_FIELDS.split(",")
    snap: dict = dict(zip(keys, values, strict=False))
    for key in ("memory.used", "memory.total"):
        snap[key] = int(float(snap[key]))
    return snap


def vram_used_mib() -> int:
    """Memoria de vídeo usada en total por todos los procesos (MiB)."""
    out = _run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"])
    return int(float(out.splitlines()[0].strip()))


def process_vram_mib(pid: int) -> float | None:
    """VRAM dedicada de un proceso (MiB), con el contador de Windows; ``None`` si falla."""
    cmd = (
        f"$s=(Get-Counter '\\GPU Process Memory(pid_{pid}*)\\Dedicated Usage' "
        "-ErrorAction SilentlyContinue).CounterSamples; "
        "if($s){($s | Measure-Object -Property CookedValue -Sum).Sum}"
    )
    out = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd])
    try:
        return float(out.replace(",", ".")) / (1024 * 1024)
    except ValueError:
        return None


def process_working_set_mib(pid: int) -> float | None:
    """Memoria RAM del proceso (conjunto de trabajo, MiB) según ``tasklist``."""
    out = _run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"])
    fields = re.findall(r'"([^"]*)"', out)
    if len(fields) >= 5:
        digits = re.sub(r"\D", "", fields[4])
        if digits:
            return int(digits) / 1024  # tasklist informa en KB
    return None


def process_exists(pid: int) -> bool:
    """¿Sigue existiendo un proceso con ese PID?"""
    out = _run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"])
    return bool(re.search(rf'"{pid}"', out))


class VramSampler(threading.Thread):
    """Hilo que muestrea ``memory.used`` cada ``interval`` s y guarda el máximo."""

    def __init__(self, interval: float = 0.25) -> None:
        super().__init__(daemon=True)
        self.interval = interval
        self.samples: list[int] = []
        self._stop_event = threading.Event()

    def run(self) -> None:
        while not self._stop_event.is_set():
            # Un muestreo fallido no debe abortar la medición.
            with contextlib.suppress(Exception):
                self.samples.append(vram_used_mib())
            self._stop_event.wait(self.interval)

    def stop(self) -> dict:
        self._stop_event.set()
        self.join(timeout=5)
        return {
            "n_samples": len(self.samples),
            "max_mib": max(self.samples) if self.samples else None,
            "min_mib": min(self.samples) if self.samples else None,
        }


def to_json(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)


def settle(seconds: float = 0.5) -> None:
    """Pausa breve para que la VRAM se estabilice tras abrir o cerrar un proceso."""
    time.sleep(seconds)
