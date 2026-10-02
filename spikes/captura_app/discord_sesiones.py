"""S6 · 4. Discord (SC-003b): ¿la emisión (Go Live) y la llamada salen por procesos distintos?

Con Discord abierto, cada 0,5 s lista los procesos de Discord que tienen sesión de audio (PID, rol, estado
activa/inactiva y pico). Con `--probar` abre además, solo para medir, una captura pasiva INCLUDE sobre cada PID con
sesión y sobre el proceso principal, y apunta el RMS de lo que entrega. **No se guarda ni se reproduce audio de
Discord: solo PID, nivel (pico y RMS) y si INCLUDE entrega audio.**

Cómo usarlo con la persona (resumen; el detalle está en README.md):
  1. Con Discord abierto y SIN llamada ni emisión:        uv run python spikes/captura_app/discord_sesiones.py --duracion 15
  2. Entrar en una llamada de voz (que suene alguien):    ... --duracion 20 --probar
  3. Con la llamada activa, empezar una emisión (Go Live) viendo una película: ... --duracion 40 --probar
  4. Parar la película y dejar solo la llamada; después solo la película (que no hable nadie en la llamada).
Al terminar imprime, por PID: cuándo estuvo activo, su pico máximo y (con --probar) si INCLUDE entrega audio, y
una conclusión sobre si la emisión y la llamada usan PIDs distintos.

Opciones: --duracion S (0 = hasta Ctrl+C), --probar, --log FICHERO.jsonl (PID, estado, pico y RMS por tick).
"""

from __future__ import annotations

import argparse
import json
import re
import threading
import time
from dataclasses import dataclass, field

import capturar_app as ca
import common as c
import numpy as np
from instanttraductor.audio.wasapi_capture import ProcessLoopbackSource

TICK_S = 0.5
AUDIO_RMS = 1e-4  # RMS (-80 dBFS) a partir del cual INCLUDE(pid) «entrega audio»
ACTIVE_PEAK = 0.001  # pico (-60 dBFS) a partir del cual una sesión «suena» a efectos del resumen


def role_of(info: c.ProcInfo) -> str:
    cmd = ca._cmdline_cached(info)
    m = re.search(r"--type=([\w-]+)", cmd)
    if not m:
        return "main"
    kind = m.group(1)
    if kind == "utility":
        sub = re.search(r"--utility-sub-type=([\w.]+)", cmd)
        return "utility:" + (sub.group(1).split(".")[0] if sub else "?")
    return kind


class Probe:
    """INCLUDE pasiva sobre un PID: solo calcula RMS por ventanas de 0,5 s (nada se guarda)."""

    def __init__(self, info: c.ProcInfo) -> None:
        self.info = info
        self.clock = ca.PerfClock()
        self.source = ProcessLoopbackSource(self.clock, include=True, target_pid=info.pid)
        self.source.start()
        self.rms_window = 0.0  # RMS de lo recibido desde la última lectura de `take`
        self.peak_window = 0.0
        self.max_rms = 0.0
        self._sum, self._n, self._peak = 0.0, 0, 0.0
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self.source.exhausted:
            chunk = self.source.read(0.1)
            if chunk is None:
                continue
            s = chunk.samples.astype(np.float64)
            with self._lock:
                self._sum += float(np.sum(s * s))
                self._n += len(s)
                self._peak = max(self._peak, float(np.max(np.abs(s))))

    def take(self) -> tuple[float, float]:
        with self._lock:
            rms = float(np.sqrt(self._sum / self._n)) if self._n else 0.0
            peak = self._peak
            self._sum, self._n, self._peak = 0.0, 0, 0.0
        self.max_rms = max(self.max_rms, rms)
        return rms, peak

    def stop(self) -> None:
        self.source.stop()


@dataclass
class Track:
    pid: int
    role: str = "?"
    ppid: int = 0
    endpoints: set[str] = field(default_factory=set)
    max_peak: float = 0.0
    active_ticks: int = 0  # ticks con estado activo
    sound_ticks: int = 0  # ticks con pico >= ACTIVE_PEAK
    ticks: int = 0
    segments: list[list[float]] = field(default_factory=list)  # [inicio, fin] con pico >= ACTIVE_PEAK
    cap_segments: list[list[float]] = field(default_factory=list)  # [inicio, fin] con INCLUDE(pid) >= AUDIO_RMS
    max_probe_rms: float | None = None  # solo con --probar


def add_segment(segments: list[list[float]], now: float) -> None:
    """Extiende el último intervalo si el hueco es de ≤ 1 s; si no, abre uno nuevo."""
    if segments and now - segments[-1][1] <= 1.0:
        segments[-1][1] = now
    else:
        segments.append([now, now])


