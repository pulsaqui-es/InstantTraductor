"""Tests de los fixtures de audio: el generador (sin red) y los WAV y TXT que se versionan."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from . import generate_fixtures as gen

FIXTURES_DIR = Path(__file__).resolve().parent
SAMPLE_RATE = 16_000
SYNTHETIC = {"tono_1k_1s.wav": 1.0, "silencio_3s.wav": 3.0, "ruido_rosa_5s.wav": 5.0}
DIALOGUE_WAV = "dialogo_en_2min.wav"
DIALOGUE_TXT = "dialogo_en_2min.txt"
PAUSE_SAMPLES = round(0.8 * SAMPLE_RATE)


def read_int16(name: str) -> np.ndarray:
    samples, rate = sf.read(FIXTURES_DIR / name, dtype="int16")
    assert rate == SAMPLE_RATE
    return samples


def dbfs(samples: np.ndarray) -> float:
    """Nivel RMS en dBFS de un array int16."""
    rms = float(np.sqrt(np.mean((samples.astype(np.float64) / 32768.0) ** 2)))
    return 20 * float(np.log10(rms))


def zero_runs(samples: np.ndarray, min_length: int) -> list[tuple[int, int]]:
    """Tramos [inicio, fin) de ceros exactos de al menos `min_length` muestras."""
    padded = np.concatenate(([0], (samples == 0).astype(np.int8), [0]))
    edges = np.flatnonzero(np.diff(padded))
    return [(int(a), int(b)) for a, b in zip(edges[::2], edges[1::2], strict=True) if b - a >= min_length]


def utterance(seconds: float, utterance_id: str = "u") -> gen.Utterance:
    return gen.Utterance(
        utterance_id, f"TEXTO {utterance_id}", np.ones(round(seconds * SAMPLE_RATE), dtype=np.int16)
    )


# --- Formato de los ficheros versionados ---


@pytest.mark.parametrize("name", [*SYNTHETIC, DIALOGUE_WAV])
def test_wav_is_pcm16_16khz_mono_and_under_5_mb(name: str) -> None:
    path = FIXTURES_DIR / name
    info = sf.info(path)

    assert (info.format, info.subtype, info.samplerate, info.channels) == ("WAV", "PCM_16", SAMPLE_RATE, 1)
    assert path.stat().st_size < 5_000_000


@pytest.mark.parametrize(("name", "seconds"), SYNTHETIC.items())
def test_synthetic_fixture_has_the_duration_in_its_name(name: str, seconds: float) -> None:
    assert sf.info(FIXTURES_DIR / name).frames == round(seconds * SAMPLE_RATE)


# --- Contenido de los sintéticos ---


def test_tone_is_a_1_khz_sine_at_minus_6_dbfs_peak() -> None:
    samples = read_int16("tono_1k_1s.wav")
    spectrum = np.abs(np.fft.rfft(samples.astype(np.float64)))
    frequencies = np.fft.rfftfreq(len(samples), d=1 / SAMPLE_RATE)

    assert frequencies[np.argmax(spectrum)] == 1000.0
    assert abs(int(samples.max()) - 16384) <= 1
    assert abs(dbfs(samples) - (-9.03)) < 0.05  # seno de amplitud 0,5: RMS = 0,5 / raíz de 2


def test_silence_is_digital_zeros() -> None:
    assert not read_int16("silencio_3s.wav").any()


def test_pink_noise_has_the_target_level_and_equal_energy_per_octave() -> None:
    samples = read_int16("ruido_rosa_5s.wav")
    assert abs(dbfs(samples) - (-20.0)) < 0.2
    assert np.abs(samples).max() < 0.99 * 32768  # sin recortes

    power = np.abs(np.fft.rfft(samples.astype(np.float64))) ** 2
    frequencies = np.fft.rfftfreq(len(samples), d=1 / SAMPLE_RATE)
    octaves = [(125, 250), (250, 500), (500, 1000), (1000, 2000), (2000, 4000)]
    levels = [
        10 * np.log10(power[(frequencies >= low) & (frequencies < high)].sum()) for low, high in octaves
    ]

    assert max(levels) - min(levels) < 1.0


# --- El diálogo y su transcripción ---


def test_dialogue_is_about_two_minutes_and_ends_with_a_pause() -> None:
    samples = read_int16(DIALOGUE_WAV)

    assert 110 <= len(samples) / SAMPLE_RATE <= 120
    assert not samples[-PAUSE_SAMPLES:].any()


def test_dialogue_has_one_0_8_s_pause_per_transcribed_utterance() -> None:
    samples = read_int16(DIALOGUE_WAV)
    lines = (FIXTURES_DIR / DIALOGUE_TXT).read_text(encoding="utf-8").splitlines()

    pauses = zero_runs(samples, min_length=PAUSE_SAMPLES)

    assert len(lines) >= 5
    assert len(pauses) == len(lines)
    assert all(end - start >= PAUSE_SAMPLES for start, end in pauses)
    assert pauses[-1][1] == len(samples)


def test_transcript_is_utf8_with_lf_and_one_non_empty_line_per_utterance() -> None:
    raw = (FIXTURES_DIR / DIALOGUE_TXT).read_bytes()
    lines = raw.decode("utf-8").split("\n")

    assert b"\r" not in raw
    assert lines[-1] == ""  # termina en salto de línea
    assert all(line and line == line.strip() for line in lines[:-1])


def test_attribution_credits_librispeech_under_cc_by_4() -> None:
    text = (FIXTURES_DIR / "ATTRIBUTION.md").read_text(encoding="utf-8")

    assert "LibriSpeech" in text
    assert "CC BY 4.0" in text
    assert "hf-internal-testing/librispeech_asr_dummy" in text


# --- El generador (sin red) ---


def test_to_pcm16_rounds_and_clips() -> None:
    result = gen.to_pcm16(np.array([0.0, 0.5, -0.5, 1.0, -1.0, 2.0, -2.0, 1 / 65536]))

    assert result.dtype == np.int16
    assert result.tolist() == [0, 16384, -16384, 32767, -32767, 32767, -32767, 0]


def test_synthetic_generators_are_deterministic() -> None:
    assert np.array_equal(gen.make_tone(), gen.make_tone())
    assert np.array_equal(gen.make_pink_noise(), gen.make_pink_noise())
    assert not np.array_equal(gen.make_pink_noise(seed=1), gen.make_pink_noise(seed=2))


def test_synthetic_generators_have_the_requested_length_and_dtype() -> None:
    for samples, seconds in (
        (gen.make_tone(duration_s=0.25), 0.25),
        (gen.make_silence(2.0), 2.0),
        (gen.make_pink_noise(duration_s=0.5), 0.5),
    ):
        assert samples.dtype == np.int16
        assert len(samples) == round(seconds * SAMPLE_RATE)


def test_write_synthetic_fixtures_reproduces_the_versioned_files(tmp_path: Path) -> None:
    gen.write_synthetic_fixtures(tmp_path)

    assert sorted(path.name for path in tmp_path.iterdir()) == sorted(SYNTHETIC)
    for name in ("tono_1k_1s.wav", "silencio_3s.wav"):
        assert (tmp_path / name).read_bytes() == (FIXTURES_DIR / name).read_bytes()
    regenerated, _ = sf.read(tmp_path / "ruido_rosa_5s.wav", dtype="int16")
    versioned = read_int16("ruido_rosa_5s.wav")
    assert np.abs(regenerated.astype(np.int32) - versioned.astype(np.int32)).max() <= 2


def test_select_utterances_takes_the_first_ones_that_fit_counting_the_pause() -> None:
    utterances = [utterance(50, "a"), utterance(40, "b"), utterance(20, "c"), utterance(5, "d")]

    # 50,8 + 40,8 + 20,8 + 5,8 = 117,4 s
    assert [u.utterance_id for u in gen.select_utterances(utterances, target_s=120.0, pause_s=0.8)] == list(
        "abcd"
    )
    # con 100 s caben a y b (91,6 s); c no (112,4 s)
    assert [u.utterance_id for u in gen.select_utterances(utterances, target_s=100.0, pause_s=0.8)] == [
        "a",
        "b",
    ]


def test_select_utterances_stops_at_the_first_one_that_does_not_fit() -> None:
    utterances = [utterance(60, "a"), utterance(60, "b"), utterance(1, "c")]

    assert [u.utterance_id for u in gen.select_utterances(utterances, target_s=120.0, pause_s=0.8)] == ["a"]


def test_select_utterances_fails_when_nothing_fits() -> None:
    with pytest.raises(ValueError, match="Ningún enunciado"):
        gen.select_utterances([utterance(130)], target_s=120.0, pause_s=0.8)


def test_assemble_dialogue_puts_a_silent_pause_after_each_utterance() -> None:
    first, second = utterance(0.1, "a"), utterance(0.2, "b")

    audio = gen.assemble_dialogue([first, second], pause_s=0.8)

    assert audio.dtype == np.int16
    assert len(audio) == round((0.1 + 0.8 + 0.2 + 0.8) * SAMPLE_RATE)
    first_end = len(first.samples)
    second_start = first_end + PAUSE_SAMPLES
    second_end = second_start + len(second.samples)
    assert audio[:first_end].all()
    assert not audio[first_end:second_start].any()
    assert audio[second_start:second_end].all()
    assert not audio[second_end:].any()
    assert len(audio) == second_end + PAUSE_SAMPLES
