"""Procesado de señal para fabricar el corpus sintético C2: susurro por DSP, time-stretch local (WSOLA),
música, efectos y mezclas. Todo con numpy/scipy, a 16 kHz mono float32.

Estas aproximaciones NO sustituyen a habla real susurrada: son una cota barata y repetible (ver README, límites).
"""

from __future__ import annotations

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from scipy import signal

from common import SR, active_rms_dbfs, scale_to_rms

# ---------------------------------------------------------------------------
# Susurro por procesamiento de señal
# ---------------------------------------------------------------------------


def whisperize(x: np.ndarray, rng: np.random.Generator, n_fft: int = 512, hop: int = 128) -> np.ndarray:
    """Convierte habla normal en una aproximación de habla susurrada.

    El susurro no tiene excitación glotal (sin tono): la envolvente espectral del habla se conserva y la
    fuente es ruido. Pasos: STFT; envolvente por liftering cepstral (quita los armónicos); excitación de
    ruido blanco filtrada con esa envolvente; recorte de graves (< 250 Hz) y ligero realce de agudos, como
    en el susurro real; vuelta al dominio temporal por solapamiento y suma.
    """
    win = signal.windows.hann(n_fft, sym=False)
    _, _, spec = signal.stft(x, SR, window=win, nperseg=n_fft, noverlap=n_fft - hop, boundary="zeros")
    mag = np.abs(spec) + 1e-8
    logmag = np.log(mag)
    # Envolvente cepstral: quefrencias bajas (< 2,5 ms ≈ sin el tono de 80-400 Hz).
    cep = np.fft.irfft(logmag, axis=0)
    lifter = np.zeros(cep.shape[0])
    keep = 30
    lifter[:keep] = 1.0
    lifter[-keep + 1 :] = 1.0
    env = np.exp(np.fft.rfft(cep * lifter[:, None], axis=0).real)
    freqs = np.linspace(0, SR / 2, env.shape[0])
    shape = np.clip((freqs - 150.0) / 250.0, 0.0, 1.0) * (1.0 + 0.6 * (freqs / (SR / 2)))
    env = env * shape[:, None]
    noise = rng.standard_normal(len(x) + 2 * n_fft).astype(np.float64)
    _, _, nspec = signal.stft(noise, SR, window=win, nperseg=n_fft, noverlap=n_fft - hop, boundary="zeros")
    nspec = nspec[:, : env.shape[1]]
    nspec = nspec / (np.abs(nspec) + 1e-8)  # fase aleatoria, módulo 1
    out_spec = env[:, : nspec.shape[1]] * nspec
    _, y = signal.istft(out_spec, SR, window=win, nperseg=n_fft, noverlap=n_fft - hop, boundary=True)
    y = y[: len(x)]
    if len(y) < len(x):
        y = np.pad(y, (0, len(x) - len(y)))
    # Conserva la dinámica silábica del original: la envolvente temporal del habla modula el ruido.
    return y.astype(np.float32)


# ---------------------------------------------------------------------------
# Time-stretch (WSOLA)
# ---------------------------------------------------------------------------


def wsola(x: np.ndarray, ratio: float, win: int = 800, tol: int = 240) -> np.ndarray:
    """Alarga (ratio > 1) o acorta la señal sin cambiar el tono, con WSOLA.

    Cada trama de salida avanza `win/2`; la de entrada, `win/2 / ratio`. La posición exacta se busca en
    ±`tol` muestras por correlación con la continuación natural de la trama anterior.
    """
    if ratio == 1.0 or len(x) < win * 2:
        return x.copy()
    x = x.astype(np.float32)
    hs = win // 2
    ha = hs / ratio
    n_frames = int(np.ceil((len(x) * ratio) / hs)) + 2
    out = np.zeros(n_frames * hs + win, dtype=np.float64)
    wsum = np.zeros_like(out)
    w = signal.windows.hann(win, sym=False)
    padded = np.pad(x, (tol, win + tol + hs))
    prev = 0  # inicio (en `padded`) de la trama anterior
    for k in range(n_frames):
        nominal = int(round(k * ha)) + tol
        if k == 0:
            start = nominal
        else:
            ref = padded[prev + hs : prev + hs + win]
            lo = max(0, nominal - tol)
            hi = min(len(padded) - win, nominal + tol)
            if hi <= lo:
                start = min(nominal, len(padded) - win)
            else:
                cand = sliding_window_view(padded[lo : hi + win], win)[::2]
                scores = cand @ ref
                start = lo + int(np.argmax(scores)) * 2
        frame = padded[start : start + win]
        if len(frame) < win:
            break
        out[k * hs : k * hs + win] += frame * w
        wsum[k * hs : k * hs + win] += w
        prev = start
    wsum[wsum < 1e-6] = 1.0
    y = (out / wsum)[: int(len(x) * ratio)]
    return y.astype(np.float32)


