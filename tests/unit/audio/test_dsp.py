"""Tests de ``audio/dsp.py`` (T027, research R9): remuestreo y time-stretch TDHS en streaming.

Se comprueba lo que pide la tarea:

- La **duración** del audio de salida, dentro del 2 % de la esperada (en el remuestreo es exacta).
- Que la salida es **finita** (sin NaN ni infinitos) y no pasa de plena escala.
- La **continuidad entre trozos**: partir el audio en trozos de cualquier tamaño no cambia ni una muestra
  de la salida (el estado pasa de un trozo al siguiente) y una senoide no tiene saltos en las uniones.

Y lo que hace falta para usarlos en la sesión: ``flush()`` entrega la cola y deja el objeto listo para la
unidad siguiente, la velocidad se cambia entre unidades y los argumentos no válidos se rechazan.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

import numpy as np
import numpy.typing as npt
import pytest
import soundfile as sf
import soxr

from instanttraductor.audio.dsp import MAX_SPEED, MIN_SPEED, StreamResampler, StreamTimeStretch
from tests.contract.helpers import tone, voiced

Samples = npt.NDArray[np.float32]

SPEECH_FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "dialogo_en_2min.wav"
TTS_RATE = 24_000  # Hz: la frecuencia de salida de Qwen3-TTS
PLAYBACK_RATE = 48_000  # Hz: la del sink
#: Tamaños de trozo de Qwen3-TTS con ``chunk_size`` 1, 4 y 8 (83, 333 y 667 ms; research R8), más 20 ms.
CHUNK_MS = (20, 83, 333, 667)
SPEEDS = (1.0, 1.1, 1.25, 1.5)


class StreamProcessor(Protocol):
    def process(self, samples: Samples) -> Samples: ...

    def flush(self) -> Samples: ...


def run(processor: StreamProcessor, samples: Samples, chunk: int) -> Samples:
    """Una unidad completa: el audio en trozos de ``chunk`` muestras y, al final, ``flush()``."""
    parts = [processor.process(samples[start : start + chunk]) for start in range(0, len(samples), chunk)]
    parts.append(processor.flush())
    return np.concatenate(parts)


def chunk_size(rate: int, milliseconds: int) -> int:
    return max(1, round(rate * milliseconds / 1000))


def relative_error(measured: float, expected: float) -> float:
    return abs(measured - expected) / expected


def max_step(samples: Samples) -> float:
    """El mayor salto entre dos muestras consecutivas (un clic en una senoide lo dispara)."""
    return float(np.max(np.abs(np.diff(samples))))


@pytest.fixture(scope="module")
def speech() -> Samples:
    """5 s de habla real (LibriSpeech, ver ``tests/fixtures/ATTRIBUTION.md``) a 24 kHz, como la voz."""
    samples, rate = sf.read(SPEECH_FIXTURE, frames=5 * 16_000, dtype="float32")
    assert rate == 16_000
    return soxr.resample(samples, 16_000, TTS_RATE).astype(np.float32)


# --------------------------------------------------------------------------------------------------
# StreamResampler
# --------------------------------------------------------------------------------------------------
RATE_PAIRS = ((24_000, 48_000), (22_050, 48_000), (16_000, 48_000), (48_000, 24_000))


class TestStreamResampler:
    @pytest.mark.parametrize(("src", "dst"), RATE_PAIRS)
    @pytest.mark.parametrize("milliseconds", CHUNK_MS)
    def test_duration_is_within_2_percent(self, src: int, dst: int, milliseconds: int) -> None:
        samples = tone(3.0, 220.0, rate=src)

        out = run(StreamResampler(src, dst), samples, chunk_size(src, milliseconds))

        assert relative_error(len(out) / dst, len(samples) / src) < 0.02

    @pytest.mark.parametrize(("src", "dst"), RATE_PAIRS)
    def test_flush_completes_the_exact_number_of_samples(self, src: int, dst: int) -> None:
        samples = voiced(1.7, rate=src)

        out = run(StreamResampler(src, dst), samples, chunk_size(src, 83))

        assert abs(len(out) - round(len(samples) * dst / src)) <= 1

    def test_output_is_mono_float32(self) -> None:
        resampler = StreamResampler(TTS_RATE, PLAYBACK_RATE)

        out = resampler.process(voiced(0.3, rate=TTS_RATE))

        assert out.dtype == np.float32
        assert out.ndim == 1

    @pytest.mark.parametrize("milliseconds", [83, 333, 667])
    def test_the_filter_delay_is_below_35_ms(self, milliseconds: int) -> None:
        """El primer trozo sale algo más corto (el filtro guarda audio) y ``flush()`` lo completa."""
        resampler = StreamResampler(TTS_RATE, PLAYBACK_RATE)
        samples = voiced(1.0, rate=TTS_RATE)[: chunk_size(TTS_RATE, milliseconds)]

        first = resampler.process(samples)
        tail = resampler.flush()

        lag_ms = (len(samples) * 2 - len(first)) / PLAYBACK_RATE * 1000
        assert 0 <= lag_ms < 35
        assert len(first) + len(tail) == len(samples) * 2

    # -- continuidad entre trozos -------------------------------------------------------------------
    @pytest.mark.parametrize("chunk", [1, 7, 480, 1999, 24_000])
    def test_chunk_boundaries_do_not_change_a_single_sample(self, chunk: int) -> None:
        samples = voiced(1.0, rate=TTS_RATE)
        whole = run(StreamResampler(TTS_RATE, PLAYBACK_RATE), samples, len(samples))

        chunked = run(StreamResampler(TTS_RATE, PLAYBACK_RATE), samples, chunk)

        assert np.array_equal(chunked, whole)

    def test_the_result_is_the_one_shot_soxr_resampling(self) -> None:
        samples = voiced(1.0, rate=TTS_RATE)

        out = run(StreamResampler(TTS_RATE, PLAYBACK_RATE), samples, 1999)

        reference = soxr.resample(samples, TTS_RATE, PLAYBACK_RATE, quality="HQ")
        assert np.array_equal(out, reference)

    def test_a_sine_has_no_jumps_at_the_chunk_boundaries(self) -> None:
        amplitude, freq = 0.5, 440.0
        samples = tone(1.0, freq, rate=TTS_RATE, amplitude=amplitude)

        out = run(StreamResampler(TTS_RATE, PLAYBACK_RATE), samples, chunk_size(TTS_RATE, 20))

        # La pendiente máxima de la senoide, con holgura para el arranque del filtro. Remuestrear cada trozo
        # por separado dejaría saltos de varias veces esa pendiente en las uniones.
        steepest = amplitude * 2 * np.pi * freq / PLAYBACK_RATE
        assert max_step(out) <= 1.5 * steepest

    # -- varias unidades ----------------------------------------------------------------------------
    def test_flush_leaves_the_resampler_ready_for_the_next_unit(self) -> None:
        resampler = StreamResampler(TTS_RATE, PLAYBACK_RATE)
        samples = voiced(0.8, rate=TTS_RATE)

        first = run(resampler, samples, 1000)
        second = run(resampler, samples, 1000)

        assert np.array_equal(first, second)

    def test_flush_without_audio_is_empty(self) -> None:
        resampler = StreamResampler(TTS_RATE, PLAYBACK_RATE)

        assert resampler.flush().size == 0
        assert resampler.process(np.zeros(0, dtype=np.float32)).size == 0

    def test_reset_discards_the_state_of_a_unit_cut_in_half(self) -> None:
        samples = voiced(0.8, rate=TTS_RATE)
        resampler = StreamResampler(TTS_RATE, PLAYBACK_RATE)
        resampler.process(samples[:5000])

        resampler.reset()

        fresh = run(StreamResampler(TTS_RATE, PLAYBACK_RATE), samples, 999)
        assert np.array_equal(run(resampler, samples, 999), fresh)

    # -- misma frecuencia ---------------------------------------------------------------------------
    def test_equal_rates_pass_the_audio_through_without_delay(self) -> None:
        samples = voiced(0.3, rate=PLAYBACK_RATE)
        resampler = StreamResampler(PLAYBACK_RATE, PLAYBACK_RATE)

        out = resampler.process(samples)

        assert np.array_equal(out, samples)
        assert resampler.flush().size == 0

    def test_the_output_is_never_the_input_array(self) -> None:
        """Los arrays de audio no se mutan: lo que sale es una copia, aunque no haya nada que remuestrear."""
        samples = voiced(0.1, rate=PLAYBACK_RATE)
        out = StreamResampler(PLAYBACK_RATE, PLAYBACK_RATE).process(samples)

        out[:] = 0.0

        assert float(np.max(np.abs(samples))) > 0.0

    # -- robustez -----------------------------------------------------------------------------------
    def test_non_finite_input_never_reaches_the_output(self) -> None:
        samples = tone(0.5, rate=TTS_RATE)
        samples[100], samples[200], samples[300] = np.nan, np.inf, -np.inf

        out = run(StreamResampler(TTS_RATE, PLAYBACK_RATE), samples, 480)

        assert np.all(np.isfinite(out))

    def test_the_output_stays_within_full_scale(self) -> None:
        """Una onda cuadrada de plena escala hace que el filtro sobrepase 1,0: se recorta."""
        square = np.where((np.arange(TTS_RATE) // 24) % 2 == 0, 1.0, -1.0).astype(np.float32)

        out = run(StreamResampler(TTS_RATE, PLAYBACK_RATE), square, 480)

        assert float(np.max(np.abs(out))) <= 1.0

    def test_accepts_float64_and_non_contiguous_input(self) -> None:
        samples = voiced(0.3, rate=TTS_RATE)
        strided = np.repeat(samples, 2)[::2]  # una vista con paso: no contigua
        resampler = StreamResampler(TTS_RATE, PLAYBACK_RATE)

        out = np.concatenate([resampler.process(samples.astype(np.float64)), resampler.flush()])
        again = run(StreamResampler(TTS_RATE, PLAYBACK_RATE), strided, 777)

        assert out.dtype == np.float32
        assert np.array_equal(out, again)

    def test_a_two_dimensional_array_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="mono"):
            StreamResampler(TTS_RATE, PLAYBACK_RATE).process(np.zeros((2, 10), dtype=np.float32))

    @pytest.mark.parametrize(("src", "dst"), [(0, 48_000), (24_000, 0), (-1, 48_000), (24_000.5, 48_000)])
    def test_invalid_rates_are_rejected(self, src: float, dst: float) -> None:
        with pytest.raises(ValueError, match="frecuencia"):
            StreamResampler(src, dst)  # type: ignore[arg-type]

    def test_exposes_its_rates(self) -> None:
        resampler = StreamResampler(TTS_RATE, PLAYBACK_RATE)

        assert (resampler.src_rate, resampler.dst_rate) == (TTS_RATE, PLAYBACK_RATE)


# --------------------------------------------------------------------------------------------------
# StreamTimeStretch
# --------------------------------------------------------------------------------------------------
def stretcher(speed: float, rate: int = TTS_RATE) -> StreamTimeStretch:
    return StreamTimeStretch(speed, rate)


class TestStreamTimeStretch:
    @pytest.mark.parametrize("speed", SPEEDS)
    @pytest.mark.parametrize("milliseconds", CHUNK_MS)
    def test_speech_duration_follows_the_speed_within_2_percent(
        self, speech: Samples, speed: float, milliseconds: int
    ) -> None:
        out = run(stretcher(speed), speech, chunk_size(TTS_RATE, milliseconds))

        assert relative_error(len(out), len(speech) / speed) < 0.02

    @pytest.mark.parametrize("speed", SPEEDS)
    def test_voiced_signal_duration_follows_the_speed_within_2_percent(self, speed: float) -> None:
        samples = voiced(4.0, rate=TTS_RATE)

        out = run(stretcher(speed), samples, chunk_size(TTS_RATE, 333))

        assert relative_error(len(out), len(samples) / speed) < 0.02

    def test_the_default_sample_rate_is_the_one_of_the_tts(self) -> None:
        assert StreamTimeStretch(1.25).sample_rate == TTS_RATE

    def test_works_at_other_sample_rates(self, speech: Samples) -> None:
        samples = soxr.resample(speech, TTS_RATE, 16_000).astype(np.float32)

        out = run(StreamTimeStretch(1.25, 16_000), samples, 1600)

        assert relative_error(len(out), len(samples) / 1.25) < 0.02

    # -- finito y dentro de plena escala ------------------------------------------------------------
    @pytest.mark.parametrize("kind", ["silence", "noise", "full_scale_square", "speech"])
    def test_the_output_is_finite_and_within_full_scale(self, kind: str, speech: Samples) -> None:
        rng = np.random.default_rng(7)
        signals: dict[str, Callable[[], Samples]] = {
            "silence": lambda: np.zeros(TTS_RATE * 2, dtype=np.float32),
            "noise": lambda: rng.uniform(-1.0, 1.0, TTS_RATE * 2).astype(np.float32),
            "full_scale_square": lambda: np.where((np.arange(TTS_RATE * 2) // 60) % 2 == 0, 1.0, -1.0).astype(
                np.float32
            ),
            "speech": lambda: speech,
        }

        out = run(stretcher(1.25), signals[kind](), 1920)

        assert out.dtype == np.float32
        assert out.ndim == 1
        assert np.all(np.isfinite(out))
        assert float(np.max(np.abs(out))) <= 1.0

    def test_silence_stays_silence(self) -> None:
        out = run(stretcher(1.5), np.zeros(TTS_RATE * 2, dtype=np.float32), 1920)

        assert not np.any(out)
        assert relative_error(len(out), TTS_RATE * 2 / 1.5) < 0.02

    def test_non_finite_input_never_reaches_the_output(self) -> None:
        samples = tone(0.5, 180.0, rate=TTS_RATE)
        samples[100], samples[200], samples[300] = np.nan, np.inf, -np.inf

        out = run(stretcher(1.25), samples, 960)

        assert np.all(np.isfinite(out))

    # -- continuidad entre trozos -------------------------------------------------------------------
    @pytest.mark.parametrize("speed", [1.1, 1.25, 1.5])
    @pytest.mark.parametrize("milliseconds", [20, 83, 333, 667])
    def test_chunk_boundaries_do_not_change_a_single_sample(
        self, speech: Samples, speed: float, milliseconds: int
    ) -> None:
        whole = run(stretcher(speed), speech, len(speech))

        chunked = run(stretcher(speed), speech, chunk_size(TTS_RATE, milliseconds))

        assert np.array_equal(chunked, whole)

    @pytest.mark.parametrize("chunk", [1, 13, 997, 4001])
    def test_odd_sized_chunks_are_fine_too(self, speech: Samples, chunk: int) -> None:
        second = speech[:TTS_RATE]
        whole = run(stretcher(1.25), second, len(second))

        assert np.array_equal(run(stretcher(1.25), second, chunk), whole)

    def test_a_stretched_sine_has_no_jumps(self) -> None:
        amplitude, freq = 0.5, 180.0
        samples = tone(2.0, freq, rate=TTS_RATE, amplitude=amplitude)

        out = run(stretcher(1.25), samples, chunk_size(TTS_RATE, 83))

        steepest = amplitude * 2 * np.pi * freq / TTS_RATE  # la pendiente máxima de la senoide
        assert max_step(out) <= 1.5 * steepest

    # -- velocidad 1,0 ------------------------------------------------------------------------------
    def test_speed_one_is_a_bit_exact_passthrough_without_delay(self, speech: Samples) -> None:
        stretch = stretcher(1.0)

        first = stretch.process(speech[:8000])

        assert np.array_equal(first, speech[:8000])
        assert stretch.flush().size == 0

    def test_speed_one_never_returns_the_input_array(self) -> None:
        samples = voiced(0.1, rate=TTS_RATE)
        out = stretcher(1.0).process(samples)

        out[:] = 0.0

        assert float(np.max(np.abs(samples))) > 0.0

    # -- retraso algorítmico ------------------------------------------------------------------------
    def test_the_algorithmic_delay_is_below_60_ms(self, speech: Samples) -> None:
        """Research R9: el time-stretch retrasa 28-46 ms el audio (guarda un trozo de señal)."""
        stretch = stretcher(1.25)
        chunk = speech[: chunk_size(TTS_RATE, 333)]

        first = stretch.process(chunk)

        delay_ms = (len(chunk) / 1.25 - len(first)) / TTS_RATE * 1000
        assert delay_ms < 60

    # -- varias unidades y cambio de velocidad ------------------------------------------------------
    def test_the_speed_changes_between_units(self, speech: Samples) -> None:
        stretch = stretcher(1.0)

        for speed in (1.0, 1.5, 1.25, 1.0, 1.1, MAX_SPEED, MIN_SPEED, 1.2):
            stretch.speed = speed
            out = run(stretch, speech, 1920)
            assert stretch.speed == speed
            assert relative_error(len(out), len(speech) / speed) < 0.02, f"velocidad {speed}"

    def test_flush_leaves_the_stretcher_ready_for_the_next_unit(self, speech: Samples) -> None:
        """Tras ``flush()`` la biblioteca C se cuelga si sigue recibiendo audio sin reiniciarse."""
        stretch = stretcher(1.25)

        first = run(stretch, speech, 1920)
        second = run(stretch, speech, 1920)
        third = run(stretch, speech, 1920)

        assert np.array_equal(first, second)
        assert np.array_equal(second, third)

    def test_a_unit_after_a_fast_one_is_not_affected_by_it(self, speech: Samples) -> None:
        stretch = stretcher(1.5)
        run(stretch, speech, 1920)
        stretch.speed = 1.25

        reused = run(stretch, speech, 1920)

        assert np.array_equal(reused, run(stretcher(1.25), speech, 1920))

    def test_flush_without_audio_is_empty(self) -> None:
        stretch = stretcher(1.25)

        assert stretch.flush().size == 0
        assert stretch.process(np.zeros(0, dtype=np.float32)).size == 0
        assert stretch.flush().size == 0

    def test_reset_discards_the_state_of_a_unit_cut_in_half(self, speech: Samples) -> None:
        stretch = stretcher(1.25)
        stretch.process(speech[:20_000])

        stretch.reset()

        assert np.array_equal(run(stretch, speech, 1920), run(stretcher(1.25), speech, 1920))

    def test_a_signal_shorter_than_a_pitch_period_is_not_lost(self) -> None:
        samples = tone(0.004, 200.0, rate=TTS_RATE)  # 96 muestras

        out = run(stretcher(1.5), samples, 1000)

        assert len(samples) / 1.5 <= len(out) <= len(samples)
        assert float(np.max(np.abs(out))) > 0.0

    def test_changing_the_speed_in_the_middle_of_a_unit_keeps_the_audio_flowing(
        self, speech: Samples
    ) -> None:
        stretch = stretcher(1.0)
        half = len(speech) // 2

        parts = [stretch.process(speech[:half])]
        stretch.speed = 1.5
        parts.append(stretch.process(speech[half:]))
        parts.append(stretch.flush())
        out = np.concatenate(parts)

        expected = half + (len(speech) - half) / 1.5
        assert relative_error(len(out), expected) < 0.02

    # -- validación ---------------------------------------------------------------------------------
    @pytest.mark.parametrize("speed", [0.99, 0.5, 1.51, 2.0, float("nan"), float("inf"), -1.25])
    def test_a_speed_out_of_range_is_rejected(self, speed: float) -> None:
        with pytest.raises(ValueError, match="velocidad"):
            StreamTimeStretch(speed)

        stretch = stretcher(1.25)
        with pytest.raises(ValueError, match="velocidad"):
            stretch.speed = speed
        assert stretch.speed == 1.25

    @pytest.mark.parametrize("speed", [1.0, 1.25, 1.5, 1.0 - 1e-12, 1.5 + 1e-12])
    def test_the_limits_are_accepted_with_a_float_tolerance(self, speed: float) -> None:
        stretch = StreamTimeStretch(speed)

        assert MIN_SPEED <= stretch.speed <= MAX_SPEED

    def test_the_limits_are_those_of_the_contract(self) -> None:
        assert (MIN_SPEED, MAX_SPEED) == (1.0, 1.5)

    @pytest.mark.parametrize("rate", [0, -24_000, 24_000.5])
    def test_an_invalid_sample_rate_is_rejected(self, rate: float) -> None:
        with pytest.raises(ValueError, match="frecuencia"):
            StreamTimeStretch(1.25, rate)  # type: ignore[arg-type]

    def test_a_two_dimensional_array_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="mono"):
            stretcher(1.25).process(np.zeros((2, 10), dtype=np.float32))
