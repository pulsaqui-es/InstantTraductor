"""Tests del AGC (T016): objetivo de -20 dBFS RMS, ataque de 50 ms, relajación de 1 s, máximo +30 dB.

Los niveles se miden con RMS en dBFS. Las señales son tonos (estacionarios: el nivel de salida es exacto) y
`voiced` (un tono modulado en amplitud que imita el habla).
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
import pytest

from instanttraductor.audio.agc import SOURCE_SILENCE_WARNING_S, AutoGain
from instanttraductor.contracts import CAPTURE_RATE, AudioChunk
from tests.contract.helpers import silence, to_chunks, tone, voiced

Samples = npt.NDArray[np.float32]


def rms_dbfs(x: Samples) -> float:
    rms = float(np.sqrt(np.mean(np.square(x, dtype=np.float64))))
    return 20.0 * np.log10(rms) if rms > 0 else float("-inf")


def at_rms(signal: Samples, dbfs: float) -> Samples:
    """Reescala `signal` para que su RMS sea `dbfs`."""
    return (
        signal * np.float32(10 ** (dbfs / 20) / np.sqrt(np.mean(np.square(signal, dtype=np.float64))))
    ).astype(np.float32)


def run(
    agc: AutoGain, signal: Samples, *, chunk_s: float = 0.02, t0: float = 0.0
) -> tuple[list[AudioChunk], Samples]:
    """Pasa `signal` por el AGC en chunks contiguos; devuelve los chunks de salida y su audio."""
    chunks = [agc.process(c) for c in to_chunks(signal, t0=t0, chunk_s=chunk_s)]
    return chunks, np.concatenate([c.samples for c in chunks])


def steady(seconds: float, dbfs: float) -> Samples:
    """Tono estacionario de 440 Hz con el RMS indicado."""
    return at_rms(tone(seconds), dbfs)


class TestLevel:
    def test_gain_starts_at_zero_db(self) -> None:
        agc = AutoGain()
        assert agc.gain_db == 0.0
        assert agc.source_silent_for_s == 0.0

    @pytest.mark.parametrize("input_dbfs", [-50.0, -40.0, -30.0, -26.0])
    def test_a_quiet_source_is_raised_to_the_target(self, input_dbfs: float) -> None:
        agc = AutoGain()
        _, out = run(agc, steady(6.0, input_dbfs))
        assert rms_dbfs(out[-CAPTURE_RATE:]) == pytest.approx(-20.0, abs=0.5)
        assert agc.gain_db == pytest.approx(-20.0 - input_dbfs, abs=0.5)

    @pytest.mark.parametrize("input_dbfs", [-15.0, -10.0, -6.0])
    def test_a_loud_source_is_attenuated_to_the_target(self, input_dbfs: float) -> None:
        agc = AutoGain()
        _, out = run(agc, steady(3.0, input_dbfs))
        assert rms_dbfs(out[-CAPTURE_RATE:]) == pytest.approx(-20.0, abs=0.5)

    def test_a_source_already_at_the_target_is_left_alone(self) -> None:
        agc = AutoGain()
        signal = steady(3.0, -20.0)
        _, out = run(agc, signal)
        assert agc.gain_db == pytest.approx(0.0, abs=0.1)
        assert np.allclose(out, signal, atol=0.01)

    def test_speech_like_audio_ends_up_near_the_target(self) -> None:
        agc = AutoGain()
        _, out = run(agc, at_rms(voiced(10.0), -42.0))
        # El ataque rápido y la relajación lenta siguen los picos de la voz: el RMS medio queda por debajo.
        assert -26.0 <= rms_dbfs(out[-3 * CAPTURE_RATE :]) <= -18.0

    def test_the_target_is_configurable(self) -> None:
        agc = AutoGain(target_dbfs=-30.0)
        _, out = run(agc, steady(6.0, -45.0))
        assert rms_dbfs(out[-CAPTURE_RATE:]) == pytest.approx(-30.0, abs=0.5)


class TestMaximumGain:
    def test_the_gain_never_exceeds_30_db(self) -> None:
        agc = AutoGain()
        _, out = run(agc, steady(15.0, -55.0))  # haría falta +35 dB
        assert 29.0 < agc.gain_db <= 30.0
        assert rms_dbfs(out[-CAPTURE_RATE:]) == pytest.approx(-25.0, abs=1.0)

    def test_the_maximum_is_configurable(self) -> None:
        agc = AutoGain(max_gain_db=10.0)
        run(agc, steady(10.0, -50.0))
        assert 9.0 < agc.gain_db <= 10.0

    def test_attenuation_is_limited_too(self) -> None:
        agc = AutoGain(min_gain_db=-6.0)
        run(agc, steady(3.0, -5.0))  # haría falta -15 dB
        assert -6.0 <= agc.gain_db < -5.9


class TestDigitalSilence:
    def test_digital_silence_comes_out_as_silence_and_the_gain_does_not_move(self) -> None:
        agc = AutoGain()
        _, out = run(agc, silence(20.0))
        assert not out.any()
        assert agc.gain_db == 0.0

    def test_silence_does_not_raise_the_gain_so_speech_after_it_is_not_blasted(self) -> None:
        agc = AutoGain()
        run(agc, silence(30.0))
        chunks, _ = run(agc, steady(0.5, -20.0), t0=30.0)
        assert rms_dbfs(chunks[0].samples) == pytest.approx(-20.0, abs=1.0)  # no +30 dB de golpe

    def test_the_gain_is_held_through_silence(self) -> None:
        agc = AutoGain()
        run(agc, steady(6.0, -45.0))
        before = agc.gain_db
        run(agc, silence(30.0), t0=6.0)
        assert agc.gain_db == before
        chunks, _ = run(agc, steady(0.2, -45.0), t0=36.0)
        assert rms_dbfs(chunks[0].samples) == pytest.approx(-45.0 + before, abs=0.5)  # sigue con su ganancia

    def test_noise_below_the_gate_is_not_chased_either(self) -> None:
        agc = AutoGain()
        run(agc, steady(6.0, -40.0))
        before = agc.gain_db
        run(
            agc, at_rms(np.random.default_rng(0).standard_normal(10 * CAPTURE_RATE).astype(np.float32), -75.0)
        )
        assert agc.gain_db == before

    def test_the_gate_is_configurable(self) -> None:
        agc = AutoGain(gate_dbfs=-80.0)
        run(agc, steady(10.0, -70.0))
        assert agc.gain_db > 20.0  # con el umbral más bajo sí persigue ese nivel


class TestAttackAndRelease:
    def test_the_attack_is_fast(self) -> None:
        agc = AutoGain()
        run(agc, steady(8.0, -45.0))
        assert agc.gain_db > 24.0
        run(agc, steady(0.25, -10.0), t0=8.0)  # una fuente mucho más fuerte: 5 constantes de 50 ms
        assert agc.gain_db == pytest.approx(-10.0, abs=1.0)

    def test_the_release_is_slow(self) -> None:
        agc = AutoGain()
        run(agc, steady(3.0, -10.0))
        assert agc.gain_db == pytest.approx(-10.0, abs=0.5)
        run(agc, steady(0.25, -45.0), t0=3.0)  # la fuente baja de golpe: solo un cuarto de constante de 1 s
        assert -10.0 < agc.gain_db < 0.0  # ha subido algo, pero está lejos de los +25 dB

    def test_one_second_of_release_covers_about_two_thirds_of_the_way(self) -> None:
        agc = AutoGain()
        run(agc, steady(1.0, -45.0))  # de 0 dB hacia +25 dB
        assert agc.gain_db == pytest.approx(25.0 * (1 - np.exp(-1.0)), abs=1.0)

    def test_the_times_are_configurable(self) -> None:
        slow, fast = AutoGain(release_s=4.0), AutoGain(release_s=0.25)
        run(slow, steady(1.0, -45.0))
        run(fast, steady(1.0, -45.0))
        assert fast.gain_db > slow.gain_db + 10.0

    def test_the_result_does_not_depend_on_the_chunk_size(self) -> None:
        gains = []
        for chunk_s in (0.01, 0.02, 0.04, 0.08):
            agc = AutoGain()
            run(agc, steady(2.0, -45.0), chunk_s=chunk_s)
            gains.append(agc.gain_db)
        assert max(gains) - min(gains) < 0.5


class TestNoClipping:
    def test_a_loud_transient_after_a_quiet_passage_never_exceeds_full_scale(self) -> None:
        agc = AutoGain()
        run(agc, steady(8.0, -50.0))  # +30 dB de ganancia
        burst = at_rms(tone(0.5, 300.0), -8.0)  # 50 dB por encima de lo que venía
        _, out = run(agc, burst, t0=8.0)
        assert float(np.max(np.abs(out))) <= 1.0

    def test_full_scale_noise_stays_in_range(self) -> None:
        agc = AutoGain()
        loud = np.clip(np.random.default_rng(1).standard_normal(3 * CAPTURE_RATE) * 0.9, -1.0, 1.0)
        _, out = run(agc, loud.astype(np.float32))
        assert float(np.max(np.abs(out))) <= 1.0
        assert np.all(np.isfinite(out))

    def test_the_gain_changes_smoothly_inside_a_chunk(self) -> None:
        agc = AutoGain()
        dc = np.full(CAPTURE_RATE, 0.5, dtype=np.float32)  # -6 dBFS: la ganancia tiene que bajar 14 dB
        out = np.concatenate([agc.process(c).samples for c in to_chunks(dc)])
        assert out[0] == pytest.approx(0.5, abs=0.01)  # arranca donde estaba (0 dB)
        assert float(np.max(np.abs(np.diff(out)))) < 0.002  # sin saltos entre muestras ni entre chunks


class TestSourceSilence:
    def test_counts_continuous_digital_silence_in_seconds(self) -> None:
        agc = AutoGain()
        run(agc, silence(12.0))
        assert agc.source_silent_for_s == pytest.approx(12.0, abs=0.02)
        assert agc.source_silent_for_s > SOURCE_SILENCE_WARNING_S

    def test_the_warning_threshold_is_ten_seconds(self) -> None:
        assert SOURCE_SILENCE_WARNING_S == 10.0

    def test_grows_chunk_by_chunk(self) -> None:
        agc = AutoGain()
        seen = [agc.source_silent_for_s]
        for chunk in to_chunks(silence(1.0)):
            agc.process(chunk)
            seen.append(agc.source_silent_for_s)
        assert seen == sorted(seen)
        assert seen[-1] == pytest.approx(1.0, abs=0.001)

    def test_resets_as_soon_as_there_is_signal(self) -> None:
        agc = AutoGain()
        run(agc, silence(12.0))
        run(agc, steady(0.02, -40.0), t0=12.0)  # un solo chunk con señal
        assert agc.source_silent_for_s == 0.0
        run(agc, silence(3.0), t0=12.02)
        assert agc.source_silent_for_s == pytest.approx(3.0, abs=0.02)

    def test_numerical_noise_of_a_muted_source_still_counts_as_silence(self) -> None:
        agc = AutoGain()
        noise = (1e-7 * np.random.default_rng(2).standard_normal(5 * CAPTURE_RATE)).astype(
            np.float32
        )  # -140 dBFS
        run(agc, noise)
        assert agc.source_silent_for_s == pytest.approx(5.0, abs=0.02)

    def test_a_very_quiet_but_real_signal_is_not_silence(self) -> None:
        agc = AutoGain()
        run(agc, steady(2.0, -85.0))
        assert agc.source_silent_for_s == 0.0

    def test_it_is_measured_on_the_input_not_on_the_output(self) -> None:
        agc = AutoGain()
        run(agc, steady(6.0, -45.0))  # ganancia alta: la salida de un tono bajo sigue sin ser silencio
        run(agc, silence(1.0), t0=6.0)
        assert agc.source_silent_for_s == pytest.approx(1.0, abs=0.02)


class TestChunks:
    def test_time_and_rate_are_preserved(self) -> None:
        agc = AutoGain()
        chunk = AudioChunk(samples=steady(0.02, -30.0), sample_rate=CAPTURE_RATE, t_start=12.34)
        out = agc.process(chunk)
        assert out.t_start == 12.34
        assert out.sample_rate == CAPTURE_RATE
        assert out.t_end == pytest.approx(chunk.t_end)

    def test_returns_a_new_float32_chunk_without_touching_the_input(self) -> None:
        agc = AutoGain()
        data = steady(0.02, -40.0)
        original = data.copy()
        chunk = AudioChunk(samples=data, sample_rate=CAPTURE_RATE, t_start=0.0)
        out = agc.process(chunk)
        assert out is not chunk
        assert out.samples.dtype == np.float32
        assert out.samples.shape == data.shape
        assert not np.shares_memory(out.samples, data)
        assert np.array_equal(data, original)

    def test_an_empty_chunk_comes_back_as_it_is(self) -> None:
        agc = AutoGain()
        chunk = AudioChunk(samples=np.zeros(0, dtype=np.float32), sample_rate=CAPTURE_RATE, t_start=1.0)
        out = agc.process(chunk)
        assert len(out.samples) == 0
        assert agc.gain_db == 0.0
        assert agc.source_silent_for_s == 0.0

    def test_the_output_is_always_finite(self) -> None:
        agc = AutoGain()
        for level in (-120.0, -80.0, -50.0, -20.0, -6.0):
            _, out = run(agc, steady(0.5, level))
            assert np.all(np.isfinite(out))
