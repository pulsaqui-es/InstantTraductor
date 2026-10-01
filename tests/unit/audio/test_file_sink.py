"""Tests de `TimelineSink` (T036): colocación en la pista, FIFO, eventos exactos, recorte y volumen.

El reloj es manual, así que el tiempo solo pasa cuando el test lo mueve. La simulación vive en un hilo
propio: los tests esperan a que entregue sus eventos con `wait_for_events`.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator

import numpy as np
import pytest

from instanttraductor.audio.file_sink import TimelineSink
from instanttraductor.contracts import (
    PLAYBACK_RATE,
    AudioSink,
    PlaybackEvent,
    PlaybackEventKind,
    SpeechPiece,
)
from instanttraductor.pipeline.clock import ManualClock
from tests.contract.test_audio_contract import AudioSinkContract

STARTED, FINISHED, CANCELLED = (
    PlaybackEventKind.STARTED,
    PlaybackEventKind.FINISHED,
    PlaybackEventKind.CANCELLED,
)


def piece(unit_id: int, seconds: float, *, value: float = 0.5, is_last: bool = True) -> SpeechPiece:
    return SpeechPiece(
        unit_id=unit_id,
        samples=np.full(round(seconds * PLAYBACK_RATE), value, dtype=np.float32),
        is_last=is_last,
    )


class Rig:
    """Un `TimelineSink` con reloj manual, sus eventos y el hilo que los entregó."""

    def __init__(self, duration_s: float | None = 10.0) -> None:
        self.clock = ManualClock()
        self.sink = TimelineSink(self.clock, duration_s=duration_s)
        self.events: list[PlaybackEvent] = []
        self.threads: list[threading.Thread] = []
        self.sink.start(self._on_event)

    def _on_event(self, event: PlaybackEvent) -> None:
        self.threads.append(threading.current_thread())
        self.events.append(event)

    def wait_for_events(self, count: int, timeout_s: float = 3.0) -> None:
        deadline = time.perf_counter() + timeout_s
        while len(self.events) < count:
            assert time.perf_counter() < deadline, (
                f"faltan eventos ({len(self.events)}/{count}): {self.events}"
            )
            time.sleep(0.002)

    def at(self, kind: PlaybackEventKind, unit_id: int) -> float:
        (event,) = (e for e in self.events if e.unit_id == unit_id and e.kind is kind)
        return event.at

    def window(self, start_s: float, end_s: float) -> np.ndarray:
        return self.sink.track()[round(start_s * PLAYBACK_RATE) : round(end_s * PLAYBACK_RATE)]


@pytest.fixture
def rig() -> Iterator[Rig]:
    rig = Rig()
    yield rig
    rig.sink.stop()


class TestPlacement:
    def test_a_unit_lands_at_the_clock_time_of_its_first_piece(self, rig: Rig) -> None:
        rig.clock.set(0.5)
        rig.sink.enqueue(piece(1, 0.1, value=0.25))
        rig.clock.advance(0.2)
        rig.wait_for_events(2)
        track = rig.sink.track()
        assert np.all(rig.window(0.5, 0.6) == np.float32(0.25))
        assert np.count_nonzero(track) == round(0.1 * PLAYBACK_RATE)
        assert np.all(track[: round(0.5 * PLAYBACK_RATE)] == 0)

    def test_the_track_has_the_duration_of_the_input_mono_float32(self) -> None:
        rig = Rig(duration_s=2.5)
        track = rig.sink.track()
        assert track.dtype == np.float32
        assert track.ndim == 1
        assert len(track) == round(2.5 * PLAYBACK_RATE)
        assert not np.any(track)
        rig.sink.stop()

    def test_without_duration_the_track_is_as_long_as_the_sound(self) -> None:
        rig = Rig(duration_s=None)
        assert len(rig.sink.track()) == 0
        rig.clock.set(1.0)
        rig.sink.enqueue(piece(1, 0.5))
        assert len(rig.sink.track()) == round(1.5 * PLAYBACK_RATE)
        rig.sink.stop()

    def test_units_queue_up_fifo_without_overlap_and_chain_exactly(self, rig: Rig) -> None:
        rig.clock.set(1.0)
        rig.sink.enqueue(piece(1, 0.3, value=0.1))
        rig.sink.enqueue(piece(2, 0.2, value=0.2))
        rig.sink.enqueue(piece(3, 0.1, value=0.3))
        rig.clock.advance(5.0)
        rig.wait_for_events(6)
        assert [(e.unit_id, e.kind) for e in rig.events] == [
            (1, STARTED),
            (1, FINISHED),
            (2, STARTED),
            (2, FINISHED),
            (3, STARTED),
            (3, FINISHED),
        ]
        assert [e.at for e in rig.events] == pytest.approx([1.0, 1.3, 1.3, 1.5, 1.5, 1.6], abs=1e-9)
        track = rig.sink.track()
        start = round(1.0 * PLAYBACK_RATE)
        n1, n2, n3 = (round(s * PLAYBACK_RATE) for s in (0.3, 0.2, 0.1))
        assert np.all(track[start : start + n1] == np.float32(0.1))
        assert np.all(track[start + n1 : start + n1 + n2] == np.float32(0.2))
        assert np.all(track[start + n1 + n2 : start + n1 + n2 + n3] == np.float32(0.3))
        assert np.count_nonzero(track) == n1 + n2 + n3

    def test_events_carry_the_exact_simulated_instant_even_if_the_clock_jumps(self, rig: Rig) -> None:
        rig.clock.set(2.0)
        rig.sink.enqueue(piece(1, 0.25))
        rig.clock.advance(100.0)  # salto enorme: nada se pierde ni se retrasa en los eventos
        rig.wait_for_events(2)
        assert rig.at(STARTED, 1) == pytest.approx(2.0, abs=1e-9)
        assert rig.at(FINISHED, 1) == pytest.approx(2.25, abs=1e-9)

    def test_a_unit_waiting_behind_another_starts_when_it_ends_not_when_the_clock_looks(
        self, rig: Rig
    ) -> None:
        rig.sink.enqueue(piece(1, 0.5))
        rig.sink.enqueue(piece(2, 0.1))
        rig.clock.advance(3.0)
        rig.wait_for_events(4)
        assert rig.at(STARTED, 2) == pytest.approx(0.5, abs=1e-9)

    def test_pieces_of_one_unit_are_contiguous(self, rig: Rig) -> None:
        rig.sink.enqueue(piece(1, 0.1, value=0.1, is_last=False))
        rig.sink.enqueue(piece(1, 0.1, value=0.2, is_last=False))
        rig.sink.enqueue(piece(1, 0.1, value=0.3, is_last=True))
        rig.clock.advance(1.0)
        rig.wait_for_events(2)
        n = round(0.1 * PLAYBACK_RATE)
        track = rig.sink.track()
        assert np.all(track[:n] == np.float32(0.1))
        assert np.all(track[n : 2 * n] == np.float32(0.2))
        assert np.all(track[2 * n : 3 * n] == np.float32(0.3))
        assert rig.at(FINISHED, 1) == pytest.approx(0.3, abs=1e-9)

    def test_a_late_piece_leaves_a_gap_and_delays_the_end(self, rig: Rig) -> None:
        rig.sink.enqueue(piece(1, 0.1, value=0.1, is_last=False))
        rig.wait_for_events(1)
        rig.clock.set(0.4)
        rig.sink.enqueue(piece(1, 0.1, value=0.2, is_last=True))
        rig.clock.advance(1.0)
        rig.wait_for_events(2)
        assert np.all(rig.window(0.0, 0.1) == np.float32(0.1))
        assert not np.any(rig.window(0.1, 0.4))
        assert np.all(rig.window(0.4, 0.5) == np.float32(0.2))
        assert rig.at(FINISHED, 1) == pytest.approx(0.5, abs=1e-9)

    def test_the_track_is_clipped_to_the_input_duration(self) -> None:
        rig = Rig(duration_s=1.0)
        rig.clock.set(0.8)
        rig.sink.enqueue(piece(1, 0.5, value=0.5))  # se pasa 0,3 s del final de la entrada
        rig.clock.advance(5.0)
        rig.wait_for_events(2)
        track = rig.sink.track()
        assert len(track) == PLAYBACK_RATE
        assert np.count_nonzero(track) == round(0.2 * PLAYBACK_RATE)
        assert rig.at(FINISHED, 1) == pytest.approx(1.3, abs=1e-9)  # los eventos siguen siendo los reales
        rig.sink.stop()

    def test_a_unit_that_starts_after_the_end_leaves_no_trace(self) -> None:
        rig = Rig(duration_s=1.0)
        rig.clock.set(1.5)
        rig.sink.enqueue(piece(1, 0.2))
        assert not np.any(rig.sink.track())
        rig.sink.stop()

    def test_an_empty_closing_piece_starts_and_finishes_the_unit(self, rig: Rig) -> None:
        rig.sink.enqueue(piece(1, 0.0))
        rig.wait_for_events(2)
        assert [e.kind for e in rig.events] == [STARTED, FINISHED]
        assert not np.any(rig.sink.track())


class TestCancelAndStop:
    def test_stop_cuts_the_unit_that_is_sounding(self, rig: Rig) -> None:
        rig.sink.enqueue(piece(1, 0.5, value=0.5))
        rig.sink.enqueue(piece(2, 0.5, value=0.9))
        rig.wait_for_events(1)
        rig.clock.set(0.2)
        rig.sink.stop()
        rig.wait_for_events(3)
        assert rig.at(CANCELLED, 1) == pytest.approx(0.2, abs=1e-9)
        track = rig.sink.track()
        assert np.count_nonzero(track) == round(0.2 * PLAYBACK_RATE)
        assert np.all(rig.window(0.0, 0.2) == np.float32(0.5))
        assert not np.any(rig.window(0.2, 2.0))  # la 2 no llegó a sonar

    def test_cancel_pending_leaves_queued_units_out_of_the_track(self, rig: Rig) -> None:
        rig.sink.enqueue(piece(1, 0.2, value=0.5))
        rig.sink.enqueue(piece(2, 0.2, value=0.9))
        rig.wait_for_events(1)
        assert rig.sink.cancel_pending() == [2]
        rig.clock.advance(2.0)
        rig.wait_for_events(3)
        assert np.count_nonzero(rig.sink.track()) == round(0.2 * PLAYBACK_RATE)
        assert not np.any(rig.sink.track() == np.float32(0.9))

    def test_pieces_after_a_closed_unit_are_ignored(self, rig: Rig) -> None:
        rig.sink.enqueue(piece(1, 0.1, value=0.5))
        rig.clock.advance(1.0)
        rig.wait_for_events(2)
        before = rig.sink.track().copy()
        rig.sink.enqueue(piece(1, 0.1, value=0.7))
        rig.sink.stop()
        rig.sink.enqueue(piece(2, 0.1, value=0.7))
        assert np.array_equal(rig.sink.track(), before)
        assert rig.sink.pending_seconds() == 0.0

    def test_stop_waits_for_the_events_to_be_delivered(self, rig: Rig) -> None:
        rig.sink.enqueue(piece(1, 0.5))
        rig.sink.enqueue(piece(2, 0.5))
        rig.wait_for_events(1)
        rig.sink.stop()
        assert [e.kind for e in rig.events if e.unit_id == 2] == [CANCELLED]
        assert not rig.threads[-1].is_alive()

    def test_stop_without_start_is_harmless(self) -> None:
        sink = TimelineSink(ManualClock(), duration_s=1.0)
        sink.enqueue(piece(1, 0.1))
        sink.stop()
        sink.stop()


class TestDelivery:
    def test_events_come_from_the_sink_thread_not_from_the_caller(self, rig: Rig) -> None:
        rig.sink.enqueue(piece(1, 0.1))
        rig.sink.cancel_pending()
        rig.clock.advance(1.0)
        rig.wait_for_events(2)
        assert all(t is not threading.current_thread() for t in rig.threads)
        assert len({t.ident for t in rig.threads}) == 1

    def test_a_callback_can_call_back_into_the_sink(self) -> None:
        clock = ManualClock()
        sink = TimelineSink(clock, duration_s=5.0)
        seen: list[PlaybackEvent] = []

        def on_event(event: PlaybackEvent) -> None:
            seen.append(event)
            sink.pending_seconds()
            if event.unit_id == 1 and event.kind is FINISHED:
                sink.enqueue(piece(2, 0.1))

        sink.start(on_event)
        sink.enqueue(piece(1, 0.1))
        clock.advance(0.5)
        deadline = time.perf_counter() + 3.0
        while len(seen) < 4 and time.perf_counter() < deadline:
            clock.advance(0.01)
            time.sleep(0.003)
        sink.stop()
        assert [(e.unit_id, e.kind) for e in seen[:4]] == [
            (1, STARTED),
            (1, FINISHED),
            (2, STARTED),
            (2, FINISHED),
        ]

    def test_a_failing_callback_does_not_kill_the_thread(self) -> None:
        clock = ManualClock()
        sink = TimelineSink(clock, duration_s=5.0)
        calls: list[PlaybackEvent] = []

        def on_event(event: PlaybackEvent) -> None:
            calls.append(event)
            raise RuntimeError("fallo del receptor")

        sink.start(on_event)
        sink.enqueue(piece(1, 0.1))
        clock.advance(1.0)
        deadline = time.perf_counter() + 3.0
        while len(calls) < 2 and time.perf_counter() < deadline:
            time.sleep(0.002)
        sink.stop()
        assert [e.kind for e in calls] == [STARTED, FINISHED]

    def test_follows_the_clock_without_being_asked(self, rig: Rig) -> None:
        rig.sink.enqueue(piece(1, 0.2))
        rig.wait_for_events(1)
        assert rig.sink.pending_seconds() == pytest.approx(0.2, abs=1e-6)
        rig.clock.advance(0.1)
        assert rig.sink.pending_seconds() == pytest.approx(0.1, abs=1e-6)
        rig.clock.advance(0.2)
        rig.wait_for_events(2)  # sin llamar a nada del sink: lo ha notado el hilo
        assert rig.at(FINISHED, 1) == pytest.approx(0.2, abs=1e-9)


class TestVolume:
    def test_volume_is_applied_when_rendering(self, rig: Rig) -> None:
        rig.sink.enqueue(piece(1, 0.1, value=0.25))
        rig.clock.advance(1.0)
        rig.wait_for_events(2)
        assert float(np.max(rig.sink.track())) == pytest.approx(0.25)
        rig.sink.set_volume(2.0)
        assert float(np.max(rig.sink.track())) == pytest.approx(0.5)
        rig.sink.set_volume(0.0)
        assert not np.any(rig.sink.track())

    def test_volume_is_clamped_and_must_be_finite(self, rig: Rig) -> None:
        rig.sink.enqueue(piece(1, 0.1, value=0.25))
        rig.sink.set_volume(9.0)
        assert float(np.max(rig.sink.track())) == pytest.approx(0.5)
        rig.sink.set_volume(-1.0)
        assert not np.any(rig.sink.track())
        with pytest.raises(ValueError):
            rig.sink.set_volume(float("nan"))

    def test_track_does_not_mutate_the_pieces(self, rig: Rig) -> None:
        original = piece(1, 0.1, value=0.25)
        rig.sink.enqueue(original)
        rig.sink.set_volume(2.0)
        rig.sink.track()
        assert float(np.max(original.samples)) == pytest.approx(0.25)


class TestValidation:
    def test_rejects_a_bad_duration(self) -> None:
        with pytest.raises(ValueError):
            TimelineSink(ManualClock(), duration_s=-1.0)
        with pytest.raises(ValueError):
            TimelineSink(ManualClock(), duration_s=float("inf"))


# --------------------------------------------------------------------------------------------------
# Contrato
# --------------------------------------------------------------------------------------------------


class TestTimelineSinkContract(AudioSinkContract):
    """La suite de contrato con reloj manual: el tiempo pasa al moverlo y dejar respirar al hilo."""

    @pytest.fixture
    def make_impl(self) -> Callable[[], AudioSink]:
        return lambda: TimelineSink(ManualClock(), duration_s=30.0)

    @pytest.fixture
    def let_time_pass(self) -> Callable[[AudioSink, float], None]:
        def advance(sink: AudioSink, seconds: float) -> None:
            sink._clock.advance(seconds)  # type: ignore[attr-defined]  # noqa: SLF001
            time.sleep(0.003)  # el hilo de la simulación tiene que enterarse

        return advance
