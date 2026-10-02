"""Lista de aplicaciones que se pueden escuchar y tabla de procesos real (spec 002, ADR-0012, research R4).

Se porta la lógica medida en el spike S6 (`spikes/captura_app/common.py` y `listar_apps.py`):

- `list_audio_apps`: sesiones de audio de **todos** los endpoints de render activos (no solo el
  predeterminado), agrupadas por ejecutable. El objetivo de cada sesión es su PID o, si el padre directo
  es la misma imagen y anterior, ese padre (INCLUDE cubre el PID y sus hijos directos, nunca nietos).
  Una **sonda INCLUDE** de `probe_s` decide si la app suena (RMS ≥ -60 dBFS): el medidor de pico de una
  sesión engaña (con Discord copia la mezcla del dispositivo). Se ocultan la propia app y **todos sus
  antepasados**: el INCLUDE de cualquiera de ellos, hasta el nivel 3, oye nuestra propia voz.
- `find_app` y `resolve_root`: de un nombre o ruta a las identidades que se pueden escuchar.
- `SystemProcessTable`: la `ProcessTable` real (psutil) que usa el vigilante de `AppLoopbackSource`.

Todo es inyectable para los tests sin dispositivo: el enumerador de sesiones, la sonda y el inspector de
procesos. La identidad que se recuerda es la ruta del ejecutable (`AppIdentity.exe_path`); el PID y la hora
de creación solo valen en la sesión.

Limitaciones: una app sin ruta de ejecutable legible (proceso protegido) no se lista, y las apps de la Store
se agrupan por su ejecutable, no por su AUMID.
"""

from __future__ import annotations

import contextlib
import ctypes
import logging
import math
import os
import time
from collections.abc import Callable, Iterator, Sequence
from ctypes import wintypes
from dataclasses import dataclass
from functools import cache
from typing import Any, Final, Protocol

import numpy as np
import psutil

# `wasapi_capture` fija `sys.coinit_flags = 0` (COM en MTA) al importarse y debe hacerlo ANTES de que
# nadie importe comtypes o pycaw: por eso esos dos se importan dentro de las funciones que los usan.
from instanttraductor.audio.app_types import AppIdentity, AudioApp, ProcessTable
from instanttraductor.audio.wasapi_capture import ProcessLoopbackSource
from instanttraductor.contracts import EngineError
from instanttraductor.pipeline.clock import SessionClock

logger = logging.getLogger(__name__)

__all__ = [
    "SOUNDING_DBFS",
    "AppEnumerator",
    "AudioSession",
    "ProbeFunction",
    "ProcessInfo",
    "ProcessInspector",
    "SessionEnumerator",
    "SystemProcessTable",
    "find_app",
    "list_audio_apps",
    "resolve_root",
]

SOUNDING_DBFS: Final = -60.0  # RMS de la sonda INCLUDE a partir del cual la app «suena»
PEAK_CANDIDATE: Final = 0.0005  # pico de sesión (-66 dBFS) a partir del cual se sondea la app
_DB_FLOOR: Final = -120.0
_E_RENDER: Final = 0
_DEVICE_STATE_ACTIVE: Final = 1
_CLSCTX_ALL: Final = 23
_STATE_ACTIVE: Final = 1
_PROBE_READ_S: Final = 0.0

# Funciones de una sola llamada, compatibles con `FakeAppEnumerator` de los tests.
AppEnumerator = Callable[..., list[AudioApp]]


def _to_db(value: float) -> float:
    return max(_DB_FLOOR, 20.0 * math.log10(max(value, 1e-9)))


# --------------------------------------------------------------------------------------------------
# Procesos
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProcessInfo:
    """Lo que se sabe de un proceso: el PID solo no basta (se reutiliza), va con `create_time`."""

    pid: int
    create_time: float
    ppid: int
    exe: str  # ruta de la imagen ('' si no se pudo leer)
    name: str  # nombre del proceso (p. ej. chrome.exe)


