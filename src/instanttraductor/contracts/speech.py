"""Contratos de escucha: detección de voz (VAD) y reconocimiento de voz (ASR)."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from instanttraductor.contracts.audio import AudioChunk


class VadEventKind(StrEnum):
    SPEECH_START = "speech_start"
    SPEECH_END = "speech_end"


@dataclass(frozen=True, slots=True)
class VadEvent:
    kind: VadEventKind
    t: float  # reloj de audio


class Vad(Protocol):
    def accept(self, chunk: AudioChunk) -> list[VadEvent]: ...

    @property
    def in_speech(self) -> bool: ...

    def reset(self) -> None: ...


class AsrEventKind(StrEnum):
    PARTIAL = "partial"  # hipótesis provisional: puede cambiar después de stable_len
    FINAL = "final"  # texto definitivo del segmento


@dataclass(frozen=True, slots=True)
class Word:
    text: str
    t_start: float  # reloj de audio
    t_end: float


@dataclass(frozen=True, slots=True)
class AsrEvent:
    kind: AsrEventKind
    segment_id: int  # único en la sesión y creciente
    revision: int  # +1 en cada evento del mismo segmento
    text: str  # hipótesis completa del segmento
    stable_len: int  # caracteres de `text` que ya no cambiarán (FINAL: len(text))
    t_start: float  # reloj de audio
    t_end: float
    is_sentence_end: bool  # el texto termina en fin de oración
    emitted_at: float  # reloj de sesión
    language: str = "en"
    words: tuple[Word, ...] = ()  # vacío si el motor no da tiempos por palabra


@dataclass(frozen=True, slots=True)
class AsrCapabilities:
    native_streaming: bool
    partials: bool
    punctuation: bool
    word_timestamps: bool
    languages: frozenset[str]
    device: str  # "cpu" | "cuda"
    est_vram_mb: int


class AsrEngine(Protocol):
    name: str
    capabilities: AsrCapabilities

    def accept(self, chunk: AudioChunk) -> list[AsrEvent]:
        """Procesa el audio y devuelve los eventos nuevos."""
        ...

    def flush(self) -> list[AsrEvent]:
        """Cierra el segmento en curso (→ FINAL si había texto)."""
        ...

    def reset(self) -> None: ...

    def close(self) -> None: ...
