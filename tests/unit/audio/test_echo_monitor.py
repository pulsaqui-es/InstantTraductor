"""Tests del monitor de eco (T024) con señales sintéticas: habla artificial con y sin eco (50 a 300 ms).

El «habla» es ruido modulado por una envolvente de sílabas de 80-200 ms con pausas de frase, como en el
experimento que fijó el umbral (ver el docstring de `echo_monitor`). Lo reproducido sale a 48 kHz y lo
captado a 16 kHz, como en la aplicación; el eco es la voz reproducida, diezmada a 16 kHz y retrasada, más (o
no) otro audio independiente que hace de programa original.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable

import numpy as np
import numpy.typing as npt
import pytest

from instanttraductor.audio.echo_monitor import (
    BINS_PER_S,
    DEFAULT_THRESHOLD,
    MAX_THRESHOLD,
    MIN_THRESHOLD,
    EchoMonitor,
    best_correlation,
    calibrate_threshold,
    detrend,
    envelope_bins,
)
from instanttraductor.contracts import CAPTURE_RATE, PLAYBACK_RATE, AudioChunk

Samples = npt.NDArray[np.float32]

BLOCK_S = 0.02
PLAYED_BLOCK = round(BLOCK_S * PLAYBACK_RATE)  # 960 muestras
CAPTURED_BLOCK = round(BLOCK_S * CAPTURE_RATE)  # 320 muestras
DECIMATION = PLAYBACK_RATE // CAPTURE_RATE


# --------------------------------------------------------------------------------------------------
# Señales sintéticas
# --------------------------------------------------------------------------------------------------


def syllable_envelope(
    duration_s: float, rng: np.random.Generator, rate: int = 1000
) -> npt.NDArray[np.float64]:
    """Envolvente de habla: sílabas de 80-200 ms, a unas 4-5 por segundo, en frases de 1,5-4 s con pausas."""
    env = np.zeros(int(duration_s * rate))
    t = 0.0
    while t < duration_s:
        end = t + rng.uniform(1.5, 4.0)
        while t < end and t < duration_s:
            width = rng.uniform(0.08, 0.20)
            amplitude = rng.lognormal(0.0, 0.45)
            i0, i1 = int(t * rate), min(len(env), int((t + width) * rate))
            if i1 - i0 > 1:
                env[i0:i1] = np.maximum(env[i0:i1], amplitude * np.hanning(i1 - i0))
            t += width * rng.uniform(0.9, 1.7)
        t = end + rng.uniform(0.3, 1.5)
    return env


def speech_like(duration_s: float, rate: int, seed: int, rms: float = 0.1) -> Samples:
    rng = np.random.default_rng(seed)
    env = syllable_envelope(duration_s + 0.1, rng)
    count = round(duration_s * rate)
    envelope = np.interp(np.arange(count) / rate, np.arange(len(env)) / 1000, env)
    x = envelope * rng.standard_normal(count)
    return (x * (rms / (np.sqrt(np.mean(x * x)) + 1e-12))).astype(np.float32)


def decimate(x: Samples) -> Samples:
    """48 kHz -> 16 kHz por promedio de 3 muestras, con el mismo RMS que la entrada.

    Promediar ruido blanco le quita 4,8 dB; sin compensarlo, una «ganancia 1,0» del eco no sería de verdad 0
    dB respecto a un audio original generado directamente a 16 kHz con el mismo RMS.
    """
    usable = len(x) // DECIMATION * DECIMATION
    y = x[:usable].reshape(-1, DECIMATION).mean(axis=1)
    return (y * (np.sqrt(np.mean(x[:usable] ** 2)) / (np.sqrt(np.mean(y**2)) + 1e-12))).astype(np.float32)


def echo_of(played48: Samples, delay_s: float | Callable[[float], float], gain: float = 1.0) -> Samples:
    """La voz reproducida tal como volvería a la captura: a 16 kHz y retrasada (el retardo puede variar)."""
    played16 = decimate(played48)
    out = np.zeros_like(played16)
    if callable(delay_s):
        blocks = -(-len(out) // CAPTURED_BLOCK)
        # un retardo por bloque de 20 ms, función del tiempo
        shifts = np.array([round(delay_s(b * BLOCK_S) * CAPTURE_RATE) for b in range(blocks)])
        source = np.arange(len(out)) - np.repeat(shifts, CAPTURED_BLOCK)[: len(out)]
        valid = source >= 0
        out[valid] = played16[source[valid]] * gain
        return out
    shift = round(delay_s * CAPTURE_RATE)
    out[shift:] = played16[: len(out) - shift] * gain
    return out


def drive(
    monitor: EchoMonitor,
    played48: Samples,
    captured16: Samples,
    *,
    jitter_s: float = 0.0,
    seed: int = 0,
    start_block: int = 0,
) -> None:
    """Entrega lo reproducido y lo captado en bloques de 20 ms, como harían el sink y la captura.

    El sink da la hora de cada bloque (su principio) y la captura, la de llegada de cada chunk (su final).
    """
    rng = np.random.default_rng(seed)
    blocks = min(len(played48) // PLAYED_BLOCK, len(captured16) // CAPTURED_BLOCK)
    for k in range(start_block, blocks):
        t = k * BLOCK_S
        monitor.feed_played(
            played48[k * PLAYED_BLOCK : (k + 1) * PLAYED_BLOCK], t + float(rng.uniform(-jitter_s, jitter_s))
        )
        chunk = AudioChunk(
            samples=captured16[k * CAPTURED_BLOCK : (k + 1) * CAPTURED_BLOCK],
            sample_rate=CAPTURE_RATE,
            t_start=t,
        )
        monitor.feed_captured(chunk, t + BLOCK_S + float(rng.uniform(-jitter_s, jitter_s)))


class Warnings:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def __call__(self, message: str) -> None:
        self.messages.append(message)


# --------------------------------------------------------------------------------------------------
# Piezas puras
# --------------------------------------------------------------------------------------------------


class TestEnvelope:
    def test_it_is_the_rms_of_each_20_ms_bin(self) -> None:
        x = np.concatenate([np.full(320, 0.5), np.zeros(320), np.full(320, -0.25)]).astype(np.float32)
        assert envelope_bins(x, CAPTURE_RATE) == pytest.approx([0.5, 0.0, 0.25])

    def test_a_sine_has_the_rms_of_its_amplitude(self) -> None:
        t = np.arange(PLAYBACK_RATE) / PLAYBACK_RATE
        x = (0.3 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
        env = envelope_bins(x, PLAYBACK_RATE)
        assert len(env) == BINS_PER_S
        assert env == pytest.approx(0.3 / np.sqrt(2), rel=1e-3)

    def test_the_remainder_that_does_not_fill_a_bin_is_dropped(self) -> None:
        assert len(envelope_bins(np.ones(700, dtype=np.float32), CAPTURE_RATE)) == 2
        assert len(envelope_bins(np.ones(10, dtype=np.float32), CAPTURE_RATE)) == 0

    def test_detrend_removes_a_constant_and_a_slow_ramp_but_keeps_the_fast_modulation(self) -> None:
        n = np.arange(200)
        ramp = 0.01 * n
        fast = np.where(n % 4 < 2, 0.5, -0.5)
        assert np.abs(detrend(np.full(100, 0.7))).max() == pytest.approx(0.0, abs=1e-12)
        assert np.abs(detrend(ramp)[10:-10]).max() < 1e-9
        kept = detrend(fast + ramp)[10:-10]
        assert np.corrcoef(kept, fast[10:-10])[0, 1] > 0.99

    def test_detrend_of_an_empty_envelope(self) -> None:
        assert len(detrend(np.zeros(0))) == 0


class TestBestCorrelation:
    @staticmethod
    def envelopes(seed: int = 0, window: int = 100, max_lag: int = 30) -> npt.NDArray[np.float64]:
        rng = np.random.default_rng(seed)
        return np.abs(np.convolve(rng.standard_normal(window + max_lag + 40), np.ones(3) / 3, mode="same"))

    @pytest.mark.parametrize("lag", [0, 3, 10, 17, 30])
    def test_a_delayed_copy_is_found_at_its_lag(self, lag: int) -> None:
        played = self.envelopes()[:130]
        captured = np.zeros(100)
        captured[:] = (
            played[30 - lag : 130 - lag] * 0.4 + 0.1
        )  # la captura repite lo reproducido `lag` bins antes
        result = best_correlation(captured, played, 30)
        assert result is not None
        r, found = result
        assert found == lag
        assert r == pytest.approx(1.0, abs=0.03)  # no es exacta: la tendencia de los bordes usa otro relleno

    def test_an_independent_envelope_does_not_correlate_strongly(self) -> None:
        result = best_correlation(self.envelopes(1)[:100], self.envelopes(2)[:130], 30)
        assert result is not None
        assert result[0] < 0.5

    def test_a_flat_capture_has_nothing_in_common(self) -> None:
        assert best_correlation(np.full(100, 0.02), self.envelopes()[:130], 30) == (0.0, 0)

    def test_a_flat_played_envelope_gives_no_information(self) -> None:
        assert best_correlation(self.envelopes()[:100], np.zeros(130), 30) is None

    def test_the_played_envelope_must_have_the_window_plus_the_lags(self) -> None:
        with pytest.raises(ValueError, match="130"):
            best_correlation(np.zeros(100), np.zeros(100), 30)


class TestCalibrateThreshold:
    @pytest.mark.parametrize(
        ("echo", "clean", "expected"),
        [
            (0.99, 0.2, 0.792),  # lo normal: el 80 % de un eco limpio
            (1.0, 0.0, 0.8),
            (0.99, 0.55, 0.85),  # un equipo con mucho azar: el azar más 0,3
            (0.99, 0.9, MAX_THRESHOLD),  # y nunca más de 0,9
            (0.6, 0.1, MIN_THRESHOLD),  # un eco flojo no baja del mínimo
            (-0.3, -0.5, MIN_THRESHOLD),
            (5.0, 5.0, MAX_THRESHOLD),  # valores fuera de rango se acotan
        ],
    )
    def test_the_threshold_follows_the_two_measures_within_the_bounds(
        self, echo: float, clean: float, expected: float
    ) -> None:
        assert calibrate_threshold(echo, clean) == pytest.approx(expected)

    def test_the_default_threshold_is_inside_the_bounds(self) -> None:
        assert MIN_THRESHOLD <= DEFAULT_THRESHOLD <= MAX_THRESHOLD


# --------------------------------------------------------------------------------------------------
# EchoMonitor
# --------------------------------------------------------------------------------------------------


@pytest.fixture
def warnings() -> Warnings:
    return Warnings()


@pytest.fixture
def monitor(warnings: Warnings) -> EchoMonitor:
    return EchoMonitor(on_echo=warnings)


class TestNoEcho:
    @pytest.mark.parametrize("seed", [1, 2, 3, 4])
    def test_independent_speech_is_never_mistaken_for_an_echo(self, seed: int, warnings: Warnings) -> None:
        """El peor caso: el audio original también es habla, con el mismo ritmo silábico."""
        monitor = EchoMonitor(on_echo=warnings)
        played = speech_like(60, PLAYBACK_RATE, seed=100 + seed)
        program = speech_like(60, CAPTURE_RATE, seed=200 + seed)
        drive(monitor, played, program)
        assert monitor.evaluations > 80  # de verdad se compararon
        assert monitor.echo_events == 0
        assert warnings.messages == []
        assert not monitor.in_echo
        assert monitor.last_correlation is not None
        assert monitor.last_correlation < DEFAULT_THRESHOLD

    def test_steady_noise_as_the_original_audio_is_not_an_echo(self, monitor: EchoMonitor) -> None:
        rng = np.random.default_rng(7)
        drive(
            monitor,
            speech_like(40, PLAYBACK_RATE, seed=1),
            (0.1 * rng.standard_normal(40 * CAPTURE_RATE)).astype(np.float32),
        )
        assert monitor.evaluations > 50
        assert monitor.echo_events == 0

    def test_a_silent_capture_is_not_an_echo(self, monitor: EchoMonitor) -> None:
        drive(monitor, speech_like(20, PLAYBACK_RATE, seed=1), np.zeros(20 * CAPTURE_RATE, dtype=np.float32))
        assert monitor.evaluations > 10
        assert monitor.last_correlation == 0.0
        assert monitor.echo_events == 0

    def test_nothing_is_compared_while_the_voice_is_silent(self, monitor: EchoMonitor) -> None:
        drive(monitor, np.zeros(20 * PLAYBACK_RATE, dtype=np.float32), speech_like(20, CAPTURE_RATE, seed=1))
        assert monitor.evaluations == 0
        assert monitor.last_correlation is None
        assert monitor.last_delay_s is None
        assert monitor.echo_events == 0

    def test_a_voice_that_barely_sounds_in_the_window_is_not_compared(self, monitor: EchoMonitor) -> None:
        played = np.zeros(20 * PLAYBACK_RATE, dtype=np.float32)
        played[: PLAYBACK_RATE // 4] = speech_like(0.25, PLAYBACK_RATE, seed=1)  # 0,25 s de 20
        program = speech_like(20, CAPTURE_RATE, seed=2)
        drive(monitor, played, program)
        assert monitor.evaluations == 0
        assert monitor.echo_events == 0


class TestEcho:
    @pytest.mark.parametrize("delay_s", [0.05, 0.1, 0.2, 0.3])
    def test_an_echo_is_detected_with_any_delay_between_50_and_300_ms(
        self, delay_s: float, warnings: Warnings
    ) -> None:
        monitor = EchoMonitor(on_echo=warnings)
        played = speech_like(25, PLAYBACK_RATE, seed=10)
        program = 0.25 * speech_like(25, CAPTURE_RATE, seed=11)  # el original, 12 dB por debajo de la voz
        drive(monitor, played, program + echo_of(played, delay_s))
        assert monitor.echo_events == 1
        assert monitor.in_echo
        assert monitor.last_delay_s == pytest.approx(delay_s, abs=0.04)
        assert monitor.last_correlation is not None and monitor.last_correlation > 0.7
        assert len(warnings.messages) == 1
        assert "Eco" in warnings.messages[0]
        assert "voz en español" in warnings.messages[0]

    def test_a_pure_echo_with_no_other_audio_is_detected(self, monitor: EchoMonitor) -> None:
        played = speech_like(15, PLAYBACK_RATE, seed=12)
        drive(monitor, played, echo_of(played, 0.12, gain=0.3))  # la escala no importa
        assert monitor.echo_events == 1

    @pytest.mark.parametrize(("program_gain", "seed"), [(1.0, 14), (0.5, 15), (0.5, 16)])
    def test_an_echo_as_loud_as_the_original_audio_is_still_detected(
        self, monitor: EchoMonitor, program_gain: float, seed: int
    ) -> None:
        """Con el eco tan alto como el original (o 6 dB por encima) la correlación de cada ventana oscila
        entre 0,5 y 0,95: aquí solo se exige que se detecte, aunque tarde o dé más de un episodio."""
        played = speech_like(45, PLAYBACK_RATE, seed=13)
        program = program_gain * speech_like(45, CAPTURE_RATE, seed=seed)
        drive(monitor, played, program + echo_of(played, 0.15))
        assert 1 <= monitor.echo_events <= 4

    def test_the_echo_is_counted_once_while_it_lasts(self, monitor: EchoMonitor, warnings: Warnings) -> None:
        played = speech_like(60, PLAYBACK_RATE, seed=15)
        drive(monitor, played, echo_of(played, 0.1))
        assert monitor.echo_events == 1
        assert len(warnings.messages) == 1

    def test_a_delay_that_drifts_inside_the_range_is_followed(self, monitor: EchoMonitor) -> None:
        played = speech_like(40, PLAYBACK_RATE, seed=16)
        program = 0.25 * speech_like(40, CAPTURE_RATE, seed=17)
        drive(monitor, played, program + echo_of(played, lambda t: 0.08 + 0.17 * t / 40))  # de 80 a 250 ms
        assert monitor.echo_events == 1
        assert monitor.in_echo
        assert monitor.last_delay_s == pytest.approx(0.08 + 0.17, abs=0.05)

    def test_a_delay_that_jumps_is_still_an_echo(self, monitor: EchoMonitor) -> None:
        played = speech_like(40, PLAYBACK_RATE, seed=18)
        program = 0.25 * speech_like(40, CAPTURE_RATE, seed=19)

        def delay(t: float) -> float:
            return 0.06 if t < 14 else 0.28 if t < 28 else 0.15

        drive(monitor, played, program + echo_of(played, delay))
        assert 1 <= monitor.echo_events <= 2  # el salto puede partir el episodio, pero no pasa desapercibido
        assert monitor.in_echo
        assert monitor.last_delay_s == pytest.approx(0.15, abs=0.04)

    def test_timestamp_jitter_does_not_hide_the_echo_nor_invent_one(self) -> None:
        played = speech_like(40, PLAYBACK_RATE, seed=20)
        program = 0.25 * speech_like(40, CAPTURE_RATE, seed=21)
        with_echo, without = EchoMonitor(), EchoMonitor()
        drive(with_echo, played, program + echo_of(played, 0.15), jitter_s=0.012, seed=1)
        drive(without, played, program, jitter_s=0.012, seed=2)
        assert with_echo.echo_events == 1
        assert without.echo_events == 0

    def test_a_constant_offset_between_the_two_clocks_is_absorbed_by_the_delay(
        self, monitor: EchoMonitor
    ) -> None:
        played = speech_like(25, PLAYBACK_RATE, seed=22)
        captured = echo_of(played, 0.1)
        blocks = min(len(played) // PLAYED_BLOCK, len(captured) // CAPTURED_BLOCK)
        for k in range(blocks):  # la hora de llegada va 150 ms más tarde que la del audio
            t = k * BLOCK_S
            monitor.feed_played(played[k * PLAYED_BLOCK : (k + 1) * PLAYED_BLOCK], t)
            chunk = AudioChunk(captured[k * CAPTURED_BLOCK : (k + 1) * CAPTURED_BLOCK], CAPTURE_RATE, t)
            monitor.feed_captured(chunk, t + BLOCK_S + 0.15)
        assert monitor.echo_events == 1
        assert monitor.last_delay_s == pytest.approx(0.25, abs=0.04)

    def test_an_echo_that_stops_ends_the_episode_and_a_new_one_counts_again(self, warnings: Warnings) -> None:
        monitor = EchoMonitor(on_echo=warnings)
        played = speech_like(54, PLAYBACK_RATE, seed=23)
        echo = echo_of(played, 0.1)
        program = 0.25 * speech_like(54, CAPTURE_RATE, seed=24)
        mask = np.zeros(len(echo), dtype=np.float32)
        mask[: 14 * CAPTURE_RATE] = 1  # eco de 0 a 14 s, limpio de 14 a 36 s y otra vez de 36 s en adelante
        mask[36 * CAPTURE_RATE :] = 1
        drive(monitor, played, program + echo * mask)
        assert monitor.echo_events == 2
        assert len(warnings.messages) == 2

    def test_in_echo_clears_after_clean_windows(self, monitor: EchoMonitor) -> None:
        played = speech_like(30, PLAYBACK_RATE, seed=25)
        echo = echo_of(played, 0.1)
        echo[12 * CAPTURE_RATE :] = 0
        drive(monitor, played, 0.25 * speech_like(30, CAPTURE_RATE, seed=26) + echo)
        assert monitor.echo_events == 1
        assert not monitor.in_echo

    def test_a_long_silence_of_the_voice_closes_the_episode(self, warnings: Warnings) -> None:
        monitor = EchoMonitor(on_echo=warnings)
        voice = speech_like(14, PLAYBACK_RATE, seed=27)
        played = np.concatenate([voice, np.zeros(8 * PLAYBACK_RATE, dtype=np.float32), voice])
        captured = echo_of(played, 0.1)
        drive(monitor, played, captured)
        assert monitor.echo_events == 2  # 8 s sin voz: el segundo eco es otro episodio

    def test_a_short_silence_of_the_voice_does_not(self, warnings: Warnings) -> None:
        monitor = EchoMonitor(on_echo=warnings)
        voice = speech_like(14, PLAYBACK_RATE, seed=28)
        played = np.concatenate([voice, np.zeros(2 * PLAYBACK_RATE, dtype=np.float32), voice])
        drive(monitor, played, echo_of(played, 0.1))
        assert monitor.echo_events == 1

    def test_the_voice_can_be_fed_at_another_sample_rate(self, monitor: EchoMonitor) -> None:
        played16 = speech_like(20, CAPTURE_RATE, seed=29)
        captured = np.zeros_like(played16)
        captured[1600:] = played16[:-1600]  # 100 ms
        for k in range(len(played16) // CAPTURED_BLOCK):
            t = k * BLOCK_S
            monitor.feed_played(played16[k * CAPTURED_BLOCK : (k + 1) * CAPTURED_BLOCK], t, CAPTURE_RATE)
            chunk = AudioChunk(captured[k * CAPTURED_BLOCK : (k + 1) * CAPTURED_BLOCK], CAPTURE_RATE, t)
            monitor.feed_captured(chunk, t + BLOCK_S)
        assert monitor.echo_events == 1


class TestWindowing:
    def test_nothing_is_evaluated_until_a_full_window_of_capture_has_arrived(
        self, monitor: EchoMonitor
    ) -> None:
        played = speech_like(10, PLAYBACK_RATE, seed=30)
        captured = echo_of(played, 0.1)
        drive(monitor, played[: round(1.9 * PLAYBACK_RATE)], captured[: round(1.9 * CAPTURE_RATE)])
        assert monitor.evaluations == 0
        drive(monitor, played[: 3 * PLAYBACK_RATE], captured[: 3 * CAPTURE_RATE], start_block=95)
        assert monitor.evaluations >= 1

    def test_it_evaluates_every_half_second_of_capture(self, monitor: EchoMonitor) -> None:
        played = speech_like(20, PLAYBACK_RATE, seed=31)
        drive(monitor, played, echo_of(played, 0.1))
        # de 2 s a 20 s, una ventana cada 0,5 s: unas 36
        assert 34 <= monitor.evaluations <= 38

    def test_the_history_stays_bounded(self, monitor: EchoMonitor) -> None:
        played = speech_like(100, PLAYBACK_RATE, seed=32)
        size = len(monitor._played._tag)
        drive(monitor, played, echo_of(played, 0.1))
        assert len(monitor._played._tag) == size == len(monitor._captured._tag) == 1500
        assert monitor.echo_events == 1


class TestRobustness:
    def test_empty_blocks_and_non_finite_samples_are_harmless(self, monitor: EchoMonitor) -> None:
        monitor.feed_played(np.zeros(0, dtype=np.float32), 0.0)
        monitor.feed_captured(AudioChunk(np.zeros(0, dtype=np.float32), CAPTURE_RATE, 0.0), 0.0)
        played = speech_like(10, PLAYBACK_RATE, seed=33)
        captured = echo_of(played, 0.1)
        played[1000:1500] = np.nan
        captured[3000:3100] = np.inf
        drive(monitor, played, captured)
        assert monitor.last_correlation is not None and np.isfinite(monitor.last_correlation)

    def test_a_failing_callback_does_not_break_the_monitor(self, caplog: pytest.LogCaptureFixture) -> None:
        def broken(message: str) -> None:
            raise RuntimeError("fallo del suscriptor")

        monitor = EchoMonitor(on_echo=broken)
        played = speech_like(15, PLAYBACK_RATE, seed=34)
        drive(monitor, played, echo_of(played, 0.1))
        assert monitor.echo_events == 1

    def test_a_monitor_without_callback_still_counts(self) -> None:
        monitor = EchoMonitor()
        played = speech_like(15, PLAYBACK_RATE, seed=35)
        drive(monitor, played, echo_of(played, 0.1))
        assert monitor.echo_events == 1

    def test_the_two_feeds_can_come_from_two_threads(self, warnings: Warnings) -> None:
        """El hilo de audio y el de la captura alimentan a la vez; la captura nunca va por delante."""
        monitor = EchoMonitor(on_echo=warnings)
        played = speech_like(25, PLAYBACK_RATE, seed=36)
        captured = echo_of(played, 0.1)
        blocks = min(len(played) // PLAYED_BLOCK, len(captured) // CAPTURED_BLOCK)
        fed = queue.Queue[int]()
        errors: list[BaseException] = []

        def feed_played() -> None:
            try:
                for k in range(blocks):
                    monitor.feed_played(played[k * PLAYED_BLOCK : (k + 1) * PLAYED_BLOCK], k * BLOCK_S)
                    fed.put(k)
            except BaseException as exc:
                errors.append(exc)

        def feed_captured() -> None:
            try:
                for k in range(blocks):
                    fed.get(timeout=10.0)  # el bloque k de lo reproducido ya está dentro
                    chunk = AudioChunk(
                        captured[k * CAPTURED_BLOCK : (k + 1) * CAPTURED_BLOCK], CAPTURE_RATE, 0.0
                    )
                    monitor.feed_captured(chunk, (k + 1) * BLOCK_S)
            except BaseException as exc:
                errors.append(exc)

        threads = [threading.Thread(target=feed_played), threading.Thread(target=feed_captured)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30.0)
        assert errors == []
        assert monitor.echo_events == 1
        assert len(warnings.messages) == 1

    def test_reset_forgets_the_history_but_keeps_the_count(self, monitor: EchoMonitor) -> None:
        played = speech_like(15, PLAYBACK_RATE, seed=37)
        drive(monitor, played, echo_of(played, 0.1))
        assert monitor.echo_events == 1
        monitor.reset()
        assert not monitor.in_echo
        assert monitor.echo_events == 1
        assert monitor.evaluations > 0
        drive(monitor, played, echo_of(played, 0.1))  # el eco de siempre vuelve a empezar tras el reset
        assert monitor.echo_events == 2

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"threshold": 0.0},
            {"threshold": 1.5},
            {"confirm_windows": 0},
            {"clear_windows": 0},
            {"window_s": 0.2},
            {"history_s": 2.0},
        ],
    )
    def test_invalid_parameters_are_rejected(self, kwargs: dict[str, float]) -> None:
        with pytest.raises(ValueError):
            EchoMonitor(**kwargs)  # type: ignore[arg-type]

    def test_the_threshold_is_the_one_given(self) -> None:
        assert EchoMonitor().threshold == DEFAULT_THRESHOLD
        assert EchoMonitor(threshold=0.72).threshold == 0.72

    def test_a_lower_threshold_catches_a_weaker_match(self) -> None:
        played = speech_like(30, PLAYBACK_RATE, seed=38)
        program = 2.0 * speech_like(30, CAPTURE_RATE, seed=39)  # el eco, 6 dB por debajo del original
        captured = program + echo_of(played, 0.1)
        strict, loose = EchoMonitor(threshold=0.99), EchoMonitor(threshold=0.4)
        drive(strict, played, captured)
        drive(loose, played, captured)
        assert strict.echo_events == 0
        assert loose.echo_events >= 1