def norm_path(path: str) -> str:
    """Ruta normalizada para comparar (Windows no distingue mayúsculas)."""
    return os.path.normcase(os.path.normpath(path)) if path else ""


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
        if not version.VerQueryValueW(
            buf, "\\VarFileInfo\\Translation", ctypes.byref(ptr), ctypes.byref(length)
        ):
            return ""
        lang, codepage = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_ushort * 2)).contents
        for key in (f"{lang:04x}{codepage:04x}", "040904b0", "040904e4", "000004b0"):
            if version.VerQueryValueW(
                buf, f"\\StringFileInfo\\{key}\\FileDescription", ctypes.byref(ptr), ctypes.byref(length)
            ):
                text = ctypes.wstring_at(ptr.value, length.value).strip("\x00 ")
                if text:
                    return text
    except (OSError, ValueError, AttributeError):
        pass
    return ""


def _stem(name: str) -> str:
    return os.path.splitext(name)[0]


class ProcessInspector(Protocol):
    """Lo que `list_audio_apps` necesita de los procesos (inyectable en los tests)."""

    def info(self, pid: int) -> ProcessInfo | None:
        """Datos del proceso, o None si ya no existe o no se puede leer."""
        ...

    def display_name(self, info: ProcessInfo) -> str:
        """Nombre visible: el `FileDescription` del ejecutable o el nombre del proceso."""
        ...

    def hidden_pids(self) -> frozenset[int]:
        """PID de la propia app y de todos sus antepasados: nunca se ofrecen para escuchar."""
        ...


class SystemProcessTable:
    """`ProcessTable` y `ProcessInspector` reales, sobre psutil.

    Medido en S6 (390 procesos): `process_iter(["pid", "name"])` ~50 ms; pedir `create_time` de todos
    tarda 7,7 s la primera vez, y `exe` unos 18 ms por proceso. Por eso `find_roots` filtra primero por
    nombre de proceso y solo pide `exe` de los candidatos, con una caché por (PID, `create_time`).
    """

    def __init__(self) -> None:
        self._exe_cache: dict[tuple[int, float], str] = {}

    # --- ProcessInspector ------------------------------------------------------------------------

    def info(self, pid: int) -> ProcessInfo | None:
        try:
            proc = psutil.Process(pid)
            with proc.oneshot():
                created = proc.create_time()
                ppid = proc.ppid()
                name = proc.name()
                exe = self._exe_of(proc, created)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None
        return ProcessInfo(pid, created, ppid, exe, name)

    def display_name(self, info: ProcessInfo) -> str:
        return file_description(info.exe) or _stem(info.name) or f"PID {info.pid}"

    def hidden_pids(self) -> frozenset[int]:
        me = os.getpid()
        try:
            ancestors = [p.pid for p in psutil.Process(me).parents()]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            ancestors = []
        return frozenset([me, *ancestors])

    # --- ProcessTable ----------------------------------------------------------------------------

    def find_roots(self, exe_path: str) -> list[AppIdentity]:
        """Procesos raíz vivos de esa app, el más antiguo primero.

        Raíz = proceso de esa imagen cuyo padre no es otro proceso de la misma imagen y anterior a él. No
        hace falta que suene: la captura INCLUDE sobre la raíz oirá a la app en cuanto empiece.
        """
        return [self._identity(info) for info in self._roots_of(exe_path)]

    def is_alive(self, pid: int, create_time: float) -> bool:
        try:
            return psutil.Process(pid).create_time() == create_time
        except psutil.NoSuchProcess:
            return False
        except psutil.AccessDenied:
            return psutil.pid_exists(pid)  # vivo, pero no se puede comprobar que sea el mismo

    # --- Auxiliares ------------------------------------------------------------------------------

    def find_by_name(self, fragment: str) -> list[ProcessInfo]:
        """Raíces de los procesos vivos cuyo nombre contiene `fragment` (sin distinguir mayúsculas)."""
        needle = fragment.lower()
        hidden = self.hidden_pids()
        found: list[ProcessInfo] = []
        for proc in psutil.process_iter(["pid", "name"]):
            name = proc.info["name"] or ""
            if needle not in name.lower() or proc.info["pid"] in hidden:
                continue
            info = self.info(proc.info["pid"])
            if info is not None and info.exe:
                found.append(info)
        return _roots(found)

    def _roots_of(self, exe_path: str) -> list[ProcessInfo]:
        wanted = norm_path(exe_path)
        name = os.path.basename(exe_path).lower()
        hidden = self.hidden_pids()
        candidates: list[ProcessInfo] = []
        for proc in psutil.process_iter(["pid", "name"]):  # las instancias se reutilizan entre llamadas
            if (proc.info["name"] or "").lower() != name or proc.info["pid"] in hidden:
                continue
            try:
                created = proc.create_time()
                ppid = proc.ppid()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            exe = self._exe_of(proc, created)
            if norm_path(exe) == wanted:
                candidates.append(ProcessInfo(proc.pid, created, ppid, exe, proc.info["name"]))
        return _roots(candidates)

    def _exe_of(self, proc: psutil.Process, created: float) -> str:
        key = (proc.pid, created)
        exe = self._exe_cache.get(key)
        if exe is None:
            try:
                exe = proc.exe()
            except (psutil.AccessDenied, psutil.ZombieProcess, psutil.NoSuchProcess):
                exe = ""
            if len(self._exe_cache) > 4096:
                self._exe_cache.clear()
            self._exe_cache[key] = exe
        return exe

    def _identity(self, info: ProcessInfo) -> AppIdentity:
        return AppIdentity(info.exe, self.display_name(info), info.pid, info.create_time)