def elongate_words(
    x: np.ndarray, rng: np.random.Generator, n_spans: int = 3, factor: float = 2.8, span_s: float = 0.26
) -> tuple[np.ndarray, list[tuple[float, float]]]:
    """Alarga `n_spans` núcleos vocálicos de la señal (voz sonora de alta energía) por `factor` con WSOLA.

    Imita «Nooooo» o «Heeeey». Devuelve la señal y los tramos estirados (en segundos, de la señal NUEVA).
    Los núcleos se buscan donde hay energía alta y pocos cruces por cero (vocal), separados al menos 0,9 s.
    """
    frame = 320
    n = len(x) // frame
    fr = x[: n * frame].reshape(n, frame)
    energy = np.sqrt(np.mean(fr**2, axis=1))
    zcr = np.mean(np.abs(np.diff(np.sign(fr), axis=1)) > 0, axis=1)
    score = energy / (energy.max() + 1e-9) - 1.5 * zcr
    span_f = int(span_s * SR / frame)
    ok = np.ones(n, dtype=bool)
    ok[:span_f] = False
    ok[-span_f - 2 :] = False
    chosen: list[int] = []
    order = np.argsort(-(score + 0.05 * rng.random(n)))
    for idx in order:
        if not ok[idx]:
            continue
        if any(abs(int(idx) - c) * frame / SR < 0.9 for c in chosen):
            continue
        chosen.append(int(idx))
        if len(chosen) == n_spans:
            break
    chosen.sort()
    pieces: list[np.ndarray] = []
    spans: list[tuple[float, float]] = []
    cursor = 0
    produced = 0
    for idx in chosen:
        a = max(cursor, idx * frame - span_f * frame // 2)
        b = min(len(x), a + span_f * frame)
        pieces.append(x[cursor:a])
        produced += a - cursor
        stretched = wsola(x[a:b], factor, win=640, tol=160)
        pieces.append(stretched)
        spans.append((produced / SR, (produced + len(stretched)) / SR))
        produced += len(stretched)
        cursor = b
    pieces.append(x[cursor:])
    return np.concatenate(pieces).astype(np.float32), spans


# ---------------------------------------------------------------------------
# Efectos sonoros sintéticos (sin diálogo)
# ---------------------------------------------------------------------------


def _env(n: int, attack: float, decay: float) -> np.ndarray:
    t = np.arange(n) / SR
    return np.minimum(t / max(attack, 1e-4), 1.0) * np.exp(-t / decay)


def sfx_explosion(rng: np.random.Generator, dur: float = 2.0) -> np.ndarray:
    n = int(dur * SR)
    noise = rng.standard_normal(n)
    sos = signal.butter(2, 900, "low", fs=SR, output="sos")
    return (signal.sosfilt(sos, noise) * _env(n, 0.005, 0.5)).astype(np.float32)


def sfx_gunshot(rng: np.random.Generator) -> np.ndarray:
    n = int(0.35 * SR)
    noise = rng.standard_normal(n)
    return (noise * _env(n, 0.001, 0.05)).astype(np.float32)


def sfx_door(rng: np.random.Generator) -> np.ndarray:
    n = int(0.5 * SR)
    t = np.arange(n) / SR
    thud = np.sin(2 * np.pi * 90 * t) * np.exp(-t / 0.07) + 0.3 * rng.standard_normal(n) * np.exp(-t / 0.02)
    return thud.astype(np.float32)


def sfx_footsteps(rng: np.random.Generator, count: int = 8) -> np.ndarray:
    out = np.zeros(int((count * 0.55 + 0.5) * SR), dtype=np.float32)
    for i in range(count):
        n = int(0.12 * SR)
        step = rng.standard_normal(n) * _env(n, 0.002, 0.025)
        sos = signal.butter(2, [100, 1500], "band", fs=SR, output="sos")
        step = signal.sosfilt(sos, step)
        a = int(i * 0.55 * SR + rng.integers(0, 2000))
        out[a : a + n] += step.astype(np.float32)
    return out


def sfx_siren(dur: float = 4.0) -> np.ndarray:
    t = np.arange(int(dur * SR)) / SR
    f = 700 + 300 * np.sin(2 * np.pi * 0.6 * t)
    phase = 2 * np.pi * np.cumsum(f) / SR
    return (np.sign(np.sin(phase)) * 0.5 + np.sin(phase)).astype(np.float32)


def sfx_wind(rng: np.random.Generator, dur: float = 6.0) -> np.ndarray:
    n = int(dur * SR)
    noise = rng.standard_normal(n)
    sos = signal.butter(2, [200, 2500], "band", fs=SR, output="sos")
    wind = signal.sosfilt(sos, noise)
    mod = 0.6 + 0.4 * np.sin(2 * np.pi * 0.3 * np.arange(n) / SR + rng.random() * 6)
    return (wind * mod).astype(np.float32)


def sfx_engine(dur: float = 6.0) -> np.ndarray:
    t = np.arange(int(dur * SR)) / SR
    f0 = 55 + 8 * np.sin(2 * np.pi * 0.2 * t)
    ph = 2 * np.pi * np.cumsum(f0) / SR
    return sum(np.sin(k * ph) / k for k in range(1, 9)).astype(np.float32)


def sfx_glass(rng: np.random.Generator) -> np.ndarray:
    n = int(0.8 * SR)
    noise = rng.standard_normal(n)
    sos = signal.butter(2, 3000, "high", fs=SR, output="sos")
    return (signal.sosfilt(sos, noise) * _env(n, 0.001, 0.15)).astype(np.float32)


def sfx_laser(dur: float = 0.6) -> np.ndarray:
    t = np.arange(int(dur * SR)) / SR
    f = 2500 * np.exp(-6 * t) + 200
    return (np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.3)).astype(np.float32)


