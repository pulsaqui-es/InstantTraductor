"""S6 · 1. Lista de apps que tienen sesión de audio, la que verá la persona usuaria al arrancar.

Enumera las sesiones de TODOS los endpoints de render activos, calcula el proceso raíz que hay que capturar
(la sesión o su padre directo), agrupa por aplicación y oculta la propia app y su padre.

Uso:
    uv run python spikes/captura_app/listar_apps.py [--peak-window 1.0] [--detalle] [--json]
"""

from __future__ import annotations

import argparse
import json
import time

import common as c


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--peak-window", type=float, default=1.0, help="segundos de sondeo del pico (máximo)")
    ap.add_argument("--detalle", action="store_true", help="muestra cada sesión (PID emisor, endpoint...)")
    ap.add_argument("--json", action="store_true", help="salida JSON (para otros scripts)")
    ap.add_argument("--incluir-propias", action="store_true", help="no oculta la app ni su padre")
    args = ap.parse_args()

    t0 = time.perf_counter()
    sessions = c.enumerate_sessions(peak_window_s=0.0)
    t_enum = time.perf_counter() - t0
    # El sondeo del pico se hace sobre las mismas sesiones ya enumeradas.
    end = time.perf_counter() + args.peak_window
    while time.perf_counter() < end:
        for s in sessions:
            s.refresh_peak()
        time.sleep(0.05)
    apps, notes = c.build_apps(sessions, hide_own=not args.incluir_propias)

    if args.json:
        print(
            json.dumps(
                [
                    {
                        "n": i,
                        "name": a.name,
                        "key": a.key,
                        "exe": a.exe,
                        "aumid": a.aumid,
                        "targets": [{"pid": t.pid, "created": t.created, "ppid": t.ppid} for t in a.targets],
                        "session_pids": [s.pid for s in a.sessions],
                        "peak": a.peak,
                        "sounding": a.sounding,
                        "endpoints": a.endpoints,
                    }
                    for i, a in enumerate(apps, 1)
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    me, parent = c.own_pids()
    n_endpoints = len({s.endpoint for s in sessions})
    print(
        f"Sesiones de audio: {len(sessions)} en {n_endpoints} endpoint(s) con sesiones "
        f"(enumeración: {t_enum * 1000:.0f} ms; pico = máximo de {args.peak_window:.1f} s). "
        f"PID propio {me}, su padre {parent}."
    )
    print()
    print("Aplicaciones con sesión de audio:")
    for i, a in enumerate(apps, 1):
        flag = "SUENA " if a.sounding else "      "
        state = c.STATE_NAMES.get(a.state, "?")
        pids = ",".join(str(t.pid) for t in a.targets)
        warn = f"  [!] emisores sin cubrir: {a.uncovered}" if a.uncovered else ""
        print(
            f" {i:2d}. {flag}{c.app_label(a):<42s} pico {a.peak:6.4f} ({c.db(a.peak):6.1f} dBFS)  "
            f"{state:<9s} objetivo PID {pids}{warn}"
        )
        if args.detalle:
            print(f"       imagen: {a.exe or '(sin acceso)'}" + (f"  AUMID: {a.aumid}" if a.aumid else ""))
            for s in a.sessions:
                p = s.proc
                print(
                    f"       - sesión PID {s.pid:<6d} ({p.name if p else '?'}) padre {p.ppid if p else '?'} "
                    f"estado {c.STATE_NAMES.get(s.state, '?'):<9s} pico {s.peak:6.4f}  endpoint: {s.endpoint}"
                )
    if not apps:
        print("  (ninguna)")
    if args.detalle and notes:
        print()
        for note in notes:
            print(" ", note)


if __name__ == "__main__":
    main()
