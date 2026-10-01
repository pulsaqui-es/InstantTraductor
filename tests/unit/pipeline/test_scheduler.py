"""Tests del `Scheduler` (T029), con los dobles de `tests/fakes` y un `ManualClock`.

Se prueba el planificador como lo usará la sesión: el test hace de hilo de traducción (`next_translation`,
`translate`, `on_translation`), de hilo de voz (`on_tts_*` y `sink.enqueue`) y de hilo de control (`tick`).
El sink es `FakeAudioSink`, que reproduce sobre el mismo reloj manual y emite STARTED, FINISHED y CANCELLED.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Sequence

import numpy as np
import numpy.typing as npt
import pytest

from instanttraductor.contracts import (
    PLAYBACK_RATE,
    DelayController,
    DelayDecision,
    DelayPolicy,
    GlossaryEntry,
    Outcome,
    PlaybackEvent,
    PlaybackEventKind,
    SpeechPiece,
    StageTimings,
    SynthesisRequest,
    TranslationMode,
    TranslationRequest,
    TranslationResult,
    TranslationUnit,
    UtteranceRecord,
    VoiceRef,
)
from instanttraductor.pipeline.clock import ManualClock
from instanttraductor.pipeline.delay import ThresholdDelayController
from instanttraductor.pipeline.scheduler import (
    CANCELLED_REASON,
    CUT_REASON,
    DROP_REASON_LAG,
    REJECTED_REASON,
    STOP_REASON,
    Scheduler,
    UnitState,
)
from tests.fakes.fake_audio import FakeAudioSink
from tests.fakes.fake_scheduling import ScriptedDelayController
from tests.fakes.fake_synthesis import FakeSynthesizer
from tests.fakes.fake_translation import FakeTranslator

NORMAL = TranslationMode.NORMAL
CONCISE = TranslationMode.CONCISE
STARTED = PlaybackEventKind.STARTED
FINISHED = PlaybackEventKind.FINISHED
CANCELLED = PlaybackEventKind.CANCELLED
VOICE = "es-f-fake"
NEUTRAL = DelayDecision(1.0, NORMAL, False)
ALWAYS_DROP = DelayDecision(1.25, NORMAL, True)


# --------------------------------------------------------------------------------------------------
# Ayudantes
# --------------------------------------------------------------------------------------------------


def pcm(seconds: float) -> npt.NDArray[np.float32]:
    """Silencio de `seconds` s a la frecuencia del sink."""
    return np.zeros(round(seconds * PLAYBACK_RATE), dtype=np.float32)


def drop_over(threshold: float, speed: float = 1.25) -> Callable[[float], DelayDecision]:
    """Guion que pide descartar mientras el retraso supere `threshold`."""
    return lambda lag: DelayDecision(speed=speed, mode=NORMAL, drop_oldest_pending=lag > threshold)


class SpySink(FakeAudioSink):
    """`FakeAudioSink` que cuenta las llamadas a `cancel_pending`."""

    def __init__(self, clock: ManualClock) -> None:
        super().__init__(clock)
        self.cancel_calls = 0

    def cancel_pending(self) -> list[int]:
        self.cancel_calls += 1
        return super().cancel_pending()


class StubSink:
    """Sink mínimo: `cancel_pending` devuelve lo que se le pida y no emite ningún evento."""

    sample_rate = PLAYBACK_RATE

    def __init__(self, cancelled: Sequence[int] = ()) -> None:
        self.cancelled = list(cancelled)
        self.cancel_calls = 0

    def start(self, on_event: Callable[[PlaybackEvent], None]) -> None: ...

    def enqueue(self, piece: SpeechPiece) -> None: ...

    def cancel_pending(self) -> list[int]:
        self.cancel_calls += 1
        return list(self.cancelled)

    def set_volume(self, gain: float) -> None: ...

    def pending_seconds(self) -> float:
        return 0.0

    def stop(self) -> None: ...


class Rig:
    """Planificador con sus dobles: reloj manual, sink, traductor falso y registro de lo que se cierra."""

    def __init__(
        self,
        controller: DelayController | None = None,
        *,
        sink: SpySink | StubSink | None = None,
        context_utterances: int = 4,
        glossary: Sequence[GlossaryEntry | tuple[str, str]] = (),
        supports_concise: bool = True,
        latency_s: float = 0.0,
    ) -> None:
        self.clock = ManualClock()
        self.sink = sink if sink is not None else SpySink(self.clock)
        self.records: list[UtteranceRecord] = []
        self.samples: list[tuple[float, float]] = []
        self.scheduler = Scheduler(
            self.clock,
            controller if controller is not None else ScriptedDelayController(),
            self.sink,
            voice=VOICE,
            context_utterances=context_utterances,
            glossary=glossary,
            on_record=self.records.append,
            on_lag_sample=lambda t, lag: self.samples.append((t, lag)),
        )
        self.sink.start(self.scheduler.on_playback_event)
        self.translator = FakeTranslator(
            clock=self.clock, supports_concise=supports_concise, latency_s=latency_s
        )

    @property
    def fake_sink(self) -> SpySink:
        assert isinstance(self.sink, SpySink)
        return self.sink

    # --- lo que haría la sesión ---

    def add(
        self,
        unit_id: int,
        text: str | None = None,
        *,
        t_end: float | None = None,
        asr_final_at: float | None = None,
        captured_at: float | None = None,
    ) -> TranslationUnit:
        end = float(unit_id) if t_end is None else t_end
        unit = TranslationUnit(
            unit_id=unit_id,
            source_text=text if text is not None else f"sentence {unit_id}",
            t_start=end - 0.8,
            t_end=end,
            is_sentence_end=True,
            ready_at=end + 0.1,
        )
        self.scheduler.add_unit(unit, asr_final_at=asr_final_at, captured_at=captured_at)
        return unit

    def translate(self) -> SynthesisRequest | None:
        """Pide la siguiente traducción, la traduce y devuelve el resultado al planificador."""
        request = self.scheduler.next_translation()
        if request is None:
            return None
        return self.scheduler.on_translation(self.translator.translate(request))

    def speak(self, request: SynthesisRequest, seconds: float = 1.0) -> None:
        """Imita al hilo de voz: marca los tiempos y entrega al sink `seconds` s de audio, de una vez."""
        unit_id = request.unit_id
        self.scheduler.on_tts_started(unit_id)
        self.scheduler.on_tts_first_audio(unit_id)
        self.scheduler.on_tts_finished(unit_id)
        self.sink.enqueue(SpeechPiece(unit_id, pcm(seconds), is_last=True))

    def run(
        self, unit_id: int, *, seconds: float = 1.0, text: str | None = None, t_end: float | None = None
    ) -> None:
        """La frase entera: la añade, la traduce y la entrega a la voz."""
        self.add(unit_id, text, t_end=t_end)
        request = self.translate()
        assert request is not None
        self.speak(request, seconds)

    def bring_to(self, unit_id: int, stage: UnitState) -> None:
        """Añade la unidad y la lleva a `stage`, sin pasar por el sink (los eventos los pone el test)."""
        self.add(unit_id)
        if stage is UnitState.PENDING:
            return
        request = self.scheduler.next_translation()
        assert request is not None and request.unit.unit_id == unit_id
        if stage is UnitState.TRANSLATING:
            return
        self.scheduler.on_translation(self.translator.translate(request))
        if stage is UnitState.SYNTHESIZING:
            return
        self.scheduler.on_tts_first_audio(unit_id)
        if stage is UnitState.QUEUED:
            return
        self.scheduler.on_playback_event(PlaybackEvent(unit_id, STARTED, self.clock.now()))

    def record(self, unit_id: int) -> UtteranceRecord:
        found = [record for record in self.records if record.unit_id == unit_id]
        assert len(found) == 1, f"debería haber un único registro de la unidad {unit_id}: {found}"
        return found[0]

    def state(self, unit_id: int) -> UnitState | None:
        return self.scheduler.state_of(unit_id)

    def states(self, *unit_ids: int) -> list[UnitState | None]:
        return [self.scheduler.state_of(unit_id) for unit_id in unit_ids]


def rejected_result(unit_id: int, at: float = 0.0) -> TranslationResult:
    return TranslationResult(
        unit_id=unit_id, text="", mode=NORMAL, started_at=at, finished_at=at, rejected=True
    )


def assert_timings(timings: StageTimings, **expected: float | None) -> None:
    """Compara los campos pedidos de `StageTimings` (con tolerancia) y exige `None` donde se pide."""
    for name, value in expected.items():
        actual = getattr(timings, name)
        if value is None:
            assert actual is None, f"{name} debería ser None y es {actual}"
        else:
            assert actual == pytest.approx(value), f"{name}: {actual} != {value}"


# --------------------------------------------------------------------------------------------------
# Recorrido de una frase
# --------------------------------------------------------------------------------------------------


class TestLifecycle:
    def test_a_unit_goes_through_every_state_and_ends_as_spoken(self) -> None:
        rig = Rig(latency_s=0.3)
        scheduler = rig.scheduler
        unit = TranslationUnit(1, "hello world", t_start=0.2, t_end=1.0, is_sentence_end=True, ready_at=1.1)

        rig.clock.set(1.1)
        scheduler.add_unit(unit, asr_final_at=1.05, captured_at=1.04)
        assert rig.state(1) is UnitState.PENDING
        assert scheduler.open_count == 1

        rig.clock.set(1.2)
        request = scheduler.next_translation()
        assert request == TranslationRequest(unit, context=(), glossary=(), mode=NORMAL)
        assert rig.state(1) is UnitState.TRANSLATING

        result = rig.translator.translate(request)  # tarda 0,3 s: el reloj pasa a 1,5
        synthesis = scheduler.on_translation(result)
        assert synthesis == SynthesisRequest(1, "ES: hello world", VoiceRef(VOICE), speed=1.0)
        assert rig.state(1) is UnitState.SYNTHESIZING

        scheduler.on_tts_started(1, 1.5)
        assert rig.state(1) is UnitState.SYNTHESIZING
        scheduler.on_tts_first_audio(1, 1.8)
        assert rig.state(1) is UnitState.QUEUED

        rig.clock.set(1.8)
        rig.sink.enqueue(SpeechPiece(1, pcm(2.0), is_last=True))  # el sink está libre: suena enseguida
        assert rig.state(1) is UnitState.PLAYING
        scheduler.on_tts_finished(1, 1.9)
        assert rig.records == []

        rig.fake_sink.advance(2.0)
        assert rig.state(1) is UnitState.SPOKEN
        assert scheduler.open_count == 0

        record = rig.record(1)
        assert (record.source_text, record.translated_text) == ("hello world", "ES: hello world")
        assert (record.mode, record.speed) == (NORMAL, 1.0)
        assert (record.outcome, record.reason) == (Outcome.SPOKEN, None)
        assert_timings(
            record.timings,
            t_start_audio=0.2,
            t_end_audio=1.0,
            unit_ready_at=1.1,
            captured_at=1.04,
            asr_final_at=1.05,
            mt_started_at=1.2,
            mt_finished_at=1.5,
            tts_started_at=1.5,
            tts_first_audio_at=1.8,
            tts_finished_at=1.9,
            play_started_at=1.8,
            play_finished_at=3.8,
        )
        assert record.timings.sentence_delay == pytest.approx(0.8)

    def test_the_whole_chain_runs_with_the_fake_synthesizer(self) -> None:
        rig = Rig()
        rig.add(1, "good morning everybody")
        request = rig.translate()
        assert request is not None and request.text == "ES: good morning everybody"

        rig.scheduler.on_tts_started(1)
        for index, chunk in enumerate(FakeSynthesizer().synthesize(request)):
            if index == 0:
                rig.scheduler.on_tts_first_audio(1)
            if chunk.is_last:
                rig.scheduler.on_tts_finished(1)
            rig.sink.enqueue(SpeechPiece(1, np.repeat(chunk.samples, 2), is_last=chunk.is_last))
        rig.fake_sink.advance(1.0)

        assert rig.state(1) is UnitState.SPOKEN
        assert rig.record(1).outcome is Outcome.SPOKEN

    def test_every_closed_unit_gives_exactly_one_record(self) -> None:
        rig = Rig()
        for unit_id in (1, 2, 3):
            rig.run(unit_id, seconds=0.5)
        rig.fake_sink.advance(5.0)
        assert [record.unit_id for record in rig.records] == [1, 2, 3]
        assert rig.scheduler.open_count == 0

    def test_the_sink_may_start_the_unit_before_the_first_audio_is_announced(self) -> None:
        rig = Rig()
        rig.add(1)
        assert rig.translate() is not None
        rig.sink.enqueue(SpeechPiece(1, pcm(1.0), is_last=True))  # STARTED llega antes que first_audio
        assert rig.state(1) is UnitState.PLAYING
        rig.scheduler.on_tts_first_audio(1, 0.5)  # solo anota el tiempo: la frase no vuelve atrás
        assert rig.state(1) is UnitState.PLAYING
        rig.fake_sink.advance(1.0)
        record = rig.record(1)
        assert record.outcome is Outcome.SPOKEN
        assert record.timings.tts_first_audio_at == pytest.approx(0.5)

    def test_only_the_first_time_of_each_voice_stage_is_kept(self) -> None:
        rig = Rig()
        rig.add(1)
        assert rig.translate() is not None
        rig.scheduler.on_tts_started(1, 1.0)
        rig.scheduler.on_tts_started(1, 1.1)
        rig.scheduler.on_tts_first_audio(1, 1.5)
        rig.scheduler.on_tts_first_audio(1, 1.6)  # uno por trozo: solo cuenta el primero
        rig.scheduler.on_failure(1, "cierre para mirar los tiempos")
        assert_timings(rig.record(1).timings, tts_started_at=1.0, tts_first_audio_at=1.5)

    def test_a_unit_without_a_started_event_that_finishes_is_still_closed_as_spoken(self) -> None:
        rig = Rig()
        rig.add(1)
        assert rig.translate() is not None
        rig.scheduler.on_playback_event(PlaybackEvent(1, FINISHED, 4.0))
        record = rig.record(1)
        assert record.outcome is Outcome.SPOKEN
        assert record.timings.play_started_at is None
        assert record.timings.sentence_delay is None

    def test_events_for_units_that_do_not_exist_are_ignored(self) -> None:
        rig = Rig()
        rig.scheduler.on_playback_event(PlaybackEvent(99, STARTED, 1.0))
        rig.scheduler.on_playback_event(PlaybackEvent(99, FINISHED, 2.0))
        rig.scheduler.on_playback_event(PlaybackEvent(99, CANCELLED, 2.0))
        rig.scheduler.on_tts_started(99, 1.0)
        rig.scheduler.on_tts_first_audio(99, 1.0)
        rig.scheduler.on_tts_finished(99, 1.0)
        rig.scheduler.on_failure(99, "no existe")
        assert rig.records == []
        assert rig.state(99) is None

    def test_a_started_event_for_a_unit_that_has_no_audio_yet_is_ignored(self) -> None:
        rig = Rig()
        rig.add(1)
        rig.scheduler.on_playback_event(PlaybackEvent(1, STARTED, 1.0))
        assert rig.state(1) is UnitState.PENDING
        rig.scheduler.next_translation()
        rig.scheduler.on_playback_event(PlaybackEvent(1, STARTED, 1.0))
        assert rig.state(1) is UnitState.TRANSLATING

    def test_the_time_stamps_default_to_the_clock(self) -> None:
        rig = Rig()
        rig.add(1)
        assert rig.translate() is not None
        rig.clock.set(2.0)
        rig.scheduler.on_tts_started(1)
        rig.clock.set(2.4)
        rig.scheduler.on_tts_first_audio(1)
        rig.clock.set(2.9)
        rig.scheduler.on_tts_finished(1)
        rig.sink.enqueue(SpeechPiece(1, pcm(0.5), is_last=True))
        rig.fake_sink.advance(0.5)
        assert_timings(rig.record(1).timings, tts_started_at=2.0, tts_first_audio_at=2.4, tts_finished_at=2.9)


# --------------------------------------------------------------------------------------------------
# Orden FIFO y sin retraducir (FR-008)
# --------------------------------------------------------------------------------------------------


class TestFifo:
    def test_translation_requests_follow_the_order_of_the_units(self) -> None:
        rig = Rig()
        for unit_id in (1, 2, 3):
            rig.add(unit_id)
        handed_out = [rig.scheduler.next_translation() for _ in range(3)]
        assert [request.unit.unit_id for request in handed_out if request is not None] == [1, 2, 3]
        assert rig.scheduler.next_translation() is None

    def test_a_unit_is_never_handed_out_twice(self) -> None:
        rig = Rig()
        rig.add(1)
        assert rig.scheduler.next_translation() is not None
        assert rig.scheduler.next_translation() is None
        rig.add(2)
        second = rig.scheduler.next_translation()
        assert second is not None and second.unit.unit_id == 2

    def test_there_is_nothing_to_translate_without_units(self) -> None:
        assert Rig().scheduler.next_translation() is None

    def test_a_result_is_accepted_only_once(self) -> None:
        rig = Rig()
        rig.add(1)
        request = rig.scheduler.next_translation()
        assert request is not None
        result = rig.translator.translate(request)
        assert rig.scheduler.on_translation(result) is not None
        assert rig.scheduler.on_translation(result) is None  # nunca se vuelve a sintetizar
        assert rig.state(1) is UnitState.SYNTHESIZING

    def test_a_result_for_a_unit_that_was_never_handed_out_is_ignored(self) -> None:
        rig = Rig()
        rig.add(1)
        stray = TranslationResult(1, "ES: hola", NORMAL, started_at=0.0, finished_at=0.1)
        assert rig.scheduler.on_translation(stray) is None
        assert rig.state(1) is UnitState.PENDING
        stray = TranslationResult(7, "ES: hola", NORMAL, started_at=0.0, finished_at=0.1)
        assert rig.scheduler.on_translation(stray) is None

    def test_unit_ids_must_grow_strictly(self) -> None:
        rig = Rig()
        rig.add(5)
        with pytest.raises(ValueError, match="unit_id"):
            rig.add(5)
        with pytest.raises(ValueError, match="unit_id"):
            rig.add(3)
        rig.add(6)
        assert rig.scheduler.open_count == 2

    def test_units_reach_the_sink_and_finish_in_order(self) -> None:
        rig = Rig()
        for unit_id in (1, 2, 3):
            rig.run(unit_id, seconds=1.0)
        rig.fake_sink.advance(10.0)
        started = [event.unit_id for event in rig.fake_sink.events if event.kind is STARTED]
        assert started == [1, 2, 3]
        assert [record.unit_id for record in rig.records] == [1, 2, 3]
        assert all(record.outcome is Outcome.SPOKEN for record in rig.records)


# --------------------------------------------------------------------------------------------------
# Contexto y glosario (FR-006)
# --------------------------------------------------------------------------------------------------


class TestContext:
    @staticmethod
    def speak_fully(rig: Rig, unit_id: int, text: str) -> None:
        rig.run(unit_id, seconds=0.5, text=text)
        rig.fake_sink.advance(0.5)
        assert rig.state(unit_id) is UnitState.SPOKEN

    @staticmethod
    def context_of_next(rig: Rig, unit_id: int) -> tuple[tuple[str, str], ...]:
        rig.add(unit_id)
        request = rig.scheduler.next_translation()
        assert request is not None and request.unit.unit_id == unit_id
        return request.context

    def test_the_first_unit_has_no_context(self) -> None:
        assert self.context_of_next(Rig(), 1) == ()

    def test_holds_the_last_spoken_units_oldest_first(self) -> None:
        rig = Rig(context_utterances=2)
        for unit_id in (1, 2, 3):
            self.speak_fully(rig, unit_id, f"text {unit_id}")
        assert self.context_of_next(rig, 4) == (("text 2", "ES: text 2"), ("text 3", "ES: text 3"))

    def test_holds_fewer_when_fewer_have_been_spoken(self) -> None:
        rig = Rig(context_utterances=4)
        self.speak_fully(rig, 1, "text 1")
        assert self.context_of_next(rig, 2) == (("text 1", "ES: text 1"),)

    def test_is_empty_with_zero_context_utterances(self) -> None:
        rig = Rig(context_utterances=0)
        self.speak_fully(rig, 1, "text 1")
        assert self.context_of_next(rig, 2) == ()

    def test_units_that_have_not_finished_playing_are_not_context(self) -> None:
        rig = Rig()
        rig.run(1, seconds=5.0, text="playing now")
        rig.run(2, seconds=1.0, text="waiting in the queue")
        assert rig.states(1, 2) == [UnitState.PLAYING, UnitState.QUEUED]
        assert self.context_of_next(rig, 3) == ()

    def test_translated_but_unspoken_units_are_not_context(self) -> None:
        rig = Rig()
        rig.add(1)
        assert rig.translate() is not None  # traducida y sintetizando, sin sonar
        assert self.context_of_next(rig, 2) == ()

    @pytest.mark.parametrize("fate", ["rejected", "failed", "dropped"])
    def test_units_that_were_not_spoken_are_not_context(self, fate: str) -> None:
        rig = Rig(ScriptedDelayController(drop_over(8.0)))
        rig.add(1, t_end=0.5)
        request = rig.scheduler.next_translation()
        assert request is not None
        if fate == "rejected":
            rig.scheduler.on_translation(rejected_result(1))
        elif fate == "failed":
            rig.scheduler.on_failure(1, "falló")
        else:
            rig.clock.set(9.0)
            rig.scheduler.tick()
        assert rig.record(1).outcome is not Outcome.SPOKEN
        assert self.context_of_next(rig, 2) == ()

    def test_spoken_units_stay_in_the_context_when_others_are_lost(self) -> None:
        rig = Rig()
        self.speak_fully(rig, 1, "heard")
        rig.add(2)
        rig.scheduler.next_translation()
        rig.scheduler.on_failure(2, "falló")
        assert self.context_of_next(rig, 3) == (("heard", "ES: heard"),)

    def test_the_context_keeps_the_summary_that_was_actually_heard(self) -> None:
        rig = Rig(ScriptedDelayController([DelayDecision(1.25, CONCISE, False)]))
        rig.scheduler.tick()
        rig.run(1, seconds=0.5, text="one two three four")
        rig.fake_sink.advance(0.5)
        assert self.context_of_next(rig, 2) == (("one two three four", "ES: one two"),)

    def test_the_glossary_goes_into_every_request(self) -> None:
        rig = Rig(glossary=(("juice", "zumo"), GlossaryEntry("fridge", "nevera")))
        expected = (GlossaryEntry("juice", "zumo"), GlossaryEntry("fridge", "nevera"))
        for unit_id in (1, 2):
            rig.add(unit_id)
            request = rig.scheduler.next_translation()
            assert request is not None and request.glossary == expected

    def test_the_default_glossary_is_empty(self) -> None:
        rig = Rig()
        rig.add(1)
        request = rig.scheduler.next_translation()
        assert request is not None and request.glossary == ()


# --------------------------------------------------------------------------------------------------
# Retraso (data-model.md)
# --------------------------------------------------------------------------------------------------


class TestLag:
    def test_is_zero_without_units(self) -> None:
        rig = Rig()
        rig.clock.set(10.0)
        assert rig.scheduler.lag() == 0.0

    def test_is_the_age_of_the_oldest_unit_that_has_not_started(self) -> None:
        rig = Rig()
        rig.add(1, t_end=1.0)
        rig.add(2, t_end=2.0)
        rig.clock.set(4.0)
        assert rig.scheduler.lag() == pytest.approx(3.0)

    def test_keeps_counting_while_the_unit_goes_through_translation_and_synthesis(self) -> None:
        rig = Rig()
        rig.add(1, t_end=1.0)
        rig.clock.set(4.0)
        assert rig.scheduler.lag() == pytest.approx(3.0)  # PENDIENTE
        request = rig.scheduler.next_translation()
        assert request is not None
        assert rig.scheduler.lag() == pytest.approx(3.0)  # TRADUCIENDO
        assert rig.scheduler.on_translation(rig.translator.translate(request)) is not None
        assert rig.scheduler.lag() == pytest.approx(3.0)  # SINTETIZANDO
        rig.scheduler.on_tts_first_audio(1)
        assert rig.state(1) is UnitState.QUEUED
        assert rig.scheduler.lag() == pytest.approx(3.0)  # EN_COLA

    def test_is_the_age_of_the_next_unit_once_the_oldest_starts_to_sound(self) -> None:
        rig = Rig()
        rig.run(1, seconds=10.0, t_end=1.0)  # empieza a sonar en cuanto llega su audio
        rig.add(2, t_end=2.0)
        rig.clock.set(6.0)
        assert rig.state(1) is UnitState.PLAYING
        assert rig.scheduler.lag() == pytest.approx(4.0)

    def test_does_not_count_the_time_a_unit_spends_sounding(self) -> None:
        rig = Rig()
        rig.run(1, seconds=30.0, t_end=1.0)
        rig.clock.set(25.0)
        assert rig.state(1) is UnitState.PLAYING
        assert rig.scheduler.lag() == 0.0  # contarlo daría aceleraciones espurias

    def test_returns_to_zero_when_everything_has_sounded(self) -> None:
        rig = Rig()
        rig.run(1, seconds=1.0, t_end=1.0)
        rig.fake_sink.advance(5.0)
        assert rig.scheduler.lag() == 0.0

    def test_never_goes_below_zero(self) -> None:
        rig = Rig()
        rig.add(1, t_end=5.0)  # el reloj de audio va un poco por delante del de sesión
        rig.clock.set(3.0)
        assert rig.scheduler.lag() == 0.0

    def test_dropped_units_do_not_count(self) -> None:
        rig = Rig(ScriptedDelayController(drop_over(8.0)))
        rig.add(1, t_end=1.0)
        rig.add(2, t_end=8.0)
        rig.clock.set(9.5)  # la 1 tiene 8,5 s y la 2, 1,5 s
        rig.scheduler.tick()
        assert rig.state(1) is UnitState.DROPPED
        assert rig.scheduler.lag() == pytest.approx(1.5)


class TestTick:
    def test_the_controller_receives_the_current_lag_once_per_tick(self) -> None:
        controller = ScriptedDelayController()
        rig = Rig(controller)
        rig.add(1, t_end=1.0)
        for now in (2.0, 3.0, 4.5):
            rig.clock.set(now)
            rig.scheduler.tick()
        assert controller.lags == pytest.approx([1.0, 2.0, 3.5])

    def test_returns_the_decision_and_keeps_it(self) -> None:
        rig = Rig(ThresholdDelayController(DelayPolicy()))
        assert rig.scheduler.decision == NEUTRAL  # antes del primer tick
        rig.add(1, t_end=1.0)
        rig.clock.set(5.0)  # retraso de 4 s: a mitad de camino entre 1,0 y 1,25
        decision = rig.scheduler.tick()
        assert decision.speed == pytest.approx(1.125)
        assert decision.mode is NORMAL
        assert rig.scheduler.decision == decision

    def test_samples_the_lag_every_half_second(self) -> None:
        rig = Rig()
        rig.add(1, t_end=1.0)
        for now in (1.0, 1.25, 1.5, 1.75, 2.0, 2.25):
            rig.clock.set(now)
            rig.scheduler.tick()
        series = rig.scheduler.lag_series()
        assert [t for t, _ in series] == pytest.approx([1.0, 1.5, 2.0])
        assert [lag for _, lag in series] == pytest.approx([0.0, 0.5, 1.0])
        assert tuple(rig.samples) == series  # la misma serie llega al callback

    def test_samples_at_every_tick_when_the_ticks_are_slower_than_the_interval(self) -> None:
        rig = Rig()
        rig.add(1, t_end=0.0)
        for now in (1.0, 2.0, 3.0):
            rig.clock.set(now)
            rig.scheduler.tick()
        assert [t for t, _ in rig.scheduler.lag_series()] == pytest.approx([1.0, 2.0, 3.0])

    def test_the_series_holds_the_lag_before_dropping(self) -> None:
        rig = Rig(ScriptedDelayController(drop_over(8.0)))
        rig.add(1, t_end=1.0)
        rig.clock.set(9.5)
        rig.scheduler.tick()
        ((t, lag),) = rig.scheduler.lag_series()
        assert (t, lag) == (pytest.approx(9.5), pytest.approx(8.5))
        assert rig.scheduler.lag() == 0.0  # después del descarte ya no hay nada pendiente

    def test_the_series_returned_is_a_copy(self) -> None:
        rig = Rig()
        rig.scheduler.tick()
        series = rig.scheduler.lag_series()
        rig.clock.advance(1.0)
        rig.scheduler.tick()
        assert len(series) == 1 and len(rig.scheduler.lag_series()) == 2

    def test_a_custom_sampling_interval(self) -> None:
        clock = ManualClock()
        scheduler = Scheduler(clock, ScriptedDelayController(), StubSink(), voice=VOICE, lag_interval_s=2.0)
        for now in (0.0, 1.0, 2.0, 3.0, 4.0):
            clock.set(now)
            scheduler.tick()
        assert [t for t, _ in scheduler.lag_series()] == [0.0, 2.0, 4.0]

    def test_a_failing_sample_callback_does_not_break_the_tick(self) -> None:
        def broken(t: float, lag: float) -> None:
            raise RuntimeError("callback roto")

        scheduler = Scheduler(
            ManualClock(), ScriptedDelayController(), StubSink(), voice=VOICE, on_lag_sample=broken
        )
        assert scheduler.tick() == NEUTRAL
        assert len(scheduler.lag_series()) == 1


# --------------------------------------------------------------------------------------------------
# Acelerar (FR-012) y resumir (FR-013)
# --------------------------------------------------------------------------------------------------


class TestAcceleration:
    def test_the_speed_of_the_latest_decision_goes_into_the_synthesis_request(self) -> None:
        rig = Rig(ScriptedDelayController([DelayDecision(1.2, NORMAL, False)]))
        rig.scheduler.tick()
        rig.add(1)
        request = rig.translate()
        assert request is not None and request.speed == pytest.approx(1.2)
        rig.speak(request)
        rig.fake_sink.advance(2.0)
        assert rig.record(1).speed == pytest.approx(1.2)

    def test_the_speed_is_one_before_any_tick(self) -> None:
        rig = Rig()
        rig.add(1)
        request = rig.translate()
        assert request is not None and request.speed == 1.0

    def test_the_speed_is_fixed_when_the_synthesis_request_is_made(self) -> None:
        script = [DelayDecision(1.1, NORMAL, False), DelayDecision(1.25, NORMAL, False)]
        rig = Rig(ScriptedDelayController(script))
        rig.scheduler.tick()  # 1,1
        rig.add(1)
        request = rig.translate()
        rig.scheduler.tick()  # 1,25: ya no afecta a la frase 1
        assert request is not None and request.speed == pytest.approx(1.1)
        rig.speak(request)
        rig.fake_sink.advance(2.0)
        assert rig.record(1).speed == pytest.approx(1.1)

    def test_speeds_up_while_a_unit_waits_behind_a_long_one(self) -> None:
        rig = Rig(ThresholdDelayController(DelayPolicy()))
        rig.run(1, seconds=10.0, t_end=1.0)  # suena de 0 a 10 s
        rig.add(2, t_end=2.0)
        rig.clock.set(5.0)  # la 2 espera desde hace 3 s: aún sin acelerar
        assert rig.scheduler.tick().speed == pytest.approx(1.0)
        rig.clock.set(6.0)  # 4 s de retraso
        assert rig.scheduler.tick().speed == pytest.approx(1.125)
        request = rig.translate()
        assert request is not None and request.speed == pytest.approx(1.125)

    def test_a_unit_that_is_never_synthesized_keeps_speed_one(self) -> None:
        rig = Rig(ScriptedDelayController([DelayDecision(1.2, NORMAL, False)]))
        rig.scheduler.tick()
        rig.add(1)
        rig.scheduler.stop()
        assert rig.record(1).speed == 1.0


class TestConcise:
    def test_the_mode_of_the_decision_goes_into_the_translation_request(self) -> None:
        rig = Rig(ThresholdDelayController(DelayPolicy()))
        rig.add(1, t_end=1.0)
        rig.add(2, t_end=2.0)
        rig.clock.set(7.0)  # 6 s de retraso: más que el segundo umbral
        assert rig.scheduler.tick().mode is CONCISE
        request = rig.scheduler.next_translation()
        assert request is not None and request.mode is CONCISE

    def test_the_unit_is_translated_and_recorded_as_concise(self) -> None:
        rig = Rig(ThresholdDelayController(DelayPolicy()))
        rig.add(1, "this is a rather long sentence indeed", t_end=1.0)
        rig.clock.set(7.0)
        rig.scheduler.tick()
        synthesis = rig.translate()
        assert synthesis is not None and synthesis.text == "ES: this is a"  # el doble recorta a la mitad
        rig.speak(synthesis)
        rig.fake_sink.advance(2.0)
        record = rig.record(1)
        assert record.mode is CONCISE
        assert record.translated_text == "ES: this is a"

    def test_it_keeps_asking_for_summaries_until_the_backlog_is_gone(self) -> None:
        rig = Rig(ThresholdDelayController(DelayPolicy()))
        rig.add(1, t_end=1.0)
        rig.add(2, t_end=2.0)
        rig.clock.set(7.0)
        assert rig.scheduler.tick().mode is CONCISE  # la 1 espera desde hace 6 s
        first = rig.translate()
        assert first is not None
        rig.speak(first, seconds=0.5)  # la 1 suena; la 2 espera desde hace 5 s: no supera el umbral...
        assert rig.scheduler.tick().mode is CONCISE  # ...pero la histéresis mantiene el resumen
        second = rig.translate()
        assert second is not None
        rig.speak(second, seconds=0.5)
        rig.fake_sink.advance(2.0)
        assert rig.scheduler.tick().mode is NORMAL  # nada pendiente: el retraso es 0
        rig.add(3, t_end=9.0)
        request = rig.scheduler.next_translation()
        assert request is not None and request.mode is NORMAL
        assert [rig.record(n).mode for n in (1, 2)] == [CONCISE, CONCISE]

    def test_a_translator_that_answers_normal_to_a_concise_request_is_recorded_as_normal(self) -> None:
        rig = Rig(ScriptedDelayController([DelayDecision(1.25, CONCISE, False)]), supports_concise=False)
        rig.scheduler.tick()
        rig.add(1, "one two three four")
        request = rig.scheduler.next_translation()
        assert request is not None and request.mode is CONCISE  # el planificador obedece al controlador
        synthesis = rig.scheduler.on_translation(rig.translator.translate(request))
        assert synthesis is not None and synthesis.text == "ES: one two three four"
        rig.speak(synthesis)
        rig.fake_sink.advance(2.0)
        assert rig.record(1).mode is NORMAL

    @staticmethod
    def run_backlog(allow_concise: bool) -> tuple[Rig, list[TranslationMode]]:
        """Cuatro frases que esperan mientras sube el retraso de la más antigua (4, 6, 7,5 y 8,4 s)."""
        rig = Rig(
            ThresholdDelayController(DelayPolicy(allow_concise=allow_concise)),
            supports_concise=allow_concise,
        )
        for unit_id in range(1, 5):
            rig.add(unit_id, t_end=float(unit_id))
        asked: list[TranslationMode] = []
        for now in (5.0, 7.0, 8.5, 9.4):
            rig.clock.set(now)
            asked.append(rig.scheduler.tick().mode)
            request = rig.scheduler.next_translation()
            if request is not None:
                asked.append(request.mode)
                rig.scheduler.on_translation(rig.translator.translate(request))
        return rig, asked

    def test_with_concise_allowed_the_backlog_is_summarised_before_anything_is_dropped(self) -> None:
        rig, asked = self.run_backlog(allow_concise=True)
        assert CONCISE in asked
        assert {call.mode for call in rig.translator.calls} == {NORMAL, CONCISE}

    def test_with_concise_not_allowed_it_is_never_asked_for_and_it_drops_instead(self) -> None:
        rig, asked = self.run_backlog(allow_concise=False)
        assert set(asked) == {NORMAL}
        assert {call.mode for call in rig.translator.calls} == {NORMAL}
        assert rig.states(1) == [UnitState.DROPPED]  # a los 8,4 s se pasa de acelerar a descartar
        assert [(record.unit_id, record.outcome) for record in rig.records] == [(1, Outcome.DROPPED)]
        assert rig.record(1).mode is NORMAL


# --------------------------------------------------------------------------------------------------
# Descartes (FR-014)
# --------------------------------------------------------------------------------------------------


class TestDrops:
    def test_drops_the_oldest_unit_that_has_not_started(self) -> None:
        rig = Rig(ScriptedDelayController(drop_over(8.0)))
        for unit_id, t_end in ((1, 0.5), (2, 1.0), (3, 1.5)):
            rig.add(unit_id, t_end=t_end)
        rig.clock.set(8.7)  # lag 8,2 > 8; tras descartar la 1, el de la 2 es 7,7
        rig.scheduler.tick()
        assert rig.states(1, 2, 3) == [UnitState.DROPPED, UnitState.PENDING, UnitState.PENDING]

    def test_keeps_dropping_oldest_first_while_the_lag_stays_above_the_threshold(self) -> None:
        rig = Rig(ScriptedDelayController(drop_over(8.0)))
        for unit_id, t_end in ((1, 0.5), (2, 1.0), (3, 1.5), (4, 5.0)):
            rig.add(unit_id, t_end=t_end)
        rig.clock.set(9.7)  # lags: 9,2 · 8,7 · 8,2 · 4,7
        rig.scheduler.tick()
        assert rig.states(1, 2, 3, 4) == [
            UnitState.DROPPED,
            UnitState.DROPPED,
            UnitState.DROPPED,
            UnitState.PENDING,
        ]
        assert [record.unit_id for record in rig.records] == [1, 2, 3]

    def test_the_decision_returned_is_the_one_after_the_drops(self) -> None:
        rig = Rig(ScriptedDelayController(drop_over(8.0, speed=1.25)))
        rig.add(1, t_end=0.5)
        rig.clock.set(9.0)
        decision = rig.scheduler.tick()
        assert decision.drop_oldest_pending is False
        assert rig.scheduler.decision == decision

    def test_a_scripted_decision_drops_one_unit_per_tick(self) -> None:
        script = [DelayDecision(1.25, NORMAL, True), DelayDecision(1.25, NORMAL, False)]
        rig = Rig(ScriptedDelayController(script))
        rig.add(1)
        rig.add(2)
        rig.scheduler.tick()  # decide descartar → cae la 1 → decide no descartar
        assert rig.states(1, 2) == [UnitState.DROPPED, UnitState.PENDING]

    def test_a_dropped_unit_is_recorded_with_its_reason_and_what_it_had(self) -> None:
        rig = Rig(ScriptedDelayController(drop_over(8.0)))
        rig.add(1, "never translated", t_end=0.5, asr_final_at=0.6, captured_at=0.55)
        rig.clock.set(9.0)
        rig.scheduler.tick()
        record = rig.record(1)
        assert (record.outcome, record.reason) == (Outcome.DROPPED, DROP_REASON_LAG)
        assert (record.source_text, record.translated_text) == ("never translated", None)
        assert (record.mode, record.speed) == (NORMAL, 1.0)
        assert_timings(
            record.timings,
            t_end_audio=0.5,
            captured_at=0.55,
            asr_final_at=0.6,
            mt_started_at=None,
            play_started_at=None,
        )

    def test_does_not_touch_the_sink_when_the_oldest_unit_is_not_in_its_queue(self) -> None:
        rig = Rig(ScriptedDelayController(drop_over(8.0)))
        rig.add(1, t_end=0.5)
        rig.scheduler.next_translation()  # TRADUCIENDO
        rig.add(2, t_end=1.0)
        rig.clock.set(9.0)
        rig.scheduler.tick()
        assert rig.fake_sink.cancel_calls == 0
        assert rig.states(1, 2) == [UnitState.DROPPED, UnitState.PENDING]

    def test_drops_a_unit_that_is_being_synthesized_without_touching_the_sink(self) -> None:
        rig = Rig(ScriptedDelayController(drop_over(8.0)))
        rig.add(1, t_end=0.5)
        assert rig.translate() is not None
        rig.scheduler.on_tts_started(1)  # SINTETIZANDO, aún sin primer audio
        rig.clock.set(9.0)
        rig.scheduler.tick()
        assert rig.state(1) is UnitState.DROPPED
        assert rig.fake_sink.cancel_calls == 0
        assert rig.scheduler.is_open(1) is False  # la voz debe dejar de sintetizarla

    def test_cancels_the_sink_queue_when_the_oldest_unit_is_queued(self) -> None:
        rig = Rig(ScriptedDelayController(drop_over(8.0)))
        rig.run(1, seconds=30.0, t_end=1.0)  # suena
        rig.run(2, seconds=1.0, t_end=2.0)  # EN_COLA: el sink está ocupado con la 1
        rig.add(3, t_end=3.0)
        rig.scheduler.next_translation()  # la 3, TRADUCIENDO
        rig.add(4, t_end=4.0)  # PENDIENTE
        assert rig.states(1, 2, 3, 4) == [
            UnitState.PLAYING,
            UnitState.QUEUED,
            UnitState.TRANSLATING,
            UnitState.PENDING,
        ]
        rig.clock.set(12.0)  # lags: la 2, 10 s; después la 3, 9 s; después la 4, 8 s (no supera)
        rig.scheduler.tick()
        assert rig.states(1, 2, 3, 4) == [
            UnitState.PLAYING,
            UnitState.DROPPED,
            UnitState.DROPPED,
            UnitState.PENDING,
        ]
        assert rig.fake_sink.cancel_calls == 1
        assert [e.unit_id for e in rig.fake_sink.events if e.kind is CANCELLED] == [2]
        assert [record.unit_id for record in rig.records] == [2, 3]  # un único registro por unidad
        assert {record.reason for record in rig.records} == {DROP_REASON_LAG}

    def test_never_drops_the_unit_that_is_sounding(self) -> None:
        rig = Rig(ScriptedDelayController([ALWAYS_DROP]))
        rig.run(1, seconds=30.0, t_end=1.0)
        rig.clock.set(20.0)
        rig.scheduler.tick()
        assert rig.state(1) is UnitState.PLAYING
        assert rig.fake_sink.cancel_calls == 0
        assert rig.records == []

    def test_cancelling_the_sink_also_drops_the_newer_units_that_were_queued(self) -> None:
        # `AudioSink.cancel_pending()` descarta todo lo que no ha empezado, no solo la unidad más antigua.
        rig = Rig(ScriptedDelayController(drop_over(8.0)))
        rig.run(1, seconds=30.0, t_end=1.0)
        rig.run(2, seconds=1.0, t_end=2.0)
        rig.run(3, seconds=1.0, t_end=9.0)
        rig.clock.set(10.5)  # la 2 supera el umbral (8,5 s) pero la 3 no (1,5 s)
        rig.scheduler.tick()
        assert rig.states(1, 2, 3) == [UnitState.PLAYING, UnitState.DROPPED, UnitState.DROPPED]
        assert [record.unit_id for record in rig.records] == [2, 3]

    def test_gives_up_for_now_when_the_sink_does_not_cancel_the_oldest_unit(self) -> None:
        sink = StubSink(cancelled=[])  # p. ej., la unidad acababa de empezar a sonar
        rig = Rig(ScriptedDelayController([ALWAYS_DROP]), sink=sink)
        rig.bring_to(1, UnitState.QUEUED)
        rig.clock.set(20.0)
        rig.scheduler.tick()  # no debe quedarse en bucle
        assert sink.cancel_calls == 1
        assert rig.state(1) is UnitState.QUEUED
        assert rig.records == []

    def test_ignores_unit_ids_that_the_sink_reports_but_the_scheduler_does_not_know(self) -> None:
        sink = StubSink(cancelled=[1, 77])
        rig = Rig(ScriptedDelayController([ALWAYS_DROP]), sink=sink)
        rig.bring_to(1, UnitState.QUEUED)
        rig.clock.set(20.0)
        rig.scheduler.tick()
        assert rig.state(1) is UnitState.DROPPED
        assert [record.unit_id for record in rig.records] == [1]

    def test_a_translation_that_arrives_after_the_drop_is_ignored(self) -> None:
        rig = Rig(ScriptedDelayController(drop_over(8.0)))
        rig.add(1, t_end=0.5)
        request = rig.scheduler.next_translation()
        assert request is not None
        rig.clock.set(9.0)
        rig.scheduler.tick()  # se descarta mientras traducía
        assert rig.state(1) is UnitState.DROPPED
        assert rig.scheduler.on_translation(rig.translator.translate(request)) is None
        assert rig.state(1) is UnitState.DROPPED
        assert len(rig.records) == 1

    def test_late_voice_and_playback_events_of_a_dropped_unit_are_ignored(self) -> None:
        rig = Rig(ScriptedDelayController(drop_over(8.0)))
        rig.add(1, t_end=0.5)
        assert rig.translate() is not None
        rig.clock.set(9.0)
        rig.scheduler.tick()
        rig.scheduler.on_tts_started(1, 9.1)
        rig.scheduler.on_tts_first_audio(1, 9.2)
        rig.scheduler.on_tts_finished(1, 9.3)
        rig.scheduler.on_playback_event(PlaybackEvent(1, STARTED, 9.4))
        rig.scheduler.on_playback_event(PlaybackEvent(1, FINISHED, 9.5))
        rig.scheduler.on_failure(1, "tarde")
        assert rig.state(1) is UnitState.DROPPED
        assert len(rig.records) == 1 and rig.records[0].outcome is Outcome.DROPPED

    def test_nothing_is_dropped_when_the_controller_does_not_ask_for_it(self) -> None:
        rig = Rig()
        rig.add(1, t_end=0.5)
        rig.clock.set(50.0)
        rig.scheduler.tick()
        assert rig.state(1) is UnitState.PENDING and rig.records == []

    def test_the_real_controller_drops_above_the_third_threshold(self) -> None:
        rig = Rig(ThresholdDelayController(DelayPolicy()))
        rig.add(1, t_end=1.0)
        rig.add(2, t_end=2.0)
        rig.clock.set(8.9)  # 7,9 s: aún no
        rig.scheduler.tick()
        assert rig.records == []
        rig.clock.set(9.1)  # 8,1 s: descarta la 1 (la 2 queda en 7,1 s)
        rig.scheduler.tick()
        assert rig.states(1, 2) == [UnitState.DROPPED, UnitState.PENDING]


# --------------------------------------------------------------------------------------------------
# Traducción rechazada
# --------------------------------------------------------------------------------------------------


class TestRejected:
    def test_a_rejected_translation_closes_the_unit_without_synthesis(self) -> None:
        rig = Rig()
        rig.add(1, "uh huh")
        assert rig.scheduler.next_translation() is not None
        assert rig.scheduler.on_translation(rejected_result(1, at=0.4)) is None
        assert rig.state(1) is UnitState.REJECTED
        record = rig.record(1)
        assert record.outcome is Outcome.REJECTED
        assert record.reason == REJECTED_REASON
        assert record.translated_text is None
        assert_timings(record.timings, mt_finished_at=0.4, tts_started_at=None, play_started_at=None)

    def test_an_empty_translation_counts_as_rejected_even_if_it_was_not_flagged(self) -> None:
        rig = Rig()
        rig.add(1)
        rig.scheduler.next_translation()
        blank = TranslationResult(1, "  ", NORMAL, started_at=0.0, finished_at=0.1, rejected=False)
        assert rig.scheduler.on_translation(blank) is None
        assert rig.record(1).outcome is Outcome.REJECTED

    def test_the_following_units_carry_on(self) -> None:
        rig = Rig()
        rig.add(1)
        rig.add(2)
        rig.scheduler.next_translation()
        rig.scheduler.on_translation(rejected_result(1))
        synthesis = rig.translate()
        assert synthesis is not None and synthesis.unit_id == 2

    def test_a_rejected_unit_no_longer_counts_for_the_lag(self) -> None:
        rig = Rig()
        rig.add(1, t_end=1.0)
        rig.add(2, t_end=3.0)
        rig.scheduler.next_translation()
        rig.clock.set(6.0)
        assert rig.scheduler.lag() == pytest.approx(5.0)
        rig.scheduler.on_translation(rejected_result(1, at=6.0))
        assert rig.scheduler.lag() == pytest.approx(3.0)

    def test_a_late_event_does_not_reopen_it(self) -> None:
        rig = Rig()
        rig.add(1)
        rig.scheduler.next_translation()
        rig.scheduler.on_translation(rejected_result(1))
        rig.scheduler.on_playback_event(PlaybackEvent(1, STARTED, 2.0))
        assert rig.state(1) is UnitState.REJECTED and len(rig.records) == 1


# --------------------------------------------------------------------------------------------------
# Fallos (FR-018)
# --------------------------------------------------------------------------------------------------


class TestFailures:
    def test_a_failed_translation_closes_the_unit_with_the_reason(self) -> None:
        rig = Rig()
        rig.add(1, t_end=0.5)
        rig.clock.set(1.0)
        rig.scheduler.next_translation()
        rig.scheduler.on_failure(1, "traducción: el servidor no responde")
        assert rig.state(1) is UnitState.FAILED
        record = rig.record(1)
        assert (record.outcome, record.reason) == (Outcome.FAILED, "traducción: el servidor no responde")
        assert record.translated_text is None
        assert_timings(record.timings, mt_started_at=1.0, mt_finished_at=None)

    def test_a_failed_voice_closes_the_unit_and_keeps_its_translation(self) -> None:
        rig = Rig()
        rig.add(1)
        assert rig.translate() is not None
        rig.scheduler.on_tts_started(1, 0.5)
        rig.scheduler.on_failure(1, "voz: el servicio se cayó")
        record = rig.record(1)
        assert record.outcome is Outcome.FAILED
        assert record.translated_text == "ES: sentence 1"
        assert_timings(record.timings, tts_started_at=0.5, tts_first_audio_at=None)

    @pytest.mark.parametrize(
        "stage",
        [
            UnitState.PENDING,
            UnitState.TRANSLATING,
            UnitState.SYNTHESIZING,
            UnitState.QUEUED,
            UnitState.PLAYING,
        ],
    )
    def test_fails_from_any_state_before_spoken(self, stage: UnitState) -> None:
        rig = Rig()
        rig.bring_to(1, stage)
        assert rig.state(1) is stage
        rig.scheduler.on_failure(1, "falló")
        assert rig.state(1) is UnitState.FAILED
        assert rig.record(1).outcome is Outcome.FAILED

    def test_a_second_failure_report_is_ignored(self) -> None:
        rig = Rig()
        rig.add(1)
        rig.scheduler.next_translation()
        rig.scheduler.on_failure(1, "primera")
        rig.scheduler.on_failure(1, "segunda")
        assert [record.reason for record in rig.records] == ["primera"]

    def test_a_failed_unit_does_not_count_for_the_lag_and_the_others_carry_on(self) -> None:
        rig = Rig()
        rig.add(1, t_end=1.0)
        rig.add(2, t_end=2.0)
        rig.scheduler.next_translation()
        rig.scheduler.on_failure(1, "falló")
        rig.clock.set(5.0)
        assert rig.scheduler.lag() == pytest.approx(3.0)
        synthesis = rig.translate()
        assert synthesis is not None and synthesis.unit_id == 2

    def test_a_late_result_after_a_failure_is_ignored(self) -> None:
        rig = Rig()
        rig.add(1)
        request = rig.scheduler.next_translation()
        assert request is not None
        rig.scheduler.on_failure(1, "falló")
        assert rig.scheduler.on_translation(rig.translator.translate(request)) is None
        assert len(rig.records) == 1


# --------------------------------------------------------------------------------------------------
# Eventos del sink
# --------------------------------------------------------------------------------------------------


class TestPlaybackEvents:
    def test_started_marks_the_unit_as_sounding(self) -> None:
        rig = Rig()
        rig.run(1, seconds=5.0)
        assert rig.state(1) is UnitState.PLAYING
        assert rig.scheduler.open_count == 1

    def test_finished_closes_the_unit_as_spoken_at_the_time_of_the_event(self) -> None:
        rig = Rig()
        rig.clock.set(2.0)
        rig.run(1, seconds=3.0, t_end=1.0)
        rig.fake_sink.advance(10.0)  # el sink emite FINISHED con la hora simulada (5,0)
        record = rig.record(1)
        assert_timings(record.timings, play_started_at=2.0, play_finished_at=5.0)
        assert record.timings.sentence_delay == pytest.approx(1.0)

    def test_a_cancelled_unit_that_was_queued_becomes_dropped(self) -> None:
        rig = Rig()
        rig.run(1, seconds=30.0)
        rig.run(2, seconds=1.0)
        rig.sink.cancel_pending()  # lo hace alguien que no es el planificador
        record = rig.record(2)
        assert (record.outcome, record.reason) == (Outcome.DROPPED, CANCELLED_REASON)
        assert rig.state(1) is UnitState.PLAYING

    def test_a_cancelled_unit_that_was_sounding_becomes_dropped_as_cut(self) -> None:
        rig = Rig()
        rig.run(1, seconds=30.0)
        rig.clock.set(3.0)
        rig.sink.stop()
        record = rig.record(1)
        assert (record.outcome, record.reason) == (Outcome.DROPPED, CUT_REASON)
        assert record.timings.play_started_at is not None
        assert record.timings.play_finished_at is None

    def test_events_after_the_unit_closed_do_not_create_second_records(self) -> None:
        rig = Rig()
        rig.run(1, seconds=1.0)
        rig.fake_sink.advance(2.0)
        rig.scheduler.on_playback_event(PlaybackEvent(1, FINISHED, 9.0))
        rig.scheduler.on_playback_event(PlaybackEvent(1, CANCELLED, 9.0))
        assert len(rig.records) == 1 and rig.records[0].outcome is Outcome.SPOKEN


# --------------------------------------------------------------------------------------------------
# Parada
# --------------------------------------------------------------------------------------------------


class TestStop:
    @staticmethod
    def build_busy() -> Rig:
        """Una frase en cada estado: 1 suena, 2 en cola, 3 sintetizando, 4 traduciendo y 5 pendiente."""
        rig = Rig()
        rig.run(1, seconds=30.0)
        rig.run(2, seconds=1.0)
        rig.add(3)
        assert rig.translate() is not None
        rig.add(4)
        rig.scheduler.next_translation()
        rig.add(5)
        assert rig.states(1, 2, 3, 4, 5) == [
            UnitState.PLAYING,
            UnitState.QUEUED,
            UnitState.SYNTHESIZING,
            UnitState.TRANSLATING,
            UnitState.PENDING,
        ]
        return rig

    def test_everything_open_becomes_dropped_with_the_reason_stop(self) -> None:
        rig = self.build_busy()
        rig.scheduler.stop()
        assert rig.states(1, 2, 3, 4, 5) == [UnitState.DROPPED] * 5
        assert [(record.unit_id, record.outcome, record.reason) for record in rig.records] == [
            (n, Outcome.DROPPED, STOP_REASON) for n in range(1, 6)
        ]
        assert rig.scheduler.open_count == 0
        assert rig.scheduler.stopped is True

    def test_accepts_a_reason(self) -> None:
        rig = self.build_busy()
        rig.scheduler.stop("fallo del motor de voz")
        assert {record.reason for record in rig.records} == {"fallo del motor de voz"}

    def test_is_idempotent(self) -> None:
        rig = self.build_busy()
        rig.scheduler.stop()
        rig.scheduler.stop("otra vez")
        assert len(rig.records) == 5

    def test_spoken_units_keep_their_outcome(self) -> None:
        rig = Rig()
        rig.run(1, seconds=1.0)
        rig.fake_sink.advance(2.0)
        rig.add(2)
        rig.scheduler.stop()
        assert [record.outcome for record in rig.records] == [Outcome.SPOKEN, Outcome.DROPPED]

    def test_the_sink_cancelling_afterwards_does_not_duplicate_the_records(self) -> None:
        rig = self.build_busy()
        rig.scheduler.stop()
        rig.sink.stop()  # emite CANCELLED para la que suena y para las que esperan
        assert len(rig.records) == 5
        assert {record.reason for record in rig.records} == {STOP_REASON}

    def test_the_sink_may_be_stopped_first(self) -> None:
        rig = self.build_busy()
        rig.sink.stop()
        rig.scheduler.stop()
        assert len(rig.records) == 5
        assert {record.outcome for record in rig.records} == {Outcome.DROPPED}
        assert (rig.record(1).reason, rig.record(2).reason) == (CUT_REASON, CANCELLED_REASON)
        assert {rig.record(n).reason for n in (3, 4, 5)} == {STOP_REASON}

    def test_nothing_is_handed_out_after_stopping(self) -> None:
        rig = Rig()
        rig.add(1)
        rig.scheduler.stop()
        assert rig.scheduler.next_translation() is None

    def test_a_unit_that_arrives_after_stopping_is_recorded_as_dropped(self) -> None:
        rig = Rig()
        rig.scheduler.stop()
        rig.add(1, "late sentence")
        record = rig.record(1)
        assert (record.outcome, record.reason) == (Outcome.DROPPED, STOP_REASON)
        assert rig.scheduler.open_count == 0

    def test_a_late_translation_is_ignored(self) -> None:
        rig = Rig()
        rig.add(1)
        request = rig.scheduler.next_translation()
        assert request is not None
        rig.scheduler.stop()
        assert rig.scheduler.on_translation(rig.translator.translate(request)) is None
        assert len(rig.records) == 1

    def test_tick_after_stopping_is_harmless(self) -> None:
        rig = self.build_busy()
        rig.scheduler.stop()
        rig.clock.set(100.0)
        assert rig.scheduler.tick() == NEUTRAL
        assert rig.scheduler.lag() == 0.0


# --------------------------------------------------------------------------------------------------
# Bucle completo de la política: planificador + controlador real + sink simulado
# --------------------------------------------------------------------------------------------------


def simulate(
    *,
    arrival_every: float,
    units: int,
    allow_concise: bool = True,
    audio_s: float = 2.0,
    step: float = 0.25,
    max_pending_s: float = 1.0,
) -> Rig:
    """Llega una frase cada `arrival_every` s y se simula el pipeline entero hasta cerrarlas todas.

    Cada frase dura `audio_s` s de voz (la mitad si se resume) dividida por la velocidad pedida: con la
    llegada más rápida que la voz hay sobrecarga. Como en la sesión real, la voz trabaja bajo demanda: solo
    sintetiza cuando al sink le quedan menos de `max_pending_s` s por reproducir, así las decisiones de
    velocidad y de resumen se aplican a las frases que van a sonar enseguida. `tick()` cada `step` s.
    """
    rig = Rig(
        ThresholdDelayController(DelayPolicy(allow_concise=allow_concise)), supports_concise=allow_concise
    )
    scheduler = rig.scheduler
    next_arrival, added = 0.0, 0
    for _ in range(5_000):
        now = rig.clock.now()
        if added < units and now >= next_arrival - 1e-9:
            added += 1
            rig.add(added, f"unit {added} has a few words in it", t_end=now)
            next_arrival += arrival_every
        while rig.sink.pending_seconds() < max_pending_s:
            request = scheduler.next_translation()
            if request is None:
                break
            result = rig.translator.translate(request)
            synthesis = scheduler.on_translation(result)
            if synthesis is not None:
                rig.speak(synthesis, audio_s * (0.5 if result.mode is CONCISE else 1.0) / synthesis.speed)
        scheduler.tick()
        if added == units and scheduler.open_count == 0:
            return rig
        rig.fake_sink.advance(step)
    pytest.fail("la simulación no terminó: quedan frases abiertas")


class TestPolicyLoop:
    """El efecto de conjunto de FR-012 a FR-014 con un controlador real y la voz bajo demanda."""

    @staticmethod
    def max_lag(rig: Rig) -> float:
        return max(lag for _, lag in rig.scheduler.lag_series())

    @staticmethod
    def outcomes(rig: Rig) -> dict[Outcome, int]:
        return {
            outcome: sum(record.outcome is outcome for record in rig.records)
            for outcome in Outcome
            if any(record.outcome is outcome for record in rig.records)
        }

    def test_an_overload_is_absorbed_by_accelerating_and_summarising_without_dropping(self) -> None:
        rig = simulate(arrival_every=1.0, units=40)  # la voz necesita 2 s por cada 1 s de habla
        spoken = [record for record in rig.records if record.outcome is Outcome.SPOKEN]
        assert self.outcomes(rig) == {Outcome.SPOKEN: 40}
        assert any(record.speed > 1.0 for record in spoken)  # acelera...
        assert max(record.speed for record in spoken) <= 1.25 + 1e-9
        assert any(record.mode is CONCISE for record in spoken)  # ...y, con eso no basta, resume
        assert self.max_lag(rig) < 8.0  # y nunca llega a descartar

    def test_a_light_load_keeps_the_normal_speed_and_mode(self) -> None:
        rig = simulate(arrival_every=3.0, units=15)
        assert self.outcomes(rig) == {Outcome.SPOKEN: 15}
        assert {(record.speed, record.mode) for record in rig.records} == {(1.0, NORMAL)}
        assert self.max_lag(rig) < 3.0

    def test_without_concise_support_the_overload_ends_in_drops_instead_of_summaries(self) -> None:
        rig = simulate(arrival_every=1.0, units=40, allow_concise=False)
        assert all(call.mode is NORMAL for call in rig.translator.calls)
        assert all(record.mode is NORMAL for record in rig.records)
        outcomes = self.outcomes(rig)
        assert outcomes.get(Outcome.DROPPED, 0) > 0  # FR-014: descarta, aunque no se resuma
        assert outcomes[Outcome.SPOKEN] + outcomes[Outcome.DROPPED] == 40
        assert max(record.speed for record in rig.records) == pytest.approx(1.25, abs=0.05)

    def test_a_heavy_overload_drops_the_oldest_and_keeps_the_lag_bounded(self) -> None:
        rig = simulate(arrival_every=0.4, units=60)
        dropped = [record for record in rig.records if record.outcome is Outcome.DROPPED]
        assert dropped, "con una sobrecarga así, aun resumiendo, hay que descartar"
        assert {record.reason for record in dropped} == {DROP_REASON_LAG}
        assert self.max_lag(rig) <= 8.5  # el retraso se medía justo antes de cada descarte

    @pytest.mark.parametrize(
        ("arrival_every", "units", "allow_concise"),
        [(1.0, 40, True), (0.4, 60, True), (1.0, 40, False), (3.0, 15, True)],
    )
    def test_in_every_scenario_each_unit_closes_once_and_the_spoken_ones_keep_the_order(
        self, arrival_every: float, units: int, allow_concise: bool
    ) -> None:
        rig = simulate(arrival_every=arrival_every, units=units, allow_concise=allow_concise)
        assert sorted(record.unit_id for record in rig.records) == list(range(1, units + 1))
        spoken = sorted(
            (record for record in rig.records if record.outcome is Outcome.SPOKEN),
            key=lambda record: record.unit_id,
        )
        starts = [record.timings.play_started_at for record in spoken]
        assert None not in starts
        assert starts == sorted(starts)  # FR-008: suenan en el orden en que se dijeron
        assert all(record.timings.sentence_delay is not None for record in spoken)
        assert rig.scheduler.open_count == 0

    def test_the_lag_series_feeds_the_streak_metric_with_the_expected_shape(self) -> None:
        rig = simulate(arrival_every=0.4, units=60)
        series = rig.scheduler.lag_series()
        times = [t for t, _ in series]
        assert all(later - earlier >= 0.5 - 1e-9 for earlier, later in zip(times, times[1:], strict=False))
        assert tuple(rig.samples) == series


# --------------------------------------------------------------------------------------------------
# Registros, hilos y construcción
# --------------------------------------------------------------------------------------------------


class TestRecordsAndThreads:
    def test_a_failing_record_callback_does_not_break_the_scheduler(self) -> None:
        seen: list[int] = []

        def broken(record: UtteranceRecord) -> None:
            seen.append(record.unit_id)
            raise RuntimeError("callback roto")

        scheduler = Scheduler(
            ManualClock(), ScriptedDelayController(), StubSink(), voice=VOICE, on_record=broken
        )
        for unit_id in (1, 2):
            scheduler.add_unit(TranslationUnit(unit_id, "x", 0.0, 1.0, True, 1.0))
        scheduler.stop()
        assert seen == [1, 2]  # el fallo de uno no impide entregar el siguiente
        assert scheduler.open_count == 0

    def test_without_a_record_callback_nothing_breaks(self) -> None:
        scheduler = Scheduler(ManualClock(), ScriptedDelayController(), StubSink(), voice=VOICE)
        scheduler.add_unit(TranslationUnit(1, "x", 0.0, 1.0, True, 1.0))
        scheduler.stop()
        assert scheduler.state_of(1) is UnitState.DROPPED

    def test_records_are_delivered_outside_the_lock(self) -> None:
        outcomes: list[bool] = []
        holder: list[Scheduler] = []

        def probe(record: UtteranceRecord) -> None:
            # Otro hilo usa el planificador mientras este callback está en marcha: no debe bloquearse.
            worker = threading.Thread(target=holder[0].lag)
            worker.start()
            worker.join(timeout=2.0)
            outcomes.append(not worker.is_alive())

        scheduler = Scheduler(
            ManualClock(), ScriptedDelayController(), StubSink(), voice=VOICE, on_record=probe
        )
        holder.append(scheduler)
        scheduler.add_unit(TranslationUnit(1, "x", 0.0, 1.0, True, 1.0))
        scheduler.stop()
        assert outcomes == [True]

    def test_the_sink_is_called_outside_the_lock(self) -> None:
        outcomes: list[bool] = []
        holder: list[Scheduler] = []

        class ProbingSink(StubSink):
            def cancel_pending(self) -> list[int]:
                worker = threading.Thread(target=holder[0].lag)
                worker.start()
                worker.join(timeout=2.0)
                outcomes.append(not worker.is_alive())
                return super().cancel_pending()

        clock = ManualClock()
        scheduler = Scheduler(clock, ScriptedDelayController([ALWAYS_DROP]), ProbingSink(), voice=VOICE)
        holder.append(scheduler)
        scheduler.add_unit(TranslationUnit(1, "x", 0.0, 1.0, True, 1.0))
        scheduler.next_translation()
        scheduler.on_translation(TranslationResult(1, "ES: x", NORMAL, 0.0, 0.1))
        scheduler.on_tts_first_audio(1, 0.2)
        clock.set(5.0)
        scheduler.tick()
        assert outcomes == [True]

    def test_the_scheduler_can_be_driven_from_several_threads(self) -> None:
        total = 200
        clock = ManualClock()
        records: list[UtteranceRecord] = []
        scheduler = Scheduler(
            clock, ScriptedDelayController(), StubSink(), voice=VOICE, on_record=records.append
        )
        translator = FakeTranslator(clock=clock)
        handed_out: list[int] = []
        errors: list[Exception] = []
        translated = threading.Event()

        def guarded(body: Callable[[], None]) -> Callable[[], None]:
            def run() -> None:
                try:
                    body()
                except Exception as error:
                    errors.append(error)

            return run

        def producer() -> None:
            for unit_id in range(1, total + 1):
                scheduler.add_unit(TranslationUnit(unit_id, f"text {unit_id}", 0.0, 1.0, True, 1.0))

        def translation_worker() -> None:
            done = 0
            while done < total:
                request = scheduler.next_translation()
                if request is None:
                    time.sleep(0.0005)
                    continue
                handed_out.append(request.unit.unit_id)
                assert scheduler.on_translation(translator.translate(request)) is not None
                done += 1
            translated.set()

        def controller_thread() -> None:
            while not translated.is_set():
                scheduler.tick()
                scheduler.lag()
                time.sleep(0.0005)

        bodies = (producer, translation_worker, controller_thread)
        threads = [threading.Thread(target=guarded(body)) for body in bodies]
        for thread in threads:
            thread.start()
        assert translated.wait(timeout=30.0), errors
        for thread in threads:
            thread.join(timeout=10.0)
        assert not errors, errors
        assert handed_out == list(range(1, total + 1))  # FIFO y sin repetir

        for unit_id in range(1, total + 1):
            scheduler.on_playback_event(PlaybackEvent(unit_id, STARTED, float(unit_id)))
            scheduler.on_playback_event(PlaybackEvent(unit_id, FINISHED, unit_id + 0.5))
        assert [record.unit_id for record in records] == list(range(1, total + 1))
        assert all(record.outcome is Outcome.SPOKEN for record in records)
        assert scheduler.open_count == 0


class TestConstruction:
    def test_rejects_a_negative_number_of_context_utterances(self) -> None:
        with pytest.raises(ValueError, match="context_utterances"):
            Scheduler(
                ManualClock(), ScriptedDelayController(), StubSink(), voice=VOICE, context_utterances=-1
            )

    @pytest.mark.parametrize("interval", [0.0, -0.5])
    def test_rejects_a_sampling_interval_that_is_not_positive(self, interval: float) -> None:
        with pytest.raises(ValueError, match="lag_interval_s"):
            Scheduler(
                ManualClock(), ScriptedDelayController(), StubSink(), voice=VOICE, lag_interval_s=interval
            )

    def test_the_voice_can_be_given_as_a_reference(self) -> None:
        scheduler = Scheduler(
            ManualClock(), ScriptedDelayController(), StubSink(), voice=VoiceRef("es-m-fake")
        )
        scheduler.add_unit(TranslationUnit(1, "x", 0.0, 1.0, True, 1.0))
        scheduler.next_translation()
        synthesis = scheduler.on_translation(TranslationResult(1, "ES: x", NORMAL, 0.0, 0.1))
        assert synthesis is not None and synthesis.voice == VoiceRef("es-m-fake")

    def test_state_of_an_unknown_unit_is_none(self) -> None:
        scheduler = Scheduler(ManualClock(), ScriptedDelayController(), StubSink(), voice=VOICE)
        assert scheduler.state_of(1) is None

    def test_a_new_scheduler_has_nothing_open_and_is_not_stopped(self) -> None:
        scheduler = Scheduler(ManualClock(), ScriptedDelayController(), StubSink(), voice=VOICE)
        assert scheduler.open_count == 0
        assert scheduler.stopped is False
        assert scheduler.lag_series() == ()
