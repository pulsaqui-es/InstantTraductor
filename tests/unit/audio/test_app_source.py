"""Tests de `AppLoopbackSource` (T010): vigilante, estados, ceros mientras espera y reanudación.

Casi todo se prueba **sin hilos** y con un `ManualClock`: el test avanza el tiempo, alimenta las capturas
falsas y llama a mano a `_pump_once` y `_watch_once` (como los tests de `ProcessLoopbackSource`). Al final,
unos pocos tests con hilos y reloj real, y la suite `AudioSourceContract` con `finite=False`.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable

import numpy as np
import pytest

from instanttraductor.audio.app_source import (
    AUDIBLE_PEAK,
    OPEN_RETRY_S,
    PROBE_INTERVAL_S,
    SESSION_PEAK,
    SILENT_AFTER_S,
    AppCaptureState,
    AppLoopbackSource,
    meter_says_sounding,
)
from instanttraductor.audio.app_types import AppIdentity
from instanttraductor.contracts import CAPTURE_RATE, AudioChunk, AudioSource, Clock, EngineError
from instanttraductor.pipeline.clock import ManualClock, SessionClock
from tests.contract.test_audio_contract import AudioSourceContract
from tests.fakes.fake_apps import FakeProcessTable, app

CHROME = r"C:\No\Existe\Chrome\chrome.exe"  # ruta que no existe: el nombre sale del ejecutable
STEP_S = 0.01
WAITING, PLAYING, SILENT = AppCaptureState.WAITING, AppCaptureState.PLAYING, AppCaptureState.SILENT


def tone_samples(count: int, level: float) -> np.ndarray:
    return np.full(count, level, dtype=np.float32)


class FakeCapture:
    """Captura INCLUDE falsa: la alimenta el test con `feed`. Lleva su propio reloj de audio, como la real."""

    sample_rate = CAPTURE_RATE

    def __init__(self, pid: int, clock: Clock) -> None:
        self.pid = pid
        self._clock = clock
        self.started = False
        self.stopped = False
        self.dead = False  # simula una captura cuyo hilo murió
        self._queue: list[AudioChunk] = []
        self._arrivals: list[tuple[float, float, float]] = []  # t_start, t_end, llegada
        self._audio_t = 0.0

    def start(self) -> None:
        self.started = True

    def feed(self, count: int, level: float) -> None:
        chunk = AudioChunk(tone_samples(count, level), CAPTURE_RATE, self._audio_t)
        self._audio_t = chunk.t_end
        self._arrivals.append((chunk.t_start, chunk.t_end, self._clock.now()))
        self._queue.append(chunk)

    def read(self, timeout: float) -> AudioChunk | None:
        if self.stopped or not self._queue:
            return None
        return self._queue.pop(0)

    @property
    def exhausted(self) -> bool:
        return self.stopped or self.dead

    def stop(self) -> None:
        self.stopped = True

    def arrival_time(self, t_audio: float) -> float | None:
        for start, end, arrival in self._arrivals:
            if start < t_audio <= end + 1e-12:
                return arrival
        return None


class FakeFactory:
    """`capture_factory` falso: guarda las capturas creadas y puede fallar al abrir las primeras."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self.captures: list[FakeCapture] = []
        self.fail_times = 0  # las próximas aperturas que fallan al llamar a `start`

    @property
    def calls(self) -> list[int]:
        return [capture.pid for capture in self.captures]

    def __call__(self, pid: int) -> FakeCapture:
        capture = FakeCapture(pid, self._clock)
        if self.fail_times > 0:
            self.fail_times -= 1

            def boom() -> None:
                raise EngineError("activación rechazada", engine="capture")

            capture.start = boom  # type: ignore[method-assign]
        self.captures.append(capture)
        return capture


