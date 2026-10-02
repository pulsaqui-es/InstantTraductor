"""Utilidades compartidas del spike S6 (captura por aplicación). No es código de producto.

- Enumeración de sesiones de audio de TODOS los endpoints de render activos (`enumerate_sessions`).
- Resolución del PID objetivo de INCLUDE: la sesión o su padre directo (`resolve_target`).
- Agrupación por aplicación con las exclusiones propias (`build_apps`).
- Nombre visible (descripción del ejecutable), AUMID de paquetes y utilidades de reloj.

Se ejecuta con el entorno raíz: `uv run python spikes/captura_app/<script>.py`.
"""

from __future__ import annotations

# COM en MTA, ANTES de que nadie importe comtypes/pycaw (igual que el código de producto).
import sys

sys.coinit_flags = 0

import contextlib  # noqa: E402
import ctypes  # noqa: E402
import math  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402
from ctypes import wintypes  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from functools import cache  # noqa: E402

import comtypes  # noqa: E402
import psutil  # noqa: E402
from pycaw.pycaw import (  # noqa: E402
    AudioUtilities,
    IAudioMeterInformation,
    IAudioSessionControl2,
    IAudioSessionManager2,
)

E_RENDER = 0
DEVICE_STATE_ACTIVE = 1
CLSCTX_ALL = 23

STATE_NAMES = {0: "inactiva", 1: "activa", 2: "expirada"}
PEAK_SOUNDING = 0.0005  # pico a partir del cual la sesión «suena» (-66 dBFS)


def db(x: float) -> float:
    return 20 * math.log10(max(x, 1e-9))


# --------------------------------------------------------------------------------------------------
# Procesos
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProcKey:
    """Identidad de un proceso a lo largo del tiempo: el PID solo no basta (se reutiliza)."""

    pid: int
    created: float

    def alive(self) -> bool:
        try:
            return psutil.Process(self.pid).create_time() == self.created
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False

    def __str__(self) -> str:
        return f"{self.pid}@{self.created:.2f}"


@dataclass(slots=True)
class ProcInfo:
    pid: int
    created: float
    ppid: int
    exe: str  # ruta de la imagen ('' si no se pudo leer)
    name: str  # nombre del proceso (p. ej. chrome.exe)

    @property
    def key(self) -> ProcKey:
        return ProcKey(self.pid, self.created)


def proc_info(pid: int) -> ProcInfo | None:
    try:
        proc = psutil.Process(pid)
        with proc.oneshot():
            created = proc.create_time()
            ppid = proc.ppid()
            name = proc.name()
            try:
                exe = proc.exe()
            except (psutil.AccessDenied, psutil.ZombieProcess):
                exe = ""
        return ProcInfo(pid, created, ppid, exe, name)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def norm_path(path: str) -> str:
    return os.path.normcase(os.path.normpath(path)) if path else ""


def own_pids() -> tuple[int, int]:
    """PID propio y de su padre directo (INCLUDE sobre cualquiera de los dos captaría nuestra voz)."""
    me = os.getpid()
    return me, psutil.Process(me).ppid()


# --------------------------------------------------------------------------------------------------
# Nombre visible y AUMID
# --------------------------------------------------------------------------------------------------


@cache
def file_description(path: str) -> str:
    """`FileDescription` del recurso de versión del ejecutable (lo que enseña el Administrador de tareas)."""
    if not path:
        return ""
    try:
        version = ctypes.WinDLL("version.dll")
        size = version.GetFileVersionInfoSizeW(path, None)
        if not size:
            return ""
        buf = ctypes.create_string_buffer(size)
        if not version.GetFileVersionInfoW(path, 0, size, buf):
            return ""
        ptr = ctypes.c_void_p()
        length = wintypes.UINT()
        if not version.VerQueryValueW(buf, "\\VarFileInfo\\Translation", ctypes.byref(ptr), ctypes.byref(length)):
            return ""
        lang, codepage = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_ushort * 2)).contents
        for key in (f"{lang:04x}{codepage:04x}", "040904b0", "040904e4", "000004b0"):
            if version.VerQueryValueW(
                buf, f"\\StringFileInfo\\{key}\\FileDescription", ctypes.byref(ptr), ctypes.byref(length)
            ):
                text = ctypes.wstring_at(ptr.value, length.value).strip("\x00 ")
                if text:
                    return text
    except OSError:
        pass
    return ""


