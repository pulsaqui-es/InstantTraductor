"""Contratos de síntesis de voz."""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal, Protocol

import numpy as np
import numpy.typing as npt


@dataclass(frozen=True, slots=True)
class VoiceRef:
    voice_id: str


@dataclass(frozen=True, slots=True)
class VoiceInfo:
    voice_id: str
    name: str
    gender: Literal["f", "m"]
    source: str
    license: str


@dataclass(frozen=True, slots=True)
class SynthesisRequest:
    unit_id: int
    text: str
    voice: VoiceRef
    speed: float = 1.0  # 1.0–1.5; si el motor no lo soporta, el núcleo aplica time-stretch


@dataclass(frozen=True, slots=True, eq=False)
class SynthesizedChunk:
    """Trozo de voz sintetizada. `eq=False`: lleva un array de audio."""

    unit_id: int
    samples: npt.NDArray[np.float32]  # mono, a `sample_rate` del motor
    sample_rate: int
    is_last: bool


class Synthesizer(Protocol):
    name: str
    sample_rate: int
    supports_speed: bool

    def synthesize(self, request: SynthesisRequest) -> Iterator[SynthesizedChunk]:
        """Síntesis en streaming. Lanza `EngineError` si falla."""
        ...

    def list_voices(self) -> tuple[VoiceInfo, ...]: ...

    def close(self) -> None: ...
