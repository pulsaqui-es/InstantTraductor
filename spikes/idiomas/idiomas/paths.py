"""Rutas del spike S5. Modelos, audio y cachés viven siempre FUERA del repositorio.

- Datos del spike: ``%LOCALAPPDATA%\\InstantTraductor\\spikes\\idiomas\\`` (modelos, corpus, música).
- Silero VAD: el de S3 (``%LOCALAPPDATA%\\InstantTraductor\\models\\silero-vad-6.2.3``).
- Resultados (JSON y tablas pequeñas, sí versionables): ``spikes/idiomas/results/``.
"""

from __future__ import annotations

import os
from pathlib import Path

#: Carpeta del spike (la que contiene ``pyproject.toml``).
SPIKE_DIR = Path(__file__).resolve().parent.parent
RESULTS_DIR = SPIKE_DIR / "results"
#: Textos del corpus (manifiesto con referencias; sin audio), versionable.
CORPUS_MANIFEST = SPIKE_DIR / "corpus_manifest.json"

LANGS = ("ja", "zh", "ko")
#: Código FLEURS de cada idioma.
FLEURS = {"ja": "ja_jp", "zh": "cmn_hans_cn", "ko": "ko_kr", "es": "es_419", "en": "en_us"}


def app_home() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / ".local" / "share"
    home = root / "InstantTraductor"
    home.mkdir(parents=True, exist_ok=True)
    return home


def data_dir() -> Path:
    path = app_home() / "spikes" / "idiomas"
    path.mkdir(parents=True, exist_ok=True)
    return path


def models_dir() -> Path:
    path = data_dir() / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def corpus_dir() -> Path:
    path = data_dir() / "corpus"
    path.mkdir(parents=True, exist_ok=True)
    return path


def music_dir() -> Path:
    path = data_dir() / "music"
    path.mkdir(parents=True, exist_ok=True)
    return path


def silero_model_path() -> Path:
    return app_home() / "models" / "silero-vad-6.2.3" / "silero_vad.onnx"
