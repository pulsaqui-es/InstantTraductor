"""E2E del filtro de idioma con dobles (spec 002, T023; SC-003b): película en «inglés» y llamada en «español».

El audio sintético alterna enunciados con un tono de 220 Hz (la película, en el idioma elegido) y con uno de
440 Hz (la conversación en español de la llamada). El `FakeLanguageVerifier` decide el idioma por el tono, así
que el test comprueba el cableado del pipeline: el anillo de audio, la ventana de cada unidad, el rechazo con
motivo «idioma» y que lo rechazado no se traduce ni suena.
"""

from __future__ import annotations

import numpy as np

from instanttraductor.config import Settings
from instanttraductor.contracts import CAPTURE_RATE, EngineError, Outcome, SourceLanguage
from instanttraductor.pipeline.clock import ManualClock
from instanttraductor.pipeline.scheduler import LANGUAGE_REJECTED_REASON
from instanttraductor.pipeline.segmenter import PauseClauseSegmenter
from instanttraductor.pipeline.session import Pipeline, PipelineParts, Warnings, make_scheduler_and_recorder
from tests.fakes.fake_audio import FakeAudioSink, FakeAudioSource
from tests.fakes.fake_language import FakeLanguageVerifier, by_dominant_frequency
from tests.fakes.fake_speech import FakeAsrEngine, FakeVad, scripted_utterance
from tests.fakes.fake_synthesis import FakeSynthesizer
from tests.fakes.fake_translation import FakeTranslator
from tests.integration.test_pipeline_fakes import PacedSource, run

FILM_HZ = 220.0
CALL_HZ = 440.0


def mixed_dialogue(kinds: list[str], *, speech_s: float = 1.5, gap_s: float = 1.0):
    """Audio con un enunciado por elemento de `kinds` («film» o «call») y su guion de ASR."""
    pieces = [np.zeros(int(0.5 * CAPTURE_RATE), np.float32)]
    script = []
    t = 0.5
    for i, kind in enumerate(kinds):
        freq = FILM_HZ if kind == "film" else CALL_HZ
        n = int(speech_s * CAPTURE_RATE)
        pieces.append((0.3 * np.sin(2 * np.pi * freq * np.arange(n) / CAPTURE_RATE)).astype(np.float32))
        script += scripted_utterance(f"{kind} line number {i} here", t_start=t, t_end=t + speech_s)
        t += speech_s
        pieces.append(np.zeros(int(gap_s * CAPTURE_RATE), np.float32))
        t += gap_s
    pieces.append(np.zeros(int(2.0 * CAPTURE_RATE), np.float32))
    return np.concatenate(pieces), script


def build(audio, script, verifier, *, language: SourceLanguage = SourceLanguage.EN):
    clock = ManualClock()
    settings = Settings(source_language=language)
    sink = FakeAudioSink(clock)
    translator = FakeTranslator(supports_concise=True)
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
        synthesizer=FakeSynthesizer(),
        sink=sink,
        scheduler=scheduler,
        recorder=recorder,
        language_verifier=verifier,
    )
    sink.start(scheduler.on_playback_event)
    return Pipeline(parts, warnings=warnings), sink, translator


def records_by_kind(pipeline: Pipeline) -> dict[str, list]:
    out: dict[str, list] = {"film": [], "call": []}
    for record in pipeline.parts.recorder.records:
        out[record.source_text.split()[0]].append(record)
    return out


def test_only_the_film_is_spoken_and_the_call_is_rejected_by_language() -> None:
    kinds = ["film", "call", "film", "call", "call", "film"]
    audio, script = mixed_dialogue(kinds)
    verifier = FakeLanguageVerifier(by_dominant_frequency({FILM_HZ: "en", CALL_HZ: "es"}))
    pipeline, sink, translator = build(audio, script, verifier)
    try:
        run(pipeline, sink, until_s=len(audio) / CAPTURE_RATE)
    finally:
        pipeline.stop()

    by_kind = records_by_kind(pipeline)
    assert len(by_kind["film"]) == 3 and all(r.outcome is Outcome.SPOKEN for r in by_kind["film"])
    assert len(by_kind["call"]) == 3
    assert all(
        r.outcome is Outcome.REJECTED and r.reason == LANGUAGE_REJECTED_REASON for r in by_kind["call"]
    )
    # Lo rechazado no llega al traductor y queda anotado cuándo se verificó.
    assert all(req.unit.source_text.startswith("film") for req in translator.calls)
    assert all(r.timings.lid_done_at is not None for r in pipeline.parts.recorder.records)
    # La ventana de cada unidad dura entre 1 y 6 s y se pide en el idioma elegido.
    assert all(1.0 - 1e-6 <= seconds <= 6.0 + 1e-6 for seconds, _ in verifier.calls)
    assert {language for _, language in verifier.calls} == {SourceLanguage.EN}
    assert not pipeline.errors


def test_the_translation_request_carries_the_chosen_language() -> None:
    audio, script = mixed_dialogue(["film"])
    verifier = FakeLanguageVerifier("ja")
    pipeline, sink, translator = build(audio, script, verifier, language=SourceLanguage.JA)
    try:
        run(pipeline, sink, until_s=len(audio) / CAPTURE_RATE)
    finally:
        pipeline.stop()
    assert [req.source_language for req in translator.calls] == [SourceLanguage.JA]


def test_if_the_verifier_fails_the_unit_is_translated_anyway() -> None:
    audio, script = mixed_dialogue(["film", "call"])
    verifier = FakeLanguageVerifier(fail_with=EngineError("sin modelo", engine="lid"))
    pipeline, sink, _ = build(audio, script, verifier)
    try:
        run(pipeline, sink, until_s=len(audio) / CAPTURE_RATE)
    finally:
        pipeline.stop()
    assert [r.outcome for r in pipeline.parts.recorder.records] == [Outcome.SPOKEN, Outcome.SPOKEN]
    assert pipeline.language_check_failures == 2


def test_without_a_verifier_everything_is_translated_as_in_0_1() -> None:
    audio, script = mixed_dialogue(["film", "call"])
    pipeline, sink, _ = build(audio, script, None)
    try:
        run(pipeline, sink, until_s=len(audio) / CAPTURE_RATE)
    finally:
        pipeline.stop()
    assert [r.outcome for r in pipeline.parts.recorder.records] == [Outcome.SPOKEN, Outcome.SPOKEN]
