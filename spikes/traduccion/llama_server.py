"""Gestor de ``llama-server`` como proceso HIJO (Windows).

- Escucha solo en 127.0.0.1, en un puerto libre, con todas las capas en GPU.
- Espera a que ``/health`` devuelva 200 y mide el tiempo de arranque.
- Lo cierra al terminar. Para no dejar procesos huérfanos se combinan tres
  mecanismos: ``try/finally`` en quien lo usa, ``atexit`` y un *Job Object* de
  Windows con ``KILL_ON_JOB_CLOSE`` (si el script muere de golpe, el sistema
  operativo mata también al servidor).

Este módulo NO toma el candado de GPU: lo hace quien lo llama (``gpu_lock``).
"""

from __future__ import annotations

import atexit
import ctypes
import os
import socket
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

import httpx

APP_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "InstantTraductor"
#: Versión de llama.cpp fijada en este spike (release v0.5.0 = build b11146).
LLAMA_BUILD = "b11146"
DEFAULT_SERVER_DIR = APP_DIR / "bin" / "llama.cpp" / LLAMA_BUILD / "cuda-13.4-x64"
DEFAULT_MODEL = APP_DIR / "models" / "Hy-MT2-1.8B-Q8_0.gguf"


# ---------------------------------------------------------------------------
# Job Object de Windows: el hijo muere si muere el padre
# ---------------------------------------------------------------------------
class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _BasicLimitInfo(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _ExtendedLimitInfo(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimitInfo),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9


class KillOnCloseJob:
    """Job Object cuyo cierre (al morir el proceso padre) mata a sus procesos."""

    def __init__(self) -> None:
        self.handle = None
        self._k32 = None
        if sys.platform != "win32":
            return
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        k32.SetInformationJobObject.restype = wintypes.BOOL
        k32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        ]
        k32.AssignProcessToJobObject.restype = wintypes.BOOL
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        handle = k32.CreateJobObjectW(None, None)
        if not handle:
            return
        info = _ExtendedLimitInfo()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = k32.SetInformationJobObject(
            handle,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            return
        self.handle = handle
        self._k32 = k32

    def assign(self, proc: subprocess.Popen) -> bool:
        """Mete el proceso en el Job Object. Devuelve False si no se pudo."""
        if self.handle is None or self._k32 is None:
            return False
        return bool(self._k32.AssignProcessToJobObject(self.handle, int(proc._handle)))  # type: ignore[attr-defined]


def free_port() -> int:
    """Devuelve un puerto TCP libre en 127.0.0.1."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


# ---------------------------------------------------------------------------
# Servidor
# ---------------------------------------------------------------------------
class LlamaServer:
    """``llama-server`` como proceso hijo: ``start()`` espera a ``/health``."""

    def __init__(
        self,
        *,
        server_dir: Path = DEFAULT_SERVER_DIR,
        model: Path = DEFAULT_MODEL,
        n_ctx: int = 4096,
        n_gpu_layers: int = 99,
        parallel: int = 1,
        extra_args: tuple[str, ...] = (),
        log_path: Path | None = None,
    ) -> None:
        self.server_dir = Path(server_dir)
        self.exe = self.server_dir / "llama-server.exe"
        self.model = Path(model)
        self.n_ctx = n_ctx
        self.n_gpu_layers = n_gpu_layers
        self.parallel = parallel
        self.extra_args = tuple(extra_args)
        self.log_path = Path(log_path) if log_path else None
        self.port: int | None = None
        self.proc: subprocess.Popen | None = None
        self.startup_s: float | None = None
        self.job_assigned = False
        self._log_fh = None
        self._job = KillOnCloseJob()
        atexit.register(self.stop)

    # -- propiedades -------------------------------------------------------
    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def pid(self) -> int | None:
        return self.proc.pid if self.proc else None

    def command(self) -> list[str]:
        """Línea de comandos con la que se lanza el servidor."""
        assert self.port is not None
        return [
            str(self.exe),
            "-m",
            str(self.model),
            "--host",
            "127.0.0.1",
            "--port",
            str(self.port),
            "-ngl",
            str(self.n_gpu_layers),  # todas las capas en GPU
            "-c",
            str(self.n_ctx),
            "-np",
            str(self.parallel),  # un solo hueco: es el uso real (una petición cada vez)
            "-fit",
            "off",  # sin autoajuste: lo que se pide es lo que se carga
            "--no-webui",
            *self.extra_args,
        ]

    # -- ciclo de vida -----------------------------------------------------
    def start(self, ready_timeout: float = 180.0) -> float:
        """Lanza el servidor y espera a ``/health`` = 200. Devuelve los segundos de arranque."""
        if self.proc is not None:
            raise RuntimeError("El servidor ya está en marcha")
        for path in (self.exe, self.model):
            if not path.exists():
                raise FileNotFoundError(
                    f"Falta {path}. Ejecuta antes: uv run python descargar.py"
                )
        self.port = free_port()
        stdout = subprocess.DEVNULL
        if self.log_path is not None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log_fh = open(self.log_path, "wb")  # noqa: SIM115 - se cierra en stop()
            stdout = self._log_fh
        flags = 0
        if sys.platform == "win32":
            flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        t0 = time.perf_counter()
        self.proc = subprocess.Popen(  # noqa: S603 - línea de comandos propia
            self.command(),
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=subprocess.STDOUT,
            cwd=str(self.server_dir),
            creationflags=flags,
        )
        self.job_assigned = self._job.assign(self.proc)
        try:
            self._wait_ready(t0, ready_timeout)
        except BaseException:
            self.stop()
            raise
        self.startup_s = time.perf_counter() - t0
        return self.startup_s

    def _wait_ready(self, t0: float, ready_timeout: float) -> None:
        assert self.proc is not None
        url = f"{self.base_url}/health"
        while True:
            code = self.proc.poll()
            if code is not None:
                raise RuntimeError(
                    f"llama-server terminó durante el arranque (código {code}).\n"
                    + self.log_tail()
                )
            try:
                if httpx.get(url, timeout=1.0).status_code == 200:
                    return
            except httpx.HTTPError:
                pass  # aún no escucha o está cargando (503)
            if time.perf_counter() - t0 > ready_timeout:
                raise TimeoutError(
                    f"llama-server no quedó listo en {ready_timeout:.0f} s.\n" + self.log_tail()
                )
            time.sleep(0.02)

    def stop(self, grace: float = 10.0) -> None:
        """Cierra el servidor (idempotente) y confirma que el proceso ya no existe."""
        proc, self.proc = self.proc, None
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=grace)
        if self._log_fh is not None:
            try:
                self._log_fh.close()
            finally:
                self._log_fh = None

    def __enter__(self) -> LlamaServer:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()

    # -- utilidades --------------------------------------------------------
    def log_text(self) -> str:
        if self.log_path is None or not self.log_path.exists():
            return ""
        return self.log_path.read_text(encoding="utf-8", errors="replace")

    def log_tail(self, n: int = 40) -> str:
        lines = self.log_text().splitlines()
        return "\n".join(lines[-n:])

    def props(self) -> dict:
        """``GET /props``: plantilla de chat, ajustes por defecto, nº de huecos, etc."""
        r = httpx.get(f"{self.base_url}/props", timeout=10.0)
        r.raise_for_status()
        return r.json()

    def apply_template(self, messages: list[dict]) -> str:
        """``POST /apply-template``: el texto exacto que recibe el modelo."""
        r = httpx.post(f"{self.base_url}/apply-template", json={"messages": messages}, timeout=10.0)
        r.raise_for_status()
        return r.json()["prompt"]