def aumid(pid: int) -> str:
    """AUMID de un proceso empaquetado (Store/UWP), o '' si no lo es (error 15703) o no se puede leer."""
    kernel32 = ctypes.WinDLL("kernel32.dll")
    kernel32.OpenProcess.restype = wintypes.HANDLE
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        length = wintypes.UINT(256)
        buf = ctypes.create_unicode_buffer(256)
        rc = kernel32.GetApplicationUserModelId(handle, ctypes.byref(length), buf)
        return buf.value if rc == 0 else ""
    except (OSError, AttributeError):
        return ""
    finally:
        kernel32.CloseHandle(handle)


def display_name(info: ProcInfo) -> str:
    return file_description(info.exe) or os.path.splitext(info.name)[0] or f"PID {info.pid}"


# --------------------------------------------------------------------------------------------------
# Sesiones de audio
# --------------------------------------------------------------------------------------------------


@dataclass(slots=True)
class SessionInfo:
    endpoint: str
    pid: int
    state: int
    peak: float
    system: bool
    identifier: str
    proc: ProcInfo | None
    ctl: object = field(default=None, repr=False)  # IAudioSessionControl2 vivo, para volver a leer el pico
    meter: object = field(default=None, repr=False)

    def refresh_peak(self) -> float:
        with contextlib.suppress(comtypes.COMError):
            self.peak = max(self.peak, float(self.meter.GetPeakValue()))
        return self.peak


def _endpoint_name(device) -> str:
    try:
        return AudioUtilities.CreateDevice(device).FriendlyName or device.GetId()
    except Exception:
        return device.GetId()


def enumerate_sessions(
    peak_window_s: float = 0.0, poll_s: float = 0.05, *, with_names: bool = True
) -> list[SessionInfo]:
    """Sesiones de render de TODOS los endpoints activos, no solo el predeterminado.

    `peak_window_s`: tiempo durante el que se sondea el pico y se guarda el máximo (el medidor es
    instantáneo: una app que suena a ráfagas puede dar 0 en una sola lectura).
    `with_names=False` se ahorra leer el nombre amistoso de cada endpoint (el sondeo del vigilante).
    """
    enumerator = AudioUtilities.GetDeviceEnumerator()
    collection = enumerator.EnumAudioEndpoints(E_RENDER, DEVICE_STATE_ACTIVE)
    sessions: list[SessionInfo] = []
    for i in range(collection.GetCount()):
        device = collection.Item(i)
        name = _endpoint_name(device) if with_names else device.GetId()
        try:
            iface = device.Activate(IAudioSessionManager2._iid_, CLSCTX_ALL, None)
            manager = iface.QueryInterface(IAudioSessionManager2)
            enum = manager.GetSessionEnumerator()
        except comtypes.COMError:
            continue
        for j in range(enum.GetCount()):
            try:
                ctl = enum.GetSession(j).QueryInterface(IAudioSessionControl2)
                pid = ctl.GetProcessId()
                state = ctl.GetState()
                system = ctl.IsSystemSoundsSession() == 0  # S_OK = es la sesión de sonidos del sistema
                identifier = ctl.GetSessionIdentifier()
                meter = ctl.QueryInterface(IAudioMeterInformation)
                peak = float(meter.GetPeakValue())
            except comtypes.COMError:
                continue
            sessions.append(SessionInfo(name, pid, state, peak, system, identifier, proc_info(pid), ctl, meter))
    if peak_window_s > 0:
        end = time.perf_counter() + peak_window_s
        while time.perf_counter() < end:
            for s in sessions:
                s.refresh_peak()
            time.sleep(poll_s)
    return sessions


# --------------------------------------------------------------------------------------------------
# PID objetivo de INCLUDE
# --------------------------------------------------------------------------------------------------


def resolve_target(session: SessionInfo) -> ProcInfo | None:
    """Proceso raíz que hay que capturar: el padre directo si es de la misma imagen y anterior; si no, el PID.

    Regla medida (informe, §3.4): INCLUDE cubre el PID objetivo y sus hijos DIRECTOS, nunca nietos. El
    emisor es el PID de la sesión; su padre directo lo cubre si es la misma aplicación (Chrome: servicio de
    audio -> browser; Discord: renderer -> main; Steam: steamwebhelper -> steamwebhelper intermedio).
    """
    emitter = session.proc
    if emitter is None:
        return None
    parent = proc_info(emitter.ppid)
    if (
        parent is not None
        and parent.created <= emitter.created
        and parent.exe
        and norm_path(parent.exe) == norm_path(emitter.exe)
    ):
        return parent
    return emitter


