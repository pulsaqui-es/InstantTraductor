"""Contratos de métricas: tiempos por etapa y registro de cada frase."""

from dataclasses import dataclass
from enum import StrEnum

from instanttraductor.contracts.translation import TranslationMode


class Outcome(StrEnum):
    SPOKEN = "pronunciada"
    DROPPED = "descartada"
    REJECTED = "rechazada"  # la traducción no pasó los filtros de salida (no se pronuncia)
    FAILED = "fallida"


@dataclass(frozen=True, slots=True)
class StageTimings:
    """Tiempos de una frase (reloj de sesión salvo `t_start_audio` y `t_end_audio`, que son de audio)."""

    t_start_audio: float
    t_end_audio: float
    unit_ready_at: float
    captured_at: float | None = None  # reloj de sesión: llegada del chunk que contiene t_end_audio
    asr_final_at: float | None = None
    mt_started_at: float | None = None
    mt_finished_at: float | None = None
    tts_started_at: float | None = None
    tts_first_audio_at: float | None = None
    tts_finished_at: float | None = None
    play_started_at: float | None = None
    play_finished_at: float | None = None
    lid_done_at: float | None = None  # spec 002: fin de la verificación de idioma (contratos-002-v1)

    @property
    def sentence_delay(self) -> float | None:
        """Retardo de frase: `play_started_at - t_end_audio` (None si no ha empezado a sonar)."""
        if self.play_started_at is None:
            return None
        return self.play_started_at - self.t_end_audio


@dataclass(frozen=True, slots=True)
class UtteranceRecord:
    unit_id: int
    source_text: str
    translated_text: str | None
    mode: TranslationMode
    speed: float
    outcome: Outcome
    reason: str | None  # motivo de descarte o fallo
    timings: StageTimings
