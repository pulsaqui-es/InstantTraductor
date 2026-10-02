"""S6 · 2. Captura INCLUDE de una aplicación elegida por nombre, con vigilante por (pid, create_time).

`AppWatcher` es la pieza que el plan de producción tendría que implementar encima de
`ProcessLoopbackSource(include=True, target_pid=...)`:

- resuelve el proceso raíz de la app por nombre (sin necesitar que suene todavía);
- estado «esperando a la app» si no existe; no captura nada mientras tanto;
- abre INCLUDE(raíz) y vigila `(pid, create_time)` cada `poll_s`; si la raíz muere cierra y vuelve a esperar;
- detecta «sesión con pico pero captura en silencio» (PID inexistente, DRM, modo exclusivo...);
- mide: activación, detección de la muerte, reapertura y primer audio tras el reinicio.

Como script, vigila la app y escribe el estado (nunca guarda audio; solo RMS y pico).

Uso:
    uv run python spikes/captura_app/capturar_app.py --app chrome [--duracion 60] [--cmdline-contains X]
    uv run python spikes/captura_app/capturar_app.py --app emisor.py --forzar-pid 999999   (demo del silencio)
"""

from __future__ import annotations

import argparse
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

import common as c  # fija sys.coinit_flags = 0 antes de importar comtypes/pycaw
import comtypes
import numpy as np
import psutil
from instanttraductor.audio.wasapi_capture import ProcessLoopbackSource

AUDIBLE_PEAK = 1e-4  # -80 dBFS: por debajo, «silencio digital» a efectos del spike
SESSION_PEAK = 0.003  # pico de sesión (-50 dBFS) a partir del cual la app «suena» de verdad
SILENT_AFTER_S = 3.0  # segundos seguidos con la sesión sonando y la captura muda para avisar


class PerfClock:
    """Reloj de sesión del spike: `time.perf_counter()` desde la construcción (cumple el contrato `Clock`)."""

    def __init__(self) -> None:
        self.origin = time.perf_counter()

    def now(self) -> float:
        return time.perf_counter() - self.origin


class State(StrEnum):
    WAITING = "esperando a la app"
    CAPTURING = "escuchando"
    SILENT = "suena pero llega silencio"


@dataclass(slots=True)
class Matcher:
    """Qué procesos son «la app»: subcadena en nombre o ruta de imagen (y, solo en pruebas, en la línea de comandos)."""

    query: str
    cmdline_contains: str = ""

    def __call__(self, info: c.ProcInfo, cmdline: str | None = None) -> bool:
        q = self.query.lower()
        if q not in info.name.lower() and q not in info.exe.lower():
            return False
        return cmdline is None or not self.cmdline_contains or self.cmdline_contains.lower() in cmdline.lower()


_CMDLINE_CACHE: dict[c.ProcKey, str] = {}


def _cmdline_cached(info: c.ProcInfo) -> str:
    """Línea de comandos (lenta: ~40 ms por proceso), con caché por (pid, create_time)."""
    key = info.key
    if key not in _CMDLINE_CACHE:
        _CMDLINE_CACHE[key] = _cmdline(info.pid)
    return _CMDLINE_CACHE[key]


def _exe_cached(info: c.ProcInfo) -> str:
    """Ruta de la imagen (lenta: ~18 ms por proceso de Chrome), con caché por (pid, create_time)."""
    key = info.key
    if key not in _EXE_CACHE:
        full = c.proc_info(info.pid)
        _EXE_CACHE[key] = full.exe if full else ""
    return _EXE_CACHE[key]


_EXE_CACHE: dict[c.ProcKey, str] = {}


def snapshot_matching(matcher: Matcher) -> list[c.ProcInfo]:
    """Procesos vivos de la app (los descendientes sin `exe`; las raíces con `exe`). Cuesta ~5 ms.

    Medido (390 procesos, 27 de Chrome): `process_iter(["pid", "name"])` cuesta ~50 ms, pero pedir
    `create_time` de TODOS los procesos tarda 7,7 s la primera vez (cada llamada abre el proceso; los
    protegidos tardan más), `exe` cuesta 18 ms por proceso y `cmdline` 40 ms. Por eso se filtra por nombre y `exe` y `cmdline` (esta solo existe en las pruebas, para distinguir
    mi navegador temporal del de uso real) se consultan solo en las RAÍCES, con caché por (pid, create_time).
    Los descendientes de una raíz aceptada entran con ella.
    """
    q = matcher.query.lower()
    me = set(c.own_pids())
    infos: list[c.ProcInfo] = []
    for p in psutil.process_iter(["pid", "name"]):  # las instancias de Process se reutilizan entre llamadas
        name = p.info["name"] or ""
        if q not in name.lower() or p.info["pid"] in me:
            continue
        try:
            infos.append(c.ProcInfo(p.pid, p.create_time(), p.ppid(), "", name))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    roots = c.root_processes(infos)
    for r in roots:
        r.exe = _exe_cached(r)
    accepted = {r.pid for r in roots if matcher(r, _cmdline_cached(r) if matcher.cmdline_contains else None)}
    by_pid = {i.pid: i for i in infos}
    changed = True
    while changed:  # propaga la aceptación a los hijos (hijo de un aceptado = aceptado)
        changed = False
        for i in infos:
            if i.pid not in accepted and i.ppid in accepted and by_pid[i.ppid].created <= i.created:
                accepted.add(i.pid)
                changed = True
    return [i for i in infos if i.pid in accepted]