@dataclass(slots=True)
class AppEntry:
    """Una aplicación de la lista: lo que verá la persona usuaria."""

    key: str  # clave estable para recordarla: ruta de la imagen normalizada (o AUMID)
    name: str
    exe: str
    aumid: str
    targets: list[ProcInfo] = field(default_factory=list)  # procesos raíz (uno por instancia)
    sessions: list[SessionInfo] = field(default_factory=list)
    uncovered: list[int] = field(default_factory=list)  # emisores que ningún objetivo cubre
    captured: float | None = None  # RMS de un sondeo corto INCLUDE (None si no se sondeó)

    @property
    def peak(self) -> float:
        return max((s.peak for s in self.sessions), default=0.0)

    @property
    def sounding(self) -> bool:
        return self.peak >= PEAK_SOUNDING

    @property
    def state(self) -> int:
        states = [s.state for s in self.sessions if s.state != 2]
        return min(2, max(states)) if states else 2

    @property
    def endpoints(self) -> list[str]:
        return sorted({s.endpoint for s in self.sessions})


def dedupe_targets(targets: list[ProcInfo]) -> list[ProcInfo]:
    """Quita los objetivos que son hijo directo de otro objetivo (doble recuento)."""
    pids = {t.pid for t in targets}
    return [t for t in targets if t.ppid not in pids]


def build_apps(sessions: list[SessionInfo], *, hide_own: bool = True) -> tuple[list[AppEntry], list[str]]:
    """Agrupa las sesiones por aplicación (imagen del objetivo) y filtra. Devuelve (apps, notas)."""
    me, my_parent = own_pids()
    notes: list[str] = []
    groups: dict[str, AppEntry] = {}
    for s in sessions:
        if s.system or s.pid == 0 or s.proc is None:
            continue
        target = resolve_target(s)
        if target is None:
            continue
        if hide_own and (s.pid in (me, my_parent) or target.pid in (me, my_parent) or s.proc.ppid == me):
            notes.append(f"oculta (propia o su padre): PID {s.pid} -> objetivo {target.pid} ({s.proc.name})")
            continue
        pkg = aumid(target.pid)
        key = pkg or norm_path(target.exe) or target.name.lower()
        entry = groups.get(key)
        if entry is None:
            entry = groups[key] = AppEntry(key, display_name(target), target.exe, pkg)
        entry.sessions.append(s)
        if all(t.pid != target.pid for t in entry.targets):
            entry.targets.append(target)
    for entry in groups.values():
        entry.targets = dedupe_targets(entry.targets)
        covered = {t.pid for t in entry.targets}
        entry.uncovered = [
            s.pid for s in entry.sessions if s.pid not in covered and (s.proc is None or s.proc.ppid not in covered)
        ]
    apps = sorted(groups.values(), key=lambda a: (not a.sounding, a.name.lower()))
    return apps, notes


def app_label(app: AppEntry) -> str:
    """Nombre para la lista; con varias instancias lleva sus PID."""
    if len(app.targets) > 1:
        return f"{app.name} (instancias: {', '.join(str(t.pid) for t in app.targets)})"
    return app.name


def find_app(apps: list[AppEntry], query: str) -> list[AppEntry]:
    """Apps cuyo nombre visible, nombre de imagen o ruta contienen `query` (sin distinguir mayúsculas)."""
    q = query.lower()
    return [a for a in apps if q in a.name.lower() or q in os.path.basename(a.exe).lower() or q in a.exe.lower()]


def find_processes(query: str) -> list[ProcInfo]:
    """Procesos vivos cuyo nombre o ruta contienen `query`."""
    q = query.lower()
    out = []
    for p in psutil.process_iter(["pid"]):
        info = proc_info(p.info["pid"])
        if info and (q in info.name.lower() or q in info.exe.lower()):
            out.append(info)
    return out


def root_processes(procs: list[ProcInfo]) -> list[ProcInfo]:
    """De un conjunto de procesos de la misma app, los que no tienen a su padre en el conjunto."""
    pids = {p.pid for p in procs}
    return [p for p in procs if p.ppid not in pids]