class FakeProbe:
    """Sonda del aviso de silencio: respuesta fija (o por guion) y registro de cuándo se la consultó."""

    def __init__(self, clock: Clock, answer: bool = True) -> None:
        self._clock = clock
        self.answer = answer
        self.raises = False
        self.calls: list[float] = []

    def __call__(self, identity: AppIdentity) -> bool:
        self.calls.append(self._clock.now())
        if self.raises:
            raise RuntimeError("sonda rota")
        return self.answer


class Rig:
    """La fuente con tabla de procesos, captura y sonda falsas, y reloj manual. **Sin hilos**."""

    def __init__(
        self, lives: Iterable[tuple[AppIdentity, float, float | None]] = (), *, probe: bool = True
    ) -> None:
        self.clock = ManualClock()
        self.table = FakeProcessTable(self.clock, list(lives))
        self.factory = FakeFactory(self.clock)
        self.probe = FakeProbe(self.clock, probe)
        self.states: list[tuple[AppCaptureState, str]] = []
        self.warnings: list[str] = []
        self.levels: dict[int, float] = {}  # nivel del audio que entrega la captura de cada PID
        self.default_level = 0.1
        self.source = AppLoopbackSource(
            self.clock,
            CHROME,
            process_table=self.table,
            capture_factory=self.factory,
            probe=self.probe,
            on_state=lambda state, name: self.states.append((state, name)),
            on_warning=self.warnings.append,
        )
        self.collected: list[AudioChunk] = []
        self._next_watch = 0.0

    def begin(self) -> None:
        """Lo que hace `start()` salvo lanzar los hilos."""
        self.source._started = True
        self.source._origin = self.clock.now()
        self.source._notify_state()
        self.source._watch_once()
        self._next_watch = self.clock.now() + 0.25

    def run(self, seconds: float) -> None:
        """Avanza en pasos de 10 ms: las capturas dan audio, se bombea y el vigilante sondea cada 0,25 s."""
        for _ in range(round(seconds / STEP_S)):
            self.clock.advance(STEP_S)
            for capture in self.factory.captures:
                if not capture.stopped and capture.started and not capture.dead:
                    capture.feed(
                        round(STEP_S * CAPTURE_RATE), self.levels.get(capture.pid, self.default_level)
                    )
            self.source._pump_once()
            if self.clock.now() >= self._next_watch - 1e-9:
                self.source._watch_once()
                self._next_watch += 0.25
        self.collect()

    def collect(self) -> list[AudioChunk]:
        while (chunk := self.source.read(0.0)) is not None:
            self.collected.append(chunk)
        return self.collected

    def state_names(self) -> list[AppCaptureState]:
        return [state for state, _ in self.states]

    def audible(self, chunk: AudioChunk) -> bool:
        return float(np.max(np.abs(chunk.samples))) >= AUDIBLE_PEAK

    def first_audible_after(self, t_audio: float) -> AudioChunk | None:
        return next((c for c in self.collect() if c.t_start >= t_audio and self.audible(c)), None)

    def assert_contiguous(self) -> None:
        chunks = self.collect()
        assert len(chunks) >= 2
        for previous, current in zip(chunks, chunks[1:], strict=False):
            assert current.t_start == pytest.approx(previous.t_end, abs=1e-9)


def chrome(pid: int = 7, create_time: float = 1.0) -> AppIdentity:
    return app(CHROME, name="Google Chrome", pid=pid, create_time=create_time)


