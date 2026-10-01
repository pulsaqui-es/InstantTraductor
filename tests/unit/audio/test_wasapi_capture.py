"""Tests de la captura por proceso (T015) sin dispositivo: relleno, vigilante, llegadas y fuente.

Todo se prueba con llegadas simuladas, un flujo de paquetes falso y un `ManualClock`: ni COM ni
dispositivos de audio. Los tests con el dispositivo real están en `tests/integration/test_capture_device.py`
(marcador `device`).
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import textwrap
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable
from types import SimpleNamespace
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

from instanttraductor.audio import wasapi_capture
from instanttraductor.audio.wasapi_capture import (
    ArrivalLog,
    CaptureWatchdog,
    GapFiller,
    Packet,
    ProcessLoopbackSource,
    WatchdogReason,
)
from instanttraductor.contracts import CAPTURE_RATE, AudioChunk, AudioSource, Clock, EngineError
from instanttraductor.pipeline.clock import ManualClock, SessionClock
from tests.contract.test_audio_contract import AudioSourceContract

Samples = npt.NDArray[np.float32]

PACKET_N = 160  # 10 ms a 16 kHz, como los paquetes reales del process loopback
PACKET_S = PACKET_N / CAPTURE_RATE
CHUNK_N = 320  # 20 ms


def samples(n: int = PACKET_N, value: float = 0.1) -> Samples:
    return np.full(n, value, dtype=np.float32)


def total_len(arrays: Iterable[Samples]) -> int:
    return sum(len(a) for a in arrays)


# --------------------------------------------------------------------------------------------------
# GapFiller: relleno de huecos de más de 100 ms
# --------------------------------------------------------------------------------------------------


def simulate(
    arrivals: list[tuple[float, int]], *, tick_step_s: float = 0.02, tail_s: float = 0.0
) -> tuple[GapFiller, int, list[float]]:
    """Reproduce llegadas `(instante, nº de muestras)` con un `tick` cada `tick_step_s`, como el hilo.

    Devuelve el relleno, las muestras emitidas y el retraso (`ahora - cubierto_hasta`) en cada paso.
    """
    filler = GapFiller()
    ordered = sorted(arrivals)
    end = ordered[-1][0] + tail_s + tick_step_s  # un paso más: que entren también las últimas llegadas
    emitted, lags, i, now = 0, [], 0, ordered[0][0]
    while now <= end:
        while i < len(ordered) and ordered[i][0] <= now:
            emitted += total_len(filler.push(ordered[i][0], samples(ordered[i][1], 0.0)))
            i += 1
        emitted += total_len(filler.tick(now))
        if filler.covered_until is not None:
            lags.append(now - filler.covered_until)
        now += tick_step_s
    return filler, emitted, lags


class TestGapFiller:
    def test_jitter_and_short_stalls_are_not_gaps(self) -> None:
        rng = np.random.default_rng(1)
        arrivals = []
        for k in range(600):
            t = 1.0 + k * 0.0100005 + rng.normal(0, 0.001)  # reloj de audio 50 ppm lento y 1 ms de jitter
            if 300 <= k < 304:
                t += 0.04  # parada de 40 ms: los paquetes se retrasan y luego llegan seguidos
            arrivals.append((t, PACKET_N))
        filler, emitted, _ = simulate(arrivals)
        assert filler.gaps == 0
        assert filler.filled_samples == 0
        assert filler.trimmed_samples == 0
        assert emitted == 600 * PACKET_N  # el audio real ni se recorta ni se duplica

    def test_the_audio_is_never_modified_outside_a_gap(self) -> None:
        rng = np.random.default_rng(2)
        filler = GapFiller()
        sent: list[Samples] = []
        out: list[Samples] = []
        for k in range(200):
            data = rng.standard_normal(PACKET_N).astype(np.float32)
            sent.append(data)
            out.extend(filler.push((k + 1) * PACKET_S + rng.normal(0, 0.002), data))
        assert np.array_equal(np.concatenate(out), np.concatenate(sent))

    @pytest.mark.parametrize(("stall_s", "filled"), [(0.09, False), (0.15, True)])
    def test_only_stalls_above_100_ms_are_filled(self, stall_s: float, filled: bool) -> None:
        filler = GapFiller()
        for k in range(50):
            filler.push((k + 1) * PACKET_S, samples())
        out = filler.push(0.5 + stall_s + PACKET_S, samples())
        assert (filler.gaps == 1) is filled
        assert filler.filled_samples == (round(stall_s * CAPTURE_RATE) if filled else 0)
        assert total_len(out) == PACKET_N + filler.filled_samples

    def test_two_real_gaps_of_two_seconds_are_filled_and_nothing_else(self) -> None:
        """Autoprueba sintética del spike S4: tres ráfagas de 2 s separadas por 2 s sin paquetes."""
        rng = np.random.default_rng(1)
        arrivals: list[tuple[float, int]] = []
        base = 0.0
        for burst in range(3):
            for k in range(200):
                t = base + k * 0.0100005 + rng.normal(0, 0.001)
                if burst == 0 and 100 <= k < 104:
                    t += 0.04
                arrivals.append((t, PACKET_N))
            base += 200 * 0.0100005 + 2.0
        filler, _, lags = simulate(arrivals)
        assert filler.gaps == 2
        assert filler.trimmed_samples / CAPTURE_RATE < 0.015  # no se recorta audio real
        assert filler.filled_samples / CAPTURE_RATE == pytest.approx(4.0, abs=0.25)
        assert max(lags) < 0.26  # la salida va pegada al reloj: margen más detección

    def test_a_gap_is_filled_in_real_time_by_tick_and_resynchronised_with_the_arrival(self) -> None:
        filler = GapFiller()
        total = 0
        for k in range(100):  # 1 s de audio
            total += total_len(filler.push((k + 1) * PACKET_S, samples()))
        assert not filler.in_gap
        now = 1.0
        for _ in range(100):  # 2 s sin paquetes, con un `tick` cada 20 ms
            now += 0.02
            total += total_len(filler.tick(now))
        assert filler.in_gap
        assert filler.gaps == 1
        assert filler.covered_until == pytest.approx(now - wasapi_capture.GAP_MARGIN_S, abs=1e-4)
        total += total_len(filler.push(3.01, samples()))  # vuelve el audio: empieza en 3,00 s
        assert not filler.in_gap
        assert total / CAPTURE_RATE == pytest.approx(3.01, abs=0.005)  # alineado con el reloj de pared

    def test_overshoot_after_a_gap_trims_the_start_of_the_first_packet(self) -> None:
        filler = GapFiller()
        for k in range(100):
            filler.push((k + 1) * PACKET_S, samples())
        now = 1.0
        for _ in range(100):
            now += 0.02
            filler.tick(now)  # los ceros llegan hasta 2,96 s
        assert filler.covered_until == pytest.approx(2.96, abs=1e-4)
        out = filler.push(3.0, samples(2560))  # 160 ms de audio que empiezan en 2,84 s: 120 ms ya cubiertos
        assert filler.trimmed_samples == pytest.approx(1920, abs=1)
        assert total_len(out) == 2560 - filler.trimmed_samples
        assert filler.covered_until == pytest.approx(3.0, abs=1e-4)

    def test_tick_before_the_first_packet_does_nothing(self) -> None:
        filler = GapFiller()
        assert filler.tick(5.0) == []
        assert not filler.in_gap
        assert filler.covered_until is None

    def test_tick_without_a_gap_emits_nothing(self) -> None:
        filler = GapFiller()
        filler.push(PACKET_S, samples())
        assert filler.tick(0.05) == []
        assert filler.tick(0.14) == []  # 140 ms tras el último paquete: aún no es un hueco

    def test_the_output_is_float32(self) -> None:
        filler = GapFiller()
        filler.push(PACKET_S, samples())
        out = filler.push(1.0, samples())
        assert all(a.dtype == np.float32 for a in out)


# --------------------------------------------------------------------------------------------------
# CaptureWatchdog: las tres condiciones y como máximo una reapertura cada 10 s
# --------------------------------------------------------------------------------------------------


class TestCaptureWatchdog:
    def check(
        self,
        dog: CaptureWatchdog,
        now: float,
        *,
        last_packet_at: float | None = None,
        error: str | None = None,
        target_ok: bool = True,
    ) -> WatchdogReason | None:
        last = now - 0.01 if last_packet_at is None else last_packet_at
        return dog.check(now, last_packet_at=last, error=error, target_ok=target_ok)

    def test_nothing_to_report_while_everything_is_fine(self) -> None:
        assert self.check(CaptureWatchdog(), 100.0) is None

    @pytest.mark.parametrize(
        ("silence_s", "reason"), [(0.4, None), (0.5, None), (0.51, WatchdogReason.NO_PACKETS)]
    )
    def test_more_than_half_a_second_without_packets(
        self, silence_s: float, reason: WatchdogReason | None
    ) -> None:
        assert self.check(CaptureWatchdog(), 10.0, last_packet_at=10.0 - silence_s) is reason

    def test_a_wasapi_error(self) -> None:
        reason = self.check(CaptureWatchdog(), 1.0, error="AUDCLNT_E_DEVICE_INVALIDATED (0x88890004)")
        assert reason is WatchdogReason.WASAPI_ERROR

    def test_the_target_pid_is_no_longer_the_right_one(self) -> None:
        assert self.check(CaptureWatchdog(), 1.0, target_ok=False) is WatchdogReason.PID_CHANGED

    def test_the_most_specific_reason_wins(self) -> None:
        dog = CaptureWatchdog()
        assert (
            self.check(dog, 5.0, last_packet_at=0.0, error="x", target_ok=False) is WatchdogReason.PID_CHANGED
        )
        assert self.check(dog, 5.0, last_packet_at=0.0, error="x") is WatchdogReason.WASAPI_ERROR

    def test_the_first_reopen_is_never_throttled(self) -> None:
        assert self.check(CaptureWatchdog(), 0.6, last_packet_at=0.0) is WatchdogReason.NO_PACKETS

    def test_at_most_one_reopen_every_10_seconds(self) -> None:
        dog = CaptureWatchdog()
        dog.note_reopen(1.0)
        assert self.check(dog, 1.5, error="x") is None
        assert self.check(dog, 10.99, error="x") is None
        assert self.check(dog, 11.0, error="x") is WatchdogReason.WASAPI_ERROR
        dog.note_reopen(11.0)
        assert self.check(dog, 20.0, error="x") is None
        assert self.check(dog, 21.5, error="x") is WatchdogReason.WASAPI_ERROR

    def test_thresholds_are_configurable(self) -> None:
        dog = CaptureWatchdog(silence_limit_s=0.2, min_reopen_interval_s=1.0)
        assert self.check(dog, 5.0, last_packet_at=4.7) is WatchdogReason.NO_PACKETS
        dog.note_reopen(5.0)
        assert self.check(dog, 5.5, error="x") is None
        assert self.check(dog, 6.0, error="x") is WatchdogReason.WASAPI_ERROR


# --------------------------------------------------------------------------------------------------
# ArrivalLog: hora de llegada de cada chunk, con 30 s de histórico
# --------------------------------------------------------------------------------------------------


class TestArrivalLog:
    @staticmethod
    def filled(seconds: float, *, latency_s: float = 0.015) -> ArrivalLog:
        log = ArrivalLog()
        for k in range(round(seconds / 0.02)):
            t_end = (k + 1) * 0.02
            log.record(k * 0.02, t_end, t_end + latency_s)
        return log

    def test_returns_the_arrival_of_the_chunk_that_contains_the_instant(self) -> None:
        log = self.filled(1.0)
        assert log.lookup(0.51) == pytest.approx(0.535)  # chunk (0,50 ; 0,52]
        assert log.lookup(0.519) == pytest.approx(0.535)
        assert log.lookup(0.521) == pytest.approx(0.555)  # el siguiente

    def test_an_instant_on_a_boundary_belongs_to_the_chunk_that_ends_there(self) -> None:
        log = self.filled(1.0)
        assert log.lookup(0.5) == pytest.approx(0.515)  # `t_end_audio` = fin del chunk (0,48 ; 0,50]
        assert log.lookup(0.0) == pytest.approx(0.035)  # el comienzo exacto de la captura

    def test_the_future_is_unknown(self) -> None:
        log = self.filled(1.0)
        assert log.lookup(1.5) is None
        assert ArrivalLog().lookup(0.0) is None

    def test_only_the_last_30_seconds_are_kept(self) -> None:
        log = self.filled(40.0)
        assert log.lookup(5.0) is None
        assert log.lookup(9.0) is None
        assert log.lookup(11.0) == pytest.approx(11.015)
        assert log.lookup(39.99) == pytest.approx(40.015)

    def test_the_history_is_bounded(self) -> None:
        log = self.filled(100.0)
        assert len(log) <= 30 / 0.02 + 2


# --------------------------------------------------------------------------------------------------
# ProcessLoopbackSource sin hilo: flujo falso y reloj manual
# --------------------------------------------------------------------------------------------------


class FakeStream:
    """Flujo de paquetes simulado (sin COM): los tests lo alimentan a mano con `feed`."""

    def __init__(self) -> None:
        self.pending: deque[Packet] = deque()
        self.error: str | None = None
        self.closed = False
        self._wake = threading.Event()

    def feed(self, arrival: float, data: Samples | None = None) -> None:
        self.pending.append(Packet(arrival, samples() if data is None else data))
        self._wake.set()

    def wait(self, timeout_s: float) -> bool:
        woke = self._wake.wait(timeout_s)
        self._wake.clear()
        return woke

    def read_packets(self) -> list[Packet]:
        packets = list(self.pending)
        self.pending.clear()
        return packets

    def close(self) -> None:
        self.closed = True
        self._wake.set()


class FakeFactory:
    """`stream_factory` que guarda las llamadas y los flujos; puede fallar en las aperturas indicadas."""

    def __init__(self, fail_on: Iterable[int] = ()) -> None:
        self.fail_on = set(fail_on)
        self.calls: list[tuple[int, bool]] = []
        self.streams: list[FakeStream] = []

    def __call__(self, pid: int, exclude: bool, now: Callable[[], float]) -> FakeStream:
        index = len(self.calls)
        self.calls.append((pid, exclude))
        if index in self.fail_on:
            raise EngineError("dispositivo no disponible (simulado)", engine="capture")
        stream = FakeStream()
        self.streams.append(stream)
        return stream


class Rig:
    """Fuente con flujo simulado y reloj manual, **sin hilo**: el test avanza el tiempo y procesa a mano."""

    def __init__(self, *, fail_on: Iterable[int] = (), **kwargs: object) -> None:
        self.clock = ManualClock()
        self.factory = FakeFactory(fail_on)
        self.warnings: list[str] = []
        self.reopened_at: list[float] = []
        self.fed = 0  # paquetes alimentados hasta ahora
        kwargs.setdefault("on_warning", self.warnings.append)
        kwargs.setdefault("on_reopen", lambda: self.reopened_at.append(self.clock.now()))
        self.source = ProcessLoopbackSource(self.clock, stream_factory=self.factory, **kwargs)
        self.source._open_stream(self.clock.now())

    @property
    def stream(self) -> FakeStream:
        return self.factory.streams[-1]

    def run(
        self, seconds: float, *, packets: bool = True, data: Callable[[int], Samples] | None = None
    ) -> None:
        """Avanza el reloj en pasos de 10 ms; en cada uno llega un paquete (si `packets`) y se procesa."""
        for _ in range(round(seconds / PACKET_S)):
            self.clock.advance(PACKET_S)
            if packets:
                self.stream.feed(self.clock.now(), None if data is None else data(self.fed))
                self.fed += 1
            self.source._pump_once()

    def chunks(self) -> list[AudioChunk]:
        out: list[AudioChunk] = []
        while (chunk := self.source.read(0.0)) is not None:
            out.append(chunk)
        return out


class TestChunking:
    def test_chunks_are_20_ms_contiguous_mono_float32_at_16_khz(self) -> None:
        rig = Rig()
        rig.run(1.0)
        chunks = rig.chunks()
        assert len(chunks) == 50
        for k, chunk in enumerate(chunks):
            assert chunk.sample_rate == CAPTURE_RATE
            assert chunk.samples.dtype == np.float32
            assert chunk.samples.shape == (CHUNK_N,)
            assert chunk.t_start == pytest.approx(k * 0.02, abs=1e-9)
        for previous, current in zip(chunks, chunks[1:], strict=False):
            assert current.t_start == pytest.approx(previous.t_end, abs=1e-9)

    def test_the_audio_passes_through_unchanged(self) -> None:
        rig = Rig()
        rng = np.random.default_rng(3)
        sent = [rng.uniform(-1, 1, PACKET_N).astype(np.float32) for _ in range(100)]
        rig.run(1.0, data=lambda i: sent[i])
        assert np.array_equal(np.concatenate([c.samples for c in rig.chunks()]), np.concatenate(sent))

    def test_packets_of_any_size_are_regrouped_into_chunks(self) -> None:
        rig = Rig()
        for k, n in enumerate((441, 441, 500, 100, 1000, 320), start=1):
            rig.clock.advance(n / CAPTURE_RATE)
            rig.stream.feed(rig.clock.now(), samples(n, 0.1 * k))
            rig.source._pump_once()
        chunks = rig.chunks()
        assert [len(c.samples) for c in chunks] == [CHUNK_N] * (2802 // CHUNK_N)
        assert chunks[0].samples[0] == np.float32(0.1)

    def test_a_chunk_is_not_published_until_it_is_complete(self) -> None:
        rig = Rig()
        rig.run(PACKET_S)  # un solo paquete: medio chunk
        assert rig.source.read(0.0) is None
        rig.run(PACKET_S)
        assert rig.source.read(0.0) is not None

    def test_the_chunk_length_is_configurable(self) -> None:
        rig = Rig(chunk_s=0.01)
        rig.run(0.5)
        assert {len(c.samples) for c in rig.chunks()} == {PACKET_N}

    def test_read_returns_none_when_there_is_nothing(self) -> None:
        assert Rig().source.read(0.0) is None

    def test_a_backlog_that_the_consumer_never_drains_is_bounded(self) -> None:
        rig = Rig(max_backlog_s=0.1)  # 5 chunks
        rig.run(2.0)
        chunks = rig.chunks()
        assert len(chunks) == 5
        assert chunks[-1].t_end == pytest.approx(2.0, abs=0.02)  # se conservan los más recientes
        assert sum("no da abasto" in w for w in rig.warnings) == 1  # y se avisa una sola vez por episodio


class TestGapFillingInTheSource:
    def test_a_gap_is_filled_with_zeros_and_the_chunks_stay_contiguous(self) -> None:
        rig = Rig()
        rig.run(1.0)
        rig.run(1.0, packets=False)  # la captura se queda sin paquetes durante 1 s
        rig.run(1.0)
        chunks = rig.chunks()
        assert sum(c.duration for c in chunks) == pytest.approx(
            3.0, abs=0.06
        )  # el reloj de audio sigue al de pared
        for previous, current in zip(chunks, chunks[1:], strict=False):
            assert current.t_start == pytest.approx(previous.t_end, abs=1e-9)
        assert all(not c.samples.any() for c in chunks if 1.3 <= c.t_start <= 1.8)  # dentro del hueco: ceros
        assert all(np.all(c.samples == np.float32(0.1)) for c in chunks if c.t_start < 0.96)
        assert all(np.all(c.samples == np.float32(0.1)) for c in chunks if c.t_start > 2.1)
        assert sum("Hueco" in w for w in rig.warnings) == 1

    def test_a_short_stall_is_not_a_gap(self) -> None:
        rig = Rig()
        rig.run(1.0)
        rig.run(0.09, packets=False)
        rig.run(1.0)
        assert not any("Hueco" in w for w in rig.warnings)
        # sin hueco no se inventa audio: solo cuenta el real (2 s), aunque haya habido una parada de 90 ms
        assert sum(c.duration for c in rig.chunks()) == pytest.approx(2.0, abs=0.02)

    def test_a_late_read_is_not_a_gap_while_wasapi_kept_the_data(self) -> None:
        """El hilo no tuvo la CPU durante 150 ms: los 15 paquetes que WASAPI retuvo se leen de golpe."""
        rig = Rig()
        rig.run(1.0)
        rig.clock.advance(0.15)  # el hilo está parado: no hay lectura ni `tick`
        for _ in range(15):
            rig.stream.feed(rig.clock.now(), samples())  # el flujo los sella al leerlos: todos a la vez
        rig.source._pump_once()
        rig.run(0.5)
        chunks = rig.chunks()
        assert not any("Hueco" in w for w in rig.warnings)
        assert all(np.all(c.samples == np.float32(0.1)) for c in chunks)  # no se inventó ningún cero
        assert sum(c.duration for c in chunks) == pytest.approx(1.65, abs=0.02)  # 1,0 + 0,15 + 0,5 s
        # La llegada es la de la lectura real: el retraso del hilo cuenta como retraso de captura.
        assert rig.source.arrival_time(1.1) == pytest.approx(1.15)

    def test_data_that_wasapi_lost_during_a_long_stall_is_replaced_by_silence(self) -> None:
        """El hilo estuvo parado 300 ms y el búfer de WASAPI (100 ms) solo conservó el último tramo."""
        rig = Rig()
        rig.run(1.0)
        rig.clock.advance(0.3)
        for _ in range(10):
            rig.stream.feed(rig.clock.now(), samples())
        rig.source._pump_once()
        chunks = rig.chunks()
        assert sum("Hueco" in w for w in rig.warnings) == 1
        assert sum(c.duration for c in chunks) == pytest.approx(
            1.3, abs=0.02
        )  # el reloj de audio sigue al de pared
        assert all(not c.samples.any() for c in chunks if 1.02 <= c.t_start <= 1.18)  # 0,2 s de ceros

    def test_the_arrival_time_of_a_filled_chunk_is_when_it_was_generated(self) -> None:
        rig = Rig()
        rig.run(1.0)
        rig.run(1.0, packets=False)
        arrival = rig.source.arrival_time(1.6)
        assert arrival is not None
        assert 1.6 <= arrival <= 1.6 + 0.2  # los ceros salen en tiempo real, con el margen del relleno


class TestWatchdogInTheSource:
    def test_no_packets_for_more_than_half_a_second_reopens_the_capture(self) -> None:
        rig = Rig()
        rig.run(1.0)
        first = rig.stream
        rig.run(0.4, packets=False)
        assert len(rig.factory.calls) == 1  # aún no
        rig.run(0.2, packets=False)
        assert len(rig.factory.calls) == 2
        assert first.closed
        assert not rig.stream.closed
        assert len(rig.reopened_at) == 1
        assert any("Reabriendo" in w and "paquetes" in w for w in rig.warnings)

    def test_after_the_reopen_the_audio_flows_again_without_reopening_again(self) -> None:
        rig = Rig()
        rig.run(1.0)
        rig.run(0.6, packets=False)  # reapertura
        rig.run(2.0)
        assert len(rig.factory.calls) == 2
        assert len(rig.reopened_at) == 1
        chunks = rig.chunks()
        for previous, current in zip(chunks, chunks[1:], strict=False):
            assert current.t_start == pytest.approx(previous.t_end, abs=1e-9)
        assert sum(c.duration for c in chunks) == pytest.approx(3.6, abs=0.06)

    def test_a_wasapi_error_reopens_the_capture(self) -> None:
        rig = Rig()
        rig.run(1.0)
        rig.stream.error = "AUDCLNT_E_DEVICE_INVALIDATED (0x88890004)"
        rig.run(PACKET_S)
        assert len(rig.factory.calls) == 2
        assert len(rig.reopened_at) == 1
        assert any("AUDCLNT_E_DEVICE_INVALIDATED" in w for w in rig.warnings)

    def test_a_changed_process_pid_reopens_the_capture_with_the_new_pid(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rig = Rig()
        rig.run(1.0)
        assert rig.factory.calls == [(os.getpid(), True)]
        monkeypatch.setattr(wasapi_capture, "_current_pid", lambda: 424242)
        rig.run(PACKET_S)
        assert rig.factory.calls == [(os.getpid(), True), (424242, True)]
        assert len(rig.reopened_at) == 1
        rig.run(1.0)
        assert len(rig.factory.calls) == 2  # el nuevo PID ya es el objetivo: no hay más reaperturas

    def test_an_explicit_target_pid_that_died_reopens_the_capture(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        alive = {"value": True}
        monkeypatch.setattr(wasapi_capture, "_pid_exists", lambda pid: alive["value"])
        rig = Rig(target_pid=1234)
        rig.run(0.5)
        assert (
            len(rig.factory.calls) == 1
        )  # un PID explícito no se compara con el del proceso: solo importa que viva
        alive["value"] = False
        rig.run(PACKET_S)
        assert rig.factory.calls == [(1234, True), (1234, True)]

    def test_at_most_one_reopen_every_10_seconds(self) -> None:
        rig = Rig()
        rig.run(1.0)
        rig.run(0.6, packets=False)  # t = 1,6: primera reapertura (la nueva captura tampoco da paquetes)
        assert len(rig.factory.calls) == 2
        rig.run(9.0, packets=False)  # t = 10,6: han pasado 9 s
        assert len(rig.factory.calls) == 2
        rig.run(1.2, packets=False)  # t = 11,8: ya pasaron 10 s
        assert len(rig.factory.calls) == 3
        assert len(rig.reopened_at) == 2
        assert rig.reopened_at[1] - rig.reopened_at[0] >= 10.0

    def test_a_failed_reopen_warns_and_is_retried_after_10_seconds(self) -> None:
        rig = Rig(fail_on={1})  # la segunda apertura (la primera reapertura) falla
        rig.run(1.0)
        rig.run(0.6, packets=False)
        assert any("No se pudo reabrir" in w for w in rig.warnings)
        assert rig.reopened_at == []  # no hay captura: la sesión no debe repetir el autotest todavía
        assert rig.source._stream is None
        rig.run(0.5, packets=False)  # sin captura el reloj de audio sigue avanzando con ceros
        assert len(rig.factory.calls) == 2
        rig.run(10.0, packets=False)
        assert len(rig.factory.calls) == 3  # segundo intento, esta vez bien
        assert len(rig.reopened_at) == 1
        rig.run(1.0)
        chunks = rig.chunks()
        assert sum(c.duration for c in chunks) == pytest.approx(13.1, abs=0.1)

    def test_include_selects_the_positive_control_mode(self) -> None:
        assert Rig().factory.calls == [(os.getpid(), True)]  # EXCLUDE por defecto
        assert Rig(include=True).factory.calls == [(os.getpid(), False)]

    def test_the_default_target_is_the_own_process_and_an_explicit_pid_is_respected(self) -> None:
        assert Rig().factory.calls[0][0] == os.getpid()
        assert Rig(target_pid=777).factory.calls[0][0] == 777

    def test_a_failing_callback_does_not_stop_the_capture(self) -> None:
        def boom(*_args: object) -> None:
            raise RuntimeError("fallo del suscriptor")

        rig = Rig(on_warning=boom, on_reopen=boom)
        rig.run(1.0)
        rig.run(0.6, packets=False)  # reapertura: avisa y notifica, y los dos callbacks fallan
        rig.run(1.0)
        assert len(rig.factory.calls) == 2
        assert rig.chunks()


class TestArrivalTimeInTheSource:
    def test_arrival_time_is_the_session_time_when_the_chunk_was_completed(self) -> None:
        rig = Rig()
        rig.run(1.0)
        assert rig.source.arrival_time(0.51) == pytest.approx(0.52, abs=1e-9)  # chunk (0,50 ; 0,52]
        assert rig.source.arrival_time(0.5) == pytest.approx(0.5, abs=1e-9)  # chunk (0,48 ; 0,50]
        assert rig.source.arrival_time(0.0) == pytest.approx(0.02, abs=1e-9)

    def test_an_instant_not_captured_yet_is_unknown(self) -> None:
        rig = Rig()
        rig.run(1.0)
        assert rig.source.arrival_time(5.0) is None

    def test_the_history_covers_the_last_30_seconds(self) -> None:
        rig = Rig()
        rig.run(40.0)
        assert rig.source.arrival_time(2.0) is None
        assert rig.source.arrival_time(25.0) == pytest.approx(25.0, abs=0.021)
        assert rig.source.arrival_time(39.99) == pytest.approx(40.0, abs=0.021)

    def test_arrival_time_does_not_consume_chunks(self) -> None:
        rig = Rig()
        rig.run(0.5)
        rig.source.arrival_time(0.2)
        assert len(rig.chunks()) == 25

    def test_arrival_time_is_available_before_the_chunks_are_read(self) -> None:
        rig = Rig()
        rig.run(1.0)
        assert rig.source.arrival_time(0.9) is not None
        rig.chunks()
        assert rig.source.arrival_time(0.9) is not None


# --------------------------------------------------------------------------------------------------
# ProcessLoopbackSource con hilo (flujo falso en tiempo real)
# --------------------------------------------------------------------------------------------------


class LiveFakeStream(FakeStream):
    """Emite un paquete de 10 ms cada 10 ms de tiempo real, con un tono: lo que hace el process loopback."""

    def __init__(self, clock: Clock) -> None:
        super().__init__()
        self._clock = clock
        self._origin = clock.now()
        self._sent = 0
        self._halt = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="flujo-falso", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._halt.wait(0.005):
            due = int((self._clock.now() - self._origin) / PACKET_S)
            while self._sent < due:
                n = np.arange(self._sent * PACKET_N, (self._sent + 1) * PACKET_N)
                self.feed(
                    self._clock.now(), (0.3 * np.sin(2 * np.pi * 440.0 * n / CAPTURE_RATE)).astype(np.float32)
                )
                self._sent += 1

    def close(self) -> None:
        super().close()
        self._halt.set()
        self._thread.join(timeout=2.0)


def live_factory(clock: Clock) -> Callable[[int, bool, Callable[[], float]], LiveFakeStream]:
    return lambda pid, exclude, now: LiveFakeStream(clock)


class TestWithAThread:
    def test_start_delivers_chunks_and_stop_ends_it(self) -> None:
        clock = SessionClock()
        source = ProcessLoopbackSource(clock, stream_factory=live_factory(clock))
        source.start()
        try:
            chunks = [source.read(1.0) for _ in range(20)]
        finally:
            source.stop()
        assert all(c is not None for c in chunks)
        assert source.exhausted
        assert source.read(0.0) is None

    def test_arrival_time_of_live_chunks_is_close_to_the_audio_time(self) -> None:
        clock = SessionClock()
        source = ProcessLoopbackSource(clock, stream_factory=live_factory(clock))
        source.start()
        try:
            chunk = None
            for _ in range(30):
                chunk = source.read(1.0)
            assert chunk is not None
            arrival = source.arrival_time(chunk.t_end)
            assert arrival is not None
            assert -0.05 <= arrival - chunk.t_end <= 0.3  # el audio llega con unas decenas de ms de retraso
        finally:
            source.stop()

    def test_start_fails_with_an_engine_error_when_the_device_cannot_be_opened(self) -> None:
        def broken(pid: int, exclude: bool, now: Callable[[], float]) -> FakeStream:
            raise OSError("sin dispositivo (simulado)")

        source = ProcessLoopbackSource(SessionClock(), stream_factory=broken)
        with pytest.raises(EngineError, match="sin dispositivo"):
            source.start()
        assert source.exhausted
        source.stop()

    def test_start_is_idempotent(self) -> None:
        clock = SessionClock()
        factory = FakeFactory()
        source = ProcessLoopbackSource(clock, stream_factory=factory)
        source.start()
        source.start()
        source.stop()
        source.start()  # tras parar no vuelve a arrancar
        assert len(factory.calls) == 1

    def test_stop_before_start_is_harmless(self) -> None:
        source = ProcessLoopbackSource(SessionClock(), stream_factory=FakeFactory())
        source.stop()
        source.stop()
        assert source.exhausted

    def test_read_waits_up_to_the_timeout_and_returns_none_without_data(self) -> None:
        factory = FakeFactory()  # un flujo que no entrega nada
        source = ProcessLoopbackSource(SessionClock(), stream_factory=factory)
        source.start()
        try:
            before = time.perf_counter()
            assert source.read(0.1) is None
            assert 0.08 <= time.perf_counter() - before < 0.4
        finally:
            source.stop()

    def test_stop_wakes_up_a_blocked_read(self) -> None:
        source = ProcessLoopbackSource(SessionClock(), stream_factory=FakeFactory())
        source.start()
        result: list[AudioChunk | None] = []
        reader = threading.Thread(target=lambda: result.append(source.read(10.0)), daemon=True)
        reader.start()
        time.sleep(0.1)
        source.stop()
        reader.join(timeout=2.0)
        assert not reader.is_alive()
        assert result == [None]

    def test_stop_closes_the_stream(self) -> None:
        clock = SessionClock()
        factory = FakeFactory()
        source = ProcessLoopbackSource(clock, stream_factory=factory)
        source.start()
        source.stop()
        assert factory.streams[0].closed

    def test_stop_from_a_callback_does_not_deadlock(self) -> None:
        clock = SessionClock()
        holder: list[ProcessLoopbackSource] = []
        stopped = threading.Event()

        def on_warning(_message: str) -> None:
            holder[0].stop()  # se llama desde el hilo de captura
            stopped.set()

        source = ProcessLoopbackSource(clock, stream_factory=FakeFactory(), on_warning=on_warning)
        holder.append(source)
        source.start()
        assert stopped.wait(3.0)  # sin paquetes: a los 0,5 s el vigilante reabre y avisa
        assert source.exhausted


class TestProcessLoopbackSourceWithAFakeStream(AudioSourceContract):
    """El contrato de `AudioSource` con el flujo falso. Es una fuente en vivo: solo termina con `stop()`."""

    finite = False

    @pytest.fixture
    def make_impl(self) -> Callable[[], AudioSource]:
        def make() -> AudioSource:
            clock = SessionClock()
            return ProcessLoopbackSource(clock, stream_factory=live_factory(clock))

        return make


# --------------------------------------------------------------------------------------------------
# Capa de Windows (sin abrir ningún dispositivo)
# --------------------------------------------------------------------------------------------------

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="La captura por proceso es de Windows")


@windows_only
def test_importing_the_module_sets_com_to_mta_before_comtypes_is_loaded() -> None:
    """`sys.coinit_flags = 0` antes de importar comtypes: el hilo que importa queda en MTA, no en STA."""
    code = textwrap.dedent(
        """
        import ctypes
        import sys

        import instanttraductor.audio.wasapi_capture  # fija sys.coinit_flags e importa comtypes

        apartment, qualifier = ctypes.c_int(), ctypes.c_int()
        hr = ctypes.windll.ole32.CoGetApartmentType(ctypes.byref(apartment), ctypes.byref(qualifier))
        print(sys.coinit_flags, hr, apartment.value)
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60, check=True
    )
    flags, hresult, apartment = result.stdout.split()
    assert (flags, hresult) == ("0", "0")
    assert apartment == "1"  # APTTYPE_MTA


