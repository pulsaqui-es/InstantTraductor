"""ASR en streaming: `NemotronStreamingAsr`, que implementa `AsrEngine` (research.md R5).

NVIDIA Nemotron Speech Streaming EN 0.6B (int8) sobre sherpa-onnx, en CPU. Se porta la parte del reconocedor
de `spikes/asr/asrspike/engine_a.py`: la puerta de VAD y el relleno previo son de la sesión, no del motor.

Cómo lo usa la sesión (el contrato `AsrEngine` no sabe nada del VAD):
- Alimenta `accept()` solo con audio de habla: desde `SPEECH_START.t` (que ya lleva el relleno previo de
  `SileroVad`) y hasta que llega `SPEECH_END`, incluido el silencio que lo confirma.
- Con `SPEECH_END` llama a `flush()`, que cierra el segmento con su FINAL.
- Un **stream nuevo por tramo**: el primer `accept()` tras `flush()`, `reset()` o el arranque abre un *stream*
  limpio. No se usa el *endpoint* nativo de sherpa (WER del 11,3 % frente al 5 % con VAD y vaciado).

Parámetros (R5): exportación de 560 ms (el trozo lo fija el modelo; el reconocedor decodifica cada 560 ms de
audio acumulado, así que sale un PARTIAL por trozo con el texto nuevo), 2 hilos, `blank_penalty` 1.

Eventos:
- PARTIAL cuando el texto cambia, con `revision` 0, 1, 2... (+1 por evento del segmento). Los parciales de
  Nemotron solo añaden texto (0 retractaciones en 2 811 cambios), pero la última palabra puede estar a medias
  (15-21 % de los casos), así que `stable_len` llega hasta la última palabra completa.
- FINAL en `flush()` si hubo texto: vacía el reconocedor con un trozo de ceros y `input_finished()`.
- `segment_id` sube de uno en uno y solo se gasta cuando el segmento da un evento: el silencio no consume ids.
- Tiempos en el reloj de audio: `t_start` es el del primer chunk del segmento y `t_end`, el del final del
  audio entregado hasta ese momento (sin tiempos por palabra, `words` queda vacío). `emitted_at`, del `Clock`.

El reconocedor de sherpa se puede inyectar (`recognizer=`): vale cualquier objeto con `create_stream`,
`is_ready`, `decode_stream` y `get_result_all`. Los tests unitarios usan uno falso. No es seguro entre hilos.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final, Protocol

import numpy as np
import numpy.typing as npt

from instanttraductor.contracts import (
    CAPTURE_RATE,
    AsrCapabilities,
    AsrEvent,
    AsrEventKind,
    AudioChunk,
    Clock,
    EngineError,
)
from instanttraductor.setup.manifest import component_dir

Samples = npt.NDArray[np.float32]

ENGINE_NAME: Final = "nemotron-streaming-en"
MODEL_FILES: Final = ("tokens.txt", "encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx")
CHUNK_S: Final = 0.56  # trozo del modelo: la exportación de 560 ms
TAIL_PADDING_S: Final = CHUNK_S  # ceros que se añaden al vaciar: un trozo del modelo
NUM_THREADS: Final = 2
BLANK_PENALTY: Final = 1.0  # con 0 no hay comas; con 1, 3,5 por 100 palabras y el mejor WER (R5)
FEATURE_DIM: Final = 128


class RecognizerResult(Protocol):
    @property
    def text(self) -> str: ...


class RecognizerStream(Protocol):
    def accept_waveform(self, sample_rate: float, waveform: Samples) -> None: ...

    def input_finished(self) -> None: ...


class Recognizer(Protocol):
    """Lo que `NemotronStreamingAsr` usa de `sherpa_onnx.OnlineRecognizer`."""

    def create_stream(self) -> RecognizerStream: ...

    def is_ready(self, stream: Any) -> bool: ...

    def decode_stream(self, stream: Any) -> None: ...

    def get_result_all(self, stream: Any) -> RecognizerResult: ...


def create_recognizer(
    model_dir: str | Path | None = None,
    *,
    num_threads: int = NUM_THREADS,
    blank_penalty: float = BLANK_PENALTY,
) -> Recognizer:
    """`OnlineRecognizer` de sherpa-onnx con el Nemotron int8 de `component_dir("nemotron-en")`.

    Un `EngineError` no recuperable avisa de que faltan ficheros del modelo (`instanttraductor preparar`) o
    de que sherpa no puede cargarlo. Un reconocedor se puede compartir entre motores: cada uno crea sus
    *streams*.
    """
    base = Path(model_dir) if model_dir is not None else component_dir("nemotron-en")
    missing = [name for name in MODEL_FILES if not (base / name).is_file()]
    if missing:
        raise EngineError(
            f"Faltan ficheros del modelo Nemotron en {base}: {', '.join(missing)}. "
            "Ejecuta «instanttraductor preparar».",
            engine=ENGINE_NAME,
            recoverable=False,
        )
    try:
        import sherpa_onnx  # perezoso: carga las DLL de sherpa y de su ONNX Runtime

        return sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=str(base / "tokens.txt"),
            encoder=str(base / "encoder.int8.onnx"),
            decoder=str(base / "decoder.int8.onnx"),
            joiner=str(base / "joiner.int8.onnx"),
            num_threads=num_threads,
            sample_rate=CAPTURE_RATE,
            feature_dim=FEATURE_DIM,
            decoding_method="greedy_search",
            blank_penalty=blank_penalty,
            enable_endpoint_detection=False,  # el fin de segmento lo decide el VAD (R5)
        )
    except Exception as exc:
        raise EngineError(
            f"No se pudo cargar el modelo Nemotron de {base}: {exc}", engine=ENGINE_NAME, recoverable=False
        ) from exc


def stable_length(text: str) -> int:
    """Caracteres de `text` que ya no cambiarán: hasta la última palabra completa.

    La última palabra de un parcial puede estar a medias (`squal` → `squalid`); las anteriores, no.
    """
    head, separator, _last = text.rpartition(" ")
    return len(head) if separator else 0


def _ends_sentence(text: str) -> bool:
    return text.rstrip("\"')").endswith((".", "?", "!"))


class NemotronStreamingAsr:
    """`AsrEngine` de Nemotron Streaming EN: un segmento por tramo de habla, con parciales y su FINAL."""

    name = ENGINE_NAME
    capabilities = AsrCapabilities(
        native_streaming=True,
        partials=True,
        punctuation=True,
        word_timestamps=False,
        languages=frozenset({"en"}),
        device="cpu",
        est_vram_mb=0,
    )

    def __init__(self, clock: Clock, *, recognizer: Recognizer | None = None) -> None:
        self._clock = clock
        self._recognizer: Recognizer | None = recognizer if recognizer is not None else create_recognizer()
        self._next_segment_id = 0  # sube en toda la sesión: `reset()` no lo reinicia
        self._stream: RecognizerStream | None = None
        self._segment_id: int | None = None  # se asigna con el primer evento del segmento
        self._revision = 0
        self._t_start = 0.0
        self._audio_end = 0.0
        self._last_text = ""
        self._stable_len = 0

    def accept(self, chunk: AudioChunk) -> list[AsrEvent]:
        """Entrega el audio al reconocedor y devuelve el PARTIAL si el texto ha cambiado."""
        recognizer = self._recognizer
        if recognizer is None:  # cerrado
            return []
        if chunk.sample_rate != CAPTURE_RATE:
            raise ValueError(
                f"{ENGINE_NAME} trabaja a {CAPTURE_RATE} Hz y el chunk llega a {chunk.sample_rate} Hz."
            )
        if len(chunk.samples) == 0:
            return []
        try:
            if self._stream is None:  # un stream nuevo por tramo
                self._stream = recognizer.create_stream()
                self._t_start = chunk.t_start
            self._stream.accept_waveform(CAPTURE_RATE, chunk.samples)
            self._audio_end = chunk.t_end
            if not self._decode_ready(recognizer, self._stream):
                return []  # sin trozo nuevo que decodificar, el texto no puede haber cambiado
            text = recognizer.get_result_all(self._stream).text.strip()
        except Exception as exc:
            self._clear_segment()
            raise EngineError(
                f"El reconocedor de voz falló: {exc}", engine=ENGINE_NAME, recoverable=True
            ) from exc
        if not text or text == self._last_text:
            return []
        self._last_text = text
        self._stable_len = min(max(self._stable_len, stable_length(text)), len(text))
        return [self._event(AsrEventKind.PARTIAL, text, self._stable_len)]

    def flush(self) -> list[AsrEvent]:
        """Cierra el segmento en curso con su FINAL (si hubo texto) y deja el motor listo para otro."""
        recognizer = self._recognizer
        stream = self._stream
        if recognizer is None or stream is None:
            return []
        try:
            # Un trozo de ceros y `input_finished()` hacen que el modelo decodifique lo que le queda.
            stream.accept_waveform(CAPTURE_RATE, np.zeros(round(TAIL_PADDING_S * CAPTURE_RATE), np.float32))
            stream.input_finished()
            self._decode_ready(recognizer, stream)
            text = recognizer.get_result_all(stream).text.strip()
        except Exception as exc:
            self._clear_segment()
            raise EngineError(
                f"El reconocedor de voz falló al vaciar: {exc}", engine=ENGINE_NAME, recoverable=True
            ) from exc
        text = (
            text or self._last_text
        )  # el vaciado solo añade texto; si no devolviera nada, se conserva lo dicho
        events = [self._event(AsrEventKind.FINAL, text, len(text))] if text else []
        self._clear_segment()
        return events

    def reset(self) -> None:
        """Descarta el segmento en curso sin emitir nada."""
        self._clear_segment()

    def close(self) -> None:
        """Suelta el reconocedor. Idempotente; después, `accept` y `flush` no devuelven nada."""
        self._clear_segment()
        self._recognizer = None

    @staticmethod
    def _decode_ready(recognizer: Recognizer, stream: RecognizerStream) -> bool:
        decoded = False
        while recognizer.is_ready(stream):
            recognizer.decode_stream(stream)
            decoded = True
        return decoded

    def _event(self, kind: AsrEventKind, text: str, stable_len: int) -> AsrEvent:
        if self._segment_id is None:
            self._segment_id = self._next_segment_id
            self._next_segment_id += 1
        event = AsrEvent(
            kind=kind,
            segment_id=self._segment_id,
            revision=self._revision,
            text=text,
            stable_len=stable_len,
            t_start=self._t_start,
            t_end=self._audio_end,
            is_sentence_end=_ends_sentence(text),
            emitted_at=self._clock.now(),
        )
        self._revision += 1
        return event

    def _clear_segment(self) -> None:
        self._stream = None
        self._segment_id = None
        self._revision = 0
        self._t_start = 0.0
        self._audio_end = 0.0
        self._last_text = ""
        self._stable_len = 0
