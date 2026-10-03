"""ASR por segmento con SenseVoice-Small: `SenseVoiceSegmentAsr`, que implementa `AsrEngine` (ADR-0013, R2).

Se usa para el coreano. El japonés pasó a Parakeet-ja (`asr/parakeet_ja.py`) en la validación de la 002: con
anime real, SenseVoice confundía homófonos y perdía negaciones (la alternativa prevista en R2).

SenseVoice-Small 2024-07-17 (int8, 163 MB) sobre sherpa-onnx `OfflineRecognizer`, en CPU, con el idioma
fijado (`ja` o `ko`) y la normalización inversa de texto (`use_itn=True`: puntuación y cifras). Licencia:
FunASR Model License v1.1 (atribución y conservar el nombre; ver research.md R9). Se porta de
`OfflinePipeline` en `spikes/idiomas/idiomas/asr.py` (S5: CER del 8,32 % en ja y del 7,14 % en ko; final
p50/p95 de 0,88/1,39 s en ja y 0,91/1,23 s en ko).

La lógica por segmento (acumular, `flush()`, corte forzado) está en `asr/segment.py` (`SegmentAsr`).

El reconocedor se puede inyectar (`recognizer=`): vale cualquier objeto con `create_stream()` y
`decode_stream(stream)`, donde el stream tiene `accept_waveform(rate, samples)` y `result.text`. Como el
idioma se fija al crear el reconocedor, uno cargado por `create_recognizer(language)` solo sirve a ese
idioma. No es seguro entre hilos.

Ficheros del modelo que espera `create_recognizer` en `component_dir("sensevoice-small")`: `MODEL_FILES`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from instanttraductor.asr.segment import (
    CUT_FRAME_S,
    CUT_WINDOW_S,
    DEFAULT_MAX_SEGMENT_S,
    SILENCE_PEAK,
    Recognizer,
    SegmentAsr,
    quietest_cut,
)
from instanttraductor.config import AppPaths
from instanttraductor.contracts import Clock, EngineError

__all__ = [
    "COMPONENT_ID",
    "CUT_FRAME_S",
    "CUT_WINDOW_S",
    "DEFAULT_MAX_SEGMENT_S",
    "MODEL_FILES",
    "SILENCE_PEAK",
    "SUPPORTED_LANGUAGES",
    "Recognizer",
    "SenseVoiceSegmentAsr",
    "create_recognizer",
    "default_model_dir",
    "engine_name",
    "quietest_cut",
]

COMPONENT_ID: Final = "sensevoice-small"
SUPPORTED_LANGUAGES: Final = ("ja", "ko")
MODEL_FILES: Final = ("model.int8.onnx", "tokens.txt")
NUM_THREADS: Final = 2


def default_model_dir() -> Path:
    """Carpeta del componente `sensevoice-small` (= `AppPaths().models / "sensevoice-small"`)."""
    return AppPaths().models / COMPONENT_ID


def engine_name(language: str) -> str:
    return f"sensevoice-small-{language}"


def create_recognizer(
    language: str, model_dir: str | Path | None = None, *, num_threads: int = NUM_THREADS
) -> Recognizer:
    """`OfflineRecognizer` de SenseVoice con el idioma fijado (`ja` o `ko`) y `use_itn=True`.

    Un `EngineError` no recuperable avisa de que faltan ficheros del modelo (`instanttraductor preparar`) o
    de que sherpa no puede cargarlo. `ValueError` si el idioma no es `ja` ni `ko`.
    """
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError(
            f"SenseVoice solo se usa para {', '.join(SUPPORTED_LANGUAGES)}, no para {language!r}."
        )
    base = Path(model_dir) if model_dir is not None else default_model_dir()
    name = engine_name(language)
    missing = [file for file in MODEL_FILES if not (base / file).is_file()]
    if missing:
        raise EngineError(
            f"Faltan ficheros del modelo SenseVoice en {base}: {', '.join(missing)}. "
            "Ejecuta «instanttraductor preparar».",
            engine=name,
            recoverable=False,
        )
    try:
        import sherpa_onnx  # perezoso: carga las DLL de sherpa y de su ONNX Runtime

        return sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(base / "model.int8.onnx"),
            tokens=str(base / "tokens.txt"),
            num_threads=num_threads,
            language=language,
            use_itn=True,
        )
    except Exception as exc:
        raise EngineError(
            f"No se pudo cargar el modelo SenseVoice de {base}: {exc}", engine=name, recoverable=False
        ) from exc


class SenseVoiceSegmentAsr(SegmentAsr):
    """`AsrEngine` por segmento de SenseVoice-Small (ja o ko): acumula y decodifica en `flush()`."""

    def __init__(
        self,
        language: str,
        clock: Clock,
        *,
        recognizer: Recognizer | None = None,
        max_segment_s: float = DEFAULT_MAX_SEGMENT_S,
    ) -> None:
        if language not in SUPPORTED_LANGUAGES:
            raise ValueError(
                f"SenseVoice solo se usa para {', '.join(SUPPORTED_LANGUAGES)}, no para {language!r}."
            )
        if max_segment_s <= 0:
            raise ValueError("max_segment_s debe ser positivo.")
        super().__init__(
            engine_name(language),
            language,
            clock,
            recognizer=recognizer if recognizer is not None else create_recognizer(language),
            max_segment_s=max_segment_s,
        )