def _roots(procs: Sequence[ProcessInfo]) -> list[ProcessInfo]:
    """De un conjunto de procesos de la misma app, los que no tienen a su padre (anterior) en el conjunto."""
    by_pid = {p.pid: p for p in procs}
    roots = [p for p in procs if not (p.ppid in by_pid and by_pid[p.ppid].create_time <= p.create_time)]
    return sorted(roots, key=lambda p: p.create_time)


# --------------------------------------------------------------------------------------------------
# Sesiones de audio
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AudioSession:
    """Una sesión de audio de un endpoint de render (los datos que `list_audio_apps` necesita)."""

    endpoint: str  # nombre del dispositivo de salida
    pid: int  # proceso que emite
    state: int  # 0 inactiva, 1 activa, 2 expirada
    peak: float  # pico del medidor de la sesión (0-1); no es fiable para decidir si suena
    system: bool  # sesión de sonidos del sistema


SessionEnumerator = Callable[[], list[AudioSession]]
# (PID objetivo, duración en s) -> RMS (0-1) captado por cada PID con una INCLUDE. Los PID sin dato valen 0.
ProbeFunction = Callable[[Sequence[int], float], dict[int, float]]


@contextlib.contextmanager
def _com_scope() -> Iterator[None]:
    """COM en MTA en el hilo actual mientras dura la enumeración (los hilos nuevos no lo traen)."""
    import comtypes

    initialized = False
    try:
        comtypes.CoInitializeEx()  # usa sys.coinit_flags = 0 (MTA)
        initialized = True
    except OSError:
        pass  # el hilo ya estaba en otro modo: se usa como esté
    try:
        yield
    finally:
        if initialized:
            comtypes.CoUninitialize()


def enumerate_audio_sessions() -> list[AudioSession]:
    """Sesiones de render de TODOS los endpoints activos, no solo el predeterminado (250-340 ms)."""
    import comtypes
    from pycaw.pycaw import (
        AudioUtilities,
        IAudioMeterInformation,
        IAudioSessionControl2,
        IAudioSessionManager2,
    )

    sessions: list[AudioSession] = []
    with _com_scope():
        enumerator = AudioUtilities.GetDeviceEnumerator()
        collection = enumerator.EnumAudioEndpoints(_E_RENDER, _DEVICE_STATE_ACTIVE)
        for i in range(collection.GetCount()):
            device = collection.Item(i)
            try:
                name = AudioUtilities.CreateDevice(device).FriendlyName or device.GetId()
            except Exception:
                name = device.GetId()
            try:
                iface = device.Activate(IAudioSessionManager2._iid_, _CLSCTX_ALL, None)
                manager = iface.QueryInterface(IAudioSessionManager2)
                enum = manager.GetSessionEnumerator()
            except comtypes.COMError:
                continue
            for j in range(enum.GetCount()):
                try:
                    ctl = enum.GetSession(j).QueryInterface(IAudioSessionControl2)
                    pid = ctl.GetProcessId()
                    state = ctl.GetState()
                    system = ctl.IsSystemSoundsSession() == 0  # S_OK = sesión de sonidos del sistema
                    peak = float(ctl.QueryInterface(IAudioMeterInformation).GetPeakValue())
                except comtypes.COMError:
                    continue
                sessions.append(AudioSession(name, pid, state, peak, system))
    return sessions


