"""Dobles de escucha: `FakeVad` (por energía) y `FakeAsrEngine` (guion de eventos por tiempo)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from instanttraductor.contracts import (
    AsrCapabilities,
    AsrEvent,
    AsrEventKind,
    AudioChunk,
    Clock,
    VadEvent,
    VadEventKind,
    Word,
)
from instanttraductor.pipeline.clock import ManualClock

_ENERGY_THRESHOLD = 0.01  # RMS: unos -40 dBFS; el habla con AGC ronda 0,1 y el silencio digital es 0


def rms(samples: npt.NDArray[np.float32]) -> float:
    """Energía (valor eficaz) de un array de audio; 0.0 si está vacío."""
    if len(samples) == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))


class FakeVad:
    """`Vad` por energía: un chunk con RMS ≥ `threshold` es voz.

    - `SPEECH_START` en el `t_start` del primer chunk con voz.
    - `SPEECH_END` cuando acumula `min_silence_s` de silencio tras la voz, con `t` = fin del último chunk
      con voz (el instante en que acabó el habla, no el de la confirmación).
    - Clasifica cada chunk entero: úsalo con chunks de 20 ms (los de `FakeAudioSource`).
    """

    def __init__(self, *, threshold: float = _ENERGY_THRESHOLD, min_silence_s: float = 0.5) -> None:
        self._threshold = threshold
        self._min_silence_s = min_silence_s
        self._in_speech = False
        self._last_speech_end = 0.0

    def accept(self, chunk: AudioChunk) -> list[VadEvent]:
        if rms(chunk.samples) >= self._threshold:
            events = []
            if not self._in_speech:
                self._in_speech = True
                events.append(VadEvent(VadEventKind.SPEECH_START, chunk.t_start))
            self._last_speech_end = chunk.t_end
            return events
        if self._in_speech and chunk.t_end - self._last_speech_end >= self._min_silence_s - 1e-9:
            self._in_speech = False
            return [VadEvent(VadEventKind.SPEECH_END, self._last_speech_end)]
        return []

    @property
    def in_speech(self) -> bool:
        return self._in_speech

    def reset(self) -> None:
        self._in_speech = False
        self._last_speech_end = 0.0


@dataclass(frozen=True, slots=True)
class ScriptedAsrEvent:
    """Una entrada del guion de `FakeAsrEngine`: qué evento emite cuando el audio alcanza `at`.

    El motor rellena `segment_id`, `revision` y `emitted_at`. Si `stable_len` es None, un PARTIAL es
    estable hasta la última palabra completa y un FINAL, entero.
    """

    at: float  # reloj de audio: se emite en el primer chunk cuyo `t_end` llega a este instante
    kind: AsrEventKind
    text: str
    t_start: float
    t_end: float
    stable_len: int | None = None
    is_sentence_end: bool = False
    language: str = "en"
    words: tuple[Word, ...] = ()


def scripted_utterance(
    text: str,
    *,
    t_start: float,
    t_end: float,
    final_delay_s: float = 0.7,
    is_sentence_end: bool = False,
    language: str = "en",
) -> list[ScriptedAsrEvent]:
    """Guion de un enunciado, como lo emitiría un motor en streaming.

    Un PARTIAL por palabra, repartidos de forma uniforme entre `t_start` y `t_end` (cada uno estable hasta
    la última palabra completa), y el FINAL `final_delay_s` después de `t_end`. Con las pausas de 0,8 s del
    diálogo de pruebas, el FINAL de un enunciado llega antes de que empiece el siguiente.
    """
    words = text.split()
    if not words:
        raise ValueError("El texto del enunciado no puede estar vacío.")
    entries = []
    for count in range(1, len(words) + 1):
        at = t_start + (t_end - t_start) * count / len(words)
        entries.append(
            ScriptedAsrEvent(
                at=at,
                kind=AsrEventKind.PARTIAL,
                text=" ".join(words[:count]),
                t_start=t_start,
                t_end=at,
                stable_len=len(" ".join(words[: count - 1])),
                language=language,
            )
        )
    entries.append(
        ScriptedAsrEvent(
            at=t_end + final_delay_s,
            kind=AsrEventKind.FINAL,
            text=" ".join(words),
            t_start=t_start,
            t_end=t_end,
            is_sentence_end=is_sentence_end,
            language=language,
        )
    )
    return entries


class FakeAsrEngine:
    """`AsrEngine` que reproduce un guion de eventos según avanza el audio.

    - `script`: entradas ordenadas por `at` (reloj de audio). `accept(chunk)` emite, en orden, todas las
      entradas con `at <= chunk.t_end`. Los eventos de un segmento son los que hay hasta su FINAL.
    - Asigna él mismo `segment_id` (creciente en toda la sesión), `revision` (+1 por evento del mismo
      segmento) y `emitted_at` (con `clock`; por defecto un `ManualClock` propio).
    - No emite nada hasta que oye energía (RMS ≥ `energy_threshold`) en algún chunk: un reconocedor no
      puede transcribir silencio absoluto. Desde entonces, el guion corre por tiempo de audio.
    - `flush()` cierra el segmento en curso con un FINAL (su último texto, `stable_len = len(text)`) y
      descarta lo que quedaba de ese segmento en el guion; sin segmento en curso devuelve `[]`.
    - `reset()` descarta el segmento en curso sin emitir nada y vuelve a esperar a oír voz.
    - `close()` es idempotente; después, `accept` y `flush` devuelven `[]`.
    """

    name = "fake-asr"
    capabilities = AsrCapabilities(
        native_streaming=True,
        partials=True,
        punctuation=True,
        word_timestamps=False,
        languages=frozenset({"en"}),
        device="cpu",
        est_vram_mb=0,
    )

    def __init__(
        self,
        script: Sequence[ScriptedAsrEvent] = (),
        *,
        clock: Clock | None = None,
        energy_threshold: float = _ENERGY_THRESHOLD,
    ) -> None:
        entries = list(script)
        if any(later.at < earlier.at for earlier, later in zip(entries, entries[1:], strict=False)):
            raise ValueError("El guion debe estar en orden creciente de `at`.")
        self._script = entries
        self._clock: Clock = clock if clock is not None else ManualClock()
        self._energy_threshold = energy_threshold
        self._pos = 0  # siguiente entrada del guion
        self._segment_id = -1  # último segmento abierto
        self._revision = -1
        self._open: AsrEvent | None = None  # último evento del segmento en curso (PARTIAL)
        self._heard = False
        self._closed = False

    def accept(self, chunk: AudioChunk) -> list[AsrEvent]:
        if self._closed:
            return []
        if not self._heard and rms(chunk.samples) >= self._energy_threshold:
            self._heard = True
        if not self._heard:
            return []
        events = []
        while self._pos < len(self._script) and self._script[self._pos].at <= chunk.t_end + 1e-9:
            events.append(self._emit(self._script[self._pos]))
            self._pos += 1
        return events

    def flush(self) -> list[AsrEvent]:
        if self._closed or self._open is None:
            return []
        last = self._open
        self._revision += 1
        final = AsrEvent(
            kind=AsrEventKind.FINAL,
            segment_id=last.segment_id,
            revision=self._revision,
            text=last.text,
            stable_len=len(last.text),
            t_start=last.t_start,
            t_end=last.t_end,
            is_sentence_end=last.is_sentence_end,
            emitted_at=self._clock.now(),
            language=last.language,
            words=last.words,
        )
        self._open = None
        self._skip_rest_of_segment()
        return [final]

    def reset(self) -> None:
        if self._open is not None:
            self._open = None
            self._skip_rest_of_segment()
        self._heard = False

    def close(self) -> None:
        self._closed = True

    def _emit(self, entry: ScriptedAsrEvent) -> AsrEvent:
        if self._open is None:  # empieza un segmento nuevo
            self._segment_id += 1
            self._revision = -1
        self._revision += 1
        is_final = entry.kind is AsrEventKind.FINAL
        if is_final:
            stable_len = len(entry.text)
        elif entry.stable_len is not None:
            stable_len = entry.stable_len
        else:
            stable_len = len(entry.text.rsplit(" ", 1)[0]) if " " in entry.text else 0
        event = AsrEvent(
            kind=entry.kind,
            segment_id=self._segment_id,
            revision=self._revision,
            text=entry.text,
            stable_len=stable_len,
            t_start=entry.t_start,
            t_end=entry.t_end,
            is_sentence_end=entry.is_sentence_end,
            emitted_at=self._clock.now(),
            language=entry.language,
            words=entry.words,
        )
        self._open = None if is_final else event
        return event

    def _skip_rest_of_segment(self) -> None:
        """Salta lo que queda del segmento cerrado: hasta su FINAL, incluido."""
        while self._pos < len(self._script):
            kind = self._script[self._pos].kind
            self._pos += 1
            if kind is AsrEventKind.FINAL:
                return
