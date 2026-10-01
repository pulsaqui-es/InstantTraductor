"""Rutas del spike. Modelos y audio viven siempre FUERA del repositorio.

- Modelos: ``%LOCALAPPDATA%\\InstantTraductor\\models\\``
- Corpus derivado (WAV montados): ``%LOCALAPPDATA%\\InstantTraductor\\spikes\\asr\\corpus\\``
- Candado de GPU compartido con otros obreros: ``%LOCALAPPDATA%\\InstantTraductor\\gpu.lock``
- Resultados (JSON y tablas pequeñas, sí versionables): ``spikes/asr/results/``
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

#: Carpeta del spike (la que contiene ``pyproject.toml``).
SPIKE_DIR = Path(__file__).resolve().parent.parent

#: Resultados de las mediciones (texto pequeño, dentro del repo).
RESULTS_DIR = SPIKE_DIR / "results"


def app_home() -> Path:
    """Carpeta de datos de InstantTraductor (se crea si no existe)."""
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / ".local" / "share"
    home = root / "InstantTraductor"
    home.mkdir(parents=True, exist_ok=True)
    return home


def models_dir() -> Path:
    path = app_home() / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def corpus_dir() -> Path:
    path = app_home() / "spikes" / "asr" / "corpus"
    path.mkdir(parents=True, exist_ok=True)
    return path


def gpu_lock_path() -> Path:
    return app_home() / "gpu.lock"


# Nombres de carpeta de los modelos dentro de ``models_dir()``.
def nemotron_dir(chunk_ms: int) -> Path:
    """Exportación int8 de Nemotron para sherpa-onnx con el trozo indicado."""
    return models_dir() / f"sherpa-onnx-nemotron-speech-streaming-en-0.6b-{chunk_ms}ms-int8-2026-04-25"


def silero_model_path() -> Path:
    return models_dir() / "silero-vad-6.2.3" / "silero_vad.onnx"


def whisper_turbo_dir() -> Path:
    return models_dir() / "faster-whisper-large-v3-turbo"


def punct_dir() -> Path:
    """Modelo opcional de restauración de puntuación (sherpa-onnx, inglés)."""
    return models_dir() / "sherpa-onnx-online-punct-en-2024-08-06"


@contextlib.contextmanager
def gpu_lock(timeout_s: float = 30 * 60):
    """Candado de fichero para TODA medición en GPU (otros obreros comparten la tarjeta).

    Espera hasta ``timeout_s`` (30 min por defecto) y se suelta al salir del bloque.
    """
    from filelock import FileLock

    lock = FileLock(str(gpu_lock_path()), timeout=timeout_s)
    lock.acquire()
    try:
        yield lock
    finally:
        lock.release()