def _probe_include(pids: Sequence[int], seconds: float) -> dict[int, float]:
    """RMS que entrega una captura INCLUDE de cada PID durante `seconds` s (en paralelo; nada se guarda)."""
    clock = SessionClock()
    sources: dict[int, ProcessLoopbackSource] = {}
    for pid in pids:
        source = ProcessLoopbackSource(clock, include=True, target_pid=pid)
        try:
            source.start()
        except (EngineError, OSError) as exc:
            logger.info("Sonda INCLUDE del PID %s no disponible: %s", pid, exc)
            continue
        sources[pid] = source
    time.sleep(seconds)
    result: dict[int, float] = {pid: 0.0 for pid in pids}
    for pid, source in sources.items():
        total, count = 0.0, 0
        while (chunk := source.read(_PROBE_READ_S)) is not None:
            data = chunk.samples.astype(np.float64)
            total += float(np.sum(data * data))
            count += len(data)
        source.stop()
        result[pid] = math.sqrt(total / count) if count else 0.0
    return result


# --------------------------------------------------------------------------------------------------
# Lista de apps
# --------------------------------------------------------------------------------------------------


def resolve_target(emitter: ProcessInfo, inspector: ProcessInspector) -> ProcessInfo:
    """Proceso raíz que hay que capturar: el padre directo si es de la misma imagen y anterior; si no, el PID.

    Regla medida (S6): INCLUDE cubre el PID objetivo y sus hijos DIRECTOS, nunca nietos. El emisor es el PID
    de la sesión; su padre directo lo cubre si es la misma aplicación (Chrome: servicio de audio -> browser;
    Discord: renderer -> main).
    """
    parent = inspector.info(emitter.ppid) if emitter.ppid else None
    if (
        parent is not None
        and parent.create_time <= emitter.create_time
        and parent.exe
        and norm_path(parent.exe) == norm_path(emitter.exe)
    ):
        return parent
    return emitter


@dataclass(slots=True)
class _Group:
    """Sesiones de una misma aplicación (misma imagen del objetivo)."""

    exe: str
    name: str
    targets: dict[int, ProcessInfo]
    sessions: list[AudioSession]

    @property
    def candidate(self) -> bool:
        """¿Merece sonda? Con sesión activa o con pico en el medidor."""
        return any(s.state == _STATE_ACTIVE or s.peak >= PEAK_CANDIDATE for s in self.sessions)


def _group_sessions(sessions: Sequence[AudioSession], inspector: ProcessInspector) -> list[_Group]:
    hidden = inspector.hidden_pids()
    groups: dict[str, _Group] = {}
    for session in sessions:
        if session.system or session.pid == 0 or session.pid in hidden:
            continue
        emitter = inspector.info(session.pid)
        if emitter is None:
            continue
        target = resolve_target(emitter, inspector)
        if target.pid in hidden or not target.exe:
            continue  # la propia app o uno de sus antepasados; o una imagen que no se puede leer
        key = norm_path(target.exe)
        group = groups.get(key)
        if group is None:
            group = groups[key] = _Group(target.exe, inspector.display_name(target), {}, [])
        group.sessions.append(session)
        group.targets.setdefault(target.pid, target)
    for group in groups.values():  # un objetivo hijo directo de otro objetivo es doble recuento
        group.targets = {p: t for p, t in group.targets.items() if t.ppid not in group.targets}
    return list(groups.values())


