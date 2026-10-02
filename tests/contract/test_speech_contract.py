"""Suites de contrato de `Vad` y `AsrEngine`.

Salen de «Tests de contrato obligatorios», en `specs/001-espina-dorsal/contracts/pipeline.md`.
Cada `XxxContract` es una clase base que pytest no recoge por sí sola: un adaptador la concreta con una
subclase `TestXxx...` que sobrescribe `make_impl` y, si hace falta, los fixtures de audio.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import numpy.typing as npt
import pytest

from instanttraductor.contracts import (
    AsrCapabilities,
    AsrEngine,
    AsrEvent,
    AsrEventKind,
    Vad,
    VadEvent,
    VadEventKind,
)
from instanttraductor.pipeline.clock import ManualClock
from tests.contract.helpers import assert_implements, silence, to_chunks, voiced
from tests.fakes.fake_speech import FakeAsrEngine, FakeVad, scripted_utterance

Samples = npt.NDArray[np.float32]


def feed_vad(vad: Vad, samples: Samples, t0: float = 0.0) -> list[VadEvent]:
    """Entrega el audio al VAD en chunks de 20 ms y devuelve todos los eventos."""
    events: list[VadEvent] = []
    for chunk in to_chunks(samples, t0=t0):
        events.extend(vad.accept(chunk))
    return events


def feed_asr(asr: AsrEngine, samples: Samples, t0: float = 0.0) -> list[AsrEvent]:
    """Entrega el audio al ASR en chunks de 20 ms y devuelve todos los eventos."""
    events: list[AsrEvent] = []
    for chunk in to_chunks(samples, t0=t0):
        events.extend(asr.accept(chunk))
    return events


class VadContract:
    """Contrato de `Vad`: sin eventos con silencio, START/END alternados y `in_speech` coherente.

    Para concretarla, sobrescribe:
    - `make_impl` (obligatorio): fábrica de un VAD nuevo.
    - `speech_samples` (opcional): audio con habla a 16 kHz. Por defecto, una señal sonora sintética que
      detecta un VAD por energía; un VAD real necesita habla de verdad.
    - `silence_samples` (opcional): silencio a continuación del habla, de más de 0,5 s (2 s por defecto).
    """

    @pytest.fixture
    def make_impl(self) -> Callable[[], Vad]:
        raise NotImplementedError("Sobrescribe el fixture `make_impl` en la subclase de la suite.")

    @pytest.fixture
    def speech_samples(self) -> Samples:
        return voiced(1.5)

    @pytest.fixture
    def silence_samples(self) -> Samples:
        return silence(2.0)

    def test_implements_the_protocol(self, make_impl: Callable[[], Vad]) -> None:
        assert_implements(make_impl(), Vad)

    def test_silence_yields_no_events(self, make_impl: Callable[[], Vad], silence_samples: Samples) -> None:
        vad = make_impl()
        assert feed_vad(vad, silence_samples) == []
        assert vad.in_speech is False

    def test_speech_then_silence_yields_alternating_start_and_end(
        self, make_impl: Callable[[], Vad], speech_samples: Samples, silence_samples: Samples
    ) -> None:
        vad = make_impl()
        audio = np.concatenate([speech_samples, silence_samples])
        events: list[VadEvent] = []
        for chunk in to_chunks(audio):
            events.extend(vad.accept(chunk))
            # `in_speech` es True si y solo si el último evento fue SPEECH_START.
            expected = bool(events) and events[-1].kind is VadEventKind.SPEECH_START
            assert vad.in_speech is expected
        assert events, "el VAD no detectó el habla"
        assert all(isinstance(e, VadEvent) for e in events)
        kinds = [e.kind for e in events]
        assert kinds == [VadEventKind.SPEECH_START, VadEventKind.SPEECH_END] * (len(kinds) // 2)
        times = [e.t for e in events]
        assert times == sorted(times)
        assert vad.in_speech is False

    def test_reset_leaves_the_vad_out_of_speech_with_no_stale_events(
        self, make_impl: Callable[[], Vad], speech_samples: Samples, silence_samples: Samples
    ) -> None:
        vad = make_impl()
        feed_vad(vad, speech_samples)
        vad.reset()
        assert vad.in_speech is False
        # Tras `reset`, el silencio no cierra un habla anterior: no hay SPEECH_END huérfano.
        assert feed_vad(vad, silence_samples, t0=len(speech_samples) / 16_000) == []

    def test_accept_returns_a_list(self, make_impl: Callable[[], Vad], silence_samples: Samples) -> None:
        vad = make_impl()
        assert isinstance(vad.accept(to_chunks(silence_samples)[0]), list)


class AsrEngineContract:
    """Contrato de `AsrEngine`.

    `segment_id` y `revision` crecientes, `stable_len` que no decrece, FINAL tras `flush()` y sin eventos
    con silencio.

    Para concretarla, sobrescribe:
    - `make_impl` (obligatorio): fábrica de un motor nuevo.
    - `speech_samples` (opcional): audio con habla, de 1 s o más y a 16 kHz, que produce al menos un
      PARTIAL. Por defecto, una señal sonora sintética que solo sirve a los dobles; un motor real
      necesita habla de verdad.
    - `silence_samples` (opcional): silencio digital (2 s por defecto) que no debe producir eventos.
    """

    @pytest.fixture
    def make_impl(self) -> Callable[[], AsrEngine]:
        raise NotImplementedError("Sobrescribe el fixture `make_impl` en la subclase de la suite.")

    @pytest.fixture
    def speech_samples(self) -> Samples:
        return voiced(1.5)

    @pytest.fixture
    def silence_samples(self) -> Samples:
        return silence(2.0)

    @staticmethod
    def assert_event_invariants(events: list[AsrEvent], capabilities: AsrCapabilities) -> None:
        """Invariantes de una secuencia completa de eventos (cada segmento acaba con su FINAL)."""
        segments: dict[int, list[AsrEvent]] = {}
        order: list[int] = []
        for event in events:
            assert isinstance(event, AsrEvent)
            if event.segment_id not in segments:
                segments[event.segment_id] = []
                order.append(event.segment_id)
            elif order[-1] != event.segment_id:
                pytest.fail(f"los eventos del segmento {event.segment_id} no son contiguos")
            segments[event.segment_id].append(event)

        # `segment_id` creciente en toda la sesión.
        assert order == sorted(order)
        assert len(set(order)) == len(order)

        for segment_id, group in segments.items():
            revisions = [e.revision for e in group]
            assert revisions == list(range(revisions[0], revisions[0] + len(group))), (
                f"segmento {segment_id}: `revision` debe subir de 1 en 1, y es {revisions}"
            )
            stable = [e.stable_len for e in group]
            assert stable == sorted(stable), f"segmento {segment_id}: `stable_len` decrece: {stable}"
            for event in group:
                assert 0 <= event.stable_len <= len(event.text)
            kinds = [e.kind for e in group]
            assert kinds.count(AsrEventKind.FINAL) == 1, f"segmento {segment_id}: debe tener un único FINAL"
            assert kinds[-1] is AsrEventKind.FINAL, f"segmento {segment_id}: el FINAL debe ir al final"
            assert group[-1].stable_len == len(group[-1].text)

        for event in events:
            assert event.t_start <= event.t_end
            assert event.language in capabilities.languages
            assert isinstance(event.words, tuple)
        emitted = [e.emitted_at for e in events]
        assert emitted == sorted(emitted), "`emitted_at` (reloj de sesión) no debe retroceder"

    def test_implements_the_protocol(self, make_impl: Callable[[], AsrEngine]) -> None:
        assert_implements(make_impl(), AsrEngine)

    def test_declares_a_name_and_its_capabilities(self, make_impl: Callable[[], AsrEngine]) -> None:
        asr = make_impl()
        assert isinstance(asr.name, str) and asr.name
        capabilities = asr.capabilities
        assert isinstance(capabilities, AsrCapabilities)
        assert capabilities.device in ("cpu", "cuda")
        assert capabilities.languages
        assert capabilities.est_vram_mb >= 0

    def test_silence_yields_no_events(
        self, make_impl: Callable[[], AsrEngine], silence_samples: Samples
    ) -> None:
        asr = make_impl()
        assert feed_asr(asr, silence_samples) == []
        assert asr.flush() == []

    def test_event_invariants_hold_over_speech_and_silence(
        self, make_impl: Callable[[], AsrEngine], speech_samples: Samples, silence_samples: Samples
    ) -> None:
        asr = make_impl()
        events = feed_asr(asr, np.concatenate([speech_samples, silence_samples]))
        events.extend(asr.flush())
        assert events, "el motor no produjo ningún evento con habla"
        self.assert_event_invariants(events, asr.capabilities)

    def test_flush_after_speech_closes_the_open_segment_with_a_final(
        self, make_impl: Callable[[], AsrEngine], speech_samples: Samples
    ) -> None:
        asr = make_impl()
        events = feed_asr(asr, speech_samples)
        open_segment = events[-1] if events and events[-1].kind is AsrEventKind.PARTIAL else None
        closed = asr.flush()
        if open_segment is not None:
            assert closed, "`flush()` debe cerrar el segmento en curso: había texto"
            final = closed[-1]
            assert final.kind is AsrEventKind.FINAL
            assert final.segment_id == open_segment.segment_id
            assert final.revision == open_segment.revision + 1
            assert final.stable_len == len(final.text)
        assert asr.flush() == [], "un segundo `flush()` no tiene nada que cerrar"
        self.assert_event_invariants(events + closed, asr.capabilities)

    def test_flush_without_text_returns_nothing(self, make_impl: Callable[[], AsrEngine]) -> None:
        assert make_impl().flush() == []

    def test_reset_discards_the_segment_in_progress(
        self, make_impl: Callable[[], AsrEngine], speech_samples: Samples
    ) -> None:
        asr = make_impl()
        feed_asr(asr, speech_samples)
        asr.reset()
        assert asr.flush() == []

    def test_segment_ids_keep_increasing_across_flushes(
        self, make_impl: Callable[[], AsrEngine], speech_samples: Samples, silence_samples: Samples
    ) -> None:
        asr = make_impl()
        first = feed_asr(asr, speech_samples) + asr.flush()
        t0 = (len(speech_samples) + len(silence_samples)) / 16_000
        second = feed_asr(asr, silence_samples, t0=len(speech_samples) / 16_000)
        second += feed_asr(asr, speech_samples, t0=t0) + asr.flush()
        assert first and second, "hacen falta eventos en las dos tandas"
        assert min(e.segment_id for e in second) > max(e.segment_id for e in first)

    def test_close_is_idempotent(self, make_impl: Callable[[], AsrEngine]) -> None:
        asr = make_impl()
        asr.close()
        asr.close()

    def test_accept_returns_a_list(
        self, make_impl: Callable[[], AsrEngine], silence_samples: Samples
    ) -> None:
        assert isinstance(make_impl().accept(to_chunks(silence_samples)[0]), list)


# --------------------------------------------------------------------------------------------------
# Dobles
# --------------------------------------------------------------------------------------------------


class TestVadFake(VadContract):
    @pytest.fixture
    def make_impl(self) -> Callable[[], Vad]:
        return FakeVad


class TestAsrEngineFake(AsrEngineContract):
    """El guion encaja con el audio por defecto: habla de 1,2 s en t=0 y otra en t=3,2."""

    @pytest.fixture
    def make_impl(self) -> Callable[[], AsrEngine]:
        script = scripted_utterance("hello there my friend", t_start=0.0, t_end=2.0) + scripted_utterance(
            "how are you today friend", t_start=3.0, t_end=4.0
        )
        return lambda: FakeAsrEngine(script, clock=ManualClock())

    @pytest.fixture
    def speech_samples(self) -> Samples:
        return voiced(1.2)
