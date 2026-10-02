"""Doble del verificador de idioma (`LanguageVerifier`)."""

from __future__ import annotations

from collections.abc import Callable, Iterable

import numpy as np
import numpy.typing as npt

from instanttraductor.contracts import VERIFIER_LANGUAGES, LanguageVerdict, SourceLanguage

Detector = Callable[[npt.NDArray[np.float32], int], str]


def by_dominant_frequency(mapping: dict[float, str]) -> Detector:
    """Detector para audio sintético: el idioma del tono dominante más cercano de `mapping` (Hz → código).

    Así los tests representan «habla en inglés» con un tono y «habla en español» con otro.
    """

    def detect(samples: npt.NDArray[np.float32], sample_rate: int) -> str:
        spectrum = np.abs(np.fft.rfft(samples))
        peak = float(np.fft.rfftfreq(len(samples), 1 / sample_rate)[int(np.argmax(spectrum))])
        return mapping[min(mapping, key=lambda freq: abs(freq - peak))]

    return detect


class FakeLanguageVerifier:
    """`LanguageVerifier` de prueba.

    - `detect`: código fijo (p. ej. «en») o función `(samples, rate) -> código`.
    - `script`: si se da, códigos que se devuelven en orden (después, `detect`).
    - `fail_with`: excepción que se lanza en cada llamada (para probar el fallo del verificador).
    - Anota cada llamada en `calls` como (duración_s, idioma pedido).
    """

    name = "fake-lid"

    def __init__(
        self,
        detect: str | Detector = "en",
        *,
        script: Iterable[str] = (),
        fail_with: Exception | None = None,
    ) -> None:
        self._detect = detect
        self._script = list(script)
        self._fail_with = fail_with
        self.calls: list[tuple[float, SourceLanguage]] = []
        self.closed = False

    def verify(
        self, samples: npt.NDArray[np.float32], sample_rate: int, language: SourceLanguage
    ) -> LanguageVerdict:
        self.calls.append((len(samples) / sample_rate, language))
        if self._fail_with is not None:
            raise self._fail_with
        if self._script:
            detected = self._script.pop(0)
        elif callable(self._detect):
            detected = self._detect(samples, sample_rate)
        else:
            detected = self._detect
        if detected not in VERIFIER_LANGUAGES:
            raise ValueError(f"idioma de prueba desconocido: {detected}")
        return LanguageVerdict(detected == language.value, detected, 0.9, 0.001)

    def close(self) -> None:
        self.closed = True