class TestWhileWaiting:
    def test_gives_zero_chunks_of_20_ms_at_the_pace_of_the_clock_and_contiguous(self) -> None:
        rig = Rig()
        rig.begin()
        rig.run(2.0)
        chunks = rig.collect()
        assert sum(c.duration for c in chunks) == pytest.approx(2.0, abs=0.021)
        assert all(len(c.samples) == 320 and c.sample_rate == CAPTURE_RATE for c in chunks)
        assert all(c.samples.dtype == np.float32 and not c.samples.any() for c in chunks)
        assert chunks[0].t_start == 0.0
        rig.assert_contiguous()

    def test_no_chunk_is_ahead_of_the_clock(self) -> None:
        rig = Rig()
        rig.begin()
        for _ in range(100):
            rig.run(STEP_S)
            assert all(c.t_end <= rig.clock.now() + 1e-9 for c in rig.collected)

    def test_the_first_state_is_waiting_with_the_name_of_the_app_and_nothing_is_captured(self) -> None:
        rig = Rig()
        rig.begin()
        rig.run(1.0)
        assert rig.states == [(WAITING, "chrome")]  # nombre del ejecutable hasta encontrarla
        assert rig.source.state is WAITING
        assert rig.source.current_pid is None
        assert rig.factory.captures == []

    def test_the_search_uses_the_executable_path(self) -> None:
        seen: list[str] = []

        class Spy(FakeProcessTable):
            def find_roots(self, exe_path: str) -> list[AppIdentity]:
                seen.append(exe_path)
                return super().find_roots(exe_path)

        rig = Rig()
        rig.source._table = Spy(rig.clock)
        rig.begin()
        assert seen == [CHROME]


class TestAppearing:
    def test_opens_include_on_the_new_root_within_one_watch_period(self) -> None:
        rig = Rig([(chrome(7), 0.6, None)])
        rig.begin()
        rig.run(0.6)
        assert rig.factory.calls == []
        rig.run(0.3)  # el vigilante sondea cada 0,25 s
        assert rig.factory.calls == [7]
        assert rig.factory.captures[0].started
        assert rig.source.state is PLAYING
        assert rig.source.current_pid == 7
        assert rig.states == [(WAITING, "chrome"), (PLAYING, "Google Chrome")]

    def test_the_app_open_at_start_is_captured_right_away(self) -> None:
        rig = Rig([(chrome(7), 0.0, None)])
        rig.begin()
        assert rig.factory.calls == [7]
        assert rig.source.state is PLAYING

    def test_zeros_before_audio_after_and_always_contiguous(self) -> None:
        rig = Rig([(chrome(7), 1.0, None)])
        rig.begin()
        rig.run(3.0)
        chunks = rig.collect()
        rig.assert_contiguous()
        assert sum(c.duration for c in chunks) == pytest.approx(3.0, abs=0.06)
        first = rig.first_audible_after(0.0)
        assert first is not None
        assert 1.0 <= first.t_start <= 1.4
        assert all(not rig.audible(c) for c in chunks if c.t_end <= first.t_start)
        assert all(rig.audible(c) for c in chunks if c.t_start >= first.t_start)

    def test_with_several_instances_it_captures_the_oldest_root(self) -> None:
        rig = Rig([(chrome(8, 5.0), 0.0, None), (chrome(7, 2.0), 0.0, None)])
        rig.begin()
        assert rig.factory.calls == [7]


