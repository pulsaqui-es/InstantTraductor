"""Suite de contrato de `Translator`.

Sale de «Tests de contrato obligatorios», en `specs/001-espina-dorsal/contracts/pipeline.md`.
`TranslatorContract` es una clase base que pytest no recoge por sí sola: un adaptador la concreta con una
subclase `TestXxx...` que sobrescribe `make_impl` (y, si hace falta, `requests`).
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from instanttraductor.contracts import (
    GlossaryEntry,
    TranslationMode,
    TranslationRequest,
    TranslationResult,
    TranslationUnit,
    Translator,
)
from tests.contract.helpers import assert_implements
from tests.fakes.fake_translation import FakeTranslator

SENTENCES = (
    "hello there my friend",
    "I think we should leave before it gets dark",
    "okay",
)


def make_request(
    unit_id: int,
    text: str,
    mode: TranslationMode = TranslationMode.NORMAL,
    *,
    context: tuple[tuple[str, str], ...] = (),
    glossary: tuple[GlossaryEntry, ...] = (),
) -> TranslationRequest:
    unit = TranslationUnit(
        unit_id=unit_id,
        source_text=text,
        t_start=float(unit_id),
        t_end=unit_id + 1.0,
        is_sentence_end=True,
        ready_at=unit_id + 1.2,
    )
    return TranslationRequest(unit=unit, context=context, glossary=glossary, mode=mode)


class TranslatorContract:
    """Contrato de `Translator`: `unit_id` preservado, `mode` respetado y `rejected` coherente con `text`.

    Para concretarla, sobrescribe:
    - `make_impl` (obligatorio): fábrica de un traductor nuevo.
    - `requests` (opcional): peticiones en modo NORMAL con las que se comprueban los resultados. Un
      adaptador real puede incluir alguna que provoque un rechazo, para probar esa rama.
    """

    @pytest.fixture
    def make_impl(self) -> Callable[[], Translator]:
        raise NotImplementedError("Sobrescribe el fixture `make_impl` en la subclase de la suite.")

    @pytest.fixture
    def requests(self) -> list[TranslationRequest]:
        return [make_request(unit_id, text) for unit_id, text in enumerate(SENTENCES, start=1)]

    def test_implements_the_protocol(self, make_impl: Callable[[], Translator]) -> None:
        assert_implements(make_impl(), Translator)

    def test_declares_its_name_and_concise_support(self, make_impl: Callable[[], Translator]) -> None:
        translator = make_impl()
        assert isinstance(translator.name, str) and translator.name
        assert isinstance(translator.supports_concise, bool)

    def test_returns_a_result_with_the_unit_id_preserved(
        self, make_impl: Callable[[], Translator], requests: list[TranslationRequest]
    ) -> None:
        translator = make_impl()
        for request in requests:
            result = translator.translate(request)
            assert isinstance(result, TranslationResult)
            assert result.unit_id == request.unit.unit_id

    def test_a_large_unit_id_is_preserved(self, make_impl: Callable[[], Translator]) -> None:
        result = make_impl().translate(make_request(123_456, "hello there"))
        assert result.unit_id == 123_456

    def test_normal_mode_is_respected(
        self, make_impl: Callable[[], Translator], requests: list[TranslationRequest]
    ) -> None:
        translator = make_impl()
        for request in requests:
            assert translator.translate(request).mode is TranslationMode.NORMAL

    def test_concise_mode_is_respected_when_supported(self, make_impl: Callable[[], Translator]) -> None:
        translator = make_impl()
        if not translator.supports_concise:
            pytest.skip("este traductor no sabe resumir (supports_concise=False)")
        result = translator.translate(make_request(1, SENTENCES[1], TranslationMode.CONCISE))
        assert result.mode is TranslationMode.CONCISE

    def test_rejected_is_consistent_with_empty_text(
        self, make_impl: Callable[[], Translator], requests: list[TranslationRequest]
    ) -> None:
        translator = make_impl()
        for request in requests:
            result = translator.translate(request)
            if result.rejected:
                assert result.text == "", "una traducción rechazada debe tener el texto vacío"
            else:
                assert result.text.strip(), "una traducción no rechazada no puede estar vacía"

    def test_timestamps_are_ordered(
        self, make_impl: Callable[[], Translator], requests: list[TranslationRequest]
    ) -> None:
        translator = make_impl()
        for request in requests:
            result = translator.translate(request)
            assert result.started_at <= result.finished_at

    def test_accepts_context_and_glossary(self, make_impl: Callable[[], Translator]) -> None:
        request = make_request(
            3,
            "put the juice in the fridge",
            context=(("hello there", "hola"), ("how are you", "cómo estás")),
            glossary=(GlossaryEntry("juice", "zumo"), GlossaryEntry("fridge", "nevera")),
        )
        result = make_impl().translate(request)
        assert result.unit_id == 3

    def test_close_is_idempotent(self, make_impl: Callable[[], Translator]) -> None:
        translator = make_impl()
        translator.close()
        translator.close()


# --------------------------------------------------------------------------------------------------
# Dobles
# --------------------------------------------------------------------------------------------------


class TestTranslatorFake(TranslatorContract):
    @pytest.fixture
    def make_impl(self) -> Callable[[], Translator]:
        return FakeTranslator


class TestTranslatorFakeWithoutConcise(TranslatorContract):
    """Un traductor sin soporte de resumen cumple el mismo contrato (y se salta la prueba de CONCISE)."""

    @pytest.fixture
    def make_impl(self) -> Callable[[], Translator]:
        return lambda: FakeTranslator(supports_concise=False)
