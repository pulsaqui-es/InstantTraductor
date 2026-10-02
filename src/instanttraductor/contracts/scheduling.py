"""Contratos de la política de retraso: acelerar, resumir y descartar."""

from dataclasses import dataclass
from typing import Protocol

from instanttraductor.contracts.translation import TranslationMode


@dataclass(frozen=True, slots=True)
class DelayPolicy:
    accelerate_after_s: float = 3.0
    max_speed: float = 1.25
    concise_after_s: float = 5.0
    drop_after_s: float = 8.0
    allow_concise: bool = True  # False si el traductor no lo soporta: se salta la fase de resumir


@dataclass(frozen=True, slots=True)
class DelayDecision:
    speed: float  # 1.0–max_speed, gradual según el retraso
    # CONCISE mientras el retraso no vuelva bajo accelerate_after_s (nunca si allow_concise=False)
    mode: TranslationMode
    drop_oldest_pending: bool  # True solo si lag > drop_after_s a velocidad máxima


class DelayController(Protocol):
    def decide(self, lag_s: float) -> DelayDecision:
        """Decide según el retraso actual. Con estado (histéresis); determinista."""
        ...
