"""ASR por segmento con un `OfflineRecognizer` de sherpa-onnx: `SegmentAsr`, que implementa `AsrEngine`.

Lo comparten SenseVoice (coreano, `asr/sensevoice.py`) y Parakeet-ja (japonés, `asr/parakeet_ja.py`).
Se porta de `OfflinePipeline` en `spikes/idiomas/idiomas/asr.py` (ADR-0013, research.md R2).

Es un motor **por segmento**: no hay parciales (`capabilities.partials=False`).
- `accept()` solo acumula el habla (no emite nada, salvo en el corte forzado).
- `flush()`, que la sesión llama con `SPEECH_END`, decodifica todo lo acumulado y devuelve un único FINAL.
- **Corte forzado** (R2): con `max_segment_s` segundos de habla continua acumulada, `accept()` cierra el
  segmento y emite su FINAL cortando en la trama de menor energía de los últimos 1,5 s; el resto del audio
  sigue como comienzo del segmento siguiente. Así se cumple el máximo de habla sin traducir sin esperar a
  que el VAD cierre.
- `segment_id` sube de uno en uno y solo se gasta cuando un segmento da un FINAL; `revision` es siempre 0.
- Tiempos en el reloj de audio: `t_start` del primer chunk del segmento y `t_end` hasta donde llega su audio
  (en un corte forzado, hasta el punto de corte). `emitted_at`, del `Clock`.
- Un segmento de silencio digital no se decodifica ni da evento, y un texto de solo puntuación suelta (lo que
  inventa el modelo con un resto de silencio) se descarta.
- `clean_text` (opcional) arregla el texto del modelo antes de emitirlo (Parakeet: quitar `<unk>`).

El reconocedor se inyecta: vale cualquier objeto con `create_stream()` y `decode_stream(stream)`, donde el
stream tiene `accept_waveform(rate, samples)` y `result.text`. No es seguro entre hilos.
"""

from __future__ import annotations

from collections.abc import Callable
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

Samples = npt.NDArray[np.float32]

DEFAULT_MAX_SEGMENT_S: Final = 6.0
CUT_WINDOW_S: Final = 1.5  # el corte forzado busca la trama más silenciosa de los últimos 1,5 s
CUT_FRAME_S: Final = 0.02  # tamaño de la trama de energía del corte forzado
SILENCE_PEAK: Final = 1e-4  # un segmento cuyo pico no llega a esto es silencio digital

_SENTENCE_END = (".", "?", "!", "。", "？", "！", "…")
_CLOSERS = "\"')」』）”’"


class RecognizerResult(Protocol):
    @property
    def text(self) -> str: ...


class RecognizerStream(Protocol):
    def accept_waveform(self, sample_rate: float, waveform: Samples) -> None: ...

    @property
    def result(self) -> RecognizerResult: ...


class Recognizer(Protocol):
    """Lo que `SegmentAsr` usa de `sherpa_onnx.OfflineRecognizer`."""

    def create_stream(self) -> RecognizerStream: ...

    def decode_stream(self, stream: Any) -> None: ...


