"""Nemotron real (T019): el modelo int8 de `component_dir("nemotron-en")` sobre sherpa-onnx.

Marcador `model`: necesita `nemotron-en` y `silero-vad` en `component_dir()` (`instanttraductor preparar`) y
solo lo ejecuta el orquestador. Lleva:
- la suite `AsrEngineContract` con habla real (el audio sintético por defecto solo lo entienden los dobles);
- el WER sobre `dialogo_en_2min.wav` (< 10 %), con la puerta de VAD que usará la sesión y, de paso, los
  invariantes de los eventos y la promesa de `stable_len` con el modelo de verdad.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pytest

from instanttraductor.asr.sherpa_streaming import NemotronStreamingAsr, Recognizer, create_recognizer
from instanttraductor.contracts import AsrEngine, AsrEvent, AsrEventKind, Vad, VadEventKind
from instanttraductor.pipeline.clock import ManualClock
from instanttraductor.vad.silero import SileroVad
from tests.contract.helpers import silence, to_chunks
from tests.contract.test_speech_contract import AsrEngineContract
from tests.integration.test_silero_model import dialogue, utterance_spans

pytestmark = pytest.mark.model

Samples = npt.NDArray[np.float32]

REFERENCE = Path(__file__).resolve().parents[1] / "fixtures" / "dialogo_en_2min.txt"
MAX_WER = 0.10


def run_session(samples: Samples, vad: Vad, asr: AsrEngine) -> list[AsrEvent]:
    """Hace lo que hará la sesión: el VAD manda y el ASR solo oye el habla.

    Con `SPEECH_START` entrega al ASR el audio desde `t` (que ya lleva el relleno previo del VAD) y, después,
    cada chunk mientras dure el habla; con `SPEECH_END` vacía el ASR. Si el audio acaba en mitad del habla, lo
    vacía al final.
    """
    chunks = to_chunks(samples)
    events: list[AsrEvent] = []
    feeding = False
    for index, chunk in enumerate(chunks):
        vad_events = vad.accept(chunk)
        for vad_event in vad_events:
            if vad_event.kind is VadEventKind.SPEECH_START:
                first = index
                while first > 0 and chunks[first - 1].t_end > vad_event.t:
                    first -= 1
                for earlier in chunks[first:index]:
                    events.extend(asr.accept(earlier))
                feeding = True
        if feeding:
            events.extend(asr.accept(chunk))
        for vad_event in vad_events:
            if vad_event.kind is VadEventKind.SPEECH_END:
                events.extend(asr.flush())
                feeding = False
    events.extend(asr.flush())
    return events


def words(text: str) -> list[str]:
    """Palabras en minúsculas y sin puntuación (el modelo da mayúsculas y comas; la referencia, no)."""
    return re.sub(r"[^a-z' ]", " ", text.lower()).split()


def word_error_rate(reference: list[str], hypothesis: list[str]) -> float:
    """Errores (sustituciones, borrados e inserciones) entre las palabras de referencia."""
    previous = list(range(len(hypothesis) + 1))
    for i, ref_word in enumerate(reference, start=1):
        current = [i]
        for j, hyp_word in enumerate(hypothesis, start=1):
            cost = 0 if ref_word == hyp_word else 1
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost))
        previous = current
    return previous[-1] / len(reference)


@pytest.fixture(scope="module")
def recognizer() -> Recognizer:
    """Un único reconocedor para todos los tests: cargar el modelo cuesta unos segundos."""
    return create_recognizer()


class TestNemotronStreamingAsrReal(AsrEngineContract):
    """El motor real cumple la suite de contrato con el primer enunciado del diálogo como habla."""

    @pytest.fixture
    def make_impl(self, recognizer: Recognizer) -> Callable[[], AsrEngine]:
        return lambda: NemotronStreamingAsr(ManualClock(), recognizer=recognizer)

    @pytest.fixture
    def speech_samples(self) -> Samples:
        start, end = utterance_spans(dialogue())[0]
        return dialogue()[start:end]

    @pytest.fixture
    def silence_samples(self) -> Samples:
        # Silencio digital: es lo que entrega un loopback sin sonido (research.md R3).
        return silence(2.0)


@pytest.mark.timeout(600)  # 2 min de audio con RTF ~0,15, más los otros procesos de la máquina
class TestNemotronOnTheDialogue:
    @pytest.fixture(scope="class")
    def events(self, recognizer: Recognizer) -> list[AsrEvent]:
        return run_session(
            dialogue(), SileroVad(), NemotronStreamingAsr(ManualClock(), recognizer=recognizer)
        )

    def test_wer_is_under_ten_percent(self, events: list[AsrEvent]) -> None:
        reference = words(REFERENCE.read_text(encoding="utf-8"))
        hypothesis = words(" ".join(e.text for e in events if e.kind is AsrEventKind.FINAL))
        wer = word_error_rate(reference, hypothesis)
        print(f"WER sobre dialogo_en_2min.wav: {wer:.2%} ({len(reference)} palabras de referencia)")
        assert wer < MAX_WER

    def test_every_segment_ends_with_one_final_and_the_invariants_hold(self, events: list[AsrEvent]) -> None:
        AsrEngineContract.assert_event_invariants(events, NemotronStreamingAsr.capabilities)

    def test_there_is_a_final_for_every_utterance(self, events: list[AsrEvent]) -> None:
        finals = [e for e in events if e.kind is AsrEventKind.FINAL]
        for number, (first, last) in enumerate(utterance_spans(dialogue())):
            t0, t1 = first / 16_000, last / 16_000
            assert any(f.t_start < t1 and f.t_end > t0 for f in finals), f"enunciado {number}: sin FINAL"

    def test_what_stable_len_promises_is_kept(self, events: list[AsrEvent]) -> None:
        """Cada evento de un segmento empieza por lo que el anterior daba por estable (R5)."""
        previous: AsrEvent | None = None
        for event in events:
            if previous is not None and previous.segment_id == event.segment_id:
                stable = previous.text[: previous.stable_len]
                assert event.text.startswith(stable), f"{stable!r} cambió a {event.text!r}"
            previous = event
