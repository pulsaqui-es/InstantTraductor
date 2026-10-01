"""Contratos de segmentación: unidades de traducción."""

from dataclasses import dataclass
from typing import Protocol

from instanttraductor.contracts.speech import AsrEvent, VadEvent


@dataclass(frozen=True, slots=True)
class TranslationUnit:
    unit_id: int  # estrictamente creciente
    source_text: str  # no vacío; solo texto estable
    t_start: float  # reloj de audio
    t_end: float  # reloj de audio; base del retardo de frase
    is_sentence_end: bool  # False = fragmento de una frase larga
    ready_at: float  # reloj de sesión
    language: str = "en"


class Segmenter(Protocol):
    """Convierte los eventos del VAD y del ASR en unidades de traducción.

    Una unidad por enunciado: se cierra con la pausa del VAD (SPEECH_END) y el FINAL del ASR.
    El ASR casi nunca pone punto final, así que no se cierra por puntuación (research.md R6).
    Habla larga: se corta en una coma o conjunción estable si el fragmento tiene ≥ 6 palabras.
    Nunca más de `max_untranslated_s` de habla sin emitir unidad (FR-004, FR-005).
    """

    def accept(self, event: AsrEvent | VadEvent) -> list[TranslationUnit]: ...

    def flush(self) -> list[TranslationUnit]:
        """Cierra lo pendiente (fin de sesión o de fichero)."""
        ...
