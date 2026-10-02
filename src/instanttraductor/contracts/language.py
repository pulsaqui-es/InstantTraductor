"""Contratos de idioma (spec 002): idioma de origen elegido a mano y verificador (ADR-0012 y 0013)."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

import numpy as np
import numpy.typing as npt


class SourceLanguage(StrEnum):
    """Idioma de origen que se traduce al español (lo elige la persona usuaria; no se detecta)."""

    EN = "en"
    JA = "ja"
    ZH = "zh"
    KO = "ko"


#: Idiomas entre los que decide el verificador: los cuatro de origen y el español (la llamada de Discord).
VERIFIER_LANGUAGES: tuple[str, ...] = ("en", "es", "ja", "zh", "ko")


@dataclass(frozen=True, slots=True)
class LanguageVerdict:
    accepted: bool  # True si gana el idioma elegido
    detected: str  # código ISO 639-1 del ganador entre VERIFIER_LANGUAGES
    probability: float  # 0–1, del ganador
    elapsed_s: float  # tiempo de CPU de la decisión


class LanguageVerifier(Protocol):
    name: str

    def verify(
        self, samples: npt.NDArray[np.float32], sample_rate: int, language: SourceLanguage
    ) -> LanguageVerdict:
        """¿Es el audio habla en `language`? Mono float32; 1 s ≤ duración ≤ 6 s (quien llama completa los
        recortes cortos). Lanza `EngineError` si falla."""
        ...

    def close(self) -> None: ...
