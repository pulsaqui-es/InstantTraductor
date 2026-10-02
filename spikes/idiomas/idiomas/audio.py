"""Utilidades de audio del spike S5: oráculo de habla por energía, ruido de fondo y mezcla con música.

``energy_speech_intervals`` es el de ``spikes/asr/asrspike/data.py`` (S3), copiado para que este spike sea autónomo.
"""

from __future__ import annotations

import numpy as np

SAMPLE_RATE = 16_000


def energy_speech_intervals(
    x: np.ndarray,
    sr: int = SAMPLE_RATE,
    frame_ms: float = 25.0,
    hop_ms: float = 10.0,
    rel_db: float = 28.0,
    floor_margin_db: float = 15.0,
    min_gap_s: float = 0.25,
    min_len_s: float = 0.15,
) -> list[tuple[float, float]]:
    """Intervalos de habla según la energía: umbral = max(suelo de ruido + 15 dB, percentil 95 - 28 dB)."""
    frame, hop = int(sr * frame_ms / 1000), int(sr * hop_ms / 1000)
    if len(x) < frame:
        return []
    n = 1 + (len(x) - frame) // hop
    idx = np.arange(frame)[None, :] + hop * np.arange(n)[:, None]
    rms = np.sqrt(np.mean(x[idx].astype(np.float64) ** 2, axis=1) + 1e-12)
    db = 20 * np.log10(rms + 1e-9)
    floor, peak = np.percentile(db, 5), np.percentile(db, 95)
    thr = max(floor + floor_margin_db, peak - rel_db)
    mask = db > thr

    runs: list[list[int]] = []
    start = None
    for i, m in enumerate(mask):
        if m and start is None:
            start = i
        elif not m and start is not None:
            runs.append([start, i - 1])
            start = None
    if start is not None:
        runs.append([start, len(mask) - 1])
    merged: list[list[int]] = []
    gap = int(min_gap_s * 1000 / hop_ms)
    for r in runs:
        if merged and r[0] - merged[-1][1] <= gap:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    hop_s = hop_ms / 1000
    out = []
    for a, b in merged:
        t0, t1 = a * hop_s, b * hop_s + frame_ms / 1000
        if t1 - t0 >= min_len_s:
            out.append((round(t0, 3), round(t1, 3)))
    return out


def noise(n: int, level_db: float, rng: np.random.Generator) -> np.ndarray:
    """Ruido blanco de fondo (un loopback real nunca es silencio digital)."""
    return (rng.standard_normal(n) * 10 ** (level_db / 20)).astype(np.float32)


def rms_db(x: np.ndarray) -> float:
    return float(20 * np.log10(np.sqrt(np.mean(x.astype(np.float64) ** 2)) + 1e-12))


def speech_rms_db(x: np.ndarray, intervals: list[tuple[float, float]], sr: int = SAMPLE_RATE) -> float:
    """RMS (dBFS) solo de los tramos con habla."""
    if not intervals:
        return rms_db(x)
    parts = [x[int(a * sr) : int(b * sr)] for a, b in intervals]
    return rms_db(np.concatenate(parts))


def music_loop(tracks: list[np.ndarray], n: int, rng: np.random.Generator) -> np.ndarray:
    """``n`` muestras de música: pistas con inicio al azar, concatenadas con fundido cruzado de 0,5 s."""
    xf = int(0.5 * SAMPLE_RATE)
    out = np.zeros(0, dtype=np.float32)
    order = int(rng.integers(len(tracks)))
    while len(out) < n:
        t = tracks[order % len(tracks)]
        order += 1
        start = int(rng.integers(0, max(1, len(t) - 20 * SAMPLE_RATE)))
        piece = t[start : start + int(rng.uniform(25, 60) * SAMPLE_RATE)].astype(np.float32)
        if len(out) and len(piece) > xf:
            fade = np.linspace(0, 1, xf, dtype=np.float32)
            piece = piece.copy()
            piece[:xf] *= fade
            out[-xf:] *= fade[::-1]
            out[-xf:] += piece[:xf]
            piece = piece[xf:]
        out = np.concatenate([out, piece])
    return out[:n]


def mix_music(
    speech: np.ndarray,
    music: np.ndarray,
    speech_level_db: float,
    snr_db: float = 10.0,
) -> np.ndarray:
    """Mezcla ``music`` a ``snr_db`` dB por debajo del nivel de habla ``speech_level_db`` (RMS de los tramos con habla).

    El nivel de la música se mide sobre toda la pista (incluye silencios y pasajes suaves).
    """
    target = speech_level_db - snr_db
    gain = 10 ** ((target - rms_db(music)) / 20)
    mixed = speech + music[: len(speech)] * gain
    peak = float(np.max(np.abs(mixed)))
    if peak > 0.99:
        mixed = mixed * (0.99 / peak)
    return mixed.astype(np.float32)
