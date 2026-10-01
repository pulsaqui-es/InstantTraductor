"""Información del sistema y carga de fondo durante una medición.

Como varios obreros miden a la vez, cada ejecución registra qué más estaba consumiendo CPU
(tiempo de CPU por proceso durante la ejecución) y la carga global de CPU y GPU.
"""

from __future__ import annotations

import importlib.metadata as md
import os
import platform
import subprocess
import sys
import threading
import time

import psutil

PACKAGES = (
    "sherpa-onnx",
    "sherpa-onnx-core",
    "onnxruntime",
    "faster-whisper",
    "ctranslate2",
    "nvidia-cublas-cu12",
    "numpy",
    "jiwer",
    "whisper-normalizer",
    "huggingface-hub",
)


def _run(cmd: list[str], timeout: float = 20.0) -> str:
    """Ejecuta un comando y devuelve su salida (vacía si falla). Decodifica UTF-8 o, si no, OEM."""
    try:
        raw = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False).stdout or b""
    except (OSError, subprocess.SubprocessError):
        return ""
    try:
        return raw.decode("utf-8").strip()
    except UnicodeDecodeError:
        return raw.decode("cp850", errors="replace").strip()


def gpu_query() -> dict:
    """Estado de la GPU con nvidia-smi (vacío si no hay)."""
    out = _run(
        [
            "nvidia-smi",
            "--query-gpu=name,driver_version,memory.total,memory.used,utilization.gpu,temperature.gpu",
            "--format=csv,noheader,nounits",
        ]
    )
    if not out:
        return {}
    name, driver, total, used, util, temp = [s.strip() for s in out.splitlines()[0].split(",")]
    return {
        "name": name,
        "driver": driver,
        "memory_total_mb": int(total),
        "memory_used_mb": int(used),
        "utilization_pct": int(util),
        "temperature_c": int(temp),
    }


def cpu_model() -> str:
    out = _run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Processor).Name"])
    return out or platform.processor()


def power_plan() -> str:
    out = _run(["powercfg", "/getactivescheme"])
    return out.split("(")[-1].rstrip(")") if "(" in out else out


def package_versions() -> dict[str, str]:
    versions = {}
    for name in PACKAGES:
        try:
            versions[name] = md.version(name)
        except md.PackageNotFoundError:
            versions[name] = "no instalado"
    return versions


def system_snapshot() -> dict:
    vm = psutil.virtual_memory()
    return {
        "os": f"{platform.system()} {platform.release()} ({platform.version()})",
        "python": sys.version.split()[0],
        "cpu": cpu_model(),
        "cores_physical": psutil.cpu_count(logical=False),
        "cores_logical": psutil.cpu_count(logical=True),
        "ram_total_gb": round(vm.total / 2**30, 1),
        "ram_available_gb": round(vm.available / 2**30, 1),
        "power_plan": power_plan(),
        "gpu": gpu_query(),
        "packages": package_versions(),
    }


class LoadTracker:
    """Mide la carga del equipo durante una ejecución.

    - Muestrea la CPU global cada segundo (mide también la propia).
    - Al empezar y al terminar toma el tiempo de CPU de todos los procesos y devuelve los que más
      han consumido, excluido este proceso.
    """

    def __init__(self, interval_s: float = 1.0) -> None:
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._samples: list[float] = []
        self._start_times: dict[int, tuple[str, float]] = {}
        self._t0 = 0.0
        self._cpu0 = 0.0
        self._self = psutil.Process()
        self.gpu_samples: list[tuple[int, int]] = []  # (utilización %, memoria MB)
        self.sample_gpu = False

    @staticmethod
    def _snapshot() -> dict[int, tuple[str, float]]:
        snap = {}
        for p in psutil.process_iter(["pid", "name", "cpu_times"]):
            try:
                ct = p.info["cpu_times"]
                if ct is not None:
                    snap[p.info["pid"]] = (p.info["name"] or "?", ct.user + ct.system)
            except (psutil.Error, OSError):
                continue
        return snap

    def start(self, sample_gpu: bool = False) -> None:
        self.sample_gpu = sample_gpu
        self._samples.clear()
        self.gpu_samples.clear()
        self._stop.clear()
        self._start_times = self._snapshot()
        self._t0 = time.perf_counter()
        ct = self._self.cpu_times()
        self._cpu0 = ct.user + ct.system
        psutil.cpu_percent(interval=None)
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_s):
            self._samples.append(psutil.cpu_percent(interval=None))
            if self.sample_gpu:
                g = gpu_query()
                if g:
                    self.gpu_samples.append((g["utilization_pct"], g["memory_used_mb"]))

    def stop(self, top: int = 10) -> dict:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        wall = time.perf_counter() - self._t0
        ct = self._self.cpu_times()
        own_cpu = ct.user + ct.system - self._cpu0
        end = self._snapshot()
        me = os.getpid()
        deltas = []
        for pid, (name, cpu_end) in end.items():
            if pid in (0, me) or name == "System Idle Process":
                continue
            cpu_start = self._start_times.get(pid, (name, 0.0))[1] if pid in self._start_times else 0.0
            d = cpu_end - cpu_start
            if d > 0.05:
                deltas.append((d, name, pid))
        deltas.sort(reverse=True)
        n_logical = psutil.cpu_count(logical=True) or 1
        agg: dict[str, float] = {}
        for d, name, _ in deltas:
            agg[name] = agg.get(name, 0.0) + d
        top_procs = sorted(agg.items(), key=lambda kv: kv[1], reverse=True)[:top]
        result = {
            "wall_s": round(wall, 2),
            "own_cpu_s": round(own_cpu, 2),
            "own_cores_avg": round(own_cpu / wall, 3) if wall else None,
            "own_cpu_pct_of_machine": round(100 * own_cpu / wall / n_logical, 2) if wall else None,
            "system_cpu_pct_mean": round(sum(self._samples) / len(self._samples), 1) if self._samples else None,
            "system_cpu_pct_max": round(max(self._samples), 1) if self._samples else None,
            "others_total_cores_avg": round(sum(d for d, _, _ in deltas) / wall, 2) if wall else None,
            "others_top": [{"name": n, "cores_avg": round(c / wall, 2)} for n, c in top_procs],
        }
        if self.gpu_samples:
            util = [u for u, _ in self.gpu_samples]
            mem = [m for _, m in self.gpu_samples]
            result["gpu_util_pct_mean"] = round(sum(util) / len(util), 1)
            result["gpu_util_pct_max"] = max(util)
            result["gpu_mem_used_mb_max"] = max(mem)
        return result
