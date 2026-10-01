"""Silero VAD real (T018): el modelo ONNX instalado sobre habla de `tests/fixtures/dialogo_en_2min.wav`.

Marcador `model`: necesita `silero-vad` en `component_dir()` (`instanttraductor preparar`) y solo lo ejecuta
el orquestador. Lleva la suite `VadContract` con habla real, porque el audio sintético por defecto de la
suite solo lo entienden los dobles.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import cache
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pytest
import soundfile as sf

from instanttraductor.contracts import CAPTURE_RATE, Vad, VadEvent, VadEventKind
from instanttraductor.vad.silero import FRAME_SAMPLES, SileroOnnx, SileroVad, default_model_path
from tests.contract.helpers import silence, to_chunks
from tests.contract.test_speech_contract import VadContract, feed_vad

pytestmark = pytest.mark.model

Samples = npt.NDArray[np.float32]

DIALOGUE = Path(__file__).resolve().parents[1] / "fixtures" / "dialogo_en_2min.wav"
MIN_PAUSE_SAMPLES = round(0.75 * CAPTURE_RATE)  # el fixture deja 0,8 s de ceros tras cada enunciado
SLACK_S = 0.2  # un chunk de 20 ms, una trama de 32 ms y el relleno previo de 150 ms caben holgados


@cache
def dialogue() -> Samples:
    samples, rate = sf.read(DIALOGUE, dtype="float32")
    assert rate == CAPTURE_RATE
    return samples


def utterance_spans(samples: Samples) -> list[tuple[int, int]]:
    """Tramos [inicio, fin) entre las pausas de ceros exactos de 0,75 s o más: un enunciado por tramo."""
    padded = np.concatenate(([0], (samples == 0.0).astype(np.int8), [0]))
    edges = np.flatnonzero(np.diff(padded))
    pauses = [
        (int(a), int(b)) for a, b in zip(edges[::2], edges[1::2], strict=True) if b - a >= MIN_PAUSE_SAMPLES
    ]
    spans: list[tuple[int, int]] = []
    cursor = 0
    for pause_start, pause_end in pauses:
        if pause_start > cursor:
            spans.append((cursor, pause_start))
        cursor = pause_end
    if cursor < len(samples):
        spans.append((cursor, len(samples)))
    return spans


class TestSileroVadReal(VadContract):
    """El VAD real cumple la suite de contrato con el primer enunciado del diálogo como habla."""

    @pytest.fixture
    def make_impl(self) -> Callable[[], Vad]:
        return SileroVad

    @pytest.fixture
    def speech_samples(self) -> Samples:
        start, end = utterance_spans(dialogue())[0]
        return dialogue()[start:end]

    @pytest.fixture
    def silence_samples(self) -> Samples:
        # Silencio digital: es lo que entrega un loopback sin sonido (research.md R3) y lo que hay entre los
        # enunciados del fixture. Se deja la duración de 2 s de la suite, más larga que la pausa del diálogo.
        return silence(2.0)


class TestSileroOnTheDialogue:
    @pytest.fixture(scope="class")
    def events(self) -> list[VadEvent]:
        return feed_vad(SileroVad(), dialogue())

    def test_the_fixture_has_ten_utterances(self) -> None:
        assert len(utterance_spans(dialogue())) == 10

    def test_every_utterance_has_a_start_and_an_end(self, events: list[VadEvent]) -> None:
        for number, (first, last) in enumerate(utterance_spans(dialogue())):
            t0, t1 = first / CAPTURE_RATE, last / CAPTURE_RATE
            starts = [
                e.t for e in events if e.kind is VadEventKind.SPEECH_START and t0 - SLACK_S <= e.t <= t1
            ]
            ends = [e.t for e in events if e.kind is VadEventKind.SPEECH_END and t0 <= e.t <= t1 + SLACK_S]
            assert starts, f"enunciado {number}: no hay SPEECH_START entre {t0:.2f} y {t1:.2f} s"
            assert ends, f"enunciado {number}: no hay SPEECH_END entre {t0:.2f} y {t1:.2f} s"

    def test_nothing_is_reported_inside_the_digital_silence(self, events: list[VadEvent]) -> None:
        spans = [(a / CAPTURE_RATE, b / CAPTURE_RATE) for a, b in utterance_spans(dialogue())]
        for event in events:
            inside = any(a - SLACK_S <= event.t <= b + SLACK_S for a, b in spans)
            assert inside, f"{event.kind} en {event.t:.2f} s, en una pausa de ceros"

    def test_starts_and_ends_alternate_and_close_every_utterance(self, events: list[VadEvent]) -> None:
        kinds = [e.kind for e in events]
        assert kinds == [VadEventKind.SPEECH_START, VadEventKind.SPEECH_END] * (len(kinds) // 2)
        # Diez enunciados, alguno partido por una pausa larga del propio hablante.
        assert 10 <= len(kinds) // 2 <= 25

    @pytest.mark.parametrize("chunk_s", [0.02, 0.1])
    def test_events_do_not_depend_on_the_chunk_size(self, events: list[VadEvent], chunk_s: float) -> None:
        samples = dialogue()
        vad = SileroVad()
        found: list[VadEvent] = []
        for chunk in to_chunks(samples, chunk_s=chunk_s):
            found.extend(vad.accept(chunk))
        assert found == events


class TestSileroOnnxModel:
    def test_the_model_file_is_there(self) -> None:
        assert default_model_path().is_file()

    def test_probability_is_high_on_speech_and_low_on_silence(self) -> None:
        model = SileroOnnx(default_model_path())
        first, last = utterance_spans(dialogue())[0]
        speech = dialogue()[first:last]
        speech_p = [
            model.prob(speech[i : i + FRAME_SAMPLES])
            for i in range(0, len(speech) - FRAME_SAMPLES, FRAME_SAMPLES)
        ]
        assert max(speech_p) > 0.9

        model.reset()
        quiet = silence(2.0)
        quiet_p = [
            model.prob(quiet[i : i + FRAME_SAMPLES])
            for i in range(0, len(quiet) - FRAME_SAMPLES, FRAME_SAMPLES)
        ]
        assert max(quiet_p) < 0.1
