"""Suite de contrato de `Synthesizer`.

Sale de «Tests de contrato obligatorios», en `specs/001-espina-dorsal/contracts/pipeline.md`.
`SynthesizerContract` es una clase base que pytest no recoge por sí sola: un adaptador la concreta con una
subclase `TestXxx...` que sobrescribe `make_impl` (y, si hace falta, `texts` y `voice`).
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pytest

from instanttraductor.contracts import (
    SynthesisRequest,
    SynthesizedChunk,
    Synthesizer,
    VoiceInfo,
    VoiceRef,
)
from tests.contract.helpers import assert_implements
from tests.fakes.fake_synthesis import FakeSynthesizer


def synthesize_all(synth: Synthesizer, request: SynthesisRequest) -> list[SynthesizedChunk]:
    return list(synth.synthesize(request))


class SynthesizerContract:
    """Contrato de `Synthesizer`: al menos un trozo, un único `is_last` al final y `sample_rate` constante.

    Para concretarla, sobrescribe:
    - `make_impl` (obligatorio): fábrica de un sintetizador nuevo.
    - `texts` (opcional): textos en español con los que se sintetiza. Mejor cortos: un motor real tarda.
    - `voice` (opcional): la voz de las peticiones. Por defecto, la primera de `list_voices()`.
    """

    @pytest.fixture
    def make_impl(self) -> Callable[[], Synthesizer]:
        raise NotImplementedError("Sobrescribe el fixture `make_impl` en la subclase de la suite.")

    @pytest.fixture
    def texts(self) -> tuple[str, ...]:
        return ("Hola.", "Vamos a salir antes de que anochezca.", "Vale")

    @pytest.fixture
    def voice(self, make_impl: Callable[[], Synthesizer]) -> VoiceRef:
        return VoiceRef(voice_id=make_impl().list_voices()[0].voice_id)

    @staticmethod
    def request(text: str, voice: VoiceRef, *, unit_id: int = 1, speed: float = 1.0) -> SynthesisRequest:
        return SynthesisRequest(unit_id=unit_id, text=text, voice=voice, speed=speed)

    def test_implements_the_protocol(self, make_impl: Callable[[], Synthesizer]) -> None:
        assert_implements(make_impl(), Synthesizer)

    def test_declares_its_name_sample_rate_and_speed_support(
        self, make_impl: Callable[[], Synthesizer]
    ) -> None:
        synth = make_impl()
        assert isinstance(synth.name, str) and synth.name
        assert isinstance(synth.sample_rate, int) and synth.sample_rate > 0
        assert isinstance(synth.supports_speed, bool)

    def test_yields_at_least_one_chunk_with_a_single_last_at_the_end(
        self, make_impl: Callable[[], Synthesizer], texts: tuple[str, ...], voice: VoiceRef
    ) -> None:
        synth = make_impl()
        for text in texts:
            chunks = synthesize_all(synth, self.request(text, voice))
            assert chunks, f"sin trozos para {text!r}"
            assert [c.is_last for c in chunks] == [False] * (len(chunks) - 1) + [True]

    def test_sample_rate_is_constant_and_matches_the_engine(
        self, make_impl: Callable[[], Synthesizer], texts: tuple[str, ...], voice: VoiceRef
    ) -> None:
        synth = make_impl()
        for text in texts:
            chunks = synthesize_all(synth, self.request(text, voice))
            assert {c.sample_rate for c in chunks} == {synth.sample_rate}

    def test_chunks_carry_the_unit_id_and_mono_float32_audio(
        self, make_impl: Callable[[], Synthesizer], texts: tuple[str, ...], voice: VoiceRef
    ) -> None:
        synth = make_impl()
        for unit_id, text in enumerate(texts, start=10):
            chunks = synthesize_all(synth, self.request(text, voice, unit_id=unit_id))
            for chunk in chunks:
                assert chunk.unit_id == unit_id
                assert chunk.samples.dtype == np.float32
                assert chunk.samples.ndim == 1
                assert np.all(np.isfinite(chunk.samples))
                assert float(np.max(np.abs(chunk.samples), initial=0.0)) <= 1.0
            assert sum(len(c.samples) for c in chunks) > 0, f"sin audio para {text!r}"

    def test_accepts_a_speed_request(
        self, make_impl: Callable[[], Synthesizer], texts: tuple[str, ...], voice: VoiceRef
    ) -> None:
        """Si el motor no soporta `speed`, lo ignora; en cualquier caso el flujo sigue siendo válido."""
        synth = make_impl()
        chunks = synthesize_all(synth, self.request(texts[0], voice, speed=1.25))
        assert chunks
        assert [c.is_last for c in chunks] == [False] * (len(chunks) - 1) + [True]

    def test_lists_voices_with_unique_ascii_ids(self, make_impl: Callable[[], Synthesizer]) -> None:
        voices = make_impl().list_voices()
        assert isinstance(voices, tuple)
        assert voices, "debe haber al menos una voz"
        assert all(isinstance(v, VoiceInfo) for v in voices)
        ids = [v.voice_id for v in voices]
        assert len(set(ids)) == len(ids)
        assert all(voice_id.isascii() and voice_id for voice_id in ids)
        assert all(v.gender in ("f", "m") for v in voices)
        assert all(v.name and v.source and v.license for v in voices)

    def test_close_is_idempotent(self, make_impl: Callable[[], Synthesizer]) -> None:
        synth = make_impl()
        synth.close()
        synth.close()


# --------------------------------------------------------------------------------------------------
# Dobles
# --------------------------------------------------------------------------------------------------


class TestSynthesizerFake(SynthesizerContract):
    @pytest.fixture
    def make_impl(self) -> Callable[[], Synthesizer]:
        return FakeSynthesizer


class TestSynthesizerFakeWithSpeedSupport(SynthesizerContract):
    @pytest.fixture
    def make_impl(self) -> Callable[[], Synthesizer]:
        return lambda: FakeSynthesizer(supports_speed=True)
