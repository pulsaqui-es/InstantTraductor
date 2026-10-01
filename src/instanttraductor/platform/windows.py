"""Capa de plataforma de Windows.

Es el único sitio del núcleo con ctypes de ``kernel32`` y con ``msvcrt`` (Principio VII: lo
específico de Windows queda aislado en la capa de audio y plataforma).

Contiene:

- Un *Job Object* con ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`` (research R10): si el núcleo muere de
  golpe, Windows cierra el job y mata a todos los procesos hijos (y a sus descendientes), de modo
  que no queda ningún proceso huérfano (FR-015 y FR-018).
- ``launch_child``: lanza un proceso hijo sin ventana, con las salidas en tuberías y dentro del job.
- ``windows_build``: número de compilación de Windows (requisito de ``preparar``).
- ``read_key_nonblocking``: lectura de teclas sin bloquear (``msvcrt``).
"""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
import threading
from collections.abc import Mapping, Sequence
from ctypes import wintypes

try:
    import msvcrt
except ImportError:  # pragma: no cover - solo fuera de Windows
    msvcrt = None  # type: ignore[assignment]

__all__ = [
    "JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE",
    "KillOnCloseJob",
    "close_job",
    "create_kill_on_close_job",
    "launch_child",
    "read_key_nonblocking",
    "windows_build",
]

logger = logging.getLogger(__name__)

# Constantes de la API de Windows.
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9  # JobObjectExtendedLimitInformation
_CREATE_NEW_PROCESS_GROUP = 0x00000200
_CREATE_NO_WINDOW = 0x08000000

# Prefijos que el teclado de consola envía antes del código de una tecla especial (flechas, F1...).
_SPECIAL_KEY_PREFIXES = ("\x00", "\xe0")


# ---------------------------------------------------------------------------
# Estructuras de ctypes (JOBOBJECT_EXTENDED_LIMIT_INFORMATION)
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


_kernel32: ctypes.WinDLL | None = None
_kernel32_lock = threading.Lock()


def _k32() -> ctypes.WinDLL:
    """``kernel32`` con los prototipos declarados (instancia propia: no toca ``ctypes.windll``)."""
    global _kernel32
    with _kernel32_lock:
        if _kernel32 is None:
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
            k32.CloseHandle.restype = wintypes.BOOL
            k32.CloseHandle.argtypes = [wintypes.HANDLE]
            _kernel32 = k32
        return _kernel32


# ---------------------------------------------------------------------------
# Job Object
# ---------------------------------------------------------------------------
class KillOnCloseJob:
    """Job Object cuyo cierre mata a todos sus procesos (``KILL_ON_JOB_CLOSE``).

    El *handle* no es heredable. Mientras el núcleo viva lo mantiene abierto; si muere (incluso
    con ``TerminateProcess``), el sistema lo cierra y mata a los procesos del job y a sus
    descendientes. ``assign`` y ``close`` se excluyen entre sí para no usar un *handle* ya cerrado.
    """

    def __init__(self, handle: int) -> None:
        self._handle: int | None = handle
        self._lock = threading.Lock()

    @property
    def closed(self) -> bool:
        return self._handle is None

    def assign(self, process: subprocess.Popen) -> None:
        """Mete el proceso (y sus futuros descendientes) en el job. Lanza ``OSError`` si no puede."""
        with self._lock:
            if self._handle is None:
                raise OSError("El Job Object ya está cerrado")
            # Popen._handle es el HANDLE del proceso (privado, pero estable en Windows).
            if not _k32().AssignProcessToJobObject(self._handle, int(process._handle)):  # type: ignore[attr-defined]
                raise ctypes.WinError(ctypes.get_last_error())

    def close(self) -> None:
        """Cierra el job (idempotente): Windows mata de inmediato a lo que siga dentro."""
        with self._lock:
            handle, self._handle = self._handle, None
            if handle is not None:
                _k32().CloseHandle(handle)


