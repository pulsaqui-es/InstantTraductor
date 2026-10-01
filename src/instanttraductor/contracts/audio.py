"""Contratos de audio: datos que cruzan etapas y fuentes y destinos de audio.

Audio: `numpy.ndarray` de `float32`, mono, en el rango [-1, 1]. Los arrays de audio no se mutan después
de crearlos. Los tiempos son `float` en segundos.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Protocol

import numpy as np
import numpy.typing as npt

CAPTURE_RATE: Final = 16_000  # Hz, entrada de VAD y ASR
PLAYBACK_RATE: Final = 48_000  # Hz, salida hacia el dispositivo o la pista


@dataclass(frozen=True, slots=True, eq=False)
class AudioChunk:
    """Trozo de audio captado. `eq=False`: comparar arrays con `==` no da un booleano."""

    samples: npt.NDArray[np.float32]  # mono
    sample_rate: int
    t_start: float  # reloj de audio

    @property
    def duration(self) -> float:
        """Duración en segundos: `len(samples) / sample_rate`."""
        return len(self.samples) / self.sample_rate

    @property
    def t_end(self) -> float:
        """Fin del trozo en el reloj de audio: `t_start + duration`."""
        return self.t_start + self.duration


@dataclass(frozen=True, slots=True, eq=False)
class SpeechPiece:
    """Trozo de la voz en español que se entrega al sink. `eq=False`: lleva un array de audio."""

    unit_id: int
    samples: npt.NDArray[np.float32]  # mono, YA a la frecuencia del sink
    is_last: bool  # último trozo de esta unidad


class PlaybackEventKind(StrEnum):
    STARTED = "started"  # primera muestra de la unidad entregada al dispositivo o a la pista
    FINISHED = "finished"  # última muestra entregada
    CANCELLED = "cancelled"  # descartada antes de empezar, o cortada por una parada


@dataclass(frozen=True, slots=True)
class PlaybackEvent:
    unit_id: int
    kind: PlaybackEventKind
    at: float  # reloj de sesión


class AudioSource(Protocol):
    sample_rate: int  # siempre CAPTURE_RATE

    def start(self) -> None: ...

    def read(self, timeout: float) -> AudioChunk | None:
        """Bloquea hasta `timeout` s. Devuelve None si no hay datos.

        Los chunks son contiguos: `chunk[i+1].t_start == chunk[i].t_end`, con los silencios de la
        captura rellenados con ceros.
        """
        ...

    @property
    def exhausted(self) -> bool:
        """True cuando ya no llegarán más datos (fin de fichero o stop)."""
        ...

    def stop(self) -> None:
        """Detiene la fuente. Idempotente."""
        ...


class AudioSink(Protocol):
    sample_rate: int  # siempre PLAYBACK_RATE

    def start(self, on_event: Callable[[PlaybackEvent], None]) -> None: ...

    def enqueue(self, piece: SpeechPiece) -> None:
        """No bloquea. Las unidades suenan en orden FIFO y los trozos de una unidad, contiguos.

        Una unidad empieza a sonar en cuanto llega su primer trozo, si el sink está libre.
        """
        ...

    def cancel_pending(self) -> list[int]:
        """Descarta las unidades que no han empezado; devuelve sus `unit_id`."""
        ...

    def set_volume(self, gain: float) -> None:
        """Volumen de 0.0 a 2.0; solo la voz en español."""
        ...

    def pending_seconds(self) -> float:
        """Audio encolado sin reproducir."""
        ...

    def stop(self) -> None:
        """Corta lo que suena, vacía la cola y emite CANCELLED. Idempotente."""
        ...
