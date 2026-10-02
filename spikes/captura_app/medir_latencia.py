"""S6 · M12: latencia de la captura INCLUDE (del bloque entregado por la app a la muestra captada).

Un emisor (`emisor.py --modo rafagas`, 777 Hz a -30 dBFS, dispositivo abierto con ceros entre ráfagas) apunta, con
`perf_counter_ns` (QPC compartido), el instante en que entrega al dispositivo el primer bloque de cada ráfaga.
Aquí se abre INCLUDE(lanzador del emisor), igual que la app real (el PID raíz, no el que suena), y se apunta cuándo
llega la muestra que empieza la ráfaga: llegada del chunk que la contiene menos lo que falta del chunk.
Latencia = llegada - entrega. Incluye el búfer del emisor, la mezcla de Windows y los paquetes de 10 ms de la
captura; no incluye el altavoz (el loopback toma el audio antes). Solo métricas, nada se guarda.

Uso:
    uv run python spikes/captura_app/medir_latencia.py [--n 20] [--buffer-ms 10]
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

import capturar_app as ca
import numpy as np
from instanttraductor.audio.wasapi_capture import ProcessLoopbackSource

HERE = Path(__file__).resolve().parent
CREATE_NO_WINDOW = 0x08000000
THRESHOLD = 0.004  # pico (-48 dBFS): la ráfaga llega a ~0,03 (-30 dBFS)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--buffer-ms", type=int, default=10)
    ap.add_argument("--cada", type=float, default=1.0)
    args = ap.parse_args()

    proc = subprocess.Popen(
        [sys.executable, str(HERE / "emisor.py"), "--modo", "rafagas", "--n", str(args.n), "--cada", str(args.cada),
         "--dur", "0.25", "--inicio", "2.0", "--buffer-ms", str(args.buffer_ms), "--freq", "777"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, creationflags=CREATE_NO_WINDOW,
    )  # fmt: skip
    bursts: list[float] = []
    threading.Thread(
        target=lambda: [bursts.append(d["t_ns"] / 1e9) for d in map(json.loads, proc.stdout) if d.get("ev") == "burst"],
        daemon=True,
    ).start()

    clock = ca.PerfClock()
    src = ProcessLoopbackSource(clock, include=True, target_pid=proc.pid)  # el lanzador del venv: la raíz
    src.start()
    onsets: list[float] = []
    armed = True
    quiet = 0
    end = time.perf_counter() + 2.0 + args.n * args.cada + 2.0
    while time.perf_counter() < end:
        chunk = src.read(0.05)
        if chunk is None:
            continue
        x = np.abs(chunk.samples)
        if x.max() < THRESHOLD:
            quiet += 1
            armed = armed or quiet >= 5  # 100 ms de silencio entre ráfagas
            continue
        quiet = 0
        if armed:
            armed = False
            idx = int(np.argmax(x >= THRESHOLD))
            arrival = src.arrival_time(chunk.t_start)
            if arrival is not None:
                onsets.append(clock.origin + arrival - (len(x) - idx) / 16000)
    src.stop()
    proc.kill()

    # Empareja cada ráfaga con la primera llegada posterior a ella.
    lat = []
    for b in bursts:
        later = [o for o in onsets if o >= b - 0.005]
        if later:
            lat.append((min(later) - b) * 1000)
    lat = [v for v in lat if 0 < v < 600]
    print(f"ráfagas entregadas: {len(bursts)}; detectadas: {len(lat)}; búfer del emisor: {args.buffer_ms} ms")
    if lat:
        q = statistics.quantiles(lat, n=20)
        print(
            f"latencia emisor -> captura INCLUDE: min {min(lat):.0f} / mediana {statistics.median(lat):.0f} / "
            f"p95 {q[18]:.0f} / max {max(lat):.0f} ms"
        )


if __name__ == "__main__":
    main()