def is_discord(info: c.ProcInfo | None) -> bool:
    return info is not None and ("discord" in info.name.lower() or "discord" in info.exe.lower())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--duracion", type=float, default=20.0)
    ap.add_argument("--probar", action="store_true", help="captura pasiva INCLUDE (solo RMS) por PID")
    ap.add_argument("--log", default="")
    args = ap.parse_args()

    tracks: dict[int, Track] = {}
    probes: dict[int, Probe] = {}
    main_pids: set[int] = set()
    log = open(args.log, "w", encoding="utf-8") if args.log else None  # noqa: SIM115
    t0 = time.perf_counter()
    tick = 0
    print(
        f"Escuchando las sesiones de audio de Discord cada {TICK_S} s ({'con' if args.probar else 'sin'} captura pasiva). "
        "'*' = sesión activa. Pico de sesión y, si hay captura, RMS de INCLUDE(pid) en dBFS.",
        flush=True,
    )
    try:
        while args.duracion <= 0 or time.perf_counter() - t0 < args.duracion:
            t_tick = time.perf_counter()
            sessions = [s for s in c.enumerate_sessions(with_names=False) if is_discord(s.proc) and not s.system]
            for _ in range(3):  # el pico es instantáneo: se queda con el máximo del tick
                time.sleep(0.08)
                for s in sessions:
                    s.refresh_peak()
            now = t_tick - t0
            parts: list[str] = []
            seen: set[int] = set()
            for s in sessions:
                assert s.proc is not None
                tr = tracks.setdefault(s.pid, Track(s.pid))
                if tr.role == "?":
                    tr.role, tr.ppid = role_of(s.proc), s.proc.ppid
                tr.endpoints.add(s.endpoint)
                seen.add(s.pid)
                active = s.state == 1
                tr.ticks += 1
                tr.max_peak = max(tr.max_peak, s.peak)
                tr.active_ticks += active
                if s.peak >= ACTIVE_PEAK:
                    tr.sound_ticks += 1
                    add_segment(tr.segments, now)
                if args.probar:
                    main_pids.add(s.proc.ppid)
                    if s.pid not in probes:
                        probes[s.pid] = Probe(s.proc)
                rms_txt = ""
                row = {"t": round(now, 2), "pid": s.pid, "role": tr.role, "estado": s.state, "pico": round(s.peak, 4)}
                if s.pid in probes:
                    rms, _ = probes[s.pid].take()
                    tr.max_probe_rms = max(tr.max_probe_rms or 0.0, rms)
                    if rms >= AUDIO_RMS:
                        add_segment(tr.cap_segments, now)
                    rms_txt = f" cap {c.db(rms):6.1f}"
                    row["rms"] = round(rms, 5)
                if log:
                    log.write(json.dumps(row) + "\n")
                parts.append(f"{s.pid}[{tr.role}]{'*' if active else ' '} {c.db(s.peak):6.1f}{rms_txt}")
            if args.probar:
                for ppid in sorted(main_pids):
                    info = c.proc_info(ppid)
                    if is_discord(info) and ppid not in probes:
                        probes[ppid] = Probe(info)
                for ppid in sorted(main_pids):
                    if ppid in probes and ppid not in seen:
                        rms, _ = probes[ppid].take()
                        tr = tracks.setdefault(ppid, Track(ppid, role="main(INCLUDE)"))
                        tr.max_probe_rms = max(tr.max_probe_rms or 0.0, rms)
                        if rms >= AUDIO_RMS:
                            add_segment(tr.cap_segments, now)
                        parts.append(f"{ppid}[main-INCLUDE]  cap {c.db(rms):6.1f}")
                        if log:
                            log.write(
                                json.dumps({"t": round(now, 2), "pid": ppid, "role": "main", "rms": round(rms, 5)})
                                + "\n"
                            )
            tick += 1
            print(f"{now:6.1f}s  " + ("  |  ".join(parts) if parts else "(Discord sin sesiones de audio)"), flush=True)
            time.sleep(max(0.0, TICK_S - (time.perf_counter() - t_tick)))
    except KeyboardInterrupt:
        pass
    finally:
        for p in probes.values():
            p.stop()
        if log:
            log.close()

    print("\n=== RESUMEN (solo PID y niveles; no se ha guardado audio) ===")
    print(
        "  'medidor' = pico de la sesión (IAudioMeterInformation); 'INCLUDE' = lo que entrega la captura sobre ese PID."
    )
    emitters = []
    for tr in sorted(tracks.values(), key=lambda t: t.pid):
        meter = ", ".join(f"{a:.1f}-{b:.1f}s" for a, b in tr.segments[:6]) or "nunca"
        cap = ""
        if tr.max_probe_rms is not None:
            cap_seg = ", ".join(f"{a:.1f}-{b:.1f}s" for a, b in tr.cap_segments[:6]) or "nunca"
            cap = f"\n{'':14s}INCLUDE({tr.pid}): RMS máx {c.db(tr.max_probe_rms):.0f} dBFS; entrega audio en: {cap_seg}"
        if tr.role.startswith("main("):
            print(f"  PID {tr.pid:<7d} proceso principal (captura de control){cap}")
            continue
        print(
            f"  PID {tr.pid:<7d} {tr.role:<16s} padre {tr.ppid:<7d} activa {tr.active_ticks}/{tr.ticks} ticks; "
            f"pico máx {c.db(tr.max_peak):.0f} dBFS; medidor con sonido en: {meter}{cap}"
        )
        delivers = tr.max_probe_rms is not None and tr.max_probe_rms > AUDIO_RMS
        if delivers or (tr.max_probe_rms is None and tr.max_peak >= ACTIVE_PEAK):
            emitters.append(tr)
    print()
    basis = "entregó audio por INCLUDE" if args.probar else "marcó sonido en el medidor (sin --probar, no verificado)"
    if len(emitters) >= 2:
        print(f"  {len(emitters)} PIDs distintos {basis}: {[t.pid for t in emitters]}.")
        print("  Si sus intervalos coinciden con la llamada y con la emisión por separado, se pueden separar por PID.")
    elif len(emitters) == 1:
        print(f"  Solo el PID {emitters[0].pid} ({emitters[0].role}) {basis}: todo sale por el mismo proceso.")
    else:
        print("  Ningún proceso de Discord entregó audio en esta medida.")
    print("  Aviso: el medidor de una sesión de Discord puede copiar la mezcla del endpoint (medido 2026-10-02).")


if __name__ == "__main__":
    main()