def create_kill_on_close_job() -> KillOnCloseJob:
    """Crea un Job Object con ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE``. Lanza ``OSError`` si falla."""
    k32 = _k32()
    handle = k32.CreateJobObjectW(None, None)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    info = _ExtendedLimitInfo()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    ok = k32.SetInformationJobObject(
        handle, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(info), ctypes.sizeof(info)
    )
    if not ok:
        error = ctypes.get_last_error()
        k32.CloseHandle(handle)
        raise ctypes.WinError(error)
    return KillOnCloseJob(handle)


# Job único del proceso: todos los hijos que lanza ``launch_child`` van a él.
_job: KillOnCloseJob | None = None
_job_lock = threading.Lock()


def _shared_job() -> KillOnCloseJob:
    """Devuelve el job único del proceso, creándolo la primera vez (o tras ``close_job``)."""
    global _job
    with _job_lock:
        if _job is None or _job.closed:
            _job = create_kill_on_close_job()
        return _job


def close_job() -> None:
    """Cierra el job único: Windows mata de inmediato a todos los hijos que sigan dentro.

    Es idempotente. Un ``launch_child`` posterior crea un job nuevo.
    """
    global _job
    with _job_lock:
        job, _job = _job, None
    if job is not None:
        job.close()


# ---------------------------------------------------------------------------
# Procesos hijos
# ---------------------------------------------------------------------------
def launch_child(
    args: Sequence[str | os.PathLike[str]],
    *,
    env: Mapping[str, str] | None = None,
    cwd: str | os.PathLike[str] | None = None,
) -> subprocess.Popen[str]:
    """Lanza un proceso hijo sin ventana y lo asigna al job único (``KILL_ON_JOB_CLOSE``).

    - Va con ``CREATE_NO_WINDOW`` y en su propio grupo de procesos: un Ctrl+C en la terminal del
      núcleo no le llega; lo para el núcleo (``stop_all``) o, si este muere, el job.
    - ``env``: variables que se **añaden o sustituyen** a las del proceso actual (no lo reemplazan).
    - ``cwd``: directorio de trabajo del hijo.
    - ``stdin`` va a ``DEVNULL``; ``stdout`` y ``stderr`` son tuberías de texto (UTF-8, los bytes
      no válidos se sustituyen). **Quien lanza debe leerlas** (``ManagedChild`` lo hace): si nadie
      las vacía, el hijo se bloquea al llenarse la tubería.
    - Si no se puede asignar al job, el hijo se mata y se lanza ``OSError``: sin job no hay garantía
      de ausencia de procesos huérfanos.
    """
    job = _shared_job()
    child_env = dict(os.environ)
    # os.environ guarda los nombres en mayúsculas en Windows; se hace igual para no duplicar claves.
    child_env.update({str(key).upper(): str(value) for key, value in (env or {}).items()})
    proc = subprocess.Popen(  # noqa: S603 - línea de comandos propia
        [os.fspath(arg) for arg in args],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        env=child_env,
        creationflags=_CREATE_NO_WINDOW | _CREATE_NEW_PROCESS_GROUP,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        job.assign(proc)
    except OSError:
        logger.error("No se pudo asignar el proceso %s al Job Object; se mata", proc.pid)
        proc.kill()
        proc.wait()
        raise
    return proc


# ---------------------------------------------------------------------------
# Versión de Windows y teclado
# ---------------------------------------------------------------------------
def windows_build() -> int:
    """Número de compilación de Windows (p. ej. 26200). Devuelve 0 si no se ejecuta en Windows."""
    getter = getattr(sys, "getwindowsversion", None)
    return int(getter().build) if getter is not None else 0


def read_key_nonblocking() -> str | None:
    """Lee una tecla de la consola sin bloquear. ``None`` si no hay ninguna pendiente.

    Es el único sitio del núcleo que lee teclas: la interfaz recibe esta función inyectada. Las
    teclas especiales (flechas, F1...) se consumen y se ignoran (``None``).
    """
    if msvcrt is None or not msvcrt.kbhit():
        return None
    char = msvcrt.getwch()
    if char in _SPECIAL_KEY_PREFIXES:
        msvcrt.getwch()  # segundo código de la tecla especial
        return None
    return char
