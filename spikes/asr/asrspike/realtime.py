"""Alimentador a ritmo de tiempo real: entrega el audio como si llegara de un dispositivo."""

from __future__ import annotations

import time

import numpy as np
import psutil

from .vad import SAMPLE_RATE


def feed(
    samples: np.ndarray,
    pipeline,
    device_chunk_ms: float = 32.0,
    paced: bool = True,
    setup_delay_s: float = 0.25,
) -> dict:
    """Entrega ``samples`` a ``pipeline.push`` en trozos de ``device_chunk_ms``.

    Con ``paced=True`` el trozo que termina en la muestra ``n`` se entrega cuando han pasado
    ``n / 16000`` s desde el inicio (reloj de pared): es lo que haría una captura real. Si el
    procesamiento se retrasa, los trozos siguientes se entregan de golpe hasta ponerse al día y
    el retraso queda registrado en ``lateness``.

    El reloj del pipeline (``pipeline.clock``) pasa a ser el tiempo transcurrido desde ``t0``.
    Con ``paced=False`` se entrega todo lo más rápido posible y el reloj es la posición del audio
    (solo valen el cómputo, el RTF y el WER, no las latencias).
    """
    step = max(1, int(SAMPLE_RATE * device_chunk_ms / 1000))
    n = len(samples)
    t0 = time.perf_counter() + setup_delay_s
    if paced:
        pipeline.clock = lambda: time.perf_counter() - t0
    else:
        pipeline.clock = lambda: pipeline.audio_pos

    lateness: list[float] = []
    push_s: list[float] = []  # duración de cada llamada a push()
    compute = 0.0
    for pos in range(0, n, step):
        chunk = samples[pos : pos + step]
        end = pos + len(chunk)
        if paced:
            due = t0 + end / SAMPLE_RATE
            wait = due - time.perf_counter()
            if wait > 0:
                time.sleep(wait)
            lateness.append(max(0.0, time.perf_counter() - due))
        c0 = time.perf_counter()
        pipeline.push(chunk)
        dt = time.perf_counter() - c0
        push_s.append(dt)
        compute += dt
    c0 = time.perf_counter()
    pipeline.flush()
    flush_s = time.perf_counter() - c0
    compute += flush_s
    wall_end = time.perf_counter() - t0
    late = np.asarray(lateness) if lateness else np.zeros(1)
    push = np.asarray(push_s) if push_s else np.zeros(1)
    # Estabilidad: cómputo y retraso por tercios de la ejecución (sin deriva si son parecidos).
    thirds = np.array_split(push, 3)
    late_thirds = np.array_split(late, 3)
    mem = psutil.Process().memory_info()
    return {
        "ram_rss_mb": round(mem.rss / 2**20),
        "ram_peak_mb": round(getattr(mem, "peak_wset", mem.rss) / 2**20),
        "paced": paced,
        "audio_s": n / SAMPLE_RATE,
        "wall_s": wall_end,
        "compute_s": compute,
        "rtf": compute / (n / SAMPLE_RATE),
        "final_flush_s": flush_s,
        "device_chunk_ms": device_chunk_ms,
        "lateness_ms": {
            "p50": float(np.percentile(late, 50) * 1000),
            "p95": float(np.percentile(late, 95) * 1000),
            "p99": float(np.percentile(late, 99) * 1000),
            "max": float(late.max() * 1000),
        },
        "push_ms": {
            "p50": float(np.percentile(push, 50) * 1000),
            "p95": float(np.percentile(push, 95) * 1000),
            "p99": float(np.percentile(push, 99) * 1000),
            "max": float(push.max() * 1000),
        },
        "rtf_by_third": [float(t.sum() / (len(t) * step / SAMPLE_RATE)) for t in thirds],
        "lateness_mean_ms_by_third": [float(t.mean() * 1000) for t in late_thirds],
    }
