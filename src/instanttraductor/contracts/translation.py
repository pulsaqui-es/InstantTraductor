"""Contratos de traducción."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from instanttraductor.contracts.units import TranslationUnit


class TranslationMode(StrEnum):
    NORMAL = "normal"
    CONCISE = "conciso"  # resumida a lo esencial (FR-013)


@dataclass(frozen=True, slots=True)
class GlossaryEntry:
    source: str
    target: str


@dataclass(frozen=True, slots=True)
class TranslationRequest:
    unit: TranslationUnit
    # (original, traducción) de las unidades previas, de la más antigua a la más reciente
    context: tuple[tuple[str, str], ...]
    glossary: tuple[GlossaryEntry, ...]
    mode: TranslationMode


@dataclass(frozen=True, slots=True)
class TranslationResult:
    unit_id: int
    text: str  # español; vacío si rejected
    mode: TranslationMode
    started_at: float  # reloj de sesión
    finished_at: float
    rejected: bool = False  # True si los filtros de salida la descartaron (muletillas, idioma, longitud)


class Translator(Protocol):
    name: str
    supports_concise: bool  # False en la reserva 1.8B: no sabe resumir (ADR-0011)

    def translate(self, request: TranslationRequest) -> TranslationResult:
        """Traduce una unidad. Lanza `EngineError` si falla."""
        ...

    def close(self) -> None: ...
