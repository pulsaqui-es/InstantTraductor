"""Tests de `DeviceSink` (T023) sin dispositivo: un *backend* falso y un `ManualClock`.

El test hace de hilo de audio: llama a `render` (lo que miniaudio llamaría cada 20 ms) y avanza el reloj lo
que dura cada bloque. Los eventos salen por el hilo de eventos real del sink; `flush_events` espera a que
lleguen. Los tests con el dispositivo real están en `tests/integration/test_playback_device.py` (marcador
`device`).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterable
from types import SimpleNamespace
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

from instanttraductor.audio import wasapi_playback
from instanttraductor.audio.wasapi_playback import (
    CHANNELS,
    LATE_CALLBACK_S,
    DeviceSink,
    NotificationCallback,
    RenderCallback,
)
from instanttraductor.contracts import (
    PLAYBACK_RATE,
    AudioSink,
    EngineError,
    PlaybackEvent,
    PlaybackEventKind,
    SpeechPiece,
)
from instanttraductor.pipeline.clock import ManualClock
from tests.contract.test_audio_contract import AudioSinkContract

Samples = npt.NDArray[np.float32]

STARTED, FINISHED, CANCELLED = (
    PlaybackEventKind.STARTED,
    PlaybackEventKind.FINISHED,
    PlaybackEventKind.CANCELLED,
)

BLOCK = 960  # 20 ms a 48 kHz: el periodo del dispositivo
BLOCK_S = BLOCK / PLAYBACK_RATE


def voice(n: int, value: float = 0.25) -> Samples:
    return np.full(n, value, dtype=np.float32)


def piece(unit_id: int, samples: Samples, *, last: bool = True) -> SpeechPiece:
    return SpeechPiece(unit_id=unit_id, samples=samples, is_last=last)


# --------------------------------------------------------------------------------------------------
# Dispositivo falso y montaje
# --------------------------------------------------------------------------------------------------


class FakeStream:
    """Un dispositivo «abierto»: guarda lo que el sink le dio (`render`, `notify`) y si se cerró."""

    def __init__(self, render: RenderCallback, notify: NotificationCallback) -> None:
        self.render = render
        self.notify = notify
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeBackend:
    """`PlaybackBackend` falso: anota las aperturas y puede fallar en las indicadas (la 0 es la primera)."""

    def __init__(self, fail_on: Iterable[int] = ()) -> None:
        self.fail_on = set(fail_on)
        self.attempts = 0
        self.streams: list[FakeStream] = []
        self._changed = threading.Condition()

    def open(self, render: RenderCallback, notify: NotificationCallback) -> FakeStream:
        with self._changed:
            index = self.attempts
            self.attempts += 1
            try:
                if index in self.fail_on:
                    raise OSError("sin dispositivo (simulado)")
                stream = FakeStream(render, notify)
                self.streams.append(stream)
                return stream
            finally:
                self._changed.notify_all()

    def wait_for(self, condition: Callable[[], bool], timeout_s: float = 3.0) -> bool:
        with self._changed:
            return self._changed.wait_for(condition, timeout=timeout_s)


def wait_until(condition: Callable[[], bool], timeout_s: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while not condition():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.002)
    return True


class Rig:
    """`DeviceSink` con dispositivo falso y reloj manual, sin arrancar (`rig.start()` lo hace)."""

    def __init__(self, *, fail_on: Iterable[int] = (), **kwargs: Any) -> None:
        self.clock = ManualClock()
        self.backend = FakeBackend(fail_on)
        self.warnings: list[str] = []
        self.events: list[PlaybackEvent] = []
        self.output: list[Samples] = []  # lo que recibió el dispositivo, bloque a bloque
        kwargs.setdefault("on_warning", self.warnings.append)
        kwargs.setdefault("reopen_delays_s", (0.0, 0.005))
        self.sink = DeviceSink(self.clock, backend=self.backend, **kwargs)
        self._debt = 0.0

    def start(self) -> Rig:
        self.sink.start(self.events.append)
        return self

    @property
    def stream(self) -> FakeStream:
        return self.backend.streams[-1]

    def pull(self, frames: int = BLOCK, *, advance: bool = True) -> Samples:
        """Una petición de datos del dispositivo en el instante actual; luego avanza el reloj lo que dura."""
        out = self.stream.render(frames)
        self.output.append(out)
        if advance:
            self.clock.advance(frames / PLAYBACK_RATE)
        return out

    def run(self, seconds: float) -> None:
        """Deja pasar `seconds` de reproducción (bloques de 20 ms) y espera a que se entreguen los eventos."""
        self._debt += seconds
        while self._debt >= BLOCK_S - 1e-12 and not self.stream.closed:
            self.pull()
            self._debt -= BLOCK_S
        self.sink.flush_events()

    def heard(self) -> Samples:
        """El canal izquierdo de todo lo que recibió el dispositivo."""
        return np.concatenate([out[:, 0] for out in self.output]) if self.output else voice(0)

    def kinds(self, unit_id: int) -> list[PlaybackEventKind]:
        return [e.kind for e in list(self.events) if e.unit_id == unit_id]

    def event(self, unit_id: int, kind: PlaybackEventKind) -> PlaybackEvent:
        (found,) = (e for e in list(self.events) if e.unit_id == unit_id and e.kind is kind)
        return found


@pytest.fixture
def rig() -> Iterable[Rig]:
    rig = Rig().start()
    yield rig
    rig.sink.stop()


# --------------------------------------------------------------------------------------------------
# Formato y reproducción
# --------------------------------------------------------------------------------------------------


class TestRender:
    def test_the_output_is_float32_stereo_with_the_voice_in_both_channels(self, rig: Rig) -> None:
        samples = np.linspace(-0.5, 0.5, 2000, dtype=np.float32)
        rig.sink.enqueue(piece(1, samples))
        out = rig.pull()
        assert out.shape == (BLOCK, CHANNELS)
        assert out.dtype == np.float32
        assert np.array_equal(out[:, 0], samples[:BLOCK])
        assert np.array_equal(out[:, 1], samples[:BLOCK])

    def test_it_is_silent_when_there_is_nothing_to_play(self, rig: Rig) -> None:
        rig.run(0.2)
        assert not rig.heard().any()
        assert rig.events == []
        assert rig.sink.underruns == 0

    def test_a_unit_plays_its_audio_exactly_once_and_in_order(self, rig: Rig) -> None:
        samples = np.random.default_rng(1).uniform(-0.8, 0.8, 5000).astype(np.float32)
        rig.sink.enqueue(piece(1, samples))
        rig.run(0.3)
        heard = rig.heard()
        assert np.array_equal(heard[:5000], samples)
        assert not heard[5000:].any()

    @pytest.mark.parametrize("frames", [441, 960, 1024, 4800])
    def test_it_adapts_to_any_block_size(self, rig: Rig, frames: int) -> None:
        samples = np.random.default_rng(2).uniform(-0.5, 0.5, 6000).astype(np.float32)
        rig.sink.enqueue(piece(1, samples))
        for _ in range(-(-6000 // frames) + 1):
            rig.pull(frames)
        assert np.array_equal(rig.heard()[:6000], samples)
        assert rig.sink.flush_events()
        assert rig.kinds(1) == [STARTED, FINISHED]

    def test_pieces_of_a_unit_play_contiguously_even_when_they_arrive_while_it_sounds(self, rig: Rig) -> None:
        rng = np.random.default_rng(3)
        parts = [rng.uniform(-0.5, 0.5, n).astype(np.float32) for n in (700, 1300, 500)]
        rig.sink.enqueue(piece(1, parts[0], last=False))
        rig.pull()  # suena el primer trozo entero y 260 muestras de silencio
        rig.sink.enqueue(piece(1, parts[1], last=False))
        rig.sink.enqueue(piece(1, parts[2]))
        rig.run(0.2)
        heard = rig.heard()
        assert np.array_equal(heard[:700], parts[0])
        # el hueco entre el primer trozo y el segundo es silencio (un underrun), no audio de otra unidad
        assert not heard[700:960].any()
        assert np.array_equal(heard[960 : 960 + 1800], np.concatenate(parts[1:]))
        assert rig.kinds(1) == [STARTED, FINISHED]

    def test_a_piece_with_a_wrong_shape_is_rejected(self, rig: Rig) -> None:
        with pytest.raises(ValueError, match="mono"):
            rig.sink.enqueue(piece(1, np.zeros((100, 2), dtype=np.float32)))

    def test_non_float32_audio_is_converted(self, rig: Rig) -> None:
        rig.sink.enqueue(piece(1, np.full(100, 0.5)))  # float64
        assert rig.pull()[:100, 0].dtype == np.float32
        assert rig.heard()[0] == np.float32(0.5)


# --------------------------------------------------------------------------------------------------
# Eventos y horas
# --------------------------------------------------------------------------------------------------


class TestEvents:
    def test_started_and_finished_carry_the_session_clock_of_the_delivery(self, rig: Rig) -> None:
        rig.clock.advance(3.0)
        rig.sink.enqueue(piece(1, voice(4800)))  # 0,1 s = 5 bloques
        rig.run(0.2)
        assert rig.event(1, STARTED).at == pytest.approx(3.0)
        assert rig.event(1, FINISHED).at == pytest.approx(3.1)  # = STARTED + duración

    def test_a_unit_that_starts_in_the_middle_of_a_block_is_stamped_with_its_position(self, rig: Rig) -> None:
        rig.sink.enqueue(piece(1, voice(1440, 0.1)))  # 1,5 bloques
        rig.sink.enqueue(piece(2, voice(960, 0.2)))
        rig.run(0.1)
        assert rig.event(1, FINISHED).at == pytest.approx(0.03)
        assert rig.event(2, STARTED).at == pytest.approx(0.03)  # sin hueco entre las dos
        assert rig.event(2, FINISHED).at == pytest.approx(0.05)
        heard = rig.heard()
        assert np.all(heard[:1440] == np.float32(0.1))
        assert np.all(heard[1440:2400] == np.float32(0.2))  # la segunda sigue a la primera sin silencio
        assert not heard[2400:].any()

    def test_units_play_one_at_a_time_in_fifo_order(self, rig: Rig) -> None:
        for unit_id in (1, 2, 3):
            rig.sink.enqueue(piece(unit_id, voice(2000, unit_id / 10)))
        rig.run(0.3)
        assert [(e.unit_id, e.kind) for e in rig.events] == [
            (1, STARTED),
            (1, FINISHED),
            (2, STARTED),
            (2, FINISHED),
            (3, STARTED),
            (3, FINISHED),
        ]
        times = [e.at for e in rig.events]
        assert times == sorted(times)

    def test_a_unit_waits_for_its_turn_even_if_it_is_enqueued_first_while_another_sounds(
        self, rig: Rig
    ) -> None:
        rig.sink.enqueue(piece(1, voice(1920, 0.1), last=False))  # sin acabar: bloquea a las siguientes
        rig.sink.enqueue(piece(2, voice(960, 0.2)))
        rig.run(0.1)
        assert rig.kinds(1) == [STARTED]
        assert rig.kinds(2) == []
        assert not (rig.heard() == np.float32(0.2)).any()  # la 2 no se cuela en medio de la 1
        rig.sink.enqueue(piece(1, voice(0), last=True))  # un trozo vacío cierra la unidad
        rig.run(0.1)
        assert rig.kinds(1) == [STARTED, FINISHED]
        assert rig.kinds(2) == [STARTED, FINISHED]

    def test_an_empty_unit_starts_and_finishes_at_once(self, rig: Rig) -> None:
        rig.sink.enqueue(piece(1, voice(0)))
        rig.run(0.04)
        assert rig.kinds(1) == [STARTED, FINISHED]
        assert rig.event(1, STARTED).at == rig.event(1, FINISHED).at

    def test_a_unit_without_audio_yet_does_not_start(self, rig: Rig) -> None:
        rig.sink.enqueue(piece(1, voice(0), last=False))
        rig.run(0.1)
        assert rig.events == []
        assert rig.sink.underruns == 0  # nada que reproducir no es un underrun
        rig.sink.enqueue(piece(1, voice(100)))
        rig.run(0.04)
        assert rig.kinds(1) == [STARTED, FINISHED]

    def test_pieces_of_a_finished_unit_are_ignored(self, rig: Rig) -> None:
        rig.sink.enqueue(piece(1, voice(960)))
        rig.run(0.04)
        rig.sink.enqueue(piece(1, voice(960, 0.9), last=False))
        rig.run(0.1)
        assert rig.kinds(1) == [STARTED, FINISHED]
        assert not (rig.heard() == np.float32(0.9)).any()

    def test_a_failing_event_callback_does_not_stop_the_delivery(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        delivered: list[PlaybackEvent] = []

        def on_event(event: PlaybackEvent) -> None:
            delivered.append(event)
            if len(delivered) == 1:
                raise RuntimeError("fallo del suscriptor")

        rig = Rig()
        rig.sink.start(on_event)
        try:
            rig.sink.enqueue(piece(1, voice(960)))
            with caplog.at_level(logging.ERROR):
                rig.run(0.1)
            assert [e.kind for e in delivered] == [STARTED, FINISHED]
            assert "fallo del suscriptor" in caplog.text
        finally:
            rig.sink.stop()

    def test_the_audio_thread_never_runs_the_event_callback(self) -> None:
        callers: list[str] = []
        rig = Rig()
        rig.sink.start(lambda event: callers.append(threading.current_thread().name))
        try:
            rig.sink.enqueue(piece(1, voice(960)))
            rig.run(0.1)
            assert callers
            assert set(callers) == {"reproduccion-eventos"}
        finally:
            rig.sink.stop()

    def test_flush_events_waits_for_the_delivery(self) -> None:
        release = threading.Event()
        seen: list[PlaybackEvent] = []

        def slow(event: PlaybackEvent) -> None:
            release.wait(2.0)
            seen.append(event)

        rig = Rig()
        rig.sink.start(slow)
        try:
            rig.sink.enqueue(piece(1, voice(960)))
            rig.pull()
            assert rig.sink.flush_events(timeout_s=0.05) is False  # el callback aún no ha vuelto
            release.set()
            assert rig.sink.flush_events() is True
            assert len(seen) == 2
        finally:
            release.set()
            rig.sink.stop()


# --------------------------------------------------------------------------------------------------
# Cancelar y parar
# --------------------------------------------------------------------------------------------------


class TestCancelAndStop:
    def test_cancel_pending_discards_only_what_has_not_started(self, rig: Rig) -> None:
        rig.sink.enqueue(piece(1, voice(4800, 0.1)))
        rig.pull()
        rig.sink.enqueue(piece(2, voice(960, 0.2)))
        rig.sink.enqueue(piece(3, voice(960, 0.3)))
        assert rig.sink.cancel_pending() == [2, 3]
        rig.run(0.2)
        assert rig.kinds(1) == [STARTED, FINISHED]
        assert rig.kinds(2) == [CANCELLED]
        assert rig.kinds(3) == [CANCELLED]
        assert not (rig.heard() == np.float32(0.2)).any()
        assert not (rig.heard() == np.float32(0.3)).any()

    def test_a_unit_enqueued_but_not_yet_started_is_cancelled(self, rig: Rig) -> None:
        rig.sink.enqueue(piece(1, voice(960)))  # el dispositivo aún no ha pedido datos
        assert rig.sink.cancel_pending() == [1]
        rig.run(0.1)
        assert rig.kinds(1) == [CANCELLED]
        assert not rig.heard().any()

    def test_cancel_pending_with_nothing_pending_returns_an_empty_list(self, rig: Rig) -> None:
        assert rig.sink.cancel_pending() == []
        rig.sink.enqueue(piece(1, voice(4800)))
        rig.pull()
        assert rig.sink.cancel_pending() == []
        rig.run(0.2)
        assert rig.kinds(1) == [STARTED, FINISHED]

    def test_late_pieces_of_a_cancelled_unit_are_ignored(self, rig: Rig) -> None:
        rig.sink.enqueue(piece(1, voice(4800, 0.1)))
        rig.pull()
        rig.sink.enqueue(piece(2, voice(960, 0.2), last=False))
        assert rig.sink.cancel_pending() == [2]
        rig.sink.enqueue(piece(2, voice(960, 0.2)))  # el resto de la síntesis llega tarde
        rig.run(0.3)
        assert rig.kinds(2) == [CANCELLED]
        assert not (rig.heard() == np.float32(0.2)).any()
        assert rig.sink.pending_seconds() == pytest.approx(0.0)

    def test_stop_cuts_what_sounds_and_cancels_everything_in_order(self, rig: Rig) -> None:
        for unit_id in (1, 2, 3):
            rig.sink.enqueue(piece(unit_id, voice(4800)))
        rig.pull()
        rig.sink.stop()
        # `stop()` entrega los eventos antes de volver: no hace falta `flush_events`.
        assert [(e.unit_id, e.kind) for e in rig.events] == [
            (1, STARTED),
            (1, CANCELLED),
            (2, CANCELLED),
            (3, CANCELLED),
        ]
        assert rig.stream.closed
        assert rig.sink.pending_seconds() == 0.0

    def test_after_stop_nothing_more_is_played_or_emitted(self, rig: Rig) -> None:
        rig.sink.enqueue(piece(1, voice(4800)))
        rig.pull()
        rig.sink.stop()
        events = list(rig.events)
        assert not rig.stream.render(BLOCK).any()  # un último bloque rezagado sale en silencio
        rig.sink.enqueue(piece(2, voice(960)))  # y no se encola nada más
        assert rig.sink.pending_seconds() == 0.0
        assert rig.sink.cancel_pending() == []
        assert rig.events == events

    def test_stop_is_idempotent(self, rig: Rig) -> None:
        rig.sink.enqueue(piece(1, voice(4800)))
        rig.pull()
        rig.sink.stop()
        events = list(rig.events)
        rig.sink.stop()
        assert rig.events == events
        assert rig.backend.attempts == 1

    def test_stop_without_start_or_with_nothing_queued_is_harmless(self) -> None:
        Rig().sink.stop()
        rig = Rig().start()
        rig.sink.stop()
        assert rig.events == []
        assert rig.stream.closed

    def test_the_threads_end_with_stop(self) -> None:
        rig = Rig().start()
        sink = rig.sink
        sink.stop()
        assert sink._dispatcher is not None and not sink._dispatcher.is_alive()
        assert sink._supervisor is not None and not sink._supervisor.is_alive()

    def test_stop_from_inside_an_event_callback_does_not_deadlock(self) -> None:
        rig = Rig()
        sink = rig.sink
        stopped = threading.Event()

        def on_event(event: PlaybackEvent) -> None:
            rig.events.append(event)
            if event.kind is STARTED:
                sink.stop()
                stopped.set()

        sink.start(on_event)
        sink.enqueue(piece(1, voice(4800)))
        rig.pull()
        assert stopped.wait(2.0)
        assert wait_until(lambda: any(e.kind is CANCELLED for e in rig.events))
        assert rig.stream.closed


# --------------------------------------------------------------------------------------------------
# Volumen y pending_seconds
# --------------------------------------------------------------------------------------------------


class TestVolume:
    def test_the_gain_scales_only_the_voice(self, rig: Rig) -> None:
        rig.sink.set_volume(0.5)
        rig.sink.enqueue(piece(1, voice(960, 0.4)))
        rig.pull()  # el primer bloque lleva la rampa hasta el nuevo volumen
        rig.sink.enqueue(piece(2, voice(960, 0.4)))
        out = rig.pull()
        assert np.allclose(out[:, 0], 0.2)
        assert np.array_equal(out[:, 0], out[:, 1])

    def test_a_change_of_volume_is_applied_with_a_ramp_inside_the_next_block(self, rig: Rig) -> None:
        rig.sink.enqueue(piece(1, voice(4800, 0.5)))
        assert np.all(rig.pull()[:, 0] == np.float32(0.5))
        rig.sink.set_volume(0.0)
        ramp = rig.pull()[:, 0]
        assert ramp[0] < 0.5
        assert ramp[-1] == pytest.approx(0.0, abs=1e-6)
        assert np.all(np.diff(ramp) <= 1e-7)  # baja sin saltos
        assert not rig.pull().any()  # y los bloques siguientes ya salen a volumen 0

    def test_a_gain_above_one_is_limited_to_full_scale(self, rig: Rig) -> None:
        rig.sink.set_volume(2.0)
        rig.sink.enqueue(piece(1, voice(4800, 0.9)))
        rig.pull()
        out = rig.pull()
        assert float(np.max(out)) == 1.0
        assert float(np.min(out)) >= -1.0

    def test_zero_gain_is_silent_but_the_unit_still_plays_through(self, rig: Rig) -> None:
        rig.sink.set_volume(0.0)
        rig.sink.enqueue(piece(1, voice(2000)))
        rig.run(0.2)
        assert rig.kinds(1) == [STARTED, FINISHED]
        assert not rig.heard()[960:].any()

    @pytest.mark.parametrize(
        ("asked", "applied"), [(-1.0, 0.0), (0.0, 0.0), (1.3, 1.3), (2.0, 2.0), (9.0, 2.0)]
    )
    def test_the_volume_is_clamped_to_the_range(self, rig: Rig, asked: float, applied: float) -> None:
        rig.sink.set_volume(asked)
        assert rig.sink.volume == applied

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
    def test_a_non_finite_volume_is_rejected(self, rig: Rig, bad: float) -> None:
        with pytest.raises(ValueError, match="finito"):
            rig.sink.set_volume(bad)
        assert rig.sink.volume == 1.0


class TestPendingSeconds:
    def test_it_counts_what_has_not_been_delivered_yet(self, rig: Rig) -> None:
        assert rig.sink.pending_seconds() == 0.0
        rig.sink.enqueue(piece(1, voice(4800), last=False))
        rig.sink.enqueue(piece(1, voice(2400)))
        rig.sink.enqueue(piece(2, voice(2400)))
        assert rig.sink.pending_seconds() == pytest.approx(0.2)
        rig.pull()  # 20 ms entregados
        assert rig.sink.pending_seconds() == pytest.approx(0.18)
        rig.run(0.5)
        assert rig.sink.pending_seconds() == pytest.approx(0.0, abs=1e-9)

    def test_cancelled_audio_no_longer_counts(self, rig: Rig) -> None:
        rig.sink.enqueue(piece(1, voice(4800)))
        rig.sink.enqueue(piece(2, voice(4800)))
        rig.pull()
        rig.sink.cancel_pending()
        assert rig.sink.pending_seconds() == pytest.approx(0.08)


# --------------------------------------------------------------------------------------------------
# Underruns
# --------------------------------------------------------------------------------------------------


class TestUnderruns:
    def test_a_unit_that_runs_out_of_data_mid_way_is_one_underrun_per_episode(self, rig: Rig) -> None:
        rig.sink.enqueue(piece(1, voice(1200), last=False))
        rig.pull()
        assert rig.sink.underruns == 0  # el primer bloque se llenó entero
        rig.pull()  # quedaban 240 muestras: el resto del bloque es silencio
        assert rig.sink.underruns == 1
        rig.pull()
        rig.pull()  # sigue sin datos: el mismo episodio
        assert rig.sink.underruns == 1
        rig.sink.enqueue(piece(1, voice(960)))
        rig.pull()
        rig.pull()
        rig.sink.flush_events()
        assert rig.kinds(1) == [STARTED, FINISHED]
        assert rig.sink.underruns == 1
        rig.sink.enqueue(piece(2, voice(1500), last=False))
        rig.run(0.1)  # otro corte, en otra unidad
        assert rig.sink.underruns == 2

    def test_idle_time_and_gaps_between_units_are_not_underruns(self, rig: Rig) -> None:
        rig.run(0.2)
        rig.sink.enqueue(piece(1, voice(960)))
        rig.run(0.2)
        rig.sink.enqueue(piece(2, voice(960)))
        rig.run(0.2)
        assert rig.sink.underruns == 0

    def test_a_late_data_request_while_the_voice_sounds_is_an_underrun(self, rig: Rig) -> None:
        rig.sink.enqueue(piece(1, voice(48000)))
        rig.pull()
        rig.clock.advance(LATE_CALLBACK_S + 0.01)  # el hilo de audio no tuvo la CPU: más que el búfer entero
        rig.pull()
        assert rig.sink.underruns == 1
        rig.pull()
        rig.pull()
        assert rig.sink.underruns == 1

    def test_a_request_within_the_buffer_is_not_late(self, rig: Rig) -> None:
        rig.sink.enqueue(piece(1, voice(48000)))
        rig.pull()
        rig.clock.advance(LATE_CALLBACK_S - 0.025)  # un bloque retrasado, pero dentro de los 60 ms
        rig.pull()
        assert rig.sink.underruns == 0

    def test_a_late_request_while_idle_is_not_audible_so_it_does_not_count(self, rig: Rig) -> None:
        rig.pull()
        rig.clock.advance(0.5)
        rig.pull()
        assert rig.sink.underruns == 0

    def test_the_first_request_of_a_new_device_is_never_late(self, rig: Rig) -> None:
        rig.sink.enqueue(piece(1, voice(48000)))
        rig.pull()
        rig.stream.notify("stopped")
        assert rig.backend.wait_for(lambda: len(rig.backend.streams) == 2)
        rig.clock.advance(0.5)  # el dispositivo estuvo caído medio segundo
        rig.pull()
        assert rig.sink.underruns == 0


# --------------------------------------------------------------------------------------------------
# Gancho on_rendered
# --------------------------------------------------------------------------------------------------


class TestRenderedHook:
    @staticmethod
    def hooked(**kwargs: Any) -> tuple[Rig, list[tuple[Samples, float]]]:
        calls: list[tuple[Samples, float]] = []
        rig = Rig(on_rendered=lambda samples, at: calls.append((samples, at)), **kwargs).start()
        return rig, calls

    def test_it_receives_the_mono_voice_with_the_time_of_each_block(self) -> None:
        rig, calls = self.hooked()
        try:
            samples = np.random.default_rng(4).uniform(-0.5, 0.5, 1500).astype(np.float32)
            rig.clock.advance(7.0)
            rig.sink.enqueue(piece(1, samples))
            rig.run(0.1)
            assert [round(at, 6) for _, at in calls] == [7.0, 7.02]
            assert all(block.ndim == 1 and block.dtype == np.float32 for block, _ in calls)
            assert [len(block) for block, _ in calls] == [BLOCK, BLOCK]  # el bloque entero, con su silencio
            assert np.array_equal(np.concatenate([block for block, _ in calls])[:1500], samples)
        finally:
            rig.sink.stop()

    def test_blocks_without_voice_are_not_delivered(self) -> None:
        rig, calls = self.hooked()
        try:
            rig.run(0.2)
            assert calls == []
        finally:
            rig.sink.stop()

    def test_it_receives_what_actually_sounds_with_the_volume_applied(self) -> None:
        rig, calls = self.hooked()
        try:
            rig.sink.set_volume(0.5)
            rig.sink.enqueue(piece(1, voice(4800, 0.4)))
            rig.run(0.04)
            assert np.allclose(calls[-1][0], 0.2)
            assert np.array_equal(calls[-1][0], rig.output[-1][:, 0])
        finally:
            rig.sink.stop()

    def test_the_hook_can_be_set_and_removed_while_running(self, rig: Rig) -> None:
        calls: list[float] = []
        rig.sink.enqueue(piece(1, voice(48000)))
        rig.pull()
        rig.sink.on_rendered = lambda samples, at: calls.append(at)
        assert rig.sink.on_rendered is not None
        rig.pull()
        rig.sink.on_rendered = None
        rig.pull()
        assert len(calls) == 1

    def test_a_failing_hook_does_not_cut_the_audio(self, caplog: pytest.LogCaptureFixture) -> None:
        def broken(samples: Samples, at: float) -> None:
            raise RuntimeError("fallo del monitor")

        rig = Rig(on_rendered=broken).start()
        try:
            rig.sink.enqueue(piece(1, voice(2400, 0.3)))
            with caplog.at_level(logging.ERROR):
                rig.run(0.2)
            assert np.all(rig.heard()[:2400] == np.float32(0.3))
            assert rig.kinds(1) == [STARTED, FINISHED]
            records = [r for r in caplog.records if "on_rendered" in r.getMessage()]
            assert len(records) == 1  # se registra una sola vez
        finally:
            rig.sink.stop()


# --------------------------------------------------------------------------------------------------
# Dispositivo: abrir, rerouted y stopped
# --------------------------------------------------------------------------------------------------


class TestDevice:
    def test_start_opens_the_device_once(self) -> None:
        rig = Rig().start()
        try:
            assert rig.backend.attempts == 1
            rig.sink.start(lambda event: None)  # un segundo `start` no abre otro dispositivo
            assert rig.backend.attempts == 1
        finally:
            rig.sink.stop()

    def test_a_second_start_only_changes_where_the_events_go(self) -> None:
        rig = Rig().start()
        later: list[PlaybackEvent] = []
        try:
            rig.sink.start(later.append)
            rig.sink.enqueue(piece(1, voice(960)))
            rig.run(0.1)
            assert rig.events == []
            assert [e.kind for e in later] == [STARTED, FINISHED]
        finally:
            rig.sink.stop()

    def test_if_the_device_cannot_be_opened_start_raises_an_engine_error(self) -> None:
        rig = Rig(fail_on={0})
        with pytest.raises(EngineError) as info:
            rig.sink.start(rig.events.append)
        assert info.value.engine == "playback"
        assert "No se pudo abrir la salida de audio" in str(info.value)
        assert "sin dispositivo" in str(info.value)
        rig.sink.stop()  # y el sink se puede parar sin más
        assert rig.sink._dispatcher is None

    def test_a_failed_start_can_be_retried(self) -> None:
        rig = Rig(fail_on={0})
        with pytest.raises(EngineError):
            rig.sink.start(rig.events.append)
        rig.sink.start(rig.events.append)  # el segundo intento abre
        try:
            rig.sink.enqueue(piece(1, voice(960)))
            rig.run(0.1)
            assert rig.kinds(1) == [STARTED, FINISHED]
        finally:
            rig.sink.stop()

    def test_stop_closes_the_device(self) -> None:
        rig = Rig().start()
        rig.sink.stop()
        assert rig.stream.closed
        assert len(rig.backend.streams) == 1

    def test_rerouted_is_followed_without_reopening(self, rig: Rig) -> None:
        rig.sink.enqueue(piece(1, voice(48000)))
        rig.pull()
        rig.stream.notify("rerouted")
        assert rig.sink.reroutes == 1
        assert any("cambió de dispositivo" in w for w in rig.warnings)
        assert rig.backend.attempts == 1
        assert not rig.stream.closed
        rig.pull()
        assert rig.sink.underruns == 0

    @pytest.mark.parametrize("name", ["started", "interruption_began", "interruption_ended", "type_99"])
    def test_other_notifications_change_nothing(self, rig: Rig, name: str) -> None:
        rig.stream.notify(name)
        assert rig.backend.attempts == 1
        assert rig.warnings == []

    def test_stopped_reopens_the_device_and_keeps_the_queue(self, rig: Rig) -> None:
        rng = np.random.default_rng(5)
        first, second = (rng.uniform(-0.5, 0.5, 4800).astype(np.float32) for _ in range(2))
        rig.sink.enqueue(piece(1, first))
        rig.sink.enqueue(piece(2, second))
        rig.pull()
        rig.pull()
        old = rig.stream
        old.notify("stopped")  # se perdió el dispositivo (por ejemplo, se desconectaron los auriculares)
        assert rig.backend.wait_for(lambda: len(rig.backend.streams) == 2)
        assert wait_until(lambda: rig.sink.reopens == 1)
        assert old.closed
        assert not rig.stream.closed
        assert any("reabriendo" in w for w in rig.warnings)
        assert any("se ha reabierto" in w for w in rig.warnings)
        # El dispositivo nuevo sigue por donde iba la unidad en curso, sin repetir ni saltarse nada.
        rig.run(0.5)
        heard = np.concatenate([out[:, 0] for out in rig.output])
        assert np.array_equal(heard[:9600], np.concatenate([first, second]))
        assert rig.kinds(1) == [STARTED, FINISHED]
        assert rig.kinds(2) == [STARTED, FINISHED]

    def test_a_stale_notification_from_the_replaced_device_is_ignored(self, rig: Rig) -> None:
        old = rig.stream
        old.notify("stopped")
        assert rig.backend.wait_for(lambda: len(rig.backend.streams) == 2)
        assert wait_until(lambda: rig.sink.reopens == 1)
        old.notify("stopped")  # el cierre del dispositivo viejo avisa tarde
        old.notify("rerouted")
        time.sleep(0.05)
        assert rig.backend.attempts == 2
        assert rig.sink.reroutes == 0

    def test_it_keeps_trying_until_the_device_comes_back(self) -> None:
        rig = Rig(fail_on={1, 2, 3}).start()  # fallan los tres primeros intentos de reabrir
        try:
            rig.stream.notify("stopped")
            assert rig.backend.wait_for(lambda: len(rig.backend.streams) == 2)
            assert wait_until(lambda: rig.sink.reopens == 1)
            assert rig.backend.attempts == 5
            failures = [w for w in rig.warnings if "No se pudo reabrir" in w]
            assert len(failures) == 1  # se avisa del primer fallo, no de cada intento
            assert "sin dispositivo" in failures[0]
        finally:
            rig.sink.stop()

    def test_stop_ends_the_attempts_to_reopen(self) -> None:
        rig = Rig(fail_on=range(1, 10_000), reopen_delays_s=(0.01,)).start()
        rig.stream.notify("stopped")
        assert rig.backend.wait_for(lambda: rig.backend.attempts >= 3)
        started = time.monotonic()
        rig.sink.stop()
        assert time.monotonic() - started < 1.0
        attempts = rig.backend.attempts
        time.sleep(0.05)
        assert rig.backend.attempts <= attempts + 1  # a lo sumo uno en curso al parar
        assert sum(stream.closed for stream in rig.backend.streams) == len(rig.backend.streams)

    def test_stop_while_the_device_is_being_reopened_leaves_no_device_open(self) -> None:
        rig = Rig(reopen_delays_s=(0.0,)).start()
        rig.stream.notify("stopped")
        rig.sink.stop()
        assert wait_until(lambda: all(stream.closed for stream in rig.backend.streams))

    def test_a_failing_warning_callback_does_not_break_the_recovery(self) -> None:
        def broken(message: str) -> None:
            raise RuntimeError("fallo del suscriptor")

        rig = Rig(on_warning=broken).start()
        try:
            rig.stream.notify("stopped")
            assert wait_until(lambda: rig.sink.reopens == 1)
        finally:
            rig.sink.stop()

    def test_invalid_reopen_delays_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="reopen_delays_s"):
            DeviceSink(ManualClock(), reopen_delays_s=())
        with pytest.raises(ValueError, match="reopen_delays_s"):
            DeviceSink(ManualClock(), reopen_delays_s=(0.1, -1.0))

    def test_the_default_backend_is_miniaudio_at_48_khz_stereo_with_20_ms_x_3_periods(self) -> None:
        sink = DeviceSink(ManualClock())
        backend = sink._backend
        assert isinstance(backend, wasapi_playback.MiniaudioBackend)
        assert (backend._sample_rate, backend._channels, backend._period_ms, backend._periods) == (
            48_000,
            2,
            20,
            3,
        )


class TestFramesGenerator:
    def test_it_hands_the_requested_frames_to_render_and_never_ends(self) -> None:
        requested: list[int] = []

        def render(frames: int) -> Samples:
            requested.append(frames)
            return np.ones((frames, CHANNELS), dtype=np.float32)

        generator = wasapi_playback._frames_generator(render)
        assert next(generator) == b""
        assert generator.send(960).shape == (960, CHANNELS)
        assert generator.send(441).shape == (441, CHANNELS)
        assert requested == [960, 441]

    def test_a_failing_render_yields_silence_instead_of_killing_the_device(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        def render(frames: int) -> Samples:
            raise RuntimeError("fallo")

        generator = wasapi_playback._frames_generator(render)
        next(generator)
        with caplog.at_level(logging.ERROR):
            out = generator.send(960)
        assert out.shape == (960, CHANNELS)
        assert not out.any()
        assert generator.send(960).shape == (960, CHANNELS)  # y sigue vivo


class FakeMiniaudioDevice:
    """Sustituye a `_NotifyingPlaybackDevice` para probar `MiniaudioBackend.open` sin abrir nada."""

    created: list[FakeMiniaudioDevice] = []
    fail_on_start = False

    def __init__(self, notify: NotificationCallback, **config: Any) -> None:
        self.notify = notify
        self.config = config
        self.backend = "WASAPI"
        self.generator: Any = None
        self.closed = False
        FakeMiniaudioDevice.created.append(self)

    def start(self, generator: Any) -> None:
        if self.fail_on_start:
            raise RuntimeError("no arranca (simulado)")
        self.generator = generator

    def close(self) -> None:
        self.closed = True


class TestMiniaudioBackend:
    @pytest.fixture(autouse=True)
    def fake_device(self, monkeypatch: pytest.MonkeyPatch) -> None:
        FakeMiniaudioDevice.created = []
        FakeMiniaudioDevice.fail_on_start = False
        monkeypatch.setattr(wasapi_playback, "_NotifyingPlaybackDevice", FakeMiniaudioDevice)

    def test_it_opens_the_default_device_with_the_adr_configuration(self) -> None:
        calls: list[int] = []
        stream = wasapi_playback.MiniaudioBackend().open(
            lambda frames: calls.append(frames) or np.zeros((frames, CHANNELS), np.float32), lambda name: None
        )
        (device,) = FakeMiniaudioDevice.created
        assert stream is device
        assert device.config == {
            "sample_rate": 48_000,
            "channels": 2,
            "period_ms": 20,
            "periods": 3,
            "app_name": "InstantTraductor",
        }
        # el generador llega ya arrancado: lo siguiente que recibe son los fotogramas que pide el dispositivo
        assert device.generator.send(960).shape == (960, CHANNELS)
        assert calls == [960]

    def test_the_notifications_are_handed_to_the_sink(self) -> None:
        names: list[str] = []
        wasapi_playback.MiniaudioBackend().open(
            lambda frames: np.zeros((frames, 2), np.float32), names.append
        )
        FakeMiniaudioDevice.created[0].notify("rerouted")
        assert names == ["rerouted"]

    def test_if_the_device_does_not_start_it_is_closed_and_the_error_propagates(self) -> None:
        FakeMiniaudioDevice.fail_on_start = True
        with pytest.raises(RuntimeError, match="no arranca"):
            wasapi_playback.MiniaudioBackend().open(lambda frames: np.zeros((frames, 2), np.float32), print)
        assert FakeMiniaudioDevice.created[0].closed

    def test_the_sink_turns_a_backend_failure_into_an_engine_error(self) -> None:
        FakeMiniaudioDevice.fail_on_start = True
        sink = DeviceSink(ManualClock())  # el backend por defecto, con el dispositivo simulado
        with pytest.raises(EngineError, match="no arranca") as info:
            sink.start(lambda event: None)
        assert info.value.engine == "playback"
        sink.stop()


class TestNotificationMapping:
    """`_NotifyingPlaybackDevice._on_notification` sin abrir ningún dispositivo."""

    @staticmethod
    def device(notify: NotificationCallback) -> Any:
        device = object.__new__(wasapi_playback._NotifyingPlaybackDevice)
        # Lo mínimo para que `__del__` (que cierra el dispositivo) no haga nada.
        device.running = False
        device._device = None
        device.stop_callback = None
        device.callback_generator = None
        device._notify = notify
        return device

    @pytest.mark.parametrize(
        ("kind", "name"),
        [
            (wasapi_playback.lib.ma_device_notification_type_started, "started"),
            (wasapi_playback.lib.ma_device_notification_type_stopped, "stopped"),
            (wasapi_playback.lib.ma_device_notification_type_rerouted, "rerouted"),
            (wasapi_playback.lib.ma_device_notification_type_interruption_began, "interruption_began"),
            (wasapi_playback.lib.ma_device_notification_type_interruption_ended, "interruption_ended"),
        ],
    )
    def test_the_miniaudio_notification_types_have_a_name(self, kind: int, name: str) -> None:
        names: list[str] = []
        device = self.device(names.append)
        device._on_notification(SimpleNamespace(type=kind))
        assert names == [name]

    def test_an_unknown_type_is_passed_on_with_its_number(self) -> None:
        names: list[str] = []
        self.device(names.append)._on_notification(SimpleNamespace(type=99))
        assert names == ["type_99"]

    def test_a_failing_handler_does_not_propagate_into_the_c_callback(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        def broken(name: str) -> None:
            raise RuntimeError("fallo")

        with caplog.at_level(logging.ERROR):
            self.device(broken)._on_notification(SimpleNamespace(type=1))
        assert "notificación del dispositivo" in caplog.text


# --------------------------------------------------------------------------------------------------
# Concurrencia: tres hilos a la vez
# --------------------------------------------------------------------------------------------------


def test_concurrent_enqueue_cancel_and_render_keep_the_invariants() -> None:
    """El hilo de audio, el productor y quien cancela van a la vez: cada unidad acaba exactamente una vez."""
    rig = Rig().start()
    units = 60
    stop_audio = threading.Event()
    errors: list[BaseException] = []

    def audio() -> None:
        try:
            while not stop_audio.is_set():
                rig.stream.render(BLOCK)
                rig.clock.advance(BLOCK_S)
                time.sleep(0.0005)
        except BaseException as exc:
            errors.append(exc)

    def producer() -> None:
        try:
            for unit_id in range(units):
                rig.sink.enqueue(piece(unit_id, voice(1500, 0.2), last=False))
                rig.sink.enqueue(piece(unit_id, voice(1500, 0.2)))
                time.sleep(0.0005)
        except BaseException as exc:
            errors.append(exc)

    def canceller() -> None:
        try:
            for _ in range(25):
                rig.sink.cancel_pending()
                time.sleep(0.002)
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=target) for target in (audio, producer, canceller)]
    for thread in threads:
        thread.start()
    threads[1].join(5.0)
    threads[2].join(5.0)
    assert wait_until(lambda: rig.sink.pending_seconds() == 0.0 or not rig.sink._by_id, timeout_s=10.0)
    rig.sink.cancel_pending()
    stop_audio.set()
    threads[0].join(5.0)
    rig.sink.stop()
    assert errors == []
    by_unit: dict[int, list[PlaybackEventKind]] = {}
    for event in rig.events:
        by_unit.setdefault(event.unit_id, []).append(event.kind)
    assert set(by_unit) <= set(range(units))
    for kinds in by_unit.values():
        assert kinds in ([STARTED, FINISHED], [CANCELLED], [STARTED, CANCELLED])
    times = [event.at for event in rig.events]
    assert times == sorted(times)
    assert rig.sink.pending_seconds() == 0.0


# --------------------------------------------------------------------------------------------------
# Contrato
# --------------------------------------------------------------------------------------------------


class TestDeviceSinkContract(AudioSinkContract):
    """`AudioSinkContract` con `DeviceSink` sobre un dispositivo falso: el reloj es manual."""

    @pytest.fixture
    def contract_rig(self) -> Iterable[Rig]:
        rig = Rig()
        yield rig
        rig.sink.stop()

    @pytest.fixture
    def make_impl(self, contract_rig: Rig) -> Callable[[], AudioSink]:
        return lambda: contract_rig.sink

    @pytest.fixture
    def let_time_pass(self, contract_rig: Rig) -> Callable[[AudioSink, float], None]:
        return lambda sink, seconds: contract_rig.run(seconds)