class AppWatcher:
    """Vigila una app por nombre y mantiene una captura INCLUDE sobre su proceso raíz.

    Hilos: uno vigilante (sondeo, reapertura, silencio) y uno consumidor (lee chunks, calcula RMS y pico).
    `on_chunk(samples, arrival_abs)` recibe el audio SOLO en memoria (las pruebas con audio propio).
    """

    def __init__(
        self,
        matcher: Matcher,
        *,
        poll_s: float = 0.25,
        force_pid: int | None = None,
        check_silent: bool = True,
        on_chunk: Callable[[np.ndarray, float, float], None] | None = None,
        verbose: bool = True,
    ) -> None:
        self.matcher = matcher
        self.poll_s = poll_s
        self.force_pid = force_pid
        self.check_silent = check_silent
        self.on_chunk = on_chunk
        self.verbose = verbose
        self.clock = PerfClock()
        self.state = State.WAITING
        self.events: list[tuple[float, str, str]] = []  # (t, tipo, texto) con t = perf_counter
        self.target: c.ProcInfo | None = None
        self.source: ProcessLoopbackSource | None = None
        self.recent: deque[tuple[float, float, float]] = deque(maxlen=2000)  # (llegada, rms, pico)
        self.open_count = 0
        self._meter_warned = False
        self.open_times: dict[int, float] = {}  # nº de apertura -> instante de la apertura
        self.warnings: list[str] = []
        self.first_audio_after_open: dict[int, float] = {}  # nº de apertura -> llegada del primer audio
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._source_lock = threading.Lock()

    # --- API ---------------------------------------------------------------------------------------

    def start(self) -> None:
        t = threading.Thread(target=self._watch, name="vigilante", daemon=True)
        t.start()
        self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=3)
        self._close_source()

    def event_times(self, kind: str) -> list[float]:
        return [t for t, k, _ in self.events if k == kind]

    def wait_for(self, kind: str, count: int = 1, timeout: float = 30.0) -> float | None:
        """Espera hasta que haya `count` eventos de `kind`; devuelve la marca del último, o None."""
        end = time.perf_counter() + timeout
        while time.perf_counter() < end:
            times = self.event_times(kind)
            if len(times) >= count:
                return times[count - 1]
            time.sleep(0.01)
        return None

    def audio_level(self, window_s: float = 1.0) -> tuple[float, float]:
        """(rms, pico) máximos de los chunks de los últimos `window_s` s."""
        cut = time.perf_counter() - window_s
        items = [(r, p) for t, r, p in list(self.recent) if t >= cut]
        if not items:
            return 0.0, 0.0
        return max(r for r, _ in items), max(p for _, p in items)

    # --- Registro ----------------------------------------------------------------------------------

    def _log(self, kind: str, text: str) -> None:
        now = time.perf_counter()
        self.events.append((now, kind, text))
        if self.verbose:
            print(f"[{now - self.clock.origin:8.3f}] {kind:<10s} {text}", flush=True)

    # --- Vigilante ---------------------------------------------------------------------------------

    def _resolve(self) -> c.ProcInfo | None:
        if self.force_pid is not None:
            existing = c.proc_info(self.force_pid)
            return existing or c.ProcInfo(self.force_pid, 0.0, 0, "", f"PID{self.force_pid}")
        procs = snapshot_matching(self.matcher)
        if not procs:
            return None
        roots = sorted(c.root_processes(procs), key=lambda p: p.created)
        if len(roots) > 1:
            self._log("AMBIGUA", f"{len(roots)} instancias raíz ({[r.pid for r in roots]}): se toma la más antigua")
        return roots[0]

    def _watch(self) -> None:
        comtypes.CoInitializeEx()  # el hilo vigilante enumera sesiones: necesita COM (MTA)
        silent_since: float | None = None
        last_check = 0.0
        try:
            while not self._stop.is_set():
                if self.state is State.WAITING:
                    target = self._resolve()
                    if target is not None:
                        self._open(target)
                        silent_since = None
                else:
                    assert self.target is not None
                    dead = self.force_pid is None and not self.target.key.alive()
                    if dead:
                        self._log("MUERTA", f"la raíz {self.target.key} ya no existe: se cierra la captura")
                        self._close_source()
                        self.target = None
                        self.state = State.WAITING
                        self._log("ESTADO", State.WAITING.value)
                    elif self.check_silent and time.perf_counter() - last_check >= 1.0:
                        last_check = time.perf_counter()
                        silent_since = self._check_silent(silent_since)
                self._stop.wait(self.poll_s)
        finally:
            comtypes.CoUninitialize()

    def _check_silent(self, silent_since: float | None) -> float | None:
        """Sesión de la app con pico y captura a ceros durante `SILENT_AFTER_S` s -> estado SILENT."""
        sessions = c.enumerate_sessions(with_names=False)
        mine = [
            s
            for s in sessions
            if s.proc is not None
            and self.matcher(s.proc, _cmdline_cached(s.proc) if self.matcher.cmdline_contains else None)
        ]
        others = [s for s in sessions if s not in mine and not s.system and s.pid != 0]
        for _ in range(3):
            for s in mine + others:
                s.refresh_peak()
            time.sleep(0.05)
        session_peak = max((s.peak for s in mine if not s.system), default=0.0)
        others_peak = max((s.peak for s in others), default=0.0)
        _, cap_peak = self.audio_level(1.2)
        if session_peak >= SESSION_PEAK and others_peak >= SESSION_PEAK and session_peak >= others_peak - 1e-4:
            # Medido con Discord: el medidor de su sesión copia la mezcla del endpoint (iguala o supera al de
            # la sesión más alta de otra app). Con él no se puede afirmar «suena pero llega silencio».
            if not self._meter_warned:
                self._meter_warned = True
                self._log("MEDIDOR", "el pico de la sesión copia al de otra app: no sirve para detectar silencio")
            return None
        silent = session_peak >= SESSION_PEAK and cap_peak < AUDIBLE_PEAK
        now = time.perf_counter()
        if silent:
            silent_since = silent_since or now
            if now - silent_since >= SILENT_AFTER_S and self.state is State.CAPTURING:
                self.state = State.SILENT
                self._log(
                    "SILENCIO",
                    f"la sesión marca pico {session_peak:.4f} ({c.db(session_peak):.0f} dBFS) "
                    f"pero la captura da ceros desde hace {now - silent_since:.1f} s",
                )
            return silent_since
        if self.state is State.SILENT:
            self.state = State.CAPTURING
            self._log("ESTADO", f"{State.CAPTURING.value} (la captura vuelve a dar audio)")
        return None

    # --- Captura -----------------------------------------------------------------------------------

    def _open(self, target: c.ProcInfo) -> None:
        t0 = time.perf_counter()
        src = ProcessLoopbackSource(self.clock, include=True, target_pid=target.pid, on_warning=self.warnings.append)
        try:
            src.start()
        except Exception as exc:
            self._log("ERROR", f"no se pudo abrir INCLUDE({target.pid}): {exc}")
            return
        activation_ms = (time.perf_counter() - t0) * 1000
        self.open_count += 1
        self.open_times[self.open_count] = time.perf_counter()
        with self._source_lock:
            self.source = src
        self.target = target
        self.state = State.CAPTURING
        self._log(
            "ABIERTA",
            f"INCLUDE({target.key}) {target.name}; activación {activation_ms:.1f} ms; apertura nº {self.open_count}",
        )
        t = threading.Thread(target=self._consume, args=(src, self.open_count), name="consumidor", daemon=True)
        t.start()
        self._threads.append(t)

    def _close_source(self) -> None:
        with self._source_lock:
            src, self.source = self.source, None
        if src is not None:
            src.stop()

    def _consume(self, src: ProcessLoopbackSource, open_no: int) -> None:
        origin = self.clock.origin
        while not src.exhausted and not self._stop.is_set():
            chunk = src.read(0.1)
            if chunk is None:
                continue
            s = chunk.samples
            rms = float(np.sqrt(np.mean(s.astype(np.float64) ** 2)))
            peak = float(np.max(np.abs(s)))
            arrival = src.arrival_time(chunk.t_start)
            arrival_abs = origin + arrival if arrival is not None else time.perf_counter()
            self.recent.append((arrival_abs, rms, peak))
            if peak >= AUDIBLE_PEAK and open_no not in self.first_audio_after_open:
                self.first_audio_after_open[open_no] = arrival_abs
                self._log("AUDIO", f"primer audio de la apertura {open_no} (pico {c.db(peak):.0f} dBFS)")
            if self.on_chunk is not None:
                self.on_chunk(s, arrival_abs, chunk.t_start)


def _cmdline(pid: int) -> str:
    try:
        return " ".join(psutil.Process(pid).cmdline())
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return ""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--app", required=True, help="subcadena del nombre o ruta de la imagen (chrome, msedge...)")
    ap.add_argument("--duracion", type=float, default=60.0)
    ap.add_argument("--cmdline-contains", default="")
    ap.add_argument("--forzar-pid", type=int, default=None, help="captura este PID en vez del de la app (demo)")
    args = ap.parse_args()

    watcher = AppWatcher(Matcher(args.app, args.cmdline_contains), force_pid=args.forzar_pid)
    watcher.start()
    end = time.perf_counter() + args.duracion
    try:
        while time.perf_counter() < end:
            time.sleep(2.0)
            rms, peak = watcher.audio_level(2.0)
            target = watcher.target.key if watcher.target else "-"
            print(
                f"  estado: {watcher.state.value:<28s} objetivo {target}  captura rms {c.db(rms):6.1f} dBFS "
                f"pico {c.db(peak):6.1f} dBFS  avisos de la fuente: {len(watcher.warnings)}",
                flush=True,
            )
    except KeyboardInterrupt:
        pass
    finally:
        watcher.stop()


if __name__ == "__main__":
    main()
