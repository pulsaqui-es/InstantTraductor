"""Guardado y lectura de los eventos crudos de una ejecución (JSON comprimido).

Con los eventos guardados se puede repetir el análisis (``reanalyze.py``) sin repetir una medición
en tiempo real de varios minutos.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

from . import paths


def events_path(label: str) -> Path:
    return paths.RESULTS_DIR / "events" / f"{label}.events.json.gz"


def save_events(label: str, events: list[dict]) -> Path:
    dest = events_path(label)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(dest, "wt", encoding="utf-8") as fh:
        json.dump(events, fh, ensure_ascii=False, default=float)
    return dest


def load_events(label: str) -> list[dict]:
    with gzip.open(events_path(label), "rt", encoding="utf-8") as fh:
        return json.load(fh)