def effects_track(rng: np.random.Generator, target_s: float, level_dbfs: float = -24.0) -> np.ndarray:
    """Pista de efectos sin diálogo: explosiones, disparos, puertas, pasos, sirenas, viento, motor, cristal."""
    makers = [
        lambda: sfx_explosion(rng),
        lambda: sfx_gunshot(rng),
        lambda: np.concatenate([sfx_gunshot(rng), np.zeros(int(0.2 * SR), np.float32), sfx_gunshot(rng)]),
        lambda: sfx_door(rng),
        lambda: sfx_footsteps(rng),
        lambda: sfx_siren(),
        lambda: sfx_wind(rng),
        lambda: sfx_engine(),
        lambda: sfx_glass(rng),
        lambda: sfx_laser(),
    ]
    parts: list[np.ndarray] = []
    total = 0
    while total < target_s * SR:
        s = makers[int(rng.integers(len(makers)))]()
        s = scale_to_rms(s, level_dbfs + float(rng.uniform(-6, 4)), ) if active_rms_dbfs(s) > -90 else s
        gap = np.zeros(int(rng.uniform(0.5, 2.5) * SR), np.float32)
        parts.extend([s, gap])
        total += len(s) + len(gap)
    return np.concatenate(parts)[: int(target_s * SR)]


def mix_at(speech: np.ndarray, background: np.ndarray, speech_dbfs: float, bg_dbfs: float) -> np.ndarray:
    """Mezcla: voz a `speech_dbfs` (RMS activo) y fondo a `bg_dbfs` (RMS global), recortada a la voz."""
    bg = background[: len(speech)]
    if len(bg) < len(speech):
        bg = np.pad(bg, (0, len(speech) - len(bg)))
    sp = scale_to_rms(speech, speech_dbfs)
    cur = 10 * np.log10(np.mean(bg.astype(np.float64) ** 2) + 1e-12)
    bg = bg * 10 ** ((bg_dbfs - cur) / 20)
    return (sp + bg).astype(np.float32)
