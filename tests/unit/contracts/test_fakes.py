"""Tests del comportamiento propio de los dobles de `tests/fakes/` (T011).

Las propiedades que exige el contrato las comprueban las suites de `tests/contract/` (`TestXxxFake`).
Aquí se prueba lo que esas suites no cubren: lo que cada doble añade (guiones, latencias, fallos
simulados, línea de tiempo del sink) y que cumplen sus Protocols.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

from instanttraductor.contracts import (
    CAPTURE_RATE,
    PLAYBACK_RATE,
    AsrEngine,
    AsrEvent,
    AsrEventKind,
    AudioSink,
    AudioSource,
    Clock,
    DelayController,
    DelayDecision,
    EngineError,
    PlaybackEvent,
    PlaybackEventKind,
    SpeechPiece,
    SynthesisRequest,
    Synthesizer,
    TranslationMode,
    TranslationRequest,
    TranslationUnit,
    Translator,
    Vad,
    VadEvent,
    VadEventKind,
    VoiceRef,
)
from instanttraductor.pipeline.clock import ManualClock, SessionClock
from tests.contract.helpers import (
    assert_implements,
    silence,
    to_chunks,
    tone,
    voiced,
)
from tests.fakes.fake_audio import FakeAudioSink, FakeAudioSource
from tests.fakes.fake_scheduling import ScriptedDelayController
from tests.fakes.fake_speech import FakeAsrEngine, FakeVad, ScriptedAsrEvent, scripted_utterance
from tests.fakes.fake_synthesis import FakeSynthesizer
from tests.fakes.fake_translation import FakeTranslator

STARTED, FINISHED, CANCELLED = (
    PlaybackEventKind.STARTED,
    PlaybackEventKind.FINISHED,
    PlaybackEventKind.CANCELLED,
)


# --------------------------------------------------------------------------------------------------
# assert_implements (el propio comprobador de Protocols)
# --------------------------------------------------------------------------------------------------


class TestAssertImplements:
    def test_accepts_a_conforming_object(self) -> None:
        assert_implements(ManualClock(), Clock)

    def test_rejects_a_missing_member(self) -> None:
        class NoStop:
            sample_rate = CAPTURE_RATE
            exhausted = False

            def start(self) -> None: ...

            def read(self, timeout: float) -> None: ...

        with pytest.raises(AssertionError, match="faltan"):
            assert_implements(NoStop(), AudioSource)

    def test_rejects_different_parameter_names(self) -> None:
        class WrongRead:
            sample_rate = CAPTURE_RATE
            exhausted = False

            def start(self) -> None: ...

            def read(self, seconds: float) -> None: ...

            def stop(self) -> None: ...

        with pytest.raises(AssertionError, match="no coincide"):
            assert_implements(WrongRead(), AudioSource)

    def test_rejects_extra_required_parameters(self) -> None:
        class ExtraRequired:
            sample_rate = CAPTURE_RATE
            exhausted = False

            def start(self) -> None: ...

            def read(self, timeout: float, extra: int) -> None: ...

            def stop(self) -> None: ...

        with pytest.raises(AssertionError, match="exige parámetros"):
            assert_implements(ExtraRequired(), AudioSource)


# --------------------------------------------------------------------------------------------------
# FakeAudioSource
# --------------------------------------------------------------------------------------------------


def _write_wav(path: Path, samples: np.ndarray, rate: int) -> None:
    """Escribe un WAV PCM de 16 bits. `soundfile` se importa aquí: si falla, no oculta los demás tests."""
    import soundfile as sf

    sf.write(path, samples, rate, subtype="PCM_16")


def _drain(source: FakeAudioSource) -> list:
    source.start()
    chunks = []
    while (chunk := source.read(0.0)) is not None:
        chunks.append(chunk)
    return chunks


class TestFakeAudioSource:
    def test_implements_the_protocol(self) -> None:
        assert_implements(FakeAudioSource(silence(0.1)), AudioSource)

    def test_sample_rate_is_the_capture_rate(self) -> None:
        assert FakeAudioSource(silence(0.1)).sample_rate == CAPTURE_RATE

    def test_chunks_are_20_ms_and_contiguous(self) -> None:
        chunks = _drain(FakeAudioSource(tone(0.1)))
        assert [len(c.samples) for c in chunks] == [320] * 5
        assert [c.t_start for c in chunks] == pytest.approx([0.0, 0.02, 0.04, 0.06, 0.08])
        for previous, current in zip(chunks, chunks[1:], strict=False):
            assert current.t_start == pytest.approx(previous.t_end, abs=1e-9)
        assert all(c.sample_rate == CAPTURE_RATE for c in chunks)

    def test_last_chunk_holds_the_remainder_and_nothing_is_lost(self) -> None:
        audio = tone(1000 / CAPTURE_RATE)
        chunks = _drain(FakeAudioSource(audio))
        assert [len(c.samples) for c in chunks] == [320, 320, 320, 40]
        np.testing.assert_array_equal(np.concatenate([c.samples for c in chunks]), audio)

    def test_chunk_size_is_configurable(self) -> None:
        chunks = _drain(FakeAudioSource(tone(0.5), chunk_s=0.1))
        assert [len(c.samples) for c in chunks] == [1600] * 5

    def test_read_returns_none_before_start(self) -> None:
        source = FakeAudioSource(tone(0.1))
        assert source.read(0.0) is None
        assert source.exhausted is False

    def test_exhausted_as_soon_as_the_last_chunk_has_been_read(self) -> None:
        source = FakeAudioSource(tone(0.04))
        source.start()
        assert source.read(0.0) is not None
        assert source.exhausted is False
        assert source.read(0.0) is not None
        assert source.exhausted is True
        assert source.read(0.0) is None

    def test_stop_ends_the_source_and_is_idempotent(self) -> None:
        source = FakeAudioSource(tone(1.0))
        source.start()
        assert source.read(0.0) is not None
        source.stop()
        source.stop()
        assert source.exhausted is True
        assert source.read(0.0) is None

    def test_empty_audio_is_exhausted_from_the_start(self) -> None:
        source = FakeAudioSource(np.zeros(0, dtype=np.float32))
        assert source.exhausted is True
        source.start()
        assert source.read(0.0) is None

    def test_chunks_are_independent_copies(self) -> None:
        audio = tone(0.1)
        original = audio.copy()
        source = FakeAudioSource(audio)
        source.start()
        first = source.read(0.0)
        assert first is not None
        first.samples[:] = 0.0
        np.testing.assert_array_equal(audio, original)

    def test_converts_to_float32(self) -> None:
        chunks = _drain(FakeAudioSource(np.zeros(640, dtype=np.float64)))
        assert all(c.samples.dtype == np.float32 for c in chunks)

    def test_rejects_non_mono_arrays(self) -> None:
        with pytest.raises(ValueError, match="mono"):
            FakeAudioSource(np.zeros((2, 320), dtype=np.float32))

    def test_reads_a_wav_file(self, tmp_path: Path) -> None:
        path = tmp_path / "tono.wav"
        audio = tone(0.5, 1000.0)
        _write_wav(path, audio, CAPTURE_RATE)
        chunks = _drain(FakeAudioSource(path))
        decoded = np.concatenate([c.samples for c in chunks])
        assert len(decoded) == len(audio)
        np.testing.assert_allclose(decoded, audio, atol=1 / 32768)

    def test_accepts_the_wav_path_as_text(self, tmp_path: Path) -> None:
        path = tmp_path / "tono.wav"
        _write_wav(path, tone(0.1), CAPTURE_RATE)
        assert len(_drain(FakeAudioSource(str(path)))) == 5

    def test_rejects_a_wav_with_another_sample_rate(self, tmp_path: Path) -> None:
        path = tmp_path / "tono_48k.wav"
        _write_wav(path, tone(0.1, rate=48_000), 48_000)
        with pytest.raises(ValueError, match="16000"):
            FakeAudioSource(path)

    def test_rejects_a_stereo_wav(self, tmp_path: Path) -> None:
        path = tmp_path / "estereo.wav"
        _write_wav(path, np.zeros((1600, 2), dtype=np.float32), CAPTURE_RATE)
        with pytest.raises(ValueError, match="mono"):
            FakeAudioSource(path)


# --------------------------------------------------------------------------------------------------
# FakeAudioSink
# --------------------------------------------------------------------------------------------------


def _piece(unit_id: int, seconds: float, *, is_last: bool = True) -> SpeechPiece:
    return SpeechPiece(
        unit_id=unit_id, samples=np.zeros(round(seconds * PLAYBACK_RATE), np.float32), is_last=is_last
    )


def _ev(unit_id: int, kind: PlaybackEventKind, at: float) -> PlaybackEvent:
    return PlaybackEvent(unit_id=unit_id, kind=kind, at=at)


@dataclass
class SinkRig:
    clock: ManualClock
    sink: FakeAudioSink
    events: list[PlaybackEvent]


@pytest.fixture
def rig() -> SinkRig:
    clock = ManualClock()
    sink = FakeAudioSink(clock)
    events: list[PlaybackEvent] = []
    sink.start(events.append)
    return SinkRig(clock, sink, events)


def _times(events: list[PlaybackEvent]) -> list[tuple[int, PlaybackEventKind, float]]:
    return [(e.unit_id, e.kind, pytest.approx(e.at)) for e in events]


class TestFakeAudioSink:
    def test_implements_the_protocol(self, rig: SinkRig) -> None:
        assert_implements(rig.sink, AudioSink)
        assert rig.sink.sample_rate == PLAYBACK_RATE

    def test_first_unit_starts_when_its_first_piece_arrives(self, rig: SinkRig) -> None:
        rig.clock.set(3.0)
        rig.sink.enqueue(_piece(1, 0.5))
        assert rig.events == [_ev(1, STARTED, 3.0)]

    def test_unit_finishes_after_its_duration(self, rig: SinkRig) -> None:
        rig.sink.enqueue(_piece(1, 0.5))
        rig.sink.advance(0.49)
        assert [e.kind for e in rig.events] == [STARTED]
        rig.sink.advance(0.01)
        assert rig.events == [_ev(1, STARTED, 0.0), _ev(1, FINISHED, 0.5)]

    def test_pending_seconds_counts_audio_not_yet_played(self, rig: SinkRig) -> None:
        assert rig.sink.pending_seconds() == 0.0
        rig.sink.enqueue(_piece(1, 0.5))
        rig.sink.enqueue(_piece(2, 0.25))
        assert rig.sink.pending_seconds() == pytest.approx(0.75)
        rig.sink.advance(0.2)
        assert rig.sink.pending_seconds() == pytest.approx(0.55)
        rig.sink.advance(10.0)
        assert rig.sink.pending_seconds() == 0.0

    def test_events_carry_simulated_times_even_after_a_big_clock_jump(self, rig: SinkRig) -> None:
        for unit_id in (1, 2, 3):
            rig.sink.enqueue(_piece(unit_id, 0.5))
        rig.clock.set(10.0)
        rig.sink.poll()
        assert _times(rig.events) == [
            (1, STARTED, 0.0),
            (1, FINISHED, 0.5),
            (2, STARTED, 0.5),
            (2, FINISHED, 1.0),
            (3, STARTED, 1.0),
            (3, FINISHED, 1.5),
        ]

    def test_a_unit_arriving_while_busy_waits_for_the_sink(self, rig: SinkRig) -> None:
        rig.sink.enqueue(_piece(1, 0.5))
        rig.sink.advance(0.2)
        rig.sink.enqueue(_piece(2, 0.3))
        assert [(e.unit_id, e.kind) for e in rig.events] == [(1, STARTED)]
        rig.sink.advance(1.0)
        assert _times(rig.events)[1:] == [(1, FINISHED, 0.5), (2, STARTED, 0.5), (2, FINISHED, 0.8)]

    def test_a_unit_arriving_after_idle_starts_on_arrival(self, rig: SinkRig) -> None:
        rig.sink.enqueue(_piece(1, 0.5))
        rig.sink.advance(2.0)
        rig.sink.enqueue(_piece(2, 0.5))
        assert rig.events[-1] == _ev(2, STARTED, 2.0)

    def test_a_multi_piece_unit_emits_one_started_and_one_finished(self, rig: SinkRig) -> None:
        rig.sink.enqueue(_piece(1, 0.2, is_last=False))
        rig.sink.enqueue(_piece(1, 0.2, is_last=False))
        rig.sink.enqueue(_piece(1, 0.1, is_last=True))
        rig.sink.advance(0.5)
        assert rig.events == [_ev(1, STARTED, 0.0), _ev(1, FINISHED, 0.5)]

    def test_an_incomplete_unit_stalls_and_resumes_with_the_next_piece(self, rig: SinkRig) -> None:
        rig.sink.enqueue(_piece(1, 0.1, is_last=False))
        rig.clock.set(1.0)
        rig.sink.poll()
        assert [e.kind for e in rig.events] == [STARTED]  # sin FINISHED: falta el último trozo
        rig.sink.enqueue(_piece(1, 0.1, is_last=True))
        assert rig.sink.pending_seconds() == pytest.approx(0.1)
        rig.sink.advance(0.1)
        assert rig.events[-1].kind is FINISHED
        assert rig.events[-1].at == pytest.approx(1.1)

    def test_an_incomplete_unit_blocks_the_following_ones(self, rig: SinkRig) -> None:
        rig.sink.enqueue(_piece(1, 0.1, is_last=False))
        rig.sink.enqueue(_piece(2, 0.2))
        rig.sink.advance(5.0)
        assert [(e.unit_id, e.kind) for e in rig.events] == [(1, STARTED)]

    def test_cancel_pending_only_discards_units_that_have_not_started(self, rig: SinkRig) -> None:
        for unit_id in (1, 2, 3):
            rig.sink.enqueue(_piece(unit_id, 0.5))
        rig.sink.advance(0.1)
        assert rig.sink.cancel_pending() == [2, 3]
        assert _times(rig.events) == [
            (1, STARTED, 0.0),
            (2, CANCELLED, 0.1),
            (3, CANCELLED, 0.1),
        ]
        rig.sink.advance(1.0)
        assert rig.events[-1] == _ev(1, FINISHED, 0.5)
        assert {e.unit_id for e in rig.events if e.kind is STARTED} == {1}

    def test_cancel_pending_with_nothing_pending_returns_an_empty_list(self, rig: SinkRig) -> None:
        assert rig.sink.cancel_pending() == []
        rig.sink.enqueue(_piece(1, 0.5))
        assert rig.sink.cancel_pending() == []
        assert [e.kind for e in rig.events] == [STARTED]

    def test_later_pieces_of_a_cancelled_unit_are_ignored_but_recorded(self, rig: SinkRig) -> None:
        rig.sink.enqueue(_piece(1, 0.5))
        rig.sink.enqueue(_piece(2, 0.2, is_last=False))
        rig.sink.cancel_pending()
        late = _piece(2, 0.2, is_last=True)
        rig.sink.enqueue(late)
        rig.sink.advance(5.0)
        assert [e.unit_id for e in rig.events if e.kind is STARTED] == [1]
        assert rig.sink.pieces[-1] is late

    def test_stop_cuts_the_playing_unit_and_cancels_the_rest(self, rig: SinkRig) -> None:
        rig.sink.enqueue(_piece(1, 0.5))
        rig.sink.enqueue(_piece(2, 0.5))
        rig.sink.advance(0.2)
        rig.sink.stop()
        assert _times(rig.events)[1:] == [(1, CANCELLED, 0.2), (2, CANCELLED, 0.2)]
        assert rig.sink.pending_seconds() == 0.0
        count = len(rig.events)
        rig.sink.advance(10.0)
        rig.sink.stop()
        assert len(rig.events) == count

    def test_enqueue_after_stop_is_ignored(self, rig: SinkRig) -> None:
        rig.sink.stop()
        rig.sink.enqueue(_piece(1, 0.5))
        assert rig.events == []
        assert len(rig.sink.pieces) == 1

    def test_stop_after_everything_finished_emits_nothing_new(self, rig: SinkRig) -> None:
        rig.sink.enqueue(_piece(1, 0.1))
        rig.sink.advance(1.0)
        count = len(rig.events)
        rig.sink.stop()
        assert len(rig.events) == count

    def test_set_volume_is_recorded(self, rig: SinkRig) -> None:
        assert rig.sink.volume == 1.0
        rig.sink.set_volume(0.5)
        assert rig.sink.volume == 0.5

    def test_pieces_are_recorded_in_order(self, rig: SinkRig) -> None:
        pieces = [_piece(1, 0.1, is_last=False), _piece(1, 0.1), _piece(2, 0.1)]
        for piece in pieces:
            rig.sink.enqueue(piece)
        assert len(rig.sink.pieces) == 3
        assert all(a is b for a, b in zip(rig.sink.pieces, pieces, strict=True))

    def test_events_are_logged_even_without_start(self) -> None:
        sink = FakeAudioSink(ManualClock())
        sink.enqueue(_piece(1, 0.1))
        assert sink.events == [_ev(1, STARTED, 0.0)]

    def test_the_callback_may_call_back_into_the_sink(self) -> None:
        clock = ManualClock()
        sink = FakeAudioSink(clock)
        delivered: list[PlaybackEvent] = []

        def on_event(event: PlaybackEvent) -> None:
            delivered.append(event)
            sink.pending_seconds()
            if event.kind is FINISHED and event.unit_id == 1:
                sink.enqueue(_piece(2, 0.25))

        sink.start(on_event)
        sink.enqueue(_piece(1, 0.5))
        sink.advance(0.5)
        assert delivered == sink.events
        assert delivered == [_ev(1, STARTED, 0.0), _ev(1, FINISHED, 0.5), _ev(2, STARTED, 0.5)]

    def test_concurrent_enqueues_keep_the_units_sequential(self, rig: SinkRig) -> None:
        def producer(first_id: int) -> None:
            for unit_id in range(first_id, first_id + 25):
                rig.sink.enqueue(_piece(unit_id, 0.01))

        threads = [threading.Thread(target=producer, args=(100 * n,)) for n in range(1, 5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        rig.sink.advance(100.0)
        assert len(rig.events) == 200
        # Cada unidad empieza y acaba antes de que empiece la siguiente: nunca suenan dos a la vez.
        for started, finished in zip(rig.events[0::2], rig.events[1::2], strict=True):
            assert (started.kind, finished.kind) == (STARTED, FINISHED)
            assert started.unit_id == finished.unit_id
        assert sorted(e.unit_id for e in rig.events[0::2]) == sorted(
            u for n in range(1, 5) for u in range(100 * n, 100 * n + 25)
        )


# --------------------------------------------------------------------------------------------------
# FakeVad
# --------------------------------------------------------------------------------------------------


def _feed_vad(vad: FakeVad, samples: np.ndarray, t0: float) -> list[VadEvent]:
    events: list[VadEvent] = []
    for chunk in to_chunks(samples, t0=t0):
        events.extend(vad.accept(chunk))
    return events


class TestFakeVad:
    def test_implements_the_protocol(self) -> None:
        assert_implements(FakeVad(), Vad)

    def test_silence_yields_no_events(self) -> None:
        vad = FakeVad()
        assert _feed_vad(vad, silence(3.0), 0.0) == []
        assert vad.in_speech is False

    def test_speech_start_is_reported_at_the_first_speech_chunk(self) -> None:
        vad = FakeVad()
        events = _feed_vad(vad, np.concatenate([silence(0.5), voiced(1.0)]), 0.0)
        assert events == [VadEvent(VadEventKind.SPEECH_START, pytest.approx(0.5))]
        assert vad.in_speech is True

    def test_speech_end_comes_after_the_minimum_silence_and_reports_the_end_of_the_speech(self) -> None:
        vad = FakeVad(min_silence_s=0.5)
        _feed_vad(vad, voiced(1.0), 0.0)
        assert _feed_vad(vad, silence(0.4), 1.0) == []
        assert vad.in_speech is True
        events = _feed_vad(vad, silence(0.2), 1.4)
        assert events == [VadEvent(VadEventKind.SPEECH_END, pytest.approx(1.0))]
        assert vad.in_speech is False

    def test_a_short_pause_does_not_end_the_speech(self) -> None:
        vad = FakeVad(min_silence_s=0.5)
        samples = np.concatenate([voiced(1.0), silence(0.3), voiced(1.0)])
        events = _feed_vad(vad, samples, 0.0)
        assert [e.kind for e in events] == [VadEventKind.SPEECH_START]

    def test_alternates_start_and_end_over_several_utterances(self) -> None:
        vad = FakeVad()
        samples = np.concatenate([voiced(1.0), silence(1.0), voiced(0.5), silence(1.0)])
        events = _feed_vad(vad, samples, 0.0)
        assert [e.kind for e in events] == [
            VadEventKind.SPEECH_START,
            VadEventKind.SPEECH_END,
            VadEventKind.SPEECH_START,
            VadEventKind.SPEECH_END,
        ]
        assert [e.t for e in events] == pytest.approx([0.0, 1.0, 2.0, 2.5])

    def test_threshold_is_configurable(self) -> None:
        quiet = (0.005 * np.sin(2 * np.pi * 150 * np.arange(16_000) / 16_000)).astype(np.float32)
        assert _feed_vad(FakeVad(), quiet, 0.0) == []
        assert [e.kind for e in _feed_vad(FakeVad(threshold=0.001), quiet, 0.0)] == [
            VadEventKind.SPEECH_START
        ]

    def test_reset_clears_the_state(self) -> None:
        vad = FakeVad()
        _feed_vad(vad, voiced(1.0), 0.0)
        assert vad.in_speech is True
        vad.reset()
        assert vad.in_speech is False
        assert [e.kind for e in _feed_vad(vad, voiced(0.2), 5.0)] == [VadEventKind.SPEECH_START]


# --------------------------------------------------------------------------------------------------
# FakeAsrEngine y su guion
# --------------------------------------------------------------------------------------------------


def _two_segments() -> list[ScriptedAsrEvent]:
    return scripted_utterance("hello there my friend", t_start=0.0, t_end=2.0) + scripted_utterance(
        "how are you", t_start=3.0, t_end=4.0
    )


def _feed_asr(asr: FakeAsrEngine, samples: np.ndarray, t0: float) -> list[AsrEvent]:
    events: list[AsrEvent] = []
    for chunk in to_chunks(samples, t0=t0):
        events.extend(asr.accept(chunk))
    return events


class TestScriptedUtterance:
    def test_builds_one_partial_per_word_and_a_final(self) -> None:
        script = scripted_utterance("hello there my friend", t_start=1.0, t_end=3.0)
        assert [e.kind for e in script] == [AsrEventKind.PARTIAL] * 4 + [AsrEventKind.FINAL]
        assert [e.text for e in script] == [
            "hello",
            "hello there",
            "hello there my",
            "hello there my friend",
            "hello there my friend",
        ]
        assert [e.at for e in script] == pytest.approx([1.5, 2.0, 2.5, 3.0, 3.7])

    def test_partials_are_stable_up_to_the_last_complete_word(self) -> None:
        script = scripted_utterance("hello there my friend", t_start=0.0, t_end=2.0)
        assert [e.stable_len for e in script[:4]] == [0, 5, 11, 14]

    def test_final_delay_and_sentence_end_are_configurable(self) -> None:
        script = scripted_utterance(
            "hi there", t_start=0.0, t_end=1.0, final_delay_s=0.2, is_sentence_end=True, language="es"
        )
        assert script[-1].at == pytest.approx(1.2)
        assert script[-1].is_sentence_end is True
        assert all(e.language == "es" for e in script)

    def test_all_entries_cover_the_utterance_times(self) -> None:
        script = scripted_utterance("a b c", t_start=2.0, t_end=3.0)
        assert all(e.t_start == 2.0 for e in script)
        assert [e.t_end for e in script] == pytest.approx([2.0 + 1 / 3, 2.0 + 2 / 3, 3.0, 3.0])

    def test_rejects_empty_text(self) -> None:
        with pytest.raises(ValueError, match="vacío"):
            scripted_utterance("   ", t_start=0.0, t_end=1.0)


class TestFakeAsrEngine:
    def test_implements_the_protocol(self) -> None:
        assert_implements(FakeAsrEngine(_two_segments()), AsrEngine)

    def test_declares_its_capabilities(self) -> None:
        asr = FakeAsrEngine()
        assert asr.name == "fake-asr"
        assert asr.capabilities.partials is True
        assert asr.capabilities.languages == frozenset({"en"})
        assert asr.capabilities.device == "cpu"

    def test_emits_each_scripted_event_in_the_chunk_that_reaches_its_time(self) -> None:
        asr = FakeAsrEngine(_two_segments())
        emitted: list[tuple[float, str]] = []
        for chunk in to_chunks(np.concatenate([voiced(2.0), silence(3.0)])):
            emitted.extend((chunk.t_end, e.text) for e in asr.accept(chunk))
        expected_at = [e.at for e in _two_segments()]
        assert len(emitted) == len(expected_at)
        for (chunk_end, _), at in zip(emitted, expected_at, strict=True):
            assert at - 1e-9 <= chunk_end <= at + 0.02 + 1e-9

    def test_assigns_segment_id_and_revision(self) -> None:
        events = _feed_asr(FakeAsrEngine(_two_segments()), np.concatenate([voiced(2.0), silence(3.0)]), 0.0)
        assert [(e.segment_id, e.revision) for e in events] == [
            (0, 0),
            (0, 1),
            (0, 2),
            (0, 3),
            (0, 4),
            (1, 0),
            (1, 1),
            (1, 2),
            (1, 3),
        ]
        assert [e.kind for e in events].count(AsrEventKind.FINAL) == 2

    def test_stable_len_of_a_final_is_the_whole_text(self) -> None:
        events = _feed_asr(FakeAsrEngine(_two_segments()), np.concatenate([voiced(2.0), silence(3.0)]), 0.0)
        finals = [e for e in events if e.kind is AsrEventKind.FINAL]
        assert [e.stable_len for e in finals] == [len(e.text) for e in finals]

    def test_emitted_at_comes_from_the_clock(self) -> None:
        clock = ManualClock()
        asr = FakeAsrEngine(scripted_utterance("hi there", t_start=0.0, t_end=0.2), clock=clock)
        clock.set(7.5)
        events = _feed_asr(asr, voiced(1.0), 0.0)
        assert events and all(e.emitted_at == 7.5 for e in events)

    def test_pure_silence_yields_nothing_even_past_the_scripted_times(self) -> None:
        asr = FakeAsrEngine(_two_segments())
        assert _feed_asr(asr, silence(6.0), 0.0) == []
        assert asr.flush() == []

    def test_scripted_events_already_due_are_emitted_when_speech_is_first_heard(self) -> None:
        asr = FakeAsrEngine(_two_segments())
        assert _feed_asr(asr, silence(1.0), 0.0) == []
        first = asr.accept(to_chunks(voiced(0.1), t0=1.0)[0])
        assert [e.text for e in first] == ["hello", "hello there"]

    def test_flush_closes_the_open_segment_with_a_final(self) -> None:
        asr = FakeAsrEngine(_two_segments())
        events = _feed_asr(asr, voiced(1.2), 0.0)
        assert [e.text for e in events] == ["hello", "hello there"]
        closed = asr.flush()
        assert len(closed) == 1
        final = closed[0]
        assert final.kind is AsrEventKind.FINAL
        assert (final.segment_id, final.revision) == (0, 2)
        assert final.text == "hello there"
        assert final.stable_len == len("hello there")
        assert asr.flush() == []

    def test_after_flush_the_rest_of_the_closed_segment_is_skipped(self) -> None:
        asr = FakeAsrEngine(_two_segments())
        _feed_asr(asr, voiced(1.2), 0.0)
        asr.flush()
        later = _feed_asr(asr, silence(4.0), 1.2)
        assert {e.segment_id for e in later} == {1}
        assert later[0].text == "how"

    def test_flush_without_an_open_segment_returns_nothing(self) -> None:
        asr = FakeAsrEngine(_two_segments())
        assert asr.flush() == []
        _feed_asr(asr, np.concatenate([voiced(2.0), silence(1.0)]), 0.0)  # el segmento 0 ya tiene FINAL
        assert asr.flush() == []

    def test_reset_discards_the_open_segment_without_emitting(self) -> None:
        asr = FakeAsrEngine(_two_segments())
        _feed_asr(asr, voiced(1.2), 0.0)
        asr.reset()
        assert asr.flush() == []
        later = _feed_asr(asr, voiced(4.0), 1.2)
        assert {e.segment_id for e in later} == {1}

    def test_close_is_idempotent_and_stops_the_events(self) -> None:
        asr = FakeAsrEngine(_two_segments())
        asr.close()
        asr.close()
        assert _feed_asr(asr, voiced(3.0), 0.0) == []
        assert asr.flush() == []

    def test_the_script_must_be_ordered_by_time(self) -> None:
        script = _two_segments()
        with pytest.raises(ValueError, match="orden"):
            FakeAsrEngine([script[3], script[0]])

    def test_explicit_stable_len_and_extra_fields_are_respected(self) -> None:
        script = [
            ScriptedAsrEvent(
                at=0.1, kind=AsrEventKind.PARTIAL, text="hello wor", t_start=0.0, t_end=0.1, stable_len=5
            ),
            ScriptedAsrEvent(
                at=0.2,
                kind=AsrEventKind.FINAL,
                text="hello world.",
                t_start=0.0,
                t_end=0.2,
                is_sentence_end=True,
                language="en",
            ),
        ]
        events = _feed_asr(FakeAsrEngine(script), voiced(0.5), 0.0)
        assert [e.stable_len for e in events] == [5, len("hello world.")]
        assert [e.is_sentence_end for e in events] == [False, True]


# --------------------------------------------------------------------------------------------------
# FakeTranslator
# --------------------------------------------------------------------------------------------------


def _request(
    text: str = "hello there my friend", mode: TranslationMode = TranslationMode.NORMAL, unit_id: int = 1
):
    unit = TranslationUnit(
        unit_id=unit_id, source_text=text, t_start=0.0, t_end=1.0, is_sentence_end=True, ready_at=1.2
    )
    return TranslationRequest(unit=unit, context=(), glossary=(), mode=mode)


class TestFakeTranslator:
    def test_implements_the_protocol(self) -> None:
        assert_implements(FakeTranslator(), Translator)

    def test_prefixes_the_source_text(self) -> None:
        result = FakeTranslator().translate(_request("hello there"))
        assert result.text == "ES: hello there"
        assert result.unit_id == 1
        assert result.mode is TranslationMode.NORMAL
        assert result.rejected is False

    def test_preserves_the_unit_id(self) -> None:
        assert FakeTranslator().translate(_request(unit_id=42)).unit_id == 42

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("a b c d", "ES: a b"),
            ("a b c d e", "ES: a b"),
            ("a b c", "ES: a"),
            ("a b", "ES: a"),
            ("a", "ES: a"),
        ],
    )
    def test_concise_keeps_half_of_the_words(self, text: str, expected: str) -> None:
        result = FakeTranslator().translate(_request(text, TranslationMode.CONCISE))
        assert result.text == expected
        assert result.mode is TranslationMode.CONCISE

    def test_without_concise_support_it_translates_normally_and_reports_normal(self) -> None:
        translator = FakeTranslator(supports_concise=False)
        assert translator.supports_concise is False
        result = translator.translate(_request("a b c d", TranslationMode.CONCISE))
        assert result.text == "ES: a b c d"
        assert result.mode is TranslationMode.NORMAL
        assert [r.mode for r in translator.calls] == [
            TranslationMode.CONCISE
        ]  # queda constancia de lo pedido

    def test_supports_concise_by_default(self) -> None:
        assert FakeTranslator().supports_concise is True

    def test_fail_times_raises_engine_error_that_many_times_then_recovers(self) -> None:
        translator = FakeTranslator(fail_times=2)
        for _ in range(2):
            with pytest.raises(EngineError) as info:
                translator.translate(_request())
            assert info.value.engine == "fake-mt"
            assert info.value.recoverable is True
        assert translator.translate(_request()).text == "ES: hello there my friend"
        assert len(translator.calls) == 3

    def test_latency_advances_a_manual_clock(self) -> None:
        clock = ManualClock(start=10.0)
        result = FakeTranslator(clock=clock, latency_s=4.0).translate(_request())
        assert result.started_at == 10.0
        assert result.finished_at == 14.0
        assert clock.now() == 14.0

    def test_without_latency_the_clock_does_not_move(self) -> None:
        clock = ManualClock(start=3.0)
        result = FakeTranslator(clock=clock).translate(_request())
        assert (result.started_at, result.finished_at) == (3.0, 3.0)

    def test_latency_sleeps_for_real_with_a_real_clock(self) -> None:
        translator = FakeTranslator(clock=SessionClock(), latency_s=0.05)
        before = time.perf_counter()
        result = translator.translate(_request())
        assert time.perf_counter() - before >= 0.04
        assert result.finished_at - result.started_at >= 0.03

    def test_rejects_negative_arguments(self) -> None:
        with pytest.raises(ValueError, match="latency_s"):
            FakeTranslator(latency_s=-1.0)
        with pytest.raises(ValueError, match="fail_times"):
            FakeTranslator(fail_times=-1)

    def test_records_the_requests_it_received(self) -> None:
        translator = FakeTranslator()
        first, second = _request("one"), _request("two", unit_id=2)
        translator.translate(first)
        translator.translate(second)
        assert translator.calls == [first, second]

    def test_close_is_idempotent(self) -> None:
        translator = FakeTranslator()
        translator.close()
        translator.close()


# --------------------------------------------------------------------------------------------------
# FakeSynthesizer
# --------------------------------------------------------------------------------------------------


def _synth_request(text: str, *, unit_id: int = 1, speed: float = 1.0) -> SynthesisRequest:
    return SynthesisRequest(unit_id=unit_id, text=text, voice=VoiceRef("es-f-fake"), speed=speed)


class TestFakeSynthesizer:
    def test_implements_the_protocol(self) -> None:
        assert_implements(FakeSynthesizer(), Synthesizer)

    def test_declares_24_khz_and_no_speed_support_by_default(self) -> None:
        synth = FakeSynthesizer()
        assert synth.sample_rate == 24_000
        assert synth.supports_speed is False
        assert synth.name == "fake-tts"

    def test_50_ms_of_tone_per_word_in_100_ms_chunks(self) -> None:
        chunks = list(FakeSynthesizer().synthesize(_synth_request("uno dos tres")))
        assert [len(c.samples) for c in chunks] == [2_400, 1_200]  # 150 ms en trozos de 100 ms
        assert [c.is_last for c in chunks] == [False, True]

    def test_an_exact_multiple_of_100_ms_ends_with_a_full_last_chunk(self) -> None:
        chunks = list(FakeSynthesizer().synthesize(_synth_request("uno dos tres cuatro")))
        assert [len(c.samples) for c in chunks] == [2_400, 2_400]
        assert [c.is_last for c in chunks] == [False, True]

    def test_a_single_word_is_a_single_last_chunk(self) -> None:
        chunks = list(FakeSynthesizer().synthesize(_synth_request("hola", unit_id=7)))
        assert len(chunks) == 1
        assert chunks[0].is_last is True
        assert chunks[0].unit_id == 7
        assert len(chunks[0].samples) == 1_200

    def test_empty_text_still_yields_one_last_chunk(self) -> None:
        chunks = list(FakeSynthesizer().synthesize(_synth_request("  ")))
        assert len(chunks) == 1
        assert chunks[0].is_last is True
        assert len(chunks[0].samples) == 1_200

    def test_chunks_are_float32_audible_and_within_range(self) -> None:
        samples = np.concatenate(
            [c.samples for c in FakeSynthesizer().synthesize(_synth_request("a b c d e"))]
        )
        assert samples.dtype == np.float32
        assert 0.05 < float(np.abs(samples).max()) <= 1.0

    def test_sample_rate_is_constant_across_chunks(self) -> None:
        chunks = list(FakeSynthesizer().synthesize(_synth_request("a b c d e f g")))
        assert {c.sample_rate for c in chunks} == {24_000}

    def test_the_tone_has_no_clicks_between_chunks(self) -> None:
        chunks = list(FakeSynthesizer().synthesize(_synth_request("a b c d e f g")))
        joined = np.concatenate([c.samples for c in chunks])
        # Un tono continuo no tiene escalones grandes entre muestras vecinas.
        assert float(np.abs(np.diff(joined)).max()) < 0.15

    def test_speed_is_ignored_when_unsupported(self) -> None:
        normal = sum(len(c.samples) for c in FakeSynthesizer().synthesize(_synth_request("a b c d")))
        fast = sum(len(c.samples) for c in FakeSynthesizer().synthesize(_synth_request("a b c d", speed=1.5)))
        assert normal == fast == 4_800

    def test_speed_shortens_the_audio_when_supported(self) -> None:
        synth = FakeSynthesizer(supports_speed=True)
        assert synth.supports_speed is True
        total = sum(len(c.samples) for c in synth.synthesize(_synth_request("a b c d", speed=1.25)))
        assert total == round(4_800 / 1.25)

    def test_synthesize_is_a_lazy_iterator(self) -> None:
        stream = FakeSynthesizer().synthesize(_synth_request("a b c"))
        assert iter(stream) is stream

    def test_lists_at_least_three_castilian_voices_of_both_genders(self) -> None:
        voices = FakeSynthesizer().list_voices()
        assert isinstance(voices, tuple)
        assert len(voices) >= 3
        assert {v.gender for v in voices} == {"f", "m"}
        assert len({v.voice_id for v in voices}) == len(voices)
        assert all(v.voice_id.isascii() and v.license and v.source for v in voices)

    def test_close_is_idempotent(self) -> None:
        synth = FakeSynthesizer()
        synth.close()
        synth.close()


# --------------------------------------------------------------------------------------------------
# ScriptedDelayController
# --------------------------------------------------------------------------------------------------


def _decision(
    speed: float, mode: TranslationMode = TranslationMode.NORMAL, drop: bool = False
) -> DelayDecision:
    return DelayDecision(speed=speed, mode=mode, drop_oldest_pending=drop)


class TestScriptedDelayController:
    def test_implements_the_protocol(self) -> None:
        assert_implements(ScriptedDelayController(), DelayController)

    def test_returns_the_scripted_decisions_in_order_and_repeats_the_last(self) -> None:
        script = [_decision(1.0), _decision(1.2), _decision(1.25, TranslationMode.CONCISE, drop=True)]
        controller = ScriptedDelayController(script)
        assert [controller.decide(lag) for lag in (0.0, 4.0, 9.0, 9.5, 0.0)] == [
            *script,
            script[-1],
            script[-1],
        ]

    def test_records_the_lags_it_received(self) -> None:
        controller = ScriptedDelayController([_decision(1.0)])
        for lag in (0.5, 3.5, 1.0):
            controller.decide(lag)
        assert controller.lags == [0.5, 3.5, 1.0]

    def test_an_empty_script_never_accelerates_summarises_or_drops(self) -> None:
        assert ScriptedDelayController().decide(100.0) == _decision(1.0)

    def test_a_function_decides_from_the_lag(self) -> None:
        controller = ScriptedDelayController(lambda lag: _decision(1.25 if lag > 3 else 1.0, drop=lag > 8))
        assert controller.decide(2.0) == _decision(1.0)
        assert controller.decide(5.0) == _decision(1.25)
        assert controller.decide(9.0) == _decision(1.25, drop=True)
        assert controller.lags == [2.0, 5.0, 9.0]

    def test_decisions_are_recorded(self) -> None:
        controller = ScriptedDelayController([_decision(1.0), _decision(1.1)])
        controller.decide(0.0)
        controller.decide(1.0)
        assert controller.decisions == [_decision(1.0), _decision(1.1)]
