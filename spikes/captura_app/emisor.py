"""Emisor de tonos del spike S6: «una aplicación» controlada que suena por el dispositivo predeterminado.

Imprime una línea JSON por evento en stdout. Las marcas son `time.perf_counter_ns()` (QPC: comparable entre
procesos de la misma máquina) y corresponden al bloque que se entrega a miniaudio, no al aire.

Modos:
    --modo continuo   tono continuo desde que abre (para medir el tiempo de reanudación tras reiniciar).
    --modo rafagas    dispositivo abierto con ceros y N ráfagas de --dur s cada --cada s (latencia).

Volumen bajo por defecto: 0,0316 = -30 dBFS.
"""

from __future__ import annotations

import argparse
import array
import json
import sys
import time

import miniaudio
import numpy as np

RATE = 48000
DEFAULT_AMP = 10 ** (-30 / 20)


def emit(**data) -> None:
    sys.stdout.write(json.dumps(data) + "\n")
    sys.stdout.flush()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--modo", choices=("continuo", "rafagas"), default="continuo")
    ap.add_argument("--freq", type=float, default=1234.0)
    ap.add_argument("--amp", type=float, default=DEFAULT_AMP)
    ap.add_argument("--dur", type=float, default=0.3, help="duración de cada ráfaga (s)")
    ap.add_argument("--cada", type=float, default=1.5, help="periodo entre ráfagas (s)")
    ap.add_argument("--inicio", type=float, default=1.0, help="silencio inicial antes de la 1ª ráfaga (s)")
    ap.add_argument("--n", type=int, default=10, help="número de ráfagas")
    ap.add_argument("--max-s", type=float, default=600.0, help="tope de vida del proceso (s)")
    ap.add_argument("--buffer-ms", type=int, default=10)
    args = ap.parse_args()

    state = {"pos": 0, "burst": 0, "announced": -1, "done": False}
    phase_inc = 2 * np.pi * args.freq / RATE
    fade = int(0.005 * RATE)

    def render(frames: int) -> array.array:
        pos = state["pos"]
        idx = np.arange(pos, pos + frames)
        tone = args.amp * np.sin(phase_inc * idx)
        if args.modo == "continuo":
            out = tone
            if state["announced"] < 0:
                state["announced"] = 0
                emit(ev="tone_start", t_ns=time.perf_counter_ns())
        else:
            t = idx / RATE
            k = np.floor((t - args.inicio) / args.cada)
            local = t - args.inicio - k * args.cada
            on = (t >= args.inicio) & (local < args.dur) & (k < args.n)
            gate = np.zeros(frames)
            if on.any():
                lf = np.minimum(local * RATE, (args.dur - local) * RATE)
                gate = np.where(on, np.minimum(1.0, np.maximum(lf, 0) / fade), 0.0)
                kk = int(k[on][0])
                if kk > state["announced"]:
                    state["announced"] = kk
                    emit(ev="burst", n=kk, t_ns=time.perf_counter_ns())
            out = tone * gate
            if t[0] > args.inicio + args.n * args.cada + 0.5:
                state["done"] = True
        state["pos"] = pos + frames
        return array.array("f", out.astype(np.float32).tobytes())

    def gen():
        frames = yield b""
        while True:
            frames = yield render(frames)

    device = miniaudio.PlaybackDevice(
        output_format=miniaudio.SampleFormat.FLOAT32,
        nchannels=1,
        sample_rate=RATE,
        buffersize_msec=args.buffer_ms,
    )
    stream = gen()
    next(stream)
    device.start(stream)
    import os

    emit(ev="ready", pid=os.getpid(), ppid=os.getppid(), t_ns=time.perf_counter_ns())
    t0 = time.perf_counter()
    try:
        while not state["done"] and time.perf_counter() - t0 < args.max_s:
            time.sleep(0.05)
    finally:
        device.close()
        emit(ev="end", t_ns=time.perf_counter_ns())


if __name__ == "__main__":
    main()