class TestDeathAndRestart:
    def test_when_the_root_dies_it_closes_the_capture_and_goes_back_to_waiting_with_zeros(self) -> None:
        rig = Rig([(chrome(7), 0.0, 2.1)])
        rig.begin()
        rig.run(2.0)
        assert rig.source.state is PLAYING
        rig.run(0.5)
        assert rig.source.state is WAITING
        assert rig.source.current_pid is None
        assert rig.factory.captures[0].stopped
        assert rig.state_names() == [WAITING, PLAYING, WAITING]
        rig.run(2.0)
        last = rig.collect()[-20:]
        assert all(not rig.audible(c) for c in last)
        rig.assert_contiguous()
        assert sum(c.duration for c in rig.collect()) == pytest.approx(4.5, abs=0.06)

    def test_a_restart_with_a_new_pid_resumes_within_5_seconds_and_without_breaking_continuity(self) -> None:
        rig = Rig([(chrome(7, 1.0), 0.0, 2.0), (chrome(8, 2.5), 3.0, None)])
        rig.begin()
        rig.run(8.0)
        assert rig.factory.calls == [7, 8]
        assert rig.state_names() == [WAITING, PLAYING, WAITING, PLAYING]
        assert rig.source.current_pid == 8
        resumed = rig.first_audible_after(2.0)
        assert resumed is not None
        assert resumed.t_start - 3.0 <= 5.0  # SC-004
        assert resumed.t_start - 3.0 <= 0.5  # con el vigilante de 0,25 s
        rig.assert_contiguous()
        assert sum(c.duration for c in rig.collect()) == pytest.approx(8.0, abs=0.06)

    def test_an_instant_restart_with_the_same_pid_but_another_creation_time_is_a_new_process(self) -> None:
        rig = Rig([(chrome(7, 1.0), 0.0, 2.0), (chrome(7, 2.0), 2.0, None)])
        rig.begin()
        rig.run(4.0)
        assert rig.factory.calls == [7, 7]
        assert rig.factory.captures[0].stopped
        assert not rig.factory.captures[1].stopped
        assert rig.state_names() == [WAITING, PLAYING, WAITING, PLAYING]
        assert rig.source._identity is not None and rig.source._identity.create_time == 2.0
        rig.assert_contiguous()

    def test_the_new_capture_restarts_its_own_clock_but_the_output_stays_continuous(self) -> None:
        rig = Rig([(chrome(7, 1.0), 0.0, 1.0), (chrome(8, 2.5), 1.0, None)])
        rig.begin()
        rig.run(3.0)
        assert [c._audio_t > 0 for c in rig.factory.captures] == [True, True]
        rig.assert_contiguous()
        assert rig.collect()[0].t_start == 0.0

    def test_the_old_capture_is_stopped_and_the_new_one_is_not(self) -> None:
        rig = Rig([(chrome(7, 1.0), 0.0, 1.0), (chrome(8, 2.5), 1.5, None)])
        rig.begin()
        rig.run(3.0)
        old, new = rig.factory.captures
        assert old.stopped and not new.stopped


class TestSilentCapture:
    def silent_rig(self, *, probe: bool = True) -> Rig:
        rig = Rig([(chrome(7), 0.0, None)], probe=probe)
        rig.levels[7] = 0.0  # la app «suena» según la sonda, pero la captura da ceros
        rig.begin()
        return rig

    def test_warns_after_4_seconds_only_if_the_probe_says_the_app_sounds(self) -> None:
        rig = self.silent_rig()
        rig.run(SILENT_AFTER_S - 0.3)
        assert rig.warnings == []
        assert rig.source.state is PLAYING
        assert rig.probe.calls == []  # antes de los 4 s ni se pregunta
        rig.run(0.8)
        assert rig.source.state is SILENT
        assert len(rig.warnings) == 1
        assert (
            "suena" in rig.warnings[0]
            and "silencio" in rig.warnings[0]
            and "Google Chrome" in rig.warnings[0]
        )
        assert rig.state_names() == [WAITING, PLAYING, SILENT]

    def test_the_time_is_counted_from_the_opening_of_the_capture(self) -> None:
        rig = Rig([(chrome(7), 2.0, None)])
        rig.levels[7] = 0.0
        rig.begin()
        rig.run(2.0 + SILENT_AFTER_S - 0.5)
        assert rig.source.state is PLAYING
        rig.run(1.0)
        assert rig.source.state is SILENT

    def test_no_warning_when_the_probe_says_the_app_does_not_sound(self) -> None:
        rig = self.silent_rig(probe=False)
        rig.run(20.0)
        assert rig.warnings == []
        assert rig.source.state is PLAYING
        assert len(rig.probe.calls) >= 2

    def test_the_probe_is_not_asked_more_often_than_its_interval(self) -> None:
        rig = self.silent_rig(probe=False)
        rig.run(30.0)
        gaps = [b - a for a, b in zip(rig.probe.calls, rig.probe.calls[1:], strict=False)]
        assert gaps and min(gaps) >= PROBE_INTERVAL_S - 1e-6

    def test_no_probe_while_audio_is_audible(self) -> None:
        rig = Rig([(chrome(7), 0.0, None)])
        rig.begin()
        rig.run(15.0)
        assert rig.probe.calls == []
        assert rig.source.state is PLAYING

    def test_audio_coming_back_goes_back_to_sounding_without_a_new_warning(self) -> None:
        rig = self.silent_rig()
        rig.run(SILENT_AFTER_S + 1.0)
        assert rig.source.state is SILENT
        rig.levels[7] = 0.1
        rig.run(0.6)
        assert rig.source.state is PLAYING
        assert rig.state_names() == [WAITING, PLAYING, SILENT, PLAYING]
        assert len(rig.warnings) == 1

    def test_a_probe_that_fails_does_not_stop_the_watcher_or_warn(self) -> None:
        rig = self.silent_rig()
        rig.probe.raises = True
        rig.run(SILENT_AFTER_S + 4.0)
        assert rig.warnings == []
        assert rig.source.state is PLAYING
        rig.probe.raises = False
        rig.run(PROBE_INTERVAL_S + 0.5)
        assert rig.source.state is SILENT

    def test_a_death_while_silent_goes_back_to_waiting(self) -> None:
        rig = Rig([(chrome(7), 0.0, 8.0)])
        rig.levels[7] = 0.0
        rig.begin()
        rig.run(7.0)
        assert rig.source.state is SILENT
        rig.run(1.5)
        assert rig.source.state is WAITING

    def test_a_new_capture_after_a_restart_starts_counting_again(self) -> None:
        rig = Rig([(chrome(7, 1.0), 0.0, 5.0), (chrome(8, 2.0), 5.2, None)])
        rig.levels[7] = 0.0
        rig.begin()
        rig.run(4.6)  # la primera ya está en SILENT
        assert rig.source.state is SILENT
        rig.run(1.2)
        assert rig.source.state is PLAYING  # la nueva (con audio)
        assert rig.factory.calls == [7, 8]


