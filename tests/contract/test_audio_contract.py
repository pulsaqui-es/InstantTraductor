"""Suites de contrato de `AudioSource` y `AudioSink`.

Salen de «Tests de contrato obligatorios», en `specs/001-espina-dorsal/contracts/pipeline.md`.
Cada `XxxContract` es una clase base que pytest no recoge por sí sola. Un adaptador la concreta con una
subclase `TestXxx...` que sobrescribe el fixture abstracto `make_impl` (y, si hace falta, los fixtures
opcionales que se indican). Los adaptadores reales llevan además los marcadores `device`, `model`...
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from typing import ClassVar

import numpy as np
import pytest

from instanttraductor.contracts import (
    CAPTURE_RATE,
    PLAYBACK_RATE,
    AudioChunk,
    AudioSink,
    AudioSource,
    PlaybackEvent,
    PlaybackEventKind,
    SpeechPiece,
)
from instanttraductor.pipeline.clock import ManualClock
from tests.contract.helpers import assert_implements, tone
from tests.fakes.fake_audio import FakeAudioSink, FakeAudioSource

STARTED, FINISHED, CANCELLED = (
    PlaybackEventKind.STARTED,
    PlaybackEventKind.FINISHED,
    PlaybackEventKind.CANCELLED,
)

READ_TIMEOUT_S = 1.0
CONTIGUITY_TOLERANCE_S = 1e-6  # mucho menos que una muestra (62,5 µs): el encadenado es exacto por muestras


def read_chunks(source: AudioSource, count: int) -> list[AudioChunk]:
    """Lee hasta `count` chunks; para en cuanto `read` devuelve None."""
    chunks: list[AudioChunk] = []
    while len(chunks) < count:
        chunk = source.read(READ_TIMEOUT_S)
        if chunk is None:
            break
        chunks.append(chunk)
    return chunks


class AudioSourceContract:
    """Contrato de `AudioSource`: chunks contiguos a `CAPTURE_RATE`, `stop()` idempotente y `exhausted`.

    Para concretarla, sobrescribe:
    - `make_impl` (obligatorio): fábrica de una fuente nueva y sin arrancar, con audio de sobra para
      `MAX_CHUNKS` chunks. Cada llamada devuelve una instancia distinta.
    - `finite` (atributo de clase): True (por defecto) si la fuente se acaba sola, como un fichero; False
      si es en vivo y solo termina con `stop()`.
    """

    finite: ClassVar[bool] = True
    MAX_CHUNKS: ClassVar[int] = 50

    @pytest.fixture
    def make_impl(self) -> Callable[[], AudioSource]:
        raise NotImplementedError("Sobrescribe el fixture `make_impl` en la subclase de la suite.")

    @pytest.fixture
    def source(self, make_impl: Callable[[], AudioSource]) -> Iterator[AudioSource]:
        source = make_impl()
        yield source
        source.stop()  # limpieza; también comprueba, de paso, que parar tras parar no falla

    def test_implements_the_protocol(self, source: AudioSource) -> None:
        assert_implements(source, AudioSource)

    def test_sample_rate_is_the_capture_rate(self, source: AudioSource) -> None:
        assert source.sample_rate == CAPTURE_RATE

    def test_chunks_are_valid_mono_float32_at_the_capture_rate(self, source: AudioSource) -> None:
        source.start()
        chunks = read_chunks(source, 5)
        assert chunks, "la fuente no entregó ningún chunk"
        for chunk in chunks:
            assert chunk.sample_rate == CAPTURE_RATE
            assert chunk.samples.dtype == np.float32
            assert chunk.samples.ndim == 1
            assert len(chunk.samples) > 0
            assert np.all(np.isfinite(chunk.samples))
            assert float(np.max(np.abs(chunk.samples))) <= 1.0
        assert chunks[0].t_start >= 0.0

    def test_chunks_are_contiguous(self, source: AudioSource) -> None:
        source.start()
        chunks = read_chunks(source, self.MAX_CHUNKS)
        assert len(chunks) >= 2, "hacen falta al menos dos chunks para comprobar el encadenado"
        for previous, current in zip(chunks, chunks[1:], strict=False):
            assert current.t_start == pytest.approx(previous.t_end, abs=CONTIGUITY_TOLERANCE_S)

    def test_is_not_exhausted_while_data_keeps_arriving(self, source: AudioSource) -> None:
        source.start()
        assert read_chunks(source, 2)
        assert source.exhausted is False

    def test_stop_is_idempotent(self, source: AudioSource) -> None:
        source.start()
        read_chunks(source, 2)
        source.stop()
        source.stop()

    def test_is_exhausted_after_stop(self, source: AudioSource) -> None:
        source.start()
        read_chunks(source, 2)
        source.stop()
        assert source.exhausted is True

    def test_is_exhausted_at_the_end_of_the_data(self, source: AudioSource) -> None:
        if not self.finite:
            pytest.skip("fuente en vivo: solo termina con stop()")
        source.start()
        chunks: list[AudioChunk] = []
        idle_reads = 0
        while not source.exhausted and idle_reads < 20:
            chunk = source.read(READ_TIMEOUT_S)
            if chunk is None:
                idle_reads += 1
            else:
                chunks.append(chunk)
        assert source.exhausted is True
        assert source.read(0.0) is None
        for previous, current in zip(chunks, chunks[1:], strict=False):
            assert current.t_start == pytest.approx(previous.t_end, abs=CONTIGUITY_TOLERANCE_S)


def speech_piece(unit_id: int, seconds: float, *, is_last: bool = True) -> SpeechPiece:
    """Trozo de silencio a `PLAYBACK_RATE`: en un dispositivo real no se oye nada."""
    return SpeechPiece(
        unit_id=unit_id,
        samples=np.zeros(round(seconds * PLAYBACK_RATE), dtype=np.float32),
        is_last=is_last,
    )


class SinkHarness:
    """El sink bajo prueba, el registro de sus eventos y una forma de dejar pasar el tiempo."""

    def __init__(self, sink: AudioSink, let_time_pass: Callable[[AudioSink, float], None]) -> None:
        self.sink = sink
        self.events: list[PlaybackEvent] = []
        self._let_time_pass = let_time_pass
        sink.start(self.events.append)

    def pass_time(self, seconds: float) -> None:
        self._let_time_pass(self.sink, seconds)

    def kinds(self, unit_id: int) -> list[PlaybackEventKind]:
        return [event.kind for event in list(self.events) if event.unit_id == unit_id]

    def has(self, unit_id: int, kind: PlaybackEventKind) -> bool:
        return kind in self.kinds(unit_id)

    def wait_until(self, condition: Callable[[], bool], timeout_s: float = 3.0, step_s: float = 0.01) -> bool:
        waited = 0.0
        while not condition():
            if waited >= timeout_s:
                return False
            self.pass_time(step_s)
            waited += step_s
        return True

    def wait_for(self, unit_id: int, kind: PlaybackEventKind) -> None:
        assert self.wait_until(lambda: self.has(unit_id, kind)), (
            f"no llegó el evento {kind} de la unidad {unit_id}; eventos: {self.events}"
        )


class AudioSinkContract:
    """Contrato de `AudioSink`: FIFO por unidad, STARTED antes que FINISHED, `cancel_pending` y `stop()`.

    Para concretarla, sobrescribe:
    - `make_impl` (obligatorio): fábrica de un sink nuevo y sin arrancar.
    - `let_time_pass` (opcional): `(sink, segundos) -> None`. Por defecto duerme (`time.sleep`), que vale
      para dispositivos reales; los dobles con reloj manual lo sustituyen por algo que adelante su reloj.
    Las unidades de prueba son silencios de 0,1 a 0,5 s, así que en un dispositivo real no se oye nada.
    """

    @pytest.fixture
    def make_impl(self) -> Callable[[], AudioSink]:
        raise NotImplementedError("Sobrescribe el fixture `make_impl` en la subclase de la suite.")

    @pytest.fixture
    def let_time_pass(self) -> Callable[[AudioSink, float], None]:
        return lambda sink, seconds: time.sleep(seconds)

    @pytest.fixture
    def harness(
        self, make_impl: Callable[[], AudioSink], let_time_pass: Callable[[AudioSink, float], None]
    ) -> Iterator[SinkHarness]:
        harness = SinkHarness(make_impl(), let_time_pass)
        yield harness
        harness.sink.stop()  # nada se queda sonando entre tests

    def test_implements_the_protocol(self, harness: SinkHarness) -> None:
        assert_implements(harness.sink, AudioSink)

    def test_sample_rate_is_the_playback_rate(self, harness: SinkHarness) -> None:
        assert harness.sink.sample_rate == PLAYBACK_RATE

    def test_enqueue_does_not_block(self, harness: SinkHarness) -> None:
        before = time.perf_counter()
        harness.sink.enqueue(speech_piece(1, 0.3))
        assert time.perf_counter() - before < 0.25

    def test_a_unit_emits_started_then_finished(self, harness: SinkHarness) -> None:
        harness.sink.enqueue(speech_piece(1, 0.2))
        harness.wait_for(1, FINISHED)
        assert harness.kinds(1) == [STARTED, FINISHED]
        started, finished = (e for e in harness.events if e.unit_id == 1)
        assert started.at <= finished.at

    def test_a_multi_piece_unit_emits_a_single_started_and_finished(self, harness: SinkHarness) -> None:
        for last, seconds in ((False, 0.1), (False, 0.1), (True, 0.1)):
            harness.sink.enqueue(speech_piece(1, seconds, is_last=last))
        harness.wait_for(1, FINISHED)
        harness.pass_time(0.1)
        assert harness.kinds(1) == [STARTED, FINISHED]

    def test_units_play_in_fifo_order_one_at_a_time(self, harness: SinkHarness) -> None:
        for unit_id in (1, 2, 3):
            harness.sink.enqueue(speech_piece(unit_id, 0.15))
        harness.wait_for(3, FINISHED)
        assert [(e.unit_id, e.kind) for e in harness.events] == [
            (1, STARTED),
            (1, FINISHED),
            (2, STARTED),
            (2, FINISHED),
            (3, STARTED),
            (3, FINISHED),
        ]
        times = [e.at for e in harness.events]
        assert times == sorted(times)

    def test_cancel_pending_only_touches_units_that_have_not_started(self, harness: SinkHarness) -> None:
        harness.sink.enqueue(speech_piece(1, 0.4))
        harness.wait_for(1, STARTED)
        harness.sink.enqueue(speech_piece(2, 0.2))
        harness.sink.enqueue(speech_piece(3, 0.2))
        assert harness.sink.cancel_pending() == [2, 3]
        harness.wait_for(2, CANCELLED)
        harness.wait_for(3, CANCELLED)
        harness.wait_for(1, FINISHED)
        assert harness.kinds(1) == [STARTED, FINISHED]
        assert harness.kinds(2) == [CANCELLED]
        assert harness.kinds(3) == [CANCELLED]

    def test_cancel_pending_with_nothing_pending_returns_an_empty_list(self, harness: SinkHarness) -> None:
        assert harness.sink.cancel_pending() == []
        harness.sink.enqueue(speech_piece(1, 0.2))
        harness.wait_for(1, STARTED)
        assert harness.sink.cancel_pending() == []
        harness.wait_for(1, FINISHED)
        assert harness.kinds(1) == [STARTED, FINISHED]

    def test_stop_cancels_everything_and_leaves_nothing_playing(self, harness: SinkHarness) -> None:
        harness.sink.enqueue(speech_piece(1, 0.5))
        harness.sink.enqueue(speech_piece(2, 0.5))
        harness.wait_for(1, STARTED)
        harness.sink.stop()
        harness.wait_for(1, CANCELLED)
        harness.wait_for(2, CANCELLED)
        assert harness.sink.pending_seconds() == pytest.approx(0.0, abs=1e-6)
        events_after_stop = list(harness.events)
        harness.pass_time(0.7)  # más que lo que quedaba por sonar
        assert harness.events == events_after_stop
        assert harness.kinds(1) == [STARTED, CANCELLED]
        assert harness.kinds(2) == [CANCELLED]

    def test_stop_is_idempotent(self, harness: SinkHarness) -> None:
        harness.sink.enqueue(speech_piece(1, 0.3))
        harness.wait_for(1, STARTED)
        harness.sink.stop()
        harness.wait_for(1, CANCELLED)
        events_after_first_stop = list(harness.events)
        harness.sink.stop()
        harness.pass_time(0.1)
        assert harness.events == events_after_first_stop

    def test_pending_seconds_counts_the_audio_not_yet_played(self, harness: SinkHarness) -> None:
        assert harness.sink.pending_seconds() == pytest.approx(0.0, abs=1e-6)
        harness.sink.enqueue(speech_piece(1, 0.4))
        harness.sink.enqueue(speech_piece(2, 0.3))
        pending = harness.sink.pending_seconds()
        assert 0.3 < pending <= 0.7 + 1e-6
        harness.wait_for(2, FINISHED)
        assert harness.sink.pending_seconds() == pytest.approx(0.0, abs=0.05)

    def test_set_volume_accepts_the_whole_range(self, harness: SinkHarness) -> None:
        for gain in (0.0, 0.5, 1.0, 2.0):
            harness.sink.set_volume(gain)

    def test_event_times_are_valid_session_times(self, harness: SinkHarness) -> None:
        harness.sink.enqueue(speech_piece(1, 0.2))
        harness.wait_for(1, FINISHED)
        assert all(np.isfinite(e.at) and e.at >= 0.0 for e in harness.events)


# --------------------------------------------------------------------------------------------------
# Dobles
# --------------------------------------------------------------------------------------------------


class TestAudioSourceFake(AudioSourceContract):
    @pytest.fixture
    def make_impl(self) -> Callable[[], AudioSource]:
        return lambda: FakeAudioSource(tone(2.0))  # 100 chunks de 20 ms


class TestAudioSinkFake(AudioSinkContract):
    @pytest.fixture
    def make_impl(self) -> Callable[[], AudioSink]:
        return lambda: FakeAudioSink(ManualClock())

    @pytest.fixture
    def let_time_pass(self) -> Callable[[AudioSink, float], None]:
        return lambda sink, seconds: sink.advance(seconds)  # type: ignore[attr-defined]


class ZeroSource:
    """Fuente infinita que solo entrega ceros, como `AppLoopbackSource` esperando a la app (spec 002)."""

    sample_rate = CAPTURE_RATE

    def __init__(self) -> None:
        self._t = 0.0
        self._started = False
        self._stopped = False

    def start(self) -> None:
        self._started = True

    def read(self, timeout: float) -> AudioChunk | None:
        if not self._started or self._stopped:
            return None
        samples = np.zeros(int(0.02 * CAPTURE_RATE), np.float32)
        chunk = AudioChunk(samples, CAPTURE_RATE, self._t)
        self._t += 0.02
        return chunk

    @property
    def exhausted(self) -> bool:
        return self._stopped

    def stop(self) -> None:
        self._stopped = True


class TestZeroSourceContract(AudioSourceContract):
    """El contrato admite fuentes en vivo que solo entregan ceros (spec 002, T006)."""

    finite = False

    @pytest.fixture
    def make_impl(self) -> Callable[[], AudioSource]:
        return ZeroSource
