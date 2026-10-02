"""Rutas y utilidades comunes del spike S7 (habla baja y «vosotros»).

Audio, modelos y cachés viven FUERA del repo: `%LOCALAPPDATA%\\InstantTraductor\\spikes\\habla_baja\\`.
"""

from __future__ import annotations

import math
import os
from pathlib import Path

import numpy as np
import soundfile as sf

APP_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "InstantTraductor"
WORK_DIR = APP_DIR / "spikes" / "habla_baja"
DL_DIR = WORK_DIR / "dl"  # descargas (LibriSpeech test-clean, música)
C2_DIR = WORK_DIR / "c2"  # corpus sintético C2
OUT_DIR = WORK_DIR / "out"  # volcados intermedios (probabilidades de VAD, resultados por clip)
RESULTS_DIR = Path(__file__).parent / "resultados"  # resultados ligeros que sí van al repo
MODELS_DIR = APP_DIR / "models"
SILERO_ONNX = MODELS_DIR / "silero-vad" / "silero_vad.onnx"
NEMOTRON_DIR = MODELS_DIR / "nemotron-en"
SR = 16_000

for _d in (DL_DIR, C2_DIR, OUT_DIR, RESULTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def read_wav(path: str | Path) -> np.ndarray:
    """WAV mono float32 a 16 kHz (si no, error: el corpus se genera ya a 16 kHz)."""
    data, rate = sf.read(str(path), dtype="float32", always_2d=False)
    if data.ndim > 1:
        data = data.mean(axis=1)
    if rate != SR:
        import soxr

        data = soxr.resample(data, rate, SR).astype(np.float32)
    return data


def write_wav(path: str | Path, samples: np.ndarray) -> None:
    sf.write(str(path), np.clip(samples, -1.0, 1.0), SR, subtype="PCM_16")


def rms_dbfs(x: np.ndarray) -> float:
    p = float(np.mean(np.square(x, dtype=np.float64))) if len(x) else 0.0
    return 10 * math.log10(p) if p > 0 else -math.inf


def scale_to_rms(x: np.ndarray, target_dbfs: float) -> np.ndarray:
    """Escala `x` para que su RMS (solo en tramos activos, ver `active_rms_dbfs`) valga `target_dbfs`."""
    cur = active_rms_dbfs(x)
    return (x * 10 ** ((target_dbfs - cur) / 20)).astype(np.float32)


def active_rms_dbfs(x: np.ndarray, frame: int = 320, margin_db: float = 30.0) -> float:
    """RMS (dBFS) de las tramas de 20 ms que están a menos de `margin_db` del pico de energía.

    Mide el nivel del habla sin contar las pausas. Es la referencia de «a -20, -30, -40 dBFS».
    """
    n = len(x) // frame
    if n == 0:
        return rms_dbfs(x)
    fr = x[: n * frame].reshape(n, frame).astype(np.float64)
    e = 10 * np.log10(np.mean(fr**2, axis=1) + 1e-12)
    keep = e > (e.max() - margin_db)
    return float(10 * np.log10(np.mean(fr[keep] ** 2) + 1e-12))