class TestFailures:
    def test_a_capture_that_cannot_be_opened_warns_and_is_retried_after_two_seconds(self) -> None:
        rig = Rig([(chrome(7), 0.0, None)])
        rig.factory.fail_times = 1
        rig.begin()
        assert rig.source.state is WAITING
        assert len(rig.warnings) == 1 and "No se pudo abrir" in rig.warnings[0]
        assert "activación rechazada" in rig.warnings[0]
        rig.run(OPEN_RETRY_S - 0.3)
        assert rig.factory.calls == [7]  # aún no reintenta
        rig.run(0.8)
        assert rig.factory.calls == [7, 7]
        assert rig.source.state is PLAYING
        rig.assert_contiguous()
        assert first_audible(rig) is not None

    def test_a_factory_that_raises_is_handled_the_same_way(self) -> None:
        rig = Rig([(chrome(7), 0.0, None)])

        def broken(pid: int) -> AudioSource:
            raise OSError("sin dispositivo")

        rig.source._factory = broken
        rig.begin()
        rig.run(1.0)
        assert rig.source.state is WAITING
        assert len(rig.warnings) == 1  # solo uno: el reintento espera 2 s

    def test_a_capture_that_dies_is_reopened_on_the_same_process(self) -> None:
        rig = Rig([(chrome(7), 0.0, None)])
        rig.begin()
        rig.run(1.0)
        rig.factory.captures[0].dead = True
        rig.run(0.6)
        assert rig.factory.calls == [7, 7]
        assert rig.factory.captures[0].stopped
        assert any("se detuvo" in w for w in rig.warnings)
        assert rig.source.state is PLAYING
        rig.assert_contiguous()

    def test_a_failing_state_callback_does_not_stop_the_source(self) -> None:
        rig = Rig([(chrome(7), 0.5, None)])

        def boom(*_args: object) -> None:
            raise RuntimeError("fallo del suscriptor")

        rig.source._on_state = boom
        rig.source._on_warning = boom
        rig.begin()
        rig.run(1.5)
        assert rig.source.state is PLAYING
        assert first_audible(rig) is not None

    def test_a_consumer_that_does_not_read_gets_a_single_overflow_warning_and_loses_the_oldest(self) -> None:
        rig = Rig()
        rig.source._max_backlog = 5
        rig.begin()
        rig.clock.advance(1.0)
        rig.source._pump_once()
        assert len([w for w in rig.warnings if "no da abasto" in w]) == 1
        rig.clock.advance(1.0)
        rig.source._pump_once()
        assert len([w for w in rig.warnings if "no da abasto" in w]) == 1
        chunks = rig.collect()
        assert len(chunks) == 5
        assert chunks[-1].t_end == pytest.approx(2.0, abs=0.021)


