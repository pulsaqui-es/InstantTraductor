"""Tests de las salidas del modo archivo (T036): WAV, SRT/JSON, mezclas con ffmpeg y escritura atómica.

Los ficheros de entrada se generan con ffmpeg real en `tmp_path`; no hay dispositivos, GPU ni modelos.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from instanttraductor.audio import file_outputs
from instanttraductor.audio.file_outputs import (
    OUTPUT_NAMES,
    build_srt,
    format_srt_time,
    transcription_entries,
    translation_entries,
    write_float_wav,
    write_outputs,
)
from instanttraductor.audio.file_source import InputFileError
from instanttraductor.config import ffmpeg_path
from instanttraductor.contracts import (
    PLAYBACK_RATE,
    EngineError,
    Outcome,
    StageTimings,
    TranslationMode,
    UtteranceRecord,
)

pytestmark = pytest.mark.skipif(ffmpeg_path() is None, reason="ffmpeg no está disponible")

REPORT_JSON = '{"schema_version": 1}\n'
REPORT_MD = "# Informe\n"


def run_ffmpeg(*args: str) -> None:
    ffmpeg = ffmpeg_path()
    assert ffmpeg is not None
    subprocess.run(
        [str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error", *args], check=True, capture_output=True
    )


def ffprobe_streams(path: Path) -> list[dict]:
    ffmpeg = ffmpeg_path()
    assert ffmpeg is not None
    ffprobe = ffmpeg.with_name("ffprobe.exe" if ffmpeg.suffix == ".exe" else "ffprobe")
    if not ffprobe.exists():
        ffprobe = Path("ffprobe")
    out = subprocess.run(
        [str(ffprobe), "-v", "error", "-show_streams", "-of", "json", str(path)],
        check=True,
        capture_output=True,
    ).stdout
    return json.loads(out)["streams"]


def make_tone_wav(path: Path, seconds: float = 1.0, *, channels: int = 2) -> Path:
    run_ffmpeg(
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}:sample_rate=44100",
        "-ac", str(channels), str(path),
    )  # fmt: skip
    return path


def make_silent_wav(path: Path, seconds: float = 1.0, *, channels: int = 1) -> Path:
    layout = "mono" if channels == 1 else "stereo"
    run_ffmpeg("-f", "lavfi", "-i", f"anullsrc=r=48000:cl={layout}", "-t", str(seconds), str(path))
    return path


def make_mkv(path: Path, seconds: float = 1.0) -> Path:
    run_ffmpeg(
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
        "-f", "lavfi", "-i", f"color=c=blue:s=64x64:r=10:d={seconds}",
        "-c:a", "aac", "-c:v", "mpeg4", "-shortest", str(path),
    )  # fmt: skip
    return path


def voice_track(
    seconds: float, *, burst: tuple[float, float] = (0.2, 0.4), value: float = 0.25
) -> np.ndarray:
    track = np.zeros(round(seconds * PLAYBACK_RATE), dtype=np.float32)
    track[round(burst[0] * PLAYBACK_RATE) : round(burst[1] * PLAYBACK_RATE)] = value
    return track


def record(
    unit_id: int,
    *,
    source: str = "Hello there.",
    translated: str | None = "Hola.",
    outcome: Outcome = Outcome.SPOKEN,
    mode: TranslationMode = TranslationMode.NORMAL,
    t_audio: tuple[float, float] = (1.0, 2.0),
    play: tuple[float | None, float | None] = (3.0, 4.0),
) -> UtteranceRecord:
    return UtteranceRecord(
        unit_id=unit_id,
        source_text=source,
        translated_text=translated,
        mode=mode,
        speed=1.0,
        outcome=outcome,
        reason=None if outcome is Outcome.SPOKEN else "motivo",
        timings=StageTimings(
            t_start_audio=t_audio[0],
            t_end_audio=t_audio[1],
            unit_ready_at=t_audio[1] + 0.5,
            play_started_at=play[0],
            play_finished_at=play[1],
        ),
    )


def write(out_dir: Path, input_path: Path, **overrides) -> list[Path]:
    arguments = {
        "input_path": input_path,
        "track_48k": voice_track(1.0),
        "records": [record(1)],
        "report_json": REPORT_JSON,
        "report_md": REPORT_MD,
    }
    arguments.update(overrides)
    return write_outputs(out_dir, **arguments)


def leftovers(parent: Path) -> list[str]:
    return sorted(p.name for p in parent.iterdir())


# --------------------------------------------------------------------------------------------------
# WAV float32
# --------------------------------------------------------------------------------------------------


class TestFloatWav:
    def test_is_a_valid_48k_mono_float32_wav(self, tmp_path: Path) -> None:
        samples = np.linspace(-1.5, 1.5, 1000, dtype=np.float32)  # ni se acota
        path = tmp_path / "voz.wav"
        write_float_wav(path, samples)
        info = sf.info(path)
        assert (info.samplerate, info.channels, info.subtype) == (48_000, 1, "FLOAT")
        assert info.frames == 1000
        data, _ = sf.read(path, dtype="float32")
        assert np.array_equal(data, samples)

    def test_ffmpeg_reads_it_too(self, tmp_path: Path) -> None:
        path = tmp_path / "voz.wav"
        write_float_wav(path, np.zeros(4800, dtype=np.float32))
        (stream,) = ffprobe_streams(path)
        assert stream["codec_name"] == "pcm_f32le"
        assert stream["sample_rate"] == "48000" and stream["channels"] == 1

    def test_an_empty_track_is_still_a_valid_wav(self, tmp_path: Path) -> None:
        path = tmp_path / "vacio.wav"
        write_float_wav(path, np.zeros(0, dtype=np.float32))
        assert sf.info(path).frames == 0

    def test_rejects_a_non_mono_array(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="mono"):
            write_float_wav(tmp_path / "x.wav", np.zeros((10, 2), dtype=np.float32))


# --------------------------------------------------------------------------------------------------
# SRT y JSON
# --------------------------------------------------------------------------------------------------


class TestSubtitles:
    def test_srt_time_format(self) -> None:
        assert format_srt_time(0.0) == "00:00:00,000"
        assert format_srt_time(3661.0075) == "01:01:01,008"  # redondea al milisegundo
        assert format_srt_time(59.9996) == "00:01:00,000"
        assert format_srt_time(-1.0) == "00:00:00,000"

    def test_transcription_has_one_entry_per_unit_in_time_order(self) -> None:
        records = [
            record(2, source="Second.", t_audio=(5.0, 6.0)),
            record(
                1,
                source="First.",
                t_audio=(1.0, 2.5),
                outcome=Outcome.DROPPED,
                translated=None,
                play=(None, None),
            ),
            record(3, source="   ", t_audio=(7.0, 8.0)),  # sin texto: no hay nada que escribir
        ]
        entries = transcription_entries(records)
        assert [(e["unit_id"], e["start"], e["end"], e["text"]) for e in entries] == [
            (1, 1.0, 2.5, "First."),
            (2, 5.0, 6.0, "Second."),
        ]

    def test_translation_only_has_spoken_units_with_their_playback_times(self) -> None:
        records = [
            record(1, translated="Hola.", play=(3.0, 4.2)),
            record(2, outcome=Outcome.DROPPED, translated=None, play=(None, None)),
            record(3, outcome=Outcome.REJECTED, translated="Mala"),
            record(4, translated="Cortada.", play=(9.0, None)),  # no terminó de sonar
            record(5, translated="Resumen.", mode=TranslationMode.CONCISE, play=(5.0, 6.5)),
        ]
        entries = translation_entries(records)
        assert [(e["unit_id"], e["start"], e["end"], e["concise"]) for e in entries] == [
            (1, 3.0, 4.2, False),
            (5, 5.0, 6.5, True),
        ]

    def test_build_srt_numbers_entries_and_marks_the_concise_ones(self) -> None:
        entries = translation_entries(
            [
                record(1, translated="Hola.", play=(3.0, 4.2)),
                record(2, translated="Resumen.", mode=TranslationMode.CONCISE, play=(5.0, 6.0)),
            ]
        )
        assert build_srt(entries, mark_concise=True) == (
            "1\n00:00:03,000 --> 00:00:04,200\nHola.\n\n"
            "2\n00:00:05,000 --> 00:00:06,000\n[resumida] Resumen.\n"
        )
        assert "[resumida]" not in build_srt(entries)
        assert build_srt([]) == ""

    def test_end_never_precedes_start(self) -> None:
        (entry,) = translation_entries([record(1, play=(5.0, 4.0))])
        assert entry["end"] == entry["start"] == 5.0


# --------------------------------------------------------------------------------------------------
# write_outputs
# --------------------------------------------------------------------------------------------------


class TestWriteOutputs:
    def test_all_outputs_of_an_audio_input(self, tmp_path: Path) -> None:
        source = make_tone_wav(tmp_path / "entrada.wav", 1.0)
        out = tmp_path / "salida"
        records = [
            record(
                1, source="Where were you?", translated="¿Dónde estabas?", t_audio=(0.1, 0.5), play=(0.6, 0.9)
            ),
            record(
                2,
                source="Never mind.",
                outcome=Outcome.DROPPED,
                translated=None,
                t_audio=(0.6, 0.9),
                play=(None, None),
            ),
        ]
        written = write(out, source, records=records)
        assert sorted(p.name for p in written) == sorted(set(OUTPUT_NAMES) - {"mezcla.mkv"})
        assert leftovers(out) == sorted(p.name for p in written)
        assert leftovers(tmp_path) == ["entrada.wav", "salida"]  # ninguna temporal

        voice = sf.info(out / "voz_es.wav")
        assert (voice.samplerate, voice.channels, voice.subtype, voice.frames) == (48_000, 1, "FLOAT", 48_000)
        mix = sf.info(out / "mezcla.wav")
        assert (mix.samplerate, mix.channels, mix.subtype) == (48_000, 2, "PCM_16")
        assert mix.duration == pytest.approx(1.0, abs=0.05)

        transcript = json.loads((out / "transcripcion.json").read_text(encoding="utf-8"))
        assert transcript["schema_version"] == 1 and transcript["input_file"] == "entrada.wav"
        assert [s["text"] for s in transcript["segments"]] == ["Where were you?", "Never mind."]
        translation = json.loads((out / "traduccion.json").read_text(encoding="utf-8"))
        assert translation["segments"] == [
            {
                "unit_id": 1,
                "start": 0.6,
                "end": 0.9,
                "text": "¿Dónde estabas?",
                "concise": False,
                "speed": 1.0,
            }
        ]
        assert (out / "traduccion.srt").read_text(encoding="utf-8") == (
            "1\n00:00:00,600 --> 00:00:00,900\n¿Dónde estabas?\n"
        )
        assert (
            (out / "transcripcion.srt")
            .read_text(encoding="utf-8")
            .startswith("1\n00:00:00,100 --> 00:00:00,500\n")
        )
        assert (out / "informe.json").read_text(encoding="utf-8") == REPORT_JSON
        assert (out / "informe.md").read_text(encoding="utf-8") == REPORT_MD

    def test_voice_wav_is_the_track_unchanged_whatever_the_volume(self, tmp_path: Path) -> None:
        source = make_silent_wav(tmp_path / "e.wav")
        track = voice_track(1.0)
        write(tmp_path / "s", source, track_48k=track, voice_volume=0.5)
        data, _ = sf.read(tmp_path / "s" / "voz_es.wav", dtype="float32")
        assert np.array_equal(data, track)

    def test_mix_adds_the_voice_to_both_channels_without_attenuating_it(self, tmp_path: Path) -> None:
        source = make_silent_wav(tmp_path / "e.wav", channels=1)  # original mono y mudo
        write(tmp_path / "s", source, track_48k=voice_track(1.0, value=0.25))
        data, _ = sf.read(tmp_path / "s" / "mezcla.wav", dtype="float32")
        burst = data[int(0.25 * PLAYBACK_RATE) : int(0.35 * PLAYBACK_RATE)]
        assert burst.shape[1] == 2
        assert np.allclose(burst, 0.25, atol=0.01)
        assert not np.any(np.abs(data[: int(0.15 * PLAYBACK_RATE)]) > 0.005)

    def test_mix_does_not_normalize_down_and_follows_the_voice_volume(self, tmp_path: Path) -> None:
        source = make_tone_wav(tmp_path / "e.wav", 1.0, channels=2)
        # Sin voz, la mezcla es el original (amix sin normalize no lo atenúa a la mitad).
        write(tmp_path / "a", source, track_48k=np.zeros(PLAYBACK_RATE, dtype=np.float32))
        original, _ = sf.read(tmp_path / "a" / "mezcla.wav", dtype="float32")
        assert float(np.max(np.abs(original))) == pytest.approx(0.0884, abs=0.005)  # 0,125 · 0,707 del -ac 2
        write(tmp_path / "b", make_silent_wav(tmp_path / "m.wav"), voice_volume=2.0)
        loud, _ = sf.read(tmp_path / "b" / "mezcla.wav", dtype="float32")
        assert float(np.max(loud)) == pytest.approx(0.5, abs=0.01)
        write(tmp_path / "c", tmp_path / "m.wav", voice_volume=0.0)
        mute, _ = sf.read(tmp_path / "c" / "mezcla.wav", dtype="float32")
        assert float(np.max(np.abs(mute))) < 0.001

    def test_the_limiter_keeps_the_mix_from_clipping(self, tmp_path: Path) -> None:
        source = make_tone_wav(tmp_path / "e.wav", 1.0)
        loud = np.full(PLAYBACK_RATE, 0.95, dtype=np.float32)
        write(tmp_path / "s", source, track_48k=loud, voice_volume=2.0)  # 1,9 de voz más el original
        data, _ = sf.read(tmp_path / "s" / "mezcla.wav", dtype="float32")
        assert float(np.max(np.abs(data))) <= 1.0
        assert float(np.max(np.abs(data))) > 0.5  # y no la ha silenciado

    def test_a_video_input_also_gets_an_mkv_with_two_audio_tracks(self, tmp_path: Path) -> None:
        source = make_mkv(tmp_path / "peli.mkv", 1.0)
        out = tmp_path / "salida"
        written = write(out, source)
        assert "mezcla.mkv" in [p.name for p in written]
        streams = ffprobe_streams(out / "mezcla.mkv")
        video = [s for s in streams if s["codec_type"] == "video"]
        audio = [s for s in streams if s["codec_type"] == "audio"]
        assert [s["codec_name"] for s in video] == ["mpeg4"]  # copiado, sin recodificar
        assert [s["codec_name"] for s in audio] == ["aac", "aac"]
        assert audio[0]["tags"]["title"].startswith("Mezcla")  # pista 1 = mezcla
        assert audio[1]["tags"]["title"] == "Original"  # pista 2 = original
        assert audio[0]["channels"] == 2 and audio[0]["sample_rate"] == "48000"
        assert audio[0]["disposition"]["default"] == 1 and audio[1]["disposition"]["default"] == 0

    def test_an_audio_only_input_has_no_mkv(self, tmp_path: Path) -> None:
        write(tmp_path / "s", make_tone_wav(tmp_path / "e.wav"))
        assert not (tmp_path / "s" / "mezcla.mkv").exists()

    def test_an_empty_session_still_produces_every_file(self, tmp_path: Path) -> None:
        source = make_silent_wav(tmp_path / "e.wav", 1.0)
        write(tmp_path / "s", source, records=[], track_48k=np.zeros(PLAYBACK_RATE, dtype=np.float32))
        assert (tmp_path / "s" / "traduccion.srt").read_text(encoding="utf-8") == ""
        data = json.loads((tmp_path / "s" / "traduccion.json").read_text(encoding="utf-8"))
        assert data["segments"] == []

    def test_rejects_a_bad_volume(self, tmp_path: Path) -> None:
        source = make_silent_wav(tmp_path / "e.wav")
        with pytest.raises(ValueError):
            write(tmp_path / "s", source, voice_volume=float("nan"))
        with pytest.raises(ValueError):
            write(tmp_path / "s", source, voice_volume=-0.1)
        assert leftovers(tmp_path) == ["e.wav"]


# --------------------------------------------------------------------------------------------------
# Escritura atómica
# --------------------------------------------------------------------------------------------------


class TestAtomicity:
    def test_a_corrupt_input_leaves_nothing_behind(self, tmp_path: Path) -> None:
        bad = tmp_path / "roto.wav"
        bad.write_bytes(b"no soy audio" * 50)
        with pytest.raises(InputFileError):
            write(tmp_path / "x" / "y" / "salida", bad)
        assert leftovers(tmp_path) == ["roto.wav"]  # ni salida, ni temporales, ni las carpetas intermedias

    def test_a_failure_halfway_removes_the_temporary_folder_and_creates_no_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = make_tone_wav(tmp_path / "e.wav")

        def boom(*args: object) -> None:
            raise EngineError("ffmpeg roto", engine="audio-file", recoverable=False)

        monkeypatch.setattr(file_outputs, "_mix_wav", boom)
        with pytest.raises(EngineError):
            write(tmp_path / "salida", source)
        assert leftovers(tmp_path) == ["e.wav"]

    def test_an_existing_output_is_only_replaced_at_the_end(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = make_tone_wav(tmp_path / "e.wav")
        out = tmp_path / "salida"
        write(out, source, report_md="# primera\n")
        seen_during_generation: list[str] = []
        real = file_outputs._mix_wav

        def spy(*args: object) -> None:
            seen_during_generation.append((out / "informe.md").read_text(encoding="utf-8"))
            real(*args)

        monkeypatch.setattr(file_outputs, "_mix_wav", spy)
        write(out, source, report_md="# segunda\n")
        assert seen_during_generation == ["# primera\n"]  # hasta el final, lo anterior sigue intacto
        assert (out / "informe.md").read_text(encoding="utf-8") == "# segunda\n"
        assert leftovers(tmp_path) == ["e.wav", "salida"]

    def test_a_failed_rerun_keeps_the_previous_outputs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = make_tone_wav(tmp_path / "e.wav")
        out = tmp_path / "salida"
        write(out, source, report_md="# buena\n")
        before = {p.name: p.read_bytes() for p in out.iterdir()}

        def boom(*args: object) -> None:
            raise EngineError("ffmpeg roto", engine="audio-file", recoverable=False)

        monkeypatch.setattr(file_outputs, "_mix_wav", boom)
        with pytest.raises(EngineError):
            write(out, source, report_md="# mala\n")
        assert {p.name: p.read_bytes() for p in out.iterdir()} == before
        assert leftovers(tmp_path) == ["e.wav", "salida"]

    def test_a_failure_while_installing_restores_the_previous_folder(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = make_tone_wav(tmp_path / "e.wav")
        out = tmp_path / "salida"
        write(out, source, report_md="# buena\n")
        (out / "mezcla.mkv").write_bytes(b"de otra ejecucion")  # un fichero nuestro que esta vez no se genera
        (out / "notas.txt").write_text("mías", encoding="utf-8")
        before = {p.name: p.read_bytes() for p in out.iterdir()}

        real_replace = os.replace

        def failing_replace(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
            if Path(dst).name == "informe.md" and ".old" not in str(src):  # solo al instalar, no al restaurar
                raise OSError("disco lleno")
            real_replace(src, dst)

        monkeypatch.setattr(file_outputs.os, "replace", failing_replace)
        with pytest.raises(OSError, match="disco lleno"):
            write(out, source, report_md="# mala\n")
        assert {p.name: p.read_bytes() for p in out.iterdir()} == before
        assert leftovers(tmp_path) == ["e.wav", "salida"]

    def test_files_that_are_not_outputs_survive_and_stale_outputs_go(self, tmp_path: Path) -> None:
        source = make_tone_wav(tmp_path / "e.wav")  # sin vídeo
        out = tmp_path / "salida"
        out.mkdir()
        (out / "notas.txt").write_text("mías", encoding="utf-8")
        (out / "mezcla.mkv").write_bytes(b"viejo")
        write(out, source)
        assert (out / "notas.txt").read_text(encoding="utf-8") == "mías"
        assert not (out / "mezcla.mkv").exists()
        assert (out / "voz_es.wav").exists()

    def test_the_output_path_must_not_be_a_file(self, tmp_path: Path) -> None:
        source = make_tone_wav(tmp_path / "e.wav")
        target = tmp_path / "salida"
        target.write_text("soy un fichero", encoding="utf-8")
        with pytest.raises(NotADirectoryError):
            write(target, source)
        assert target.read_text(encoding="utf-8") == "soy un fichero"

    def test_missing_parent_folders_are_created(self, tmp_path: Path) -> None:
        source = make_tone_wav(tmp_path / "e.wav")
        write(tmp_path / "a" / "b" / "salida", source)
        assert (tmp_path / "a" / "b" / "salida" / "informe.json").exists()
