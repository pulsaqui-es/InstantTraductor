"""E2E del pipeline con dobles y reloj simulado (T033). Sin GPU, sin modelos y sin dispositivos.

El audio sintético (tonos = habla, ceros = silencio) llega a «tiempo real simulado»: el test mueve un
``ManualClock`` y la fuente solo entrega cada chunk cuando el reloj lo alcanza. El sink falso reproduce
según ese mismo reloj, así que el retraso, la aceleración, el resumen y los descartes se comportan como
en directo, pero en segundos reales.
"""

from __future__ import annotations

import time
from datetime import datetime

import numpy as np
import pytest

from instanttraductor.config import Settings
from instanttraductor.contracts import (
    CAPTURE_RATE,
    AudioChunk,
    Outcome,
    SynthesisRequest,
    SynthesizedChunk,
    TranslationMode,
)
from instanttraductor.metrics.report import build_report
from instanttraductor.pipeline.clock import ManualClock
from instanttraductor.pipeline.segmenter import PauseClauseSegmenter
from instanttraductor.pipeline.session import Pipeline, PipelineParts, Warnings, make_scheduler_and_recorder
from tests.fakes.fake_audio import FakeAudioSink, FakeAudioSource
from tests.fakes.fake_speech import FakeAsrEngine, FakeVad, scripted_utterance
from tests.fakes.fake_synthesis import FakeSynthesizer
from tests.fakes.fake_translation import FakeTranslator

STEP_S = 0.02  # avance del reloj simulado en cada vuelta del test


class PacedSource:
    """Entrega los chunks de otra fuente solo cuando el reloj simulado llega a su ``t_end``."""

    def __init__(self, inner: FakeAudioSource, clock: ManualClock) -> None:
        self._inner = inner
        self._clock = clock
        self._next: AudioChunk | None = None
        self.sample_rate = inner.sample_rate

    def start(self) -> None:
        self._inner.start()

    def read(self, timeout: float) -> AudioChunk | None:
        if self._next is None:
            self._next = self._inner.read(0.0)
        if self._next is None or self._clock.now() + 1e-9 < self._next.t_end:
            time.sleep(0.001)
            return None
        chunk, self._next = self._next, None
        return chunk

    @property
    def exhausted(self) -> bool:
        return self._next is None and self._inner.exhausted

    def stop(self) -> None:
        self._inner.stop()


class LongSynthesizer(FakeSynthesizer):
    """Como el doble normal, pero cada frase dura ``seconds`` (para provocar retraso)."""

    def __init__(self, seconds: float) -> None:
        super().__init__()
        self._seconds = seconds

    def synthesize(self, request: SynthesisRequest):  # type: ignore[override]
        total = int(self._seconds * self.sample_rate)
        step = int(0.1 * self.sample_rate)
        for start in range(0, total, step):
            n = min(step, total - start)
            yield SynthesizedChunk(request.unit_id, np.full(n, 0.1, np.float32), self.sample_rate, False)
        yield SynthesizedChunk(request.unit_id, np.zeros(0, np.float32), self.sample_rate, True)


def dialogue(n: int, *, speech_s: float = 1.2, gap_s: float = 1.0, lead_s: float = 0.5):
    """Audio con ``n`` enunciados (tonos) y su guion de ASR."""
    script = []
    pieces = [np.zeros(int(lead_s * CAPTURE_RATE), np.float32)]
    t = lead_s
    for i in range(n):
        tone = 0.3 * np.sin(2 * np.pi * 220 * np.arange(int(speech_s * CAPTURE_RATE)) / CAPTURE_RATE)
        pieces.append(tone.astype(np.float32))
        script += scripted_utterance(f"sentence number {i} is here", t_start=t, t_end=t + speech_s)
        t += speech_s
        pieces.append(np.zeros(int(gap_s * CAPTURE_RATE), np.float32))
        t += gap_s
    pieces.append(np.zeros(int(2.0 * CAPTURE_RATE), np.float32))
    return np.concatenate(pieces), script


def build(audio, script, *, synthesizer=None, translator=None, settings=None):
    clock = ManualClock()
    settings = settings or Settings()
    sink = FakeAudioSink(clock)
    translator = translator or FakeTranslator(supports_concise=True)
    warnings = Warnings(clock)
    scheduler, recorder = make_scheduler_and_recorder(
        clock, sink, translator, settings, on_record=warnings.on_record
    )
    parts = PipelineParts(
        clock=clock,
        source=PacedSource(FakeAudioSource(audio), clock),
        vad=FakeVad(),
        asr=FakeAsrEngine(script, clock=clock),
        segmenter=PauseClauseSegmenter(clock, max_untranslated_s=settings.max_untranslated_s),
        translator=translator,
        synthesizer=synthesizer or FakeSynthesizer(),
        sink=sink,
        scheduler=scheduler,
        recorder=recorder,
    )
    sink.start(scheduler.on_playback_event)
    return Pipeline(parts, warnings=warnings), sink, clock


