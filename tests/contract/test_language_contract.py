"""Contrato `LanguageVerifier` (contratos-002-v1).

`LanguageVerifierContract` lo reutilizan las implementaciones reales (p. ej. `WhisperLanguageVerifier`) con un
fixture `verifier`.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
import pytest

from instanttraductor.contracts import (
    CAPTURE_RATE,
    VERIFIER_LANGUAGES,
    EngineError,
    LanguageVerdict,
    LanguageVerifier,
    SourceLanguage,
)
from tests.fakes.fake_language import FakeLanguageVerifier, by_dominant_frequency


def tone(freq: float, seconds: float = 2.0) -> npt.NDArray[np.float32]:
    t = np.arange(int(seconds * CAPTURE_RATE)) / CAPTURE_RATE
    return (0.2 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


class LanguageVerifierContract:
    """Pruebas que debe pasar cualquier `LanguageVerifier`. Requiere el fixture `verifier`."""

    def test_implements_the_protocol(self, verifier: LanguageVerifier) -> None:
        assert isinstance(verifier.name, str) and verifier.name

    @pytest.mark.parametrize("seconds", [1.0, 3.0, 6.0])
    def test_returns_a_valid_verdict_for_1_to_6_seconds(
        self, verifier: LanguageVerifier, seconds: float
    ) -> None:
        verdict = verifier.verify(tone(220.0, seconds), CAPTURE_RATE, SourceLanguage.EN)
        assert isinstance(verdict, LanguageVerdict)
        assert verdict.detected in VERIFIER_LANGUAGES
        assert 0.0 <= verdict.probability <= 1.0
        assert verdict.elapsed_s >= 0.0

    def test_accepted_means_the_chosen_language_won(self, verifier: LanguageVerifier) -> None:
        for language in SourceLanguage:
            verdict = verifier.verify(tone(220.0), CAPTURE_RATE, language)
            assert verdict.accepted == (verdict.detected == language.value)

    def test_close_is_idempotent(self, verifier: LanguageVerifier) -> None:
        verifier.close()
        verifier.close()


class TestFakeLanguageVerifier(LanguageVerifierContract):
    @pytest.fixture
    def verifier(self) -> FakeLanguageVerifier:
        return FakeLanguageVerifier(by_dominant_frequency({220.0: "en", 440.0: "es"}))


def test_the_fake_tells_the_film_from_the_call_by_its_tone() -> None:
    fake = FakeLanguageVerifier(by_dominant_frequency({220.0: "en", 440.0: "es"}))
    assert fake.verify(tone(220.0), CAPTURE_RATE, SourceLanguage.EN).accepted
    assert not fake.verify(tone(440.0), CAPTURE_RATE, SourceLanguage.EN).accepted
    assert [language for _, language in fake.calls] == [SourceLanguage.EN, SourceLanguage.EN]


def test_the_fake_can_fail_like_a_real_engine() -> None:
    fake = FakeLanguageVerifier(fail_with=EngineError("sin modelo", engine="lid"))
    with pytest.raises(EngineError):
        fake.verify(tone(220.0), CAPTURE_RATE, SourceLanguage.EN)


def test_the_contract_additions_have_defaults_so_001_code_still_works() -> None:
    from instanttraductor.contracts import (
        StageTimings,
        TranslationMode,
        TranslationRequest,
        TranslationUnit,
    )

    unit = TranslationUnit(
        unit_id=1, source_text="Hi.", t_start=0.0, t_end=1.0, is_sentence_end=True, ready_at=1.0
    )
    request = TranslationRequest(unit=unit, context=(), glossary=(), mode=TranslationMode.NORMAL)
    assert request.source_language is SourceLanguage.EN
    assert StageTimings(t_start_audio=0.0, t_end_audio=1.0, unit_ready_at=1.0).lid_done_at is None