@windows_only
def test_the_flag_is_set_in_this_process_too() -> None:
    assert sys.coinit_flags == 0


@windows_only
def test_the_activation_structures_have_the_layout_that_windows_expects() -> None:
    import ctypes

    assert ctypes.sizeof(wasapi_capture.AUDIOCLIENT_ACTIVATION_PARAMS) == 12  # tipo + PID + modo
    assert ctypes.sizeof(wasapi_capture.PROPVARIANT) == (24 if ctypes.sizeof(ctypes.c_void_p) == 8 else 16)


@windows_only
def test_hresults_have_readable_names() -> None:
    assert "AUDCLNT_E_DEVICE_INVALIDATED" in wasapi_capture.hresult_name(-2004287484)  # 0x88890004
    assert wasapi_capture.hresult_name(0x80070057).startswith("E_INVALIDARG")
    assert "0x12345678" in wasapi_capture.hresult_name(0x12345678)


@windows_only
class TestActivationWithoutADevice:
    """La activación hasta justo antes de hablar con Windows: se sustituye `ActivateAudioInterfaceAsync`."""

    E_INVALIDARG = -2147024809  # 0x80070057

    @pytest.fixture
    def seen(self, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
        """Apunta lo que recibe `ActivateAudioInterfaceAsync` y responde con un error."""
        seen: dict[str, object] = {}

        def fake_activate(
            name: str, iid: object, variant_ref: Any, handler: object, operation: object
        ) -> int:
            variant = variant_ref._obj  # lo que había dentro de `byref(...)`
            blob = variant.data.blob
            params_type = ctypes.POINTER(wasapi_capture.AUDIOCLIENT_ACTIVATION_PARAMS)
            params = ctypes.cast(blob.pBlobData, params_type).contents
            seen.update(
                name=name,
                vt=variant.vt,
                size=blob.cbSize,
                type=params.ActivationType,
                pid=params.ProcessLoopbackParams.TargetProcessId,
                mode=params.ProcessLoopbackParams.ProcessLoopbackMode,
            )
            return self.E_INVALIDARG

        monkeypatch.setattr(wasapi_capture, "_win_api", lambda: SimpleNamespace(activate=fake_activate))
        return seen

    @pytest.mark.parametrize(("exclude", "mode"), [(True, 1), (False, 0)])
    def test_the_blob_carries_the_pid_and_the_loopback_mode(
        self, seen: dict[str, object], exclude: bool, mode: int
    ) -> None:
        with pytest.raises(EngineError, match="E_INVALIDARG"):
            wasapi_capture._activate_process_client(4321, exclude, 1.0)
        assert seen == {
            "name": "VAD\\Process_Loopback",
            "vt": 65,  # VT_BLOB
            "size": 12,
            "type": 1,  # AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK
            "pid": 4321,
            "mode": mode,  # 1 = EXCLUDE_TARGET_PROCESS_TREE, 0 = INCLUDE_TARGET_PROCESS_TREE
        }

    def test_the_stream_reports_a_failed_activation_as_an_engine_error(self, seen: dict[str, object]) -> None:
        with pytest.raises(EngineError, match="E_INVALIDARG"):
            wasapi_capture._ProcessLoopbackStream(4321, True, lambda: 0.0)
        assert seen["pid"] == 4321

    def test_start_reports_a_failed_activation_from_the_real_stream(self, seen: dict[str, object]) -> None:
        """Hilo, COM por hilo y propagación del error hasta `start()`, con la clase real y sin dispositivo."""
        source = ProcessLoopbackSource(SessionClock(), target_pid=4321, include=True)
        with pytest.raises(EngineError, match="E_INVALIDARG"):
            source.start()
        assert source.exhausted
        assert (seen["pid"], seen["mode"]) == (4321, 0)

    def test_a_windows_without_process_loopback_is_not_recoverable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def missing() -> None:
            raise AttributeError("ActivateAudioInterfaceAsync")

        monkeypatch.setattr(wasapi_capture, "_win_api", missing)
        with pytest.raises(EngineError, match="no admite") as error:
            wasapi_capture._activate_process_client(1, True, 1.0)
        assert error.value.recoverable is False


class FakeCaptureClient:
    """`IAudioCaptureClient` falso: entrega paquetes desde un búfer de ctypes, como WASAPI.

    `ReleaseBuffer` machaca el búfer: lo que se lea después de soltarlo sería basura.
    """

    def __init__(self, packets: list[tuple[Samples, int]], channels: int = 1) -> None:
        self.packets = deque(packets)
        self.channels = channels
        self.released: list[int] = []
        self.fail_after: int | None = None  # nº de paquetes tras los que `GetBuffer` lanza un COMError
        self._buffer: Any = None

    def GetNextPacketSize(self) -> int:  # noqa: N802 - nombre de la API de WASAPI
        return len(self.packets[0][0]) // self.channels if self.packets else 0

    def GetBuffer(self) -> tuple[Any, int, int, int, int]:  # noqa: N802
        if self.fail_after is not None and self.fail_after <= 0:
            raise wasapi_capture.COMError(-2004287484, "dispositivo invalidado", (None, None, None, 0, None))
        if self.fail_after is not None:
            self.fail_after -= 1
        data, flags = self.packets.popleft()
        self._buffer = (ctypes.c_ubyte * data.nbytes).from_buffer_copy(data.tobytes())
        return (
            ctypes.cast(self._buffer, ctypes.POINTER(ctypes.c_ubyte)),
            len(data) // self.channels,
            flags,
            0,
            0,
        )

    def ReleaseBuffer(self, frames: int) -> None:  # noqa: N802
        self.released.append(frames)
        if self._buffer is not None:
            ctypes.memset(self._buffer, 0xFF, ctypes.sizeof(self._buffer))  # NaN: ya no es nuestro


def make_real_stream(capture: FakeCaptureClient, clock: Callable[[], float] = lambda: 1.5) -> Any:
    """Un `_ProcessLoopbackStream` sin abrir (sin `__init__`) que lee de `capture`."""
    stream = object.__new__(wasapi_capture._ProcessLoopbackStream)
    stream._now = clock
    stream._error = None
    stream._client = None
    stream._capture = capture
    stream._event = None
    stream._channels = capture.channels
    stream._com_initialized = False  # no se ha llamado a CoInitializeEx: `close` no debe deshacerlo
    return stream


@windows_only
class TestRealStreamReading:
    """La lectura de paquetes de `_ProcessLoopbackStream` con un `IAudioCaptureClient` falso."""

    def test_mono_packets_are_copied_before_they_are_released(self) -> None:
        data = [np.linspace(-0.5, 0.5, 160, dtype=np.float32), np.full(160, 0.25, dtype=np.float32)]
        capture = FakeCaptureClient([(d, 0) for d in data])
        stream = make_real_stream(capture, clock=iter([1.0, 1.01]).__next__)
        packets = stream.read_packets()
        assert [p.arrival for p in packets] == [1.0, 1.01]
        assert all(p.samples.dtype == np.float32 for p in packets)
        assert np.array_equal(np.concatenate([p.samples for p in packets]), np.concatenate(data))
        assert capture.released == [160, 160]
        assert stream.error is None

    def test_silent_packets_are_zeros_whatever_the_buffer_holds(self) -> None:
        garbage = np.full(160, 0.9, dtype=np.float32)  # WASAPI: con el flag SILENT el contenido no vale
        capture = FakeCaptureClient([(garbage, 0x2), (garbage, 0)])
        packets = make_real_stream(capture).read_packets()
        assert not packets[0].samples.any()
        assert np.all(packets[1].samples == np.float32(0.9))
        assert capture.released == [160, 160]

    def test_stereo_is_mixed_down_to_mono(self) -> None:
        left, right = np.full(160, 0.5, dtype=np.float32), np.full(160, -0.1, dtype=np.float32)
        interleaved = np.stack([left, right], axis=1).reshape(-1)
        packets = make_real_stream(FakeCaptureClient([(interleaved, 0)], channels=2)).read_packets()
        assert packets[0].samples.shape == (160,)
        assert np.allclose(packets[0].samples, 0.2)

    def test_nothing_pending_gives_no_packets(self) -> None:
        assert make_real_stream(FakeCaptureClient([])).read_packets() == []

    def test_a_wasapi_error_is_recorded_and_keeps_what_was_already_read(self) -> None:
        capture = FakeCaptureClient([(samples(), 0)] * 3)
        capture.fail_after = 1
        stream = make_real_stream(capture)
        assert len(stream.read_packets()) == 1
        assert stream.error is not None
        assert "AUDCLNT_E_DEVICE_INVALIDATED" in stream.error

    def test_each_call_reads_a_bounded_number_of_packets(self) -> None:
        capture = FakeCaptureClient([(samples(), 0)] * 250)
        stream = make_real_stream(capture)
        assert len(stream.read_packets()) == 200
        assert len(stream.read_packets()) == 50

    def test_a_closed_stream_reads_nothing(self) -> None:
        stream = make_real_stream(FakeCaptureClient([(samples(), 0)]))
        stream._capture = None
        assert stream.read_packets() == []

    @pytest.mark.parametrize(
        ("result", "ready", "error"),
        [(0, True, False), (0x102, False, False), (0xFFFFFFFF, False, True)],
    )
    def test_wait_maps_the_win32_result(
        self, monkeypatch: pytest.MonkeyPatch, result: int, ready: bool, error: bool
    ) -> None:
        monkeypatch.setattr(
            wasapi_capture, "_win_api", lambda: SimpleNamespace(wait=lambda event, ms: result)
        )
        stream = make_real_stream(FakeCaptureClient([]))
        assert stream.wait(0.02) is ready
        assert (stream.error is not None) is error

    def test_close_is_idempotent_and_tolerates_a_dead_device(self) -> None:
        class DeadClient:
            stopped = 0

            def Stop(self) -> None:  # noqa: N802
                self.stopped += 1
                raise wasapi_capture.COMError(
                    -2004287484, "dispositivo invalidado", (None, None, None, 0, None)
                )

        stream = make_real_stream(FakeCaptureClient([]))
        client = DeadClient()
        stream._client, stream._event, stream._com_initialized = client, None, False
        stream.close()
        stream.close()
        assert client.stopped == 1
        assert stream._client is None
        assert stream._capture is None


class FakeAudioClient:
    """`IAudioClient` falso: rechaza los formatos con los canales indicados."""

    def __init__(self, reject_channels: Iterable[int] = ()) -> None:
        self.reject_channels = set(reject_channels)
        self.initialized: list[dict[str, int]] = []
        self.event: object = None
        self.started = False
        self.stopped = False
        self.capture = FakeCaptureClient([])

    def Initialize(
        self, mode: int, flags: int, duration: int, period: int, fmt: Any, session: object
    ) -> None:  # noqa: N802
        wave_format = fmt.contents
        self.initialized.append(
            {
                "mode": mode,
                "flags": flags,
                "duration": duration,
                "period": period,
                "tag": wave_format.wFormatTag,
                "channels": wave_format.nChannels,
                "rate": wave_format.nSamplesPerSec,
                "bits": wave_format.wBitsPerSample,
                "align": wave_format.nBlockAlign,
            }
        )
        if wave_format.nChannels in self.reject_channels:
            raise wasapi_capture.COMError(-2004287480, "formato no admitido", (None, None, None, 0, None))

    def SetEventHandle(self, handle: object) -> None:  # noqa: N802
        self.event = handle

    def GetService(self, iid_ref: object) -> Any:  # noqa: N802
        return SimpleNamespace(QueryInterface=lambda interface: self.capture)

    def Start(self) -> None:  # noqa: N802
        self.started = True

    def Stop(self) -> None:  # noqa: N802
        self.stopped = True


@windows_only
class TestRealStreamOpening:
    """`_ProcessLoopbackStream` se abre con el formato correcto y cae a estéreo si Windows rechaza el mono."""

    @pytest.fixture
    def clients(self, monkeypatch: pytest.MonkeyPatch) -> list[FakeAudioClient]:
        """Los clientes que `_activate_process_client` va entregando; cada test fija `clients.reject`."""
        made: list[FakeAudioClient] = []
        closed: list[object] = []

        class Clients(list):
            reject: tuple[int, ...] = ()

        clients = Clients()

        def fake_activate(pid: int, exclude: bool, timeout_s: float) -> FakeAudioClient:
            client = FakeAudioClient(clients.reject)
            made.append(client)
            clients.append(client)
            return client

        monkeypatch.setattr(wasapi_capture, "_activate_process_client", fake_activate)
        monkeypatch.setattr(
            wasapi_capture,
            "_win_api",
            lambda: SimpleNamespace(create_event=lambda *args: 4242, close_handle=closed.append),
        )
        return clients

    def test_it_asks_for_16_khz_mono_float_loopback_with_events(self, clients: Any) -> None:
        stream = wasapi_capture._ProcessLoopbackStream(4321, True, lambda: 0.0)
        try:
            (client,) = clients
            (request,) = client.initialized
            assert request["mode"] == 0  # AUDCLNT_SHAREMODE_SHARED
            assert request["flags"] == 0x00020000 | 0x00040000 | 0x80000000 | 0x08000000
            assert request["duration"] == 100 * 10_000  # 100 ms en unidades de 100 ns
            assert request["period"] == 0
            assert (request["tag"], request["channels"], request["rate"], request["bits"]) == (
                3,
                1,
                16000,
                32,
            )
            assert request["align"] == 4
            assert client.event == 4242
            assert client.started
            assert stream.error is None
        finally:
            stream.close()
        assert client.stopped

    def test_it_falls_back_to_stereo_when_windows_rejects_mono(self, clients: Any) -> None:
        clients.reject = (1,)
        stream = wasapi_capture._ProcessLoopbackStream(4321, True, lambda: 0.0)
        try:
            assert [c.initialized[0]["channels"] for c in clients] == [1, 2]  # un cliente nuevo por intento
            assert clients[1].started
            assert not clients[0].started
            assert stream._channels == 2
            assert clients[1].initialized[0]["align"] == 8
        finally:
            stream.close()

    def test_it_fails_with_a_clear_error_when_no_format_is_accepted(self, clients: Any) -> None:
        clients.reject = (1, 2)
        with pytest.raises(EngineError, match=r"1 canal\(es\).*2 canal\(es\)"):
            wasapi_capture._ProcessLoopbackStream(4321, True, lambda: 0.0)
        assert not any(c.started for c in clients)

    def test_close_stops_the_client_and_is_idempotent(self, clients: Any) -> None:
        stream = wasapi_capture._ProcessLoopbackStream(4321, False, lambda: 0.0)
        stream.close()
        stream.close()
        assert clients[0].stopped


def test_constructing_the_source_does_not_open_anything() -> None:
    source = ProcessLoopbackSource(ManualClock())  # factoría real, pero sin `start()`: ni COM ni dispositivo
    assert source.sample_rate == CAPTURE_RATE
    assert not source.exhausted
    assert source.read(0.0) is None
    source.stop()
