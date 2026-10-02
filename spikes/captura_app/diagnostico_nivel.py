"""S6 · diagnóstico de nivel: pico de sesión frente a lo que entrega cada captura (solo métricas, sin guardar audio).

Compara, durante unos segundos y a la vez:
  - el pico de cada sesión de audio (IAudioMeterInformation) de las apps indicadas, con su volumen y silencio;
  - INCLUDE(pid) para cada PID indicado;
  - EXCLUDE(propio) = «todo el sistema salvo nosotros» (la referencia del modo 0.1).
Sirve para distinguir «la app suena pero Windows no entrega su audio por proceso» (DRM, Teams...) de «la app
está en silencio o muy baja». Es la comprobación detrás del estado «suena pero llega silencio».

Uso:
    uv run python spikes/captura_app/diagnostico_nivel.py --pids 15112,692572 --apps discord,chrome --duracion 6
"""

from __future__ import annotations

import argparse
import time

import capturar_app as ca
import common as c
import numpy as np
from instanttraductor.audio.wasapi_capture import ProcessLoopbackSource
from pycaw.pycaw import ISimpleAudioVolume


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pids", default="", help="PIDs separados por comas para INCLUDE")
    ap.add_argument("--apps", default="", help="subcadenas de nombre de proceso cuyas sesiones se miden")
    ap.add_argument("--duracion", type=float, default=6.0)
    args = ap.parse_args()

    clock = ca.PerfClock()
    srcs = {"EXCLUDE(propio) = todo el sistema": ProcessLoopbackSource(clock, include=False)}
    for pid in [int(p) for p in args.pids.split(",") if p]:
        srcs[f"INCLUDE({pid})"] = ProcessLoopbackSource(clock, include=True, target_pid=pid)
    for s in srcs.values():
        s.start()
    acc = {k: [0.0, 0, 0.0] for k in srcs}  # suma de cuadrados, muestras, pico
    wanted = [a.lower() for a in args.apps.split(",") if a]
    sessions = [
        s
        for s in c.enumerate_sessions(with_names=False)
        if s.proc and not s.system and any(w in s.proc.name.lower() for w in wanted)
    ]
    end = time.perf_counter() + args.duracion
    while time.perf_counter() < end:
        for k, s in srcs.items():
            chunk = s.read(0.01)
            while chunk is not None:
                x = chunk.samples.astype(np.float64)
                a = acc[k]
                a[0] += float(np.sum(x * x))
                a[1] += len(x)
                a[2] = max(a[2], float(np.max(np.abs(x))))
                chunk = s.read(0.0)
        for s in sessions:
            s.refresh_peak()
    for k, a in acc.items():
        rms = (a[0] / max(a[1], 1)) ** 0.5
        print(f"{k:36s} rms {c.db(rms):7.1f} dBFS   pico {c.db(a[2]):7.1f} dBFS")
    for s in sessions:
        vol = s.ctl.QueryInterface(ISimpleAudioVolume)
        print(
            f"sesión PID {s.pid:<7d} {s.proc.name:<14s} estado {c.STATE_NAMES.get(s.state, '?'):<9s} "
            f"pico {c.db(s.peak):7.1f} dBFS  volumen {vol.GetMasterVolume():.2f}  silenciada {bool(vol.GetMute())}"
        )
    for s in srcs.values():
        s.stop()


if __name__ == "__main__":
    main()
