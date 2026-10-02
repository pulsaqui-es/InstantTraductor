"""Fábrica de motores de ASR por idioma de origen (ADR-0013, research.md R2).

| Idioma | Motor | Carpeta del modelo (dentro de `models_dir`) |
|---|---|---|
| en | `NemotronStreamingAsr` (`asr/sherpa_streaming.py`, sin cambios) | `nemotron-en` |
| zh | `XAsrZhStreaming` (`asr/xasr_zh.py`) | `x-asr-zh` |
| ja, ko | `SenseVoiceSegmentAsr` (`asr/sensevoice.py`), con el idioma fijado | `sensevoice-small` |

`models_dir` es la carpeta que contiene una subcarpeta por componente (con los ids del manifiesto). Con
`None` se usa la de la app: `AppPaths().models`, que es donde `instanttraductor preparar` instala cada
componente (`component_dir(id)`).

Arranque en dos tiempos: cargar el modelo cuesta unos segundos, así que `load_recognizer(language)` se llama
en el hilo de arranque y el resultado se pasa a `create_asr(..., recognizer=...)`, que entonces no carga
nada. Sin `recognizer`, `create_asr` carga el modelo él mismo. Un reconocedor cargado solo sirve a su idioma.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

from instanttraductor.asr import sensevoice, xasr_zh
from instanttraductor.asr.sherpa_streaming import NemotronStreamingAsr
from instanttraductor.asr.sherpa_streaming import create_recognizer as create_nemotron_recognizer
from instanttraductor.config import AppPaths
from instanttraductor.contracts import AsrEngine, Clock, SourceLanguage

#: Carpeta del modelo de cada idioma dentro de `models_dir` (= los ids del manifiesto).
MODEL_FOLDERS: Final[dict[SourceLanguage, str]] = {
    SourceLanguage.EN: "nemotron-en",
    SourceLanguage.ZH: xasr_zh.COMPONENT_ID,
    SourceLanguage.JA: sensevoice.COMPONENT_ID,
    SourceLanguage.KO: sensevoice.COMPONENT_ID,
}


def _model_dir(language: SourceLanguage, models_dir: str | Path | None) -> Path:
    root = Path(models_dir) if models_dir is not None else AppPaths().models
    return root / MODEL_FOLDERS[language]


def load_recognizer(language: SourceLanguage | str, models_dir: str | Path | None = None) -> Any:
    """Carga el reconocedor de sherpa-onnx del idioma (lento: para el hilo de arranque).

    Devuelve el objeto que espera `recognizer=` del motor correspondiente. Lanza `ValueError` si el idioma no
    es `en`, `ja`, `zh` ni `ko`, y `EngineError` (no recuperable) si faltan ficheros del modelo o no carga.
    """
    lang = SourceLanguage(language)
    directory = _model_dir(lang, models_dir)
    match lang:
        case SourceLanguage.EN:
            return create_nemotron_recognizer(directory)
        case SourceLanguage.ZH:
            return xasr_zh.create_recognizer(directory)
        case _:
            return sensevoice.create_recognizer(lang.value, directory)


def create_asr(
    language: SourceLanguage | str,
    clock: Clock,
    *,
    models_dir: str | Path | None = None,
    max_segment_s: float = sensevoice.DEFAULT_MAX_SEGMENT_S,
    recognizer: Any | None = None,
) -> AsrEngine:
    """Motor de ASR del idioma de origen.

    - `max_segment_s`: tope de habla continua antes del corte forzado; solo lo usan los motores por segmento
      (ja y ko); los de streaming (en, zh) ya emiten parciales y no lo necesitan.
    - `recognizer`: el que devolvió `load_recognizer(language, models_dir)`; si no se da, se carga aquí.
    """
    lang = SourceLanguage(language)
    reco = recognizer if recognizer is not None else load_recognizer(lang, models_dir)
    match lang:
        case SourceLanguage.EN:
            return NemotronStreamingAsr(clock, recognizer=reco)
        case SourceLanguage.ZH:
            return xasr_zh.XAsrZhStreaming(clock, recognizer=reco)
        case _:
            return sensevoice.SenseVoiceSegmentAsr(
                lang.value, clock, recognizer=reco, max_segment_s=max_segment_s
            )