def first_audible(rig: Rig) -> AudioChunk | None:
    return rig.first_audible_after(0.0)


class TestArrivalTimeAndPid:
    def test_a_zero_chunk_arrives_when_the_clock_says(self) -> None:
        rig = Rig()
        rig.begin()
        rig.run(1.0)
        arrival = rig.source.arrival_time(0.5)
        assert arrival is not None
        assert arrival == pytest.approx(0.5, abs=0.021)

    def test_a_captured_chunk_arrives_when_the_capture_got_it(self) -> None:
        rig = Rig([(chrome(7), 0.0, None)])
        rig.begin()
        rig.run(1.0)
        chunk = rig.first_audible_after(0.0)
        assert chunk is not None
        arrival = rig.source.arrival_time(chunk.t_end)
        assert arrival is not None
        assert arrival == pytest.approx(chunk.t_end, abs=0.021)  # la captura falsa entrega al ritmo del reloj

    def test_unknown_instants_have_no_arrival(self) -> None:
        rig = Rig()
        rig.begin()
        rig.run(0.5)
        assert rig.source.arrival_time(10.0) is None

    def test_current_pid_follows_the_process(self) -> None:
        rig = Rig([(chrome(7, 1.0), 0.0, 1.0), (chrome(8, 2.0), 2.0, None)])
        rig.begin()
        seen = []
        for _ in range(12):
            rig.run(0.5)
            seen.append(rig.source.current_pid)
        assert seen[0] == 7
        assert None in seen
        assert seen[-1] == 8


class TestStop:
    def test_stop_closes_the_capture_and_exhausts_the_source(self) -> None:
        rig = Rig([(chrome(7), 0.0, None)])
        rig.begin()
        rig.run(0.5)
        rig.source.stop()
        assert rig.factory.captures[0].stopped
        assert rig.source.exhausted is True
        assert rig.source.read(0.0) is None
        assert rig.source.current_pid is None

    def test_stop_is_idempotent_and_works_before_start(self) -> None:
        rig = Rig()
        rig.source.stop()
        rig.source.stop()
        assert rig.source.exhausted is True

    def test_after_stop_the_watcher_does_not_open_anything(self) -> None:
        rig = Rig([(chrome(7), 1.0, None)])
        rig.begin()
        rig.source.stop()
        rig.run(2.0)
        assert rig.factory.calls == []


class TestMeterProbeDecision:
    def test_the_app_sounds_when_its_meter_reaches_the_threshold_and_no_other_app_masks_it(self) -> None:
        assert meter_says_sounding(0.05, 0.0) is True
        assert meter_says_sounding(0.05, 0.001) is True  # las demás por debajo del umbral: no hay duda
        assert meter_says_sounding(SESSION_PEAK, 0.0) is True

    def test_below_the_threshold_it_does_not_sound(self) -> None:
        assert meter_says_sounding(SESSION_PEAK / 2, 0.0) is False
        assert meter_says_sounding(0.0, 0.5) is False

    def test_a_meter_that_copies_the_mix_of_another_app_proves_nothing(self) -> None:
        assert meter_says_sounding(0.05, 0.05) is False  # Discord igualando a Chrome (S6)
        assert meter_says_sounding(0.06, 0.05) is False  # o superándolo
        assert meter_says_sounding(0.05, 0.1) is True  # claramente por debajo del de otra: es suya


