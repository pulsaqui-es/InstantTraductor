"""Transcripción con Whisper-small en CPU.

Solo se usa para (1) obtener el texto de la voz de referencia (ref_text de Qwen3-TTS en modo ICL) y
(2) la comprobación de inteligibilidad de ida y vuelta (WER) de las muestras. No usa la GPU, así que no necesita candado.
"""

from __future__ import annotations

import re
import sys
import unicodedata
from math import gcd
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vozbench as vb  # noqa: E402

_pipe = None


def get_pipe():
    global _pipe
    if _pipe is None:
        import os

        import torch
        from transformers import pipeline

        # Pocos hilos por defecto: otros obreros miden latencias en la misma máquina y la CPU es compartida.
        torch.set_num_threads(int(os.environ.get("VOZ_ASR_HILOS", "4")))
        model_dir = str(vb.models_dir() / "whisper-small")
        _pipe = pipeline("automatic-speech-recognition", model=model_dir, device="cpu", dtype=torch.float32)
    return _pipe


def to_16k(audio: np.ndarray, sr: int) -> np.ndarray:
    if sr == 16000:
        return np.asarray(audio, dtype=np.float32)
    from scipy.signal import resample_poly

    g = gcd(int(sr), 16000)
    return resample_poly(np.asarray(audio, dtype=np.float32), 16000 // g, int(sr) // g).astype(np.float32)


def transcribe(audio: np.ndarray, sr: int, words: bool = False) -> dict:
    """Devuelve {'text': str, 'chunks': [{'text','timestamp':(t0,t1)}...]} (chunks solo con words=True)."""
    pipe = get_pipe()
    a16 = to_16k(audio, sr)
    out = pipe(
        {"raw": a16, "sampling_rate": 16000},
        return_timestamps="word" if words else False,
        generate_kwargs={"language": "es", "task": "transcribe"},
        chunk_length_s=30,
    )
    return out


def normalize_text(t: str) -> list[str]:
    """Minúsculas, sin tildes ni puntuación, para calcular el WER."""
    t = unicodedata.normalize("NFKD", t.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-z0-9ñ ]+", " ", t)
    return t.split()


def wer(ref: str, hyp: str) -> float:
    r, h = normalize_text(ref), normalize_text(hyp)
    if not r:
        return 0.0
    d = np.zeros((len(r) + 1, len(h) + 1), dtype=np.int32)
    d[:, 0] = np.arange(len(r) + 1)
    d[0, :] = np.arange(len(h) + 1)
    for i in range(1, len(r) + 1):
        for j in range(1, len(h) + 1):
            cost = 0 if r[i - 1] == h[j - 1] else 1
            d[i, j] = min(d[i - 1, j] + 1, d[i, j - 1] + 1, d[i - 1, j - 1] + cost)
    return float(d[len(r), len(h)] / len(r))