def run(pipeline: Pipeline, sink: FakeAudioSink, *, until_s: float, real_timeout_s: float = 30.0) -> None:
    pipeline.parts.source.start()
    pipeline.start()
    deadline = time.monotonic() + real_timeout_s
    while pipeline.parts.clock.now() < until_s and time.monotonic() < deadline:
        sink.advance(STEP_S)
        time.sleep(0.002)
    # Deja terminar lo que quede en vuelo.
    for _ in range(500):
        if pipeline.drained() or time.monotonic() > deadline:
            break
        sink.advance(STEP_S)
        time.sleep(0.002)


def outcomes(pipeline: Pipeline) -> list:
    return [r.outcome for r in pipeline.parts.recorder.records]


def test_utterances_are_spoken_in_order_without_repeats() -> None:
    audio, script = dialogue(5)
    pipeline, sink, _ = build(audio, script)
    try:
        run(pipeline, sink, until_s=len(audio) / CAPTURE_RATE)
    finally:
        pipeline.stop()

    records = pipeline.parts.recorder.records
    assert [r.unit_id for r in records] == sorted(r.unit_id for r in records)
    spoken = [r for r in records if r.outcome is Outcome.SPOKEN]
    assert len(spoken) == 5
    assert [r.source_text for r in spoken] == [f"sentence number {i} is here" for i in range(5)]
    assert all(r.translated_text == "ES: " + r.source_text for r in spoken)
    started = [e.unit_id for e in sink.events if e.kind.value == "started"]
    assert started == sorted(started) and len(started) == len(set(started))  # FIFO y sin repetir (FR-008)
    assert all(r.timings.sentence_delay is not None and r.timings.sentence_delay < 3.0 for r in spoken)
    assert not pipeline.errors


def test_nothing_is_spoken_during_silence() -> None:
    audio = np.zeros(5 * CAPTURE_RATE, np.float32)
    pipeline, sink, _ = build(audio, [])
    try:
        run(pipeline, sink, until_s=5.0)
    finally:
        pipeline.stop()
    assert pipeline.parts.recorder.records == ()
    assert sink.pieces == [] or len(sink.pieces) == 0


def test_delay_policy_accelerates_summarizes_and_drops() -> None:
    audio, script = dialogue(10, speech_s=1.0, gap_s=0.6)
    pipeline, sink, _ = build(audio, script, synthesizer=LongSynthesizer(4.0))
    try:
        run(pipeline, sink, until_s=len(audio) / CAPTURE_RATE + 20.0)
    finally:
        pipeline.stop()

    records = pipeline.parts.recorder.records
    assert any(r.speed > 1.0 for r in records), "no se aceleró nunca"
    assert any(r.mode is TranslationMode.CONCISE for r in records), "no se resumió nunca"
    assert all(r.speed <= Settings().max_speed + 1e-9 for r in records)
    assert not pipeline.errors


def test_without_concise_support_it_never_summarizes() -> None:
    audio, script = dialogue(10, speech_s=1.0, gap_s=0.6)
    translator = FakeTranslator(supports_concise=False)
    pipeline, sink, _ = build(audio, script, synthesizer=LongSynthesizer(4.0), translator=translator)
    try:
        run(pipeline, sink, until_s=len(audio) / CAPTURE_RATE + 20.0)
    finally:
        pipeline.stop()

    records = pipeline.parts.recorder.records
    assert all(r.mode is TranslationMode.NORMAL for r in records)
    assert all(req.mode is TranslationMode.NORMAL for req in translator.calls)
    assert any(r.outcome is Outcome.DROPPED for r in records), (
        "sin resumen, el retraso debe acabar descartando"
    )


def test_report_follows_the_contract_schema() -> None:
    audio, script = dialogue(3)
    pipeline, sink, clock = build(audio, script)
    try:
        run(pipeline, sink, until_s=len(audio) / CAPTURE_RATE)
    finally:
        pipeline.stop()
    report = build_report(
        pipeline.parts.recorder,
        mode="directo",
        started_at=datetime.now().astimezone(),
        duration_s=clock.now(),
        settings=Settings(),
    )
    assert report["schema_version"] == 1
    assert set(report["summary"]["stages_s"]) == {"capture", "asr", "mt", "tts_first", "playback"}
    assert report["summary"]["spoken"] == 3


@pytest.mark.timeout(20)
def test_stop_is_fast_even_while_speaking() -> None:
    audio, script = dialogue(4)
    pipeline, sink, _ = build(audio, script, synthesizer=LongSynthesizer(30.0))
    pipeline.parts.source.start()
    pipeline.start()
    for _ in range(300):  # hasta que haya algo sonando
        sink.advance(STEP_S)
        time.sleep(0.002)
    t0 = time.monotonic()
    pipeline.stop()
    assert time.monotonic() - t0 < 2.0
    assert pipeline.stopped