class TestWithThreads:
    """Con hilos y reloj real: lo que no se puede probar a mano."""

    def make(self, lives: Callable[[Clock], FakeProcessTable]) -> tuple[AppLoopbackSource, list]:
        clock = SessionClock()
        states: list[tuple[AppCaptureState, str]] = []
        factory = FakeFactory(clock)
        source = AppLoopbackSource(
            clock,
            CHROME,
            process_table=lives(clock),
            capture_factory=factory,
            probe=lambda identity: False,
            on_state=lambda state, name: states.append((state, name)),
        )
        return source, states

    def test_waiting_gives_zero_chunks_at_real_pace(self) -> None:
        source, states = self.make(lambda clock: FakeProcessTable(clock))
        source.start()
        began = time.perf_counter()
        chunks = []
        try:
            while len(chunks) < 15:
                chunk = source.read(1.0)
                assert chunk is not None
                chunks.append(chunk)
        finally:
            source.stop()
        took = time.perf_counter() - began
        assert 0.2 <= took <= 1.0  # 15 chunks de 20 ms = 0,3 s
        assert not any(c.samples.any() for c in chunks)
        assert states == [(WAITING, "chrome")]

    def test_threads_end_with_stop(self) -> None:
        source, _ = self.make(lambda clock: FakeProcessTable(clock, [(chrome(7), 0.0, None)]))
        source.start()
        assert source.current_pid == 7
        source.stop()
        assert not any(thread.is_alive() for thread in source._threads)
        assert source.exhausted is True

    def test_start_is_idempotent(self) -> None:
        source, _ = self.make(lambda clock: FakeProcessTable(clock))
        source.start()
        count = len(source._threads)
        source.start()
        assert len(source._threads) == count == 2
        source.stop()


class PacedCapture:
    """Captura en vivo falsa para la suite de contrato: un chunk de 20 ms de tono cada 20 ms reales."""

    sample_rate = CAPTURE_RATE

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._t0 = 0.0
        self._n = 0
        self._stopped = False

    def start(self) -> None:
        self._t0 = self._clock.now()

    def read(self, timeout: float) -> AudioChunk | None:
        deadline = time.perf_counter() + max(0.0, timeout)
        while not self._stopped:
            if self._clock.now() >= self._t0 + (self._n + 1) * 0.02:
                t = np.arange(320) / CAPTURE_RATE + self._n * 0.02
                samples = (0.05 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
                chunk = AudioChunk(samples, CAPTURE_RATE, self._n * 0.02)
                self._n += 1
                return chunk
            if time.perf_counter() >= deadline:
                return None
            time.sleep(0.002)
        return None

    @property
    def exhausted(self) -> bool:
        return self._stopped

    def stop(self) -> None:
        self._stopped = True


class TestAppLoopbackSourceWithFakes(AudioSourceContract):
    """`AppLoopbackSource` cumple el contrato de `AudioSource` (en vivo: `finite=False`).

    La app aparece a los 0,15 s: la fuente empieza con ceros y pasa a la captura a mitad de la lectura.
    """

    finite = False

    @pytest.fixture
    def make_impl(self) -> Callable[[], AudioSource]:
        def make() -> AudioSource:
            clock = SessionClock()
            return AppLoopbackSource(
                clock,
                CHROME,
                process_table=FakeProcessTable(clock, [(chrome(7), 0.15, None)]),
                capture_factory=lambda pid: PacedCapture(clock),
                probe=lambda identity: False,
            )

        return make


class TestAppLoopbackSourceWaitingForever(AudioSourceContract):
    """Y también cuando la app no llega a aparecer: solo ceros, igual de contiguos."""

    finite = False

    @pytest.fixture
    def make_impl(self) -> Callable[[], AudioSource]:
        def make() -> AudioSource:
            clock = SessionClock()
            return AppLoopbackSource(clock, CHROME, process_table=FakeProcessTable(clock))

        return make