def list_audio_apps(
    *,
    probe_s: float = 0.6,
    enumerate_sessions: SessionEnumerator | None = None,
    inspector: ProcessInspector | None = None,
    probe: ProbeFunction | None = None,
) -> list[AudioApp]:
    """Aplicaciones con sesión de audio, para elegir cuál escuchar. Primero las que suenan, por nivel.

    - `probe_s`: duración de la sonda INCLUDE de las apps candidatas (con sesión activa o con pico). 0 la
      omite: todas salen con `sounding=False`. Una app «suena» con RMS ≥ -60 dBFS en la sonda.
    - Con varias instancias de una app (varios procesos raíz) la identidad es la que más suena; si no suena
      ninguna, la más antigua.
    - Se ocultan las sesiones del sistema, la propia app y todos sus antepasados.
    - `enumerate_sessions`, `inspector` y `probe` se inyectan solo en los tests.
    """
    inspector = inspector or SystemProcessTable()
    try:
        sessions = (enumerate_sessions or enumerate_audio_sessions)()
    except Exception:
        logger.exception("No se pudieron enumerar las sesiones de audio")
        return []
    groups = _group_sessions(sessions, inspector)
    rms_by_pid: dict[int, float] = {}
    if probe_s > 0:
        pids = sorted({pid for g in groups if g.candidate for pid in g.targets})
        if pids:
            try:
                rms_by_pid = (probe or _probe_include)(pids, probe_s)
            except Exception:
                logger.exception("Falló la sonda INCLUDE de las apps")
    apps: list[AudioApp] = []
    for group in groups:
        best = max(group.targets.values(), key=lambda t: (rms_by_pid.get(t.pid, 0.0), -t.create_time))
        rms = rms_by_pid.get(best.pid, 0.0)
        level = _to_db(rms)
        identity = AppIdentity(group.exe, group.name, best.pid, best.create_time)
        endpoints = tuple(sorted({s.endpoint for s in group.sessions}))
        apps.append(AudioApp(identity, level >= SOUNDING_DBFS, level, endpoints))
    apps.sort(key=lambda a: (not a.sounding, -a.level_dbfs, a.identity.display_name.lower()))
    return apps


def find_app(
    name_or_path: str,
    *,
    enumerate_apps: AppEnumerator | None = None,
    table: Any | None = None,
) -> list[AppIdentity]:
    """Apps que encajan con un nombre o ruta, sin distinguir mayúsculas.

    Encaja por la ruta exacta del ejecutable o por una subcadena del nombre visible, del nombre del
    ejecutable o de su ruta. Mira primero las apps con sesión de audio (`list_audio_apps` sin sonda) y
    después los procesos abiertos que aún no tienen sesión (Chrome sin ningún vídeo sonando). Sin
    duplicados por ejecutable; las que ya tienen sesión van primero.

    - `enumerate_apps`: sustituye a `list_audio_apps` (se llama con `probe_s=0`).
    - `table`: objeto con `find_by_name(fragmento)` (por defecto `SystemProcessTable`).
    """
    query = name_or_path.strip().lower()
    if not query:
        return []
    listing = enumerate_apps or list_audio_apps
    found: dict[str, AppIdentity] = {}

    def matches(identity: AppIdentity) -> bool:
        exe = identity.exe_path.lower()
        base = os.path.basename(exe)
        return (
            norm_path(identity.exe_path) == norm_path(name_or_path.strip())
            or query in identity.display_name.lower()
            or query in base
            or query in exe
        )

    for audio_app in listing(probe_s=0):
        if matches(audio_app.identity):
            found.setdefault(norm_path(audio_app.identity.exe_path), audio_app.identity)
    lookup = table if table is not None else SystemProcessTable()
    for info in lookup.find_by_name(_stem(os.path.basename(query))):
        key = norm_path(info.exe)
        if key not in found:
            found[key] = AppIdentity(
                info.exe, file_description(info.exe) or _stem(info.name), info.pid, info.create_time
            )
    return list(found.values())


def resolve_root(exe_path: str, *, table: ProcessTable | None = None) -> AppIdentity | None:
    """Identidad actual (PID y `create_time`) del proceso raíz más antiguo de la app, o None si no está."""
    roots = (table or SystemProcessTable()).find_roots(exe_path)
    return min(roots, key=lambda r: r.create_time) if roots else None
