"""E2E del modo archivo con motores falsos (T038). Sin GPU, sin modelos y sin dispositivos.

La sesión es la real (`FileSession` con `FileSource`, `TimelineSink` y las salidas de verdad, con
ffmpeg); solo los motores son dobles. El reloj de sesión corre `SPEED` veces más rápido que el real,
así que el «ritmo real» del modo archivo dura segundos.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from instanttraductor.audio.file_source import FileSource, InputFileError
from instanttraductor.config import AppPaths, Settings
from instanttraductor.pipeline.clock import SessionClock
from instanttraductor.pipeline.file_session import FileSession, default_output_dir
from instanttraductor.pipeline.session import EXIT_BAD_INPUT, EXIT_USAGE, SessionError
from tests.fakes.fake_engines import FakeEngines
from tests.fakes.fake_speech import scripted_utterance

FIXTURES = Path(__file__).parent.parent / "fixtures"
DIALOGUE = FIXTURES / "dialogo_en_2min.wav"
SILENCE = FIXTURES / "silencio_3s.wav"
SPEED = 10.0  # el reloj de sesión corre 10 veces más rápido
EXPECTED_OUTPUTS = {
    "voz_es.wav",
    "mezcla.wav",
    "transcripcion.srt",
    "transcripcion.json",
    "traduccion.srt",
    "traduccion.json",
    "informe.json",
    "informe.md",
}


def fast_clock() -> SessionClock:
    return SessionClock(lambda: time.perf_counter() * SPEED)


def utterance_spans(path: Path, *, min_gap_s: float = 0.4) -> list[tuple[float, float]]:
    """Tramos con voz del fichero (energía en bloques de 20 ms) separados por pausas de ≥ `min_gap_s`."""
    audio, rate = sf.read(path, dtype="float32")
    frame = int(0.02 * rate)
    count = len(audio) // frame
    energy = np.sqrt((audio[: count * frame].reshape(count, frame) ** 2).mean(axis=1))
    voiced = energy > 0.1 * np.percentile(energy, 90)
    spans: list[tuple[float, float]] = []
    start = last = None
    for i, is_voiced in enumerate(voiced):
        t = i * 0.02
        if is_voiced:
            start = t if start is None else start
            last = t + 0.02
        elif start is not None and last is not None and t - last >= min_gap_s:
            spans.append((start, last))
            start = None
    if start is not None and last is not None:
        spans.append((start, last))
    return spans


def dialogue_script() -> list:
    """Un enunciado del guion por cada tramo con voz del diálogo (el texto lo «reconoce» el doble).

    Los tramos se cortan en pausas más cortas que las del `FakeVad` (0,5 s): así ningún enunciado del guion
    queda partido por un fin de voz, que haría al `FakeAsrEngine` descartar su resto.
    """
    script = []
    for i, (t_start, t_end) in enumerate(utterance_spans(DIALOGUE)):
        script += scripted_utterance(
            f"utterance number {i} is here", t_start=t_start, t_end=t_end, is_sentence_end=True
        )
    return script


def run_session(session: FileSession, *, real_timeout_s: float = 60.0) -> dict:
    cancel = threading.Event()
    timer = threading.Timer(real_timeout_s, cancel.set)
    timer.start()
    try:
        session.start()
        assert session.run(cancel), "la sesión no terminó a tiempo"
        return session.finish()
    finally:
        timer.cancel()
        session.abort()


@pytest.mark.timeout(120)
def test_a_dialogue_produces_all_the_outputs(tmp_path: Path) -> None:
    script = dialogue_script()
    utterances = sum(1 for entry in script if entry.kind.value == "final")
    assert utterances >= 8
    engines = FakeEngines(script)
    out = tmp_path / "salida"
    session = FileSession(
        Settings(),
        DIALOGUE,
        output_dir=out,
        paths=AppPaths(tmp_path),
        engines=engines,
        clock_factory=fast_clock,
    )
    report = run_session(session)

    assert {p.name for p in out.iterdir()} == EXPECTED_OUTPUTS  # un WAV no tiene vídeo: sin mezcla.mkv
    assert engines.started and engines.stopped
    assert report["mode"] == "archivo"
    assert report["input_file"].endswith("dialogo_en_2min.wav")

    voice, rate = sf.read(out / "voz_es.wav", dtype="float32")
    original = sf.info(DIALOGUE).duration
    assert rate == 48_000 and abs(len(voice) / rate - original) < 0.05  # misma duración que la entrada
    assert np.abs(voice).max() > 0.0

    transcription = json.loads((out / "transcripcion.json").read_text(encoding="utf-8"))
    translation = json.loads((out / "traduccion.json").read_text(encoding="utf-8"))
    heard = " ".join(segment["text"] for segment in transcription["segments"])
    assert all(f"utterance number {i} is here" in heard for i in range(utterances)), heard
    spoken = translation["segments"]
    assert len(spoken) == report["summary"]["spoken"] >= utterances - 2
    assert all(segment["text"].startswith("ES: ") for segment in spoken)
    starts = [segment["start"] for segment in spoken]
    assert starts == sorted(starts)  # FIFO, sin solapes
    assert all(a["end"] <= b["start"] + 1e-6 for a, b in zip(spoken, spoken[1:], strict=False))


def test_a_damaged_file_exits_with_code_5_and_leaves_no_output(tmp_path: Path) -> None:
    damaged = tmp_path / "dañado.mp4"
    damaged.write_bytes(b"esto no es un video" * 100)
    engines = FakeEngines()
    session = FileSession(
        Settings(), damaged, paths=AppPaths(tmp_path), engines=engines, clock_factory=fast_clock
    )

    with pytest.raises(SessionError) as raised:
        session.start()

    assert raised.value.exit_code == EXIT_BAD_INPUT
    assert not engines.started  # se valida antes de arrancar los motores
    assert not default_output_dir(damaged).exists()
    assert [p.name for p in tmp_path.iterdir()] == ["dañado.mp4"]


@pytest.mark.timeout(60)
def test_silence_gives_a_silent_track_and_a_report_without_speech(tmp_path: Path) -> None:
    out = tmp_path / "salida"
    session = FileSession(
        Settings(),
        SILENCE,
        output_dir=out,
        paths=AppPaths(tmp_path),
        engines=FakeEngines(),
        clock_factory=fast_clock,
    )
    report = run_session(session)

    voice, rate = sf.read(out / "voz_es.wav", dtype="float32")
    assert abs(len(voice) / rate - 3.0) < 0.05
    assert not np.any(voice)
    assert report["summary"]["utterances"] == 0
    assert "no se detectó habla" in (out / "informe.md").read_text(encoding="utf-8")


def test_an_output_path_that_is_a_file_is_rejected_before_starting(tmp_path: Path) -> None:
    taken = tmp_path / "salida.txt"
    taken.write_text("ya existe", encoding="utf-8")
    engines = FakeEngines()
    session = FileSession(
        Settings(),
        SILENCE,
        output_dir=taken,
        paths=AppPaths(tmp_path),
        engines=engines,
        clock_factory=fast_clock,
    )

    with pytest.raises(SessionError) as raised:
        session.start()

    assert raised.value.exit_code == EXIT_USAGE
    assert not engines.started


@pytest.mark.timeout(60)
def test_a_file_that_breaks_halfway_exits_with_code_5_and_leaves_no_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FR-022: si ffmpeg falla a mitad del fichero, no se escriben salidas de la parte leída."""
    broken = InputFileError("El fichero está dañado a partir del segundo 1.")
    monkeypatch.setattr(FileSource, "failure", property(lambda source: broken if source.exhausted else None))
    out = tmp_path / "salida"
    session = FileSession(
        Settings(),
        SILENCE,
        output_dir=out,
        paths=AppPaths(tmp_path),
        engines=FakeEngines(),
        clock_factory=fast_clock,
    )
    session.start()
    try:
        with pytest.raises(SessionError) as raised:
            session.run()
    finally:
        session.abort()

    assert raised.value.exit_code == EXIT_BAD_INPUT
    assert not out.exists()
