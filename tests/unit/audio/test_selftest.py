"""Tests del autotest de la exclusión (T024) con fuentes y sink falsos: ni dispositivos ni esperas.

Cada captura falsa es un array de 16 kHz que el autotest va leyendo: la INCLUDE lleva el tono propio (o no),
la EXCLUDE lleva otro audio (o, si falla la exclusión, también el tono). Los tests con el dispositivo real
están en `tests/integration/test_selftest_device.py` (marcador `device`).
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import numpy.typing as npt
import pytest

from instanttraductor.audio.echo_monitor import DEFAULT_THRESHOLD, MAX_THRESHOLD, MIN_THRESHOLD
from instanttraductor.audio.selftest import (
    PRESENT_DB,
    SELFTEST_UNIT_ID,
    TONE_DBFS,
    TONE_HZ,
    TONE_S,
    SelftestResult,
    make_tone,
    pulse_correlation,
    run_echo_selftest,
    tone_ratio_db,
)
from instanttraductor.contracts import (
    CAPTURE_RATE,
    PLAYBACK_RATE,
    AudioChunk,
    AudioSource,
    EngineError,
    SpeechPiece,
)
from instanttraductor.pipeline.clock import ManualClock
from tests.fakes.fake_audio import FakeAudioSink, FakeAudioSource

Samples = npt.NDArray[np.float32]

TONE_AMPLITUDE = 10 ** (TONE_DBFS / 20)
CAPTURE_S = 5.0  # audio de sobra en cada captura falsa (el autotest lee unos 1,5 s)


def noise(seconds: float, rms: float = 0.05, seed: int = 0) -> Samples:
    rng = np.random.default_rng(seed)
    return (rms * rng.standard_normal(round(seconds * CAPTURE_RATE))).astype(np.float32)


def silence(seconds: float = CAPTURE_S) -> Samples:
    return np.zeros(round(seconds * CAPTURE_RATE), dtype=np.float32)


def with_tone(base: Samples, at_s: float = 0.6, amplitude_gain: float = 1.0) -> Samples:
    """`base` con el tono propio sumado en el instante `at_s` (como llegaría a la captura)."""
    out = base.copy()
    tone = make_tone(rate=CAPTURE_RATE) * np.float32(amplitude_gain)
    start = round(at_s * CAPTURE_RATE)
    out[start : start + len(tone)] += tone
    return out


class RecordingSource(FakeAudioSource):
    """Fuente falsa que anota en un registro común cuándo arranca y para, y cuánto audio le leyeron."""

    def __init__(self, audio: Samples, label: str, log: list[str]) -> None:
        super().__init__(audio)
        self.label = label
        self.log = log
        self.read_s = 0.0

    def start(self) -> None:
        super().start()
        self.log.append(f"start {self.label}")

    def read(self, timeout: float = 0.0) -> AudioChunk | None:
        chunk = super().read(timeout)
        if chunk is not None:
            self.read_s += chunk.duration
        return chunk

    def stop(self) -> None:
        super().stop()
        self.log.append(f"stop {self.label}")


class RecordingSink(FakeAudioSink):
    """`FakeAudioSink` que anota cuándo llega el tono y puede decir que tiene voz por delante (`pending`)."""

    def __init__(self, log: list[str], pending: float | None = None) -> None:
        super().__init__(ManualClock())
        self.log = log
        self.pending = pending

    def enqueue(self, piece: SpeechPiece) -> None:
        self.log.append("tone")
        super().enqueue(piece)

    def pending_seconds(self) -> float:
        return super().pending_seconds() if self.pending is None else self.pending


class Setup:
    """Un sink y dos capturas falsas, con el registro de lo que hizo el autotest."""

    def __init__(self, exclude: Samples, include: Samples, *, pending: float | None = None) -> None:
        self.log: list[str] = []
        self.modes: list[bool] = []
        self.sink = RecordingSink(self.log, pending)
        self.sources: dict[bool, RecordingSource] = {}
        self._audio = {False: exclude, True: include}

    def make_source(self, include: bool) -> AudioSource:
        self.modes.append(include)
        source = RecordingSource(self._audio[include], "INCLUDE" if include else "EXCLUDE", self.log)
        self.sources[include] = source
        return source

    def run(self) -> SelftestResult:
        return run_echo_selftest(self.sink, self.make_source)


def healthy() -> Setup:
    """La exclusión funciona: el tono solo llega a la INCLUDE; en la EXCLUDE solo suena otro audio."""
    return Setup(exclude=noise(CAPTURE_S, 0.05, seed=1), include=with_tone(silence()))


# --------------------------------------------------------------------------------------------------
# Un equipo sano
# --------------------------------------------------------------------------------------------------


class TestHealthy:
    def test_it_passes_with_a_reason_that_is_empty_and_a_calibrated_threshold(self) -> None:
        result = healthy().run()
        assert result.ok
        assert result.reason == ""
        assert MIN_THRESHOLD <= result.correlation_threshold <= MAX_THRESHOLD

    def test_the_tone_stands_out_in_include_and_not_in_exclude(self) -> None:
        result = healthy().run()
        assert result.include_ratio_db is not None and result.exclude_ratio_db is not None
        assert result.include_ratio_db >= PRESENT_DB + 30  # sin otro audio, el tono destaca decenas de dB
        assert result.exclude_ratio_db < PRESENT_DB

    def test_the_tone_goes_through_the_sink_as_the_reserved_unit(self) -> None:
        setup = healthy()
        setup.run()
        (piece,) = setup.sink.pieces
        assert piece.unit_id == SELFTEST_UNIT_ID == -1
        assert piece.is_last
        assert piece.samples.dtype == np.float32 and piece.samples.ndim == 1
        assert len(piece.samples) == round(TONE_S * PLAYBACK_RATE)  # 0,3 s a la frecuencia del sink
        assert float(np.max(np.abs(piece.samples))) == pytest.approx(TONE_AMPLITUDE, rel=1e-3)  # -30 dBFS

    def test_both_captures_run_before_the_tone_and_are_stopped_after(self) -> None:
        setup = healthy()
        setup.run()
        assert setup.modes == [False, True]  # primero la EXCLUDE de la app y luego la INCLUDE de control
        assert setup.log == ["start EXCLUDE", "start INCLUDE", "tone", "stop EXCLUDE", "stop INCLUDE"]

    def test_it_reads_about_a_second_and_a_half_of_audio(self) -> None:
        setup = healthy()
        setup.run()
        for source in setup.sources.values():
            assert 1.4 <= source.read_s <= 1.7  # 0,4 antes del tono + 0,3 del tono + 0,8 de cola

    def test_other_loud_audio_in_the_pc_does_not_fail_it(self) -> None:
        """La detección compara con el fondo: música alta y otro tono en la EXCLUDE no se confunden."""
        t = np.arange(round(CAPTURE_S * CAPTURE_RATE)) / CAPTURE_RATE
        loud = noise(CAPTURE_S, 0.3, seed=2) + (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
        result = Setup(exclude=loud.astype(np.float32), include=with_tone(silence())).run()
        assert result.ok, result.reason

    def test_the_threshold_depends_on_the_measures_within_the_bounds(self) -> None:
        result = healthy().run()
        # eco limpio (INCLUDE sin otro audio): el 80 % de ~1 es ~0,8; nunca fuera de los límites
        assert 0.75 <= result.correlation_threshold <= MAX_THRESHOLD


# --------------------------------------------------------------------------------------------------
# Fallos
# --------------------------------------------------------------------------------------------------


class TestFeedback:
    def test_the_tone_in_the_exclude_capture_is_a_failure(self) -> None:
        setup = Setup(exclude=with_tone(noise(CAPTURE_S, 0.05, seed=3)), include=with_tone(silence()))
        result = setup.run()
        assert not result.ok
        assert "reaparece" in result.reason
        assert "realimentación" in result.reason
        assert result.correlation_threshold == DEFAULT_THRESHOLD
        assert result.exclude_ratio_db is not None and result.exclude_ratio_db >= PRESENT_DB
        assert setup.log[-2:] == ["stop EXCLUDE", "stop INCLUDE"]  # y se paran las dos capturas

    def test_a_quiet_leak_under_loud_audio_is_still_found(self) -> None:
        loud_with_leak = with_tone(noise(CAPTURE_S, 0.05, seed=4))
        result = Setup(exclude=loud_with_leak, include=with_tone(silence())).run()
        assert not result.ok and "reaparece" in result.reason

    def test_a_leak_is_reported_even_if_the_positive_control_also_failed(self) -> None:
        result = Setup(exclude=with_tone(silence()), include=silence()).run()
        assert not result.ok
        assert "reaparece" in result.reason  # lo grave primero


class TestPositiveControl:
    def test_if_the_include_capture_does_not_hear_the_tone_nothing_can_be_claimed(self) -> None:
        result = Setup(exclude=noise(CAPTURE_S, seed=5), include=silence()).run()
        assert not result.ok
        assert "control positivo" in result.reason
        assert "volumen" in result.reason  # la pista más probable
        assert result.correlation_threshold == DEFAULT_THRESHOLD
        assert result.include_ratio_db == 0.0

    def test_a_tone_too_weak_to_stand_out_does_not_count(self) -> None:
        weak = noise(CAPTURE_S, 0.05, seed=6) + 0.0  # solo ruido: ni rastro del tono
        result = Setup(exclude=noise(CAPTURE_S, seed=7), include=weak).run()
        assert not result.ok and "control positivo" in result.reason


class TestCaptureProblems:
    def test_if_the_include_capture_cannot_be_opened_the_exclude_one_is_still_stopped(self) -> None:
        log: list[str] = []
        sink = RecordingSink(log)

        def make_source(include: bool) -> AudioSource:
            if include:
                raise EngineError("el dispositivo no está disponible", engine="capture")
            return RecordingSource(noise(CAPTURE_S), "EXCLUDE", log)

        result = run_echo_selftest(sink, make_source)
        assert not result.ok
        assert "No se pudo abrir la captura" in result.reason
        assert "no está disponible" in result.reason
        assert log == ["start EXCLUDE", "stop EXCLUDE"]
        assert sink.pieces == []  # y no llegó a sonar nada

    def test_if_a_capture_fails_to_start_the_other_one_is_stopped(self) -> None:
        log: list[str] = []

        class Broken(RecordingSource):
            def start(self) -> None:
                raise EngineError("no arranca", engine="capture")

        def make_source(include: bool) -> AudioSource:
            if include:
                return Broken(silence(), "INCLUDE", log)
            return RecordingSource(noise(CAPTURE_S), "EXCLUDE", log)

        result = run_echo_selftest(RecordingSink(log), make_source)
        assert not result.ok and "No se pudo abrir la captura" in result.reason
        assert "stop EXCLUDE" in log and "stop INCLUDE" in log

    def test_a_source_that_ends_without_audio_is_a_failure(self) -> None:
        result = Setup(exclude=noise(CAPTURE_S), include=silence(0.0)).run()
        assert not result.ok
        assert "INCLUDE" in result.reason and "no entregó audio" in result.reason

    def test_a_live_capture_that_never_delivers_is_a_failure_and_does_not_hang(self) -> None:
        log: list[str] = []

        class Stalled(RecordingSource):
            def read(self, timeout: float = 0.0) -> AudioChunk | None:
                return None

            @property
            def exhausted(self) -> bool:
                return False

        def make_source(include: bool) -> AudioSource:
            if include:
                return RecordingSource(with_tone(silence()), "INCLUDE", log)
            return Stalled(noise(CAPTURE_S), "EXCLUDE", log)

        result = run_echo_selftest(RecordingSink(log), make_source)
        assert not result.ok
        assert "EXCLUDE" in result.reason and "no entregó audio" in result.reason
        assert log[-2:] == ["stop EXCLUDE", "stop INCLUDE"]

    def test_a_failing_stop_does_not_hide_the_result(self) -> None:
        class BadStop(RecordingSource):
            def stop(self) -> None:
                raise RuntimeError("no se puede parar")

        def make_source(include: bool) -> AudioSource:
            audio = with_tone(silence()) if include else noise(CAPTURE_S, seed=8)
            return BadStop(audio, "INCLUDE" if include else "EXCLUDE", [])

        assert run_echo_selftest(RecordingSink([]), make_source).ok


class TestBusySink:
    def test_it_waits_for_the_voice_ahead_of_the_tone(self) -> None:
        """Mitad de sesión: con 2 s de voz por delante, el tono suena 2 s más tarde y se sigue escuchando."""
        include = with_tone(
            silence(), at_s=2.3 + 0.15
        )  # suena tras 2 s de voz (más el retardo de la captura)
        setup = Setup(exclude=noise(8.0, 0.05, seed=9), include=include.copy(), pending=2.3)
        setup._audio[True] = np.concatenate([include, silence(3.0)])
        result = setup.run()
        assert result.ok, result.reason
        assert all(source.read_s >= 0.4 + 2.3 + 0.8 - 0.05 for source in setup.sources.values())

    def test_the_wait_is_capped(self) -> None:
        setup = Setup(exclude=noise(20.0, seed=10), include=silence(20.0), pending=100.0)
        result = setup.run()
        assert not result.ok and "control positivo" in result.reason  # el tono no llegó a sonar a tiempo
        for source in setup.sources.values():
            assert source.read_s <= 0.4 + 6.0 + 0.8 + 0.05

    def test_at_least_the_duration_of_the_tone_is_awaited_if_the_sink_reports_nothing(self) -> None:
        setup = Setup(exclude=noise(CAPTURE_S, seed=11), include=with_tone(silence()), pending=0.0)
        assert setup.run().ok
        assert all(source.read_s >= 0.4 + TONE_S + 0.8 - 0.05 for source in setup.sources.values())


# --------------------------------------------------------------------------------------------------
# Piezas puras
# --------------------------------------------------------------------------------------------------


class TestMakeTone:
    def test_it_is_a_30_ms_free_mono_float32_sine_at_the_selftest_frequency_and_level(self) -> None:
        tone = make_tone()
        assert tone.dtype == np.float32 and tone.ndim == 1
        assert len(tone) == round(0.3 * PLAYBACK_RATE)
        assert float(np.max(np.abs(tone))) == pytest.approx(TONE_AMPLITUDE, rel=1e-3)
        spectrum = np.abs(np.fft.rfft(tone))
        assert np.fft.rfftfreq(len(tone), 1 / PLAYBACK_RATE)[int(np.argmax(spectrum))] == pytest.approx(
            TONE_HZ, abs=5
        )

    def test_it_fades_in_and_out_without_clicks(self) -> None:
        tone = make_tone()
        assert tone[0] == 0.0 and abs(float(tone[-1])) < 1e-3
        assert float(np.max(np.abs(tone[:48]))) < TONE_AMPLITUDE * 0.6  # 1 ms: aún subiendo

    def test_the_parameters_can_be_changed(self) -> None:
        tone = make_tone(500.0, 0.1, -20.0, rate=16_000)
        assert len(tone) == 1600
        assert float(np.max(np.abs(tone))) == pytest.approx(0.1, rel=1e-3)


class TestToneRatio:
    def test_a_pure_tone_stands_out_by_tens_of_db(self) -> None:
        x = np.concatenate([silence(0.5), make_tone(rate=CAPTURE_RATE), silence(0.5)])
        assert tone_ratio_db(x, CAPTURE_RATE) > 60

    @pytest.mark.parametrize("seed", range(5))
    def test_noise_does_not_look_like_the_tone(self, seed: int) -> None:
        assert tone_ratio_db(noise(2.0, 0.1, seed), CAPTURE_RATE) < PRESENT_DB

    def test_the_tone_under_noise_louder_than_it_is_still_found(self) -> None:
        x = noise(1.5, 0.05, seed=3) + np.pad(make_tone(rate=CAPTURE_RATE), (4000, 24000 - 4000 - 4800))
        assert tone_ratio_db(x.astype(np.float32), CAPTURE_RATE) >= PRESENT_DB

    def test_another_frequency_is_not_the_tone(self) -> None:
        x = np.pad(make_tone(1700.0, 0.3, -10.0, CAPTURE_RATE), (2000, 2000))
        assert tone_ratio_db(x, CAPTURE_RATE) < PRESENT_DB

    def test_silence_and_too_short_audio_give_zero(self) -> None:
        assert tone_ratio_db(silence(1.0), CAPTURE_RATE) == pytest.approx(0.0, abs=1e-6)
        assert tone_ratio_db(np.zeros(0, dtype=np.float32), CAPTURE_RATE) == 0.0
        assert tone_ratio_db(make_tone(rate=CAPTURE_RATE)[:4000], CAPTURE_RATE) == 0.0  # menos de una ventana


class TestPulseCorrelation:
    def test_an_isolated_pulse_of_the_tone_matches_the_template(self) -> None:
        x = np.concatenate([silence(0.5), make_tone(rate=CAPTURE_RATE), silence(0.5)])
        assert pulse_correlation(x, CAPTURE_RATE) > 0.9

    def test_the_pulse_is_found_wherever_it_is(self) -> None:
        for at_s in (0.3, 0.9, 1.4):
            x = with_tone(silence(2.0), at_s)
            assert pulse_correlation(x, CAPTURE_RATE) > 0.9

    def test_digital_silence_and_too_little_audio_give_zero(self) -> None:
        assert pulse_correlation(silence(1.5), CAPTURE_RATE) == 0.0
        assert pulse_correlation(make_tone(rate=CAPTURE_RATE)[:3000], CAPTURE_RATE) == 0.0

    @pytest.mark.parametrize("seed", range(5))
    def test_stationary_noise_does_not_look_like_a_pulse(self, seed: int) -> None:
        assert pulse_correlation(noise(1.5, 0.05, seed), CAPTURE_RATE) < 0.8


class TestResult:
    def test_it_compares_only_ok_reason_and_threshold(self) -> None:
        a = SelftestResult(True, "", 0.8, include_ratio_db=120.0, exclude_ratio_db=3.0)
        b = SelftestResult(True, "", 0.8)
        assert a == b
        assert SelftestResult(False, "x", 0.8) != b

    def test_it_is_frozen(self) -> None:
        with pytest.raises(AttributeError):
            SelftestResult(True, "", 0.8).ok = False  # type: ignore[misc]


def test_make_source_can_be_any_callable() -> None:
    """La firma es `make_source(include: bool) -> AudioSource`, sin más requisitos."""
    factory: Callable[[bool], AudioSource] = lambda include: FakeAudioSource(  # noqa: E731
        with_tone(silence()) if include else noise(CAPTURE_S, seed=12)
    )
    assert run_echo_selftest(FakeAudioSink(ManualClock()), factory).ok
