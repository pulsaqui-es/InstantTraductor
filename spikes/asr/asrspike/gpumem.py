"""VRAM de este proceso en Windows (WDDM), con el contador «GPU Process Memory».

``nvidia-smi`` no da la memoria por proceso con WDDM (devuelve N/A), pero el contador de
rendimiento ``\\GPU Process Memory(pid_<pid>_*)\\Dedicated Usage`` sí. Se lee con un PowerShell
persistente que imprime un valor (MB) cada ~0,25 s.
"""

from __future__ import annotations

import os
import subprocess
import threading
import time

_SCRIPT = r"""
$id = {pid}
while ($true) {{
  $s = (Get-Counter "\GPU Process Memory(pid_${{id}}_*)\Dedicated Usage" -ErrorAction SilentlyContinue).CounterSamples
  if ($s) {{ $v = ($s | Measure-Object CookedValue -Sum).Sum; [Console]::Out.WriteLine([int64]($v / 1MB)) }}
  else {{ [Console]::Out.WriteLine(0) }}
  [Console]::Out.Flush()
  Start-Sleep -Milliseconds 150
}}
"""


class GpuProcMemSampler:
    """Muestrea la memoria dedicada de GPU del proceso (MB) en un hilo."""

    def __init__(self, pid: int | None = None) -> None:
        self.pid = pid or os.getpid()
        self.samples: list[tuple[float, int]] = []
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", _SCRIPT.format(pid=self.pid)],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()

    def _read(self) -> None:
        assert self._proc and self._proc.stdout
        for line in self._proc.stdout:
            line = line.strip()
            if line.isdigit():
                self.samples.append((time.perf_counter(), int(line)))

    def current_mb(self) -> int:
        return self.samples[-1][1] if self.samples else 0

    def stop(self) -> dict:
        if self._proc:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        if self._thread:
            self._thread.join(timeout=5)
        vals = [v for _, v in self.samples]
        return {
            "peak_mb": max(vals) if vals else None,
            "last_mb": vals[-1] if vals else None,
            "samples": len(vals),
        }
