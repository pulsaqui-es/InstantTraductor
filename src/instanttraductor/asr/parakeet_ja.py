"""ASR por segmento para japonés con Parakeet-ja: `ParakeetJaSegmentAsr`, que implementa `AsrEngine`.

NVIDIA `parakeet-tdt_ctc-0.6b-ja` (cabeza CTC, int8, 656 MB) exportado por sherpa-onnx, sobre
`OfflineRecognizer.from_nemo_ctc`, en CPU. Licencia: CC-BY-4.0 (atribución). Es la alternativa del japonés que
preveía research.md R2 (S5: CER del 5,31 % frente al 8,32 % de SenseVoice; final p95 de 2,0 s y 3,35 s con la
CPU cargada). Sustituye a SenseVoice en el japonés tras la validación de la 002 con anime real: SenseVoice
confundía homófonos (勝算 → 称賛, 醜態 → 醜体) y perdía negaciones (手を出すな → 手を出す).

La lógica por segmento es la de `SegmentAsr` (`asr/segment.py`). Parakeet apenas puntúa
(`punctuation=False`) y escribe `<unk>` donde le falta un kanji del vocabulario: se quita antes de emitir.

Ficheros del modelo que espera `create_recognizer` en `component_dir("parakeet-ja")`: `MODEL_FILES`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from instanttraductor.asr.segment import DEFAULT_MAX_SEGMENT_S, Recognizer, SegmentAsr
from instanttraductor.config import AppPaths
from instanttraductor.contracts import Clock, EngineError

COMPONENT_ID: Final = "parakeet-ja"
ENGINE_NAME: Final = "parakeet-ja"
LANGUAGE: Final = "ja"
MODEL_FILES: Final = ("model.int8.onnx", "tokens.txt")
NUM_THREADS: Final = 2
UNKNOWN_TOKEN: Final = "<unk>"


def default_model_dir() -> Path:
    """Carpeta del componente `parakeet-ja` (= `AppPaths().models / "parakeet-ja"`)."""
    return AppPaths().models / COMPONENT_ID


def clean_text(text: str) -> str:
    """Quita los `<unk>` que deja Parakeet donde le falta un carácter del vocabulario."""
    return text.replace(UNKNOWN_TOKEN, "")


def create_recognizer(model_dir: str | Path | None = None, *, num_threads: int = NUM_THREADS) -> Recognizer:
    """`OfflineRecognizer` CTC de Parakeet-ja.

    Un `EngineError` no recuperable avisa de que faltan ficheros del modelo (`instanttraductor preparar`) o
    de que sherpa no puede cargarlo.
    """
    base = Path(model_dir) if model_dir is not None else default_model_dir()
    missing = [file for file in MODEL_FILES if not (base / file).is_file()]
    if missing:
        raise EngineError(
            f"Faltan ficheros del modelo Parakeet-ja en {base}: {', '.join(missing)}. "
            "Ejecuta «instanttraductor preparar».",
            engine=ENGINE_NAME,
            recoverable=False,
        )
    try:
        import sherpa_onnx  # perezoso: carga las DLL de sherpa y de su ONNX Runtime

        return sherpa_onnx.OfflineRecognizer.from_nemo_ctc(
            model=str(base / "model.int8.onnx"), tokens=str(base / "tokens.txt"), num_threads=num_threads
        )
    except Exception as exc:
        raise EngineError(
            f"No se pudo cargar el modelo Parakeet-ja de {base}: {exc}", engine=ENGINE_NAME, recoverable=False
        ) from exc


class ParakeetJaSegmentAsr(SegmentAsr):
    """`AsrEngine` por segmento de Parakeet-ja: acumula y decodifica en `flush()`."""

    def __init__(
        self,
        clock: Clock,
        *,
        recognizer: Recognizer | None = None,
        max_segment_s: float = DEFAULT_MAX_SEGMENT_S,
    ) -> None:
        if max_segment_s <= 0:
            raise ValueError("max_segment_s debe ser positivo.")
        super().__init__(
            ENGINE_NAME,
            LANGUAGE,
            clock,
            recognizer=recognizer if recognizer is not None else create_recognizer(),
            max_segment_s=max_segment_s,
            punctuation=False,
            clean_text=clean_text,
        )
