"""Tests de `FileSource` y `probe_input` (T035): ficheros de prueba generados con ffmpeg real.

No usan dispositivos de audio, GPU ni modelos. Además de los tests propios, `FileSource` pasa la suite de
contrato `AudioSourceContract` (con `finite=True`).
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest

from instanttraductor.audio import file_source as file_source_module
from instanttraductor.audio.file_source import FileSource, InputFileError, probe_input
from instanttraductor.config import ffmpeg_path
from instanttraductor.contracts import CAPTURE_RATE, AudioChunk, AudioSource, EngineError
from instanttraductor.pipeline.clock import ManualClock, SessionClock
from tests.contract.test_audio_contract import AudioSourceContract

pytestmark = pytest.mark.skipif(ffmpeg_path() is None, reason="ffmpeg no está disponible")


def run_ffmpeg(*args: str) -> None:
    ffmpeg = ffmpeg_path()
    assert ffmpeg is not None
    subprocess.run(
        [str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error", *args], check=True, capture_output=True
    )


def make_wav(path: Path, seconds: float = 1.0, *, rate: int = 44_100, channels: int = 2) -> Path:
    """WAV con un tono de 440 Hz, a otra frecuencia y con otro número de canales que la fuente."""
    run_ffmpeg(
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}:sample_rate={rate}",
        "-ac", str(channels), str(path),
    )  # fmt: skip
    return path


def make_mkv_with_video(path: Path, seconds: float = 1.0) -> Path:
    run_ffmpeg(
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
        "-f", "lavfi", "-i", f"color=c=blue:s=64x64:r=10:d={seconds}",
        "-c:a", "aac", "-c:v", "mpeg4", "-shortest", str(path),
    )  # fmt: skip
    return path


def drain(source: AudioSource, *, limit: int = 100_000) -> list[AudioChunk]:
    chunks: list[AudioChunk] = []
    idle = 0
    while not source.exhausted and len(chunks) < limit and idle < 50:
        chunk = source.read(0.5)
        if chunk is None:
            idle += 1
        else:
            chunks.append(chunk)
    return chunks


@pytest.fixture
def wav(tmp_path: Path) -> Path:
    return make_wav(tmp_path / "tono.wav", 1.0)


# --------------------------------------------------------------------------------------------------
# probe_input
# --------------------------------------------------------------------------------------------------


class TestProbeInput:
    def test_reports_duration_and_no_video_for_a_wav(self, wav: Path) -> None:
        info = probe_input(wav)
        assert info.duration_s == pytest.approx(1.0, abs=0.05)
        assert info.has_video is False

    def test_reports_video_for_an_mkv(self, tmp_path: Path) -> None:
        info = probe_input(make_mkv_with_video(tmp_path / "v.mkv"))
        assert info.has_video is True
        assert info.duration_s == pytest.approx(1.0, abs=0.15)

    def test_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(InputFileError, match="No existe"):
            probe_input(tmp_path / "nada.wav")

    def test_garbage_file(self, tmp_path: Path) -> None:
        bad = tmp_path / "roto.wav"
        bad.write_bytes(b"esto no es audio" * 100)
        with pytest.raises(InputFileError):
            probe_input(bad)

    def test_video_without_audio_track(self, tmp_path: Path) -> None:
        silent = tmp_path / "mudo.mkv"
        run_ffmpeg("-f", "lavfi", "-i", "color=c=red:s=64x64:r=10:d=1", "-c:v", "mpeg4", str(silent))
        with pytest.raises(InputFileError, match="no tiene pista de audio"):
            probe_input(silent)

    def test_without_ffmpeg_it_is_an_engine_error(self, wav: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(file_source_module, "ffmpeg_path", lambda: None)
        with pytest.raises(EngineError) as info:
            probe_input(wav)
        assert info.value.recoverable is False

    def test_without_ffprobe_it_validates_with_ffmpeg(
        self, wav: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(file_source_module, "ffprobe_path", lambda: None)
        info = probe_input(wav)
        assert info.duration_s is None
        assert info.has_video is False
        bad = wav.with_name("roto.wav")
        bad.write_bytes(b"basura" * 50)
        with pytest.raises(InputFileError):
            probe_input(bad)


# --------------------------------------------------------------------------------------------------
# FileSource
# --------------------------------------------------------------------------------------------------


class TestFileSource:
    def test_decodes_to_16k_mono_float32_contiguous_chunks(self, wav: Path) -> None:
        source = FileSource(SessionClock(), wav, realtime=False)
        source.start()
        chunks = drain(source)
        source.stop()
        assert chunks
        assert source.duration_s == pytest.approx(1.0, abs=0.05)
        total = sum(len(c.samples) for c in chunks)
        assert total == pytest.approx(CAPTURE_RATE, abs=CAPTURE_RATE * 0.05)
        assert all(len(c.samples) == 320 for c in chunks[:-1])
        assert chunks[0].t_start == 0.0
        for previous, current in zip(chunks, chunks[1:], strict=False):
            assert current.t_start == pytest.approx(previous.t_end, abs=1e-9)
        samples = np.concatenate([c.samples for c in chunks])
        assert samples.dtype == np.float32
        assert 0.05 < float(np.max(np.abs(samples))) <= 1.0  # el tono (amplitud ~0,125) está ahí

    def test_a_video_file_yields_its_audio(self, tmp_path: Path) -> None:
        source = FileSource(SessionClock(), make_mkv_with_video(tmp_path / "v.mkv"), realtime=False)
        source.start()
        chunks = drain(source)
        source.stop()
        assert sum(len(c.samples) for c in chunks) == pytest.approx(CAPTURE_RATE, abs=CAPTURE_RATE * 0.15)

    def test_custom_chunk_size(self, wav: Path) -> None:
        source = FileSource(SessionClock(), wav, chunk_s=0.1, realtime=False)
        source.start()
        first = source.read(1.0)
        source.stop()
        assert first is not None
        assert len(first.samples) == 1600

    def test_chunks_follow_the_clock_in_realtime(self, wav: Path) -> None:
        clock = ManualClock()
        source = FileSource(clock, wav)
        source.start()  # vuelve con el primer chunk leído, pero aún sin entregar: el reloj está en 0
        try:
            assert source.read(0.05) is None
            assert source.arrival_time(0.02) is None
            clock.advance(0.02)
            first = source.read(1.0)
            assert first is not None and first.t_start == 0.0
            assert source.read(0.05) is None  # el segundo chunk toca en 0,04
            clock.advance(0.1)  # el reloj da un salto: se entregan todos los vencidos
            got = [source.read(1.0) for _ in range(5)]
            assert all(c is not None for c in got)
            assert source.read(0.05) is None  # nada más hasta que el reloj avance
        finally:
            source.stop()

    def test_realtime_pace_matches_the_session_clock(self, tmp_path: Path) -> None:
        wav = make_wav(tmp_path / "corto.wav", 0.6)
        clock = SessionClock()
        source = FileSource(clock, wav)
        begin = clock.now()
        source.start()
        chunks = drain(source)
        elapsed = clock.now() - begin
        source.stop()
        assert sum(len(c.samples) for c in chunks) == pytest.approx(0.6 * CAPTURE_RATE, abs=800)
        assert 0.5 <= elapsed <= 1.5  # a ritmo real: no va ni mucho más rápido ni mucho más lento

    def test_arrival_time_is_recorded_before_the_chunk_is_readable(self, wav: Path) -> None:
        clock = ManualClock()
        source = FileSource(clock, wav)
        source.start()
        try:
            clock.advance(0.1)
            chunk = source.read(1.0)
            assert chunk is not None
            arrival = source.arrival_time(chunk.t_end)
            assert arrival is not None and chunk.t_end <= arrival <= 0.1 + 1e-9
            assert source.arrival_time(10.0) is None  # aún no ha llegado
        finally:
            source.stop()

    def test_arrival_time_boundary_belongs_to_the_chunk_that_ends_there(self, wav: Path) -> None:
        clock = ManualClock()
        source = FileSource(clock, wav)
        source.start()
        try:
            clock.advance(0.02)
            assert source.read(1.0) is not None
            first_arrival = source.arrival_time(0.02)
            assert first_arrival == pytest.approx(0.02)
            assert source.arrival_time(0.01) == first_arrival
            assert source.arrival_time(0.03) is None  # el segundo chunk aún no ha llegado
        finally:
            source.stop()

    def test_stop_interrupts_a_realtime_source_and_kills_ffmpeg(self, wav: Path) -> None:
        source = FileSource(ManualClock(), wav)  # el reloj no avanza: el productor espera
        source.start()
        process = source._process  # noqa: SLF001 (se comprueba que no queda ffmpeg huérfano)
        assert process is not None
        source.stop()
        source.stop()
        assert source.exhausted is True
        assert source.read(0.0) is None
        assert process.poll() is not None

    def test_start_fails_for_a_missing_file(self, tmp_path: Path) -> None:
        source = FileSource(SessionClock(), tmp_path / "nada.wav")
        with pytest.raises(InputFileError):
            source.start()

    def test_start_fails_for_a_corrupt_file(self, tmp_path: Path) -> None:
        bad = tmp_path / "roto.wav"
        bad.write_bytes(b"RIFF\x00\x00\x00\x00WAVEfmt garbage" * 10)
        source = FileSource(SessionClock(), bad)
        with pytest.raises(InputFileError):
            source.start()
        source.stop()

    def test_start_fails_when_the_header_is_fine_but_there_is_no_audio_data(self, tmp_path: Path) -> None:
        """ffprobe da por bueno el fichero, pero ffmpeg no decodifica nada: lo atrapa la primera lectura."""
        empty = tmp_path / "vacio.wav"
        run_ffmpeg("-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", "0", str(empty))
        source = FileSource(SessionClock(), empty, realtime=False)
        with pytest.raises(InputFileError):
            source.start()
        source.stop()

    def test_start_without_ffmpeg_is_an_unrecoverable_engine_error(
        self, wav: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(file_source_module, "ffmpeg_path", lambda: None)
        with pytest.raises(EngineError) as info:
            FileSource(SessionClock(), wav).start()
        assert info.value.recoverable is False

    def test_rejects_a_non_positive_chunk_size(self, wav: Path) -> None:
        with pytest.raises(ValueError, match="chunk_s"):
            FileSource(SessionClock(), wav, chunk_s=0)

    def test_read_before_start_returns_none_after_the_timeout(self, wav: Path) -> None:
        source = FileSource(SessionClock(), wav)
        before = time.perf_counter()
        assert source.read(0.05) is None
        assert time.perf_counter() - before < 1.0


# --------------------------------------------------------------------------------------------------
# Contrato
# --------------------------------------------------------------------------------------------------


class TestFileSourceContractRealtime(AudioSourceContract):
    @pytest.fixture
    def make_impl(self, tmp_path: Path) -> Callable[[], AudioSource]:
        path = make_wav(tmp_path / "contrato.wav", 2.0)
        return lambda: FileSource(SessionClock(), path)


class TestFileSourceContractFast(AudioSourceContract):
    @pytest.fixture
    def make_impl(self, tmp_path: Path) -> Callable[[], AudioSource]:
        path = make_wav(tmp_path / "contrato.wav", 2.0)
        return lambda: FileSource(SessionClock(), path, realtime=False)