def quietest_cut(samples: Samples, *, window_s: float = CUT_WINDOW_S, frame_s: float = CUT_FRAME_S) -> int:
    """Índice de muestra por el que cortar: el centro de la trama de menos energía de los últimos `window_s`.

    La búsqueda se limita a la parte final del audio; el resultado queda siempre dentro de `(0, len(samples))`
    (salvo audio de menos de dos tramas, que se corta por la mitad). Con varias tramas igual de silenciosas
    gana la más reciente, para dejar poco audio sin decodificar.
    """
    frame = max(1, round(frame_s * CAPTURE_RATE))
    n = len(samples)
    if n < 2 * frame:
        return max(1, n // 2)
    first = max(0, n - round(window_s * CAPTURE_RATE))
    count = (n - first) // frame
    frames = samples[first : first + count * frame].reshape(count, frame).astype(np.float64)
    energy = np.sum(frames * frames, axis=1)
    # `argmin` sobre la lista invertida da la trama más reciente entre las de energía mínima.
    index = count - 1 - int(np.argmin(energy[::-1]))
    cut = first + index * frame + frame // 2
    return min(max(cut, 1), n - 1)


def _ends_sentence(text: str) -> bool:
    return text.rstrip(_CLOSERS).endswith(_SENTENCE_END)


class SegmentAsr:
    """`AsrEngine` por segmento sobre un reconocedor offline: acumula y decodifica en `flush()`."""

    def __init__(
        self,
        name: str,
        language: str,
        clock: Clock,
        *,
        recognizer: Recognizer,
        max_segment_s: float = DEFAULT_MAX_SEGMENT_S,
        punctuation: bool = True,
        clean_text: Callable[[str], str] | None = None,
    ) -> None:
        if max_segment_s <= 0:
            raise ValueError("max_segment_s debe ser positivo.")
        self._language = language
        self._clock = clock
        self._max_segment_s = max_segment_s
        self._clean_text = clean_text
        self.name = name
        self.capabilities = AsrCapabilities(
            native_streaming=False,
            partials=False,
            punctuation=punctuation,
            word_timestamps=False,
            languages=frozenset({language}),
            device="cpu",
            est_vram_mb=0,
        )
        self._recognizer: Recognizer | None = recognizer
        self._next_segment_id = 0  # sube en toda la sesión: `reset()` no lo reinicia
        self._parts: list[Samples] = []
        self._samples = 0  # muestras acumuladas del segmento en curso
        self._t_start = 0.0

    @property
    def max_segment_s(self) -> float:
        return self._max_segment_s

    def accept(self, chunk: AudioChunk) -> list[AsrEvent]:
        """Acumula el audio. Devuelve un FINAL solo si se alcanza `max_segment_s` (corte forzado)."""
        if self._recognizer is None:  # cerrado
            return []
        if chunk.sample_rate != CAPTURE_RATE:
            raise ValueError(
                f"{self.name} trabaja a {CAPTURE_RATE} Hz y el chunk llega a {chunk.sample_rate} Hz."
            )
        if len(chunk.samples) == 0:
            return []
        if not self._parts:
            self._t_start = chunk.t_start
        self._parts.append(chunk.samples)
        self._samples += len(chunk.samples)
        events: list[AsrEvent] = []
        limit = round(self._max_segment_s * CAPTURE_RATE)
        while self._samples >= limit:
            audio = np.concatenate(self._parts)
            cut = quietest_cut(audio)
            head, rest = audio[:cut], audio[cut:]
            t_cut = self._t_start + cut / CAPTURE_RATE
            events.extend(self._final(head, self._t_start, t_cut))
            self._parts = [rest] if len(rest) else []
            self._samples = len(rest)
            self._t_start = t_cut
        return events

    def flush(self) -> list[AsrEvent]:
        """Decodifica lo acumulado y devuelve su FINAL (si hubo texto); deja el motor listo para otro."""
        if self._recognizer is None or not self._parts:
            return []
        audio = np.concatenate(self._parts)
        t_start, t_end = self._t_start, self._t_start + len(audio) / CAPTURE_RATE
        self._clear_segment()
        return self._final(audio, t_start, t_end)

    def reset(self) -> None:
        """Descarta el segmento en curso sin emitir nada."""
        self._clear_segment()

    def close(self) -> None:
        """Suelta el reconocedor. Idempotente; después, `accept` y `flush` no devuelven nada."""
        self._clear_segment()
        self._recognizer = None

    def _final(self, audio: Samples, t_start: float, t_end: float) -> list[AsrEvent]:
        """Decodifica `audio` y devuelve su FINAL, o nada si es silencio o el reconocedor no dice nada."""
        recognizer = self._recognizer
        if recognizer is None or len(audio) == 0 or float(np.max(np.abs(audio))) < SILENCE_PEAK:
            return []
        try:
            stream = recognizer.create_stream()
            stream.accept_waveform(CAPTURE_RATE, audio)
            recognizer.decode_stream(stream)
            text = stream.result.text.strip()
        except Exception as exc:
            self._clear_segment()
            raise EngineError(
                f"El reconocedor de voz falló: {exc}", engine=self.name, recoverable=True
            ) from exc
        if self._clean_text is not None:
            text = self._clean_text(text).strip()
        if not any(char.isalnum() for char in text):
            return []  # sin texto, o solo puntuación suelta (lo que inventa con un resto de silencio)
        event = AsrEvent(
            kind=AsrEventKind.FINAL,
            segment_id=self._next_segment_id,
            revision=0,
            text=text,
            stable_len=len(text),
            t_start=t_start,
            t_end=t_end,
            is_sentence_end=_ends_sentence(text),
            emitted_at=self._clock.now(),
            language=self._language,
        )
        self._next_segment_id += 1
        return [event]

    def _clear_segment(self) -> None:
        self._parts = []
        self._samples = 0
        self._t_start = 0.0
