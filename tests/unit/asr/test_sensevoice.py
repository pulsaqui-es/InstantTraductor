"""Tests de `SenseVoiceSegmentAsr` (T013) sin modelo: el `OfflineRecognizer` de sherpa es un doble.

`FakeRecognizer` guarda el audio de cada decodificación y devuelve, por orden, los textos del guion (cuando se
acaban, un texto por defecto). Un guion con `""` simula un segmento sin texto.

La suite `AsrEngineContract` se concreta aquí con ese doble; con el modelo real, en
`tests/integration/test_asr_multilang_model.py` (marcador `model`).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

from instanttraductor.asr.sensevoice import (
    MODEL_FILES,
    SenseVoiceSegmentAsr,
    create_recognizer,
    quietest_cut,
)
from instanttraductor.contracts import (
    CAPTURE_RATE,
    AsrCapabilities,
    AsrEngine,
    AsrEvent,
    AsrEventKind,
    AudioChunk,
    EngineError,
)
from instanttraductor.pipeline.clock import ManualClock
from tests.contract.helpers import assert_implements, silence, to_chunks, voiced
from tests.contract.test_speech_contract import AsrEngineContract, feed_asr

Samples = npt.NDArray[np.float32]
FINAL = AsrEventKind.FINAL


class FakeStream:
    def __init__(self) -> None:
        self.waveforms: list[tuple[float, Samples]] = []
        self.result = SimpleNamespace(text="")

    def accept_waveform(self, sample_rate: float, waveform: Samples) -> None:
        self.waveforms.append((sample_rate, np.array(waveform, copy=True)))


class FakeRecognizer:
    """Doble de `sherpa_onnx.OfflineRecognizer`."""

    def __init__(self, *texts: str, default: str = "テスト。") -> None:
        self._texts = list(texts)
        self._default = default
        self.streams: list[FakeStream] = []
        self.decoded: list[Samples] = []  # el audio de cada `decode_stream`, en orden
        self.fail_on_decode: Exception | None = None

    def create_stream(self) -> FakeStream:
        stream = FakeStream()
        self.streams.append(stream)
        return stream

    def decode_stream(self, stream: FakeStream) -> None:
        if self.fail_on_decode is not None:
            raise self.fail_on_decode
        self.decoded.append(np.concatenate([w for _, w in stream.waveforms]))
        index = len(self.decoded) - 1
        stream.result = SimpleNamespace(
            text=self._texts[index] if index < len(self._texts) else self._default
        )


def make_asr(
    *texts: str, language: str = "ja", max_segment_s: float = 6.0, clock: ManualClock | None = None
) -> tuple[SenseVoiceSegmentAsr, FakeRecognizer, ManualClock]:
    recognizer = FakeRecognizer(*texts)
    clock = clock if clock is not None else ManualClock()
    asr = SenseVoiceSegmentAsr(language, clock, recognizer=recognizer, max_segment_s=max_segment_s)
    return asr, recognizer, clock


def speech_with_gap(total_s: float, gap_at_s: float) -> Samples:
    """Audio sonoro de `total_s` con una trama de 20 ms de silencio digital que empieza en `gap_at_s`."""
    samples = voiced(total_s)
    start = round(gap_at_s * CAPTURE_RATE)
    samples[start : start + 320] = 0.0
    return samples


# --------------------------------------------------------------------------------------------------
# Suite de contrato con el doble
# --------------------------------------------------------------------------------------------------


class TestSenseVoiceContract(AsrEngineContract):
    @pytest.fixture
    def make_impl(self) -> Callable[[], AsrEngine]:
        return lambda: make_asr()[0]


class TestSenseVoiceKoreanContract(AsrEngineContract):
    @pytest.fixture
    def make_impl(self) -> Callable[[], AsrEngine]:
        return lambda: make_asr(language="ko")[0]


# --------------------------------------------------------------------------------------------------
# Declaración y acumulación
# --------------------------------------------------------------------------------------------------


class TestDeclaration:
    @pytest.mark.parametrize("language", ["ja", "ko"])
    def test_it_is_a_per_segment_engine_without_partials(self, language: str) -> None:
        asr, _, _ = make_asr(language=language)
        assert asr.name == f"sensevoice-small-{language}"
        assert asr.capabilities == AsrCapabilities(
            native_streaming=False,
            partials=False,
            punctuation=True,
            word_timestamps=False,
            languages=frozenset({language}),
            device="cpu",
            est_vram_mb=0,
        )
        assert_implements(asr, AsrEngine)

    @pytest.mark.parametrize("language", ["en", "zh", "", "JA"])
    def test_only_japanese_and_korean_are_accepted(self, language: str) -> None:
        with pytest.raises(ValueError, match="ja, ko"):
            SenseVoiceSegmentAsr(language, ManualClock(), recognizer=FakeRecognizer())

    def test_max_segment_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="max_segment_s"):
            SenseVoiceSegmentAsr("ja", ManualClock(), recognizer=FakeRecognizer(), max_segment_s=0.0)


class TestAccumulate:
    def test_accept_only_accumulates_and_never_decodes(self) -> None:
        asr, recognizer, _ = make_asr()
        assert feed_asr(asr, voiced(4.0)) == []
        assert recognizer.streams == []

    def test_empty_chunks_are_ignored(self) -> None:
        asr, recognizer, _ = make_asr()
        assert asr.accept(AudioChunk(np.zeros(0, dtype=np.float32), CAPTURE_RATE, 0.0)) == []
        assert asr.flush() == []
        assert recognizer.streams == []

    def test_a_chunk_that_is_not_16_khz_is_rejected(self) -> None:
        asr, _, _ = make_asr()
        with pytest.raises(ValueError, match="16000"):
            asr.accept(AudioChunk(np.zeros(480, dtype=np.float32), 48_000, 0.0))


# --------------------------------------------------------------------------------------------------
# flush(): un FINAL por segmento
# --------------------------------------------------------------------------------------------------


class TestFlush:
    def test_flush_decodes_all_the_audio_once_and_emits_a_final(self) -> None:
        asr, recognizer, _ = make_asr("今日は、いい天気です。")
        audio = voiced(2.0)
        feed_asr(asr, audio, t0=5.0)
        (final,) = asr.flush()
        assert final.kind is FINAL
        assert (final.text, final.stable_len) == ("今日は、いい天気です。", len("今日は、いい天気です。"))
        assert (final.segment_id, final.revision, final.language) == (0, 0, "ja")
        assert final.is_sentence_end
        assert final.words == ()
        assert (final.t_start, final.t_end) == (5.0, pytest.approx(7.0))
        (decoded,) = recognizer.decoded
        np.testing.assert_array_equal(decoded, audio)
        (stream,) = recognizer.streams
        assert [rate for rate, _ in stream.waveforms] == [16_000]

    def test_the_final_carries_the_language_of_the_engine(self) -> None:
        asr, _, _ = make_asr("안녕하세요 여러분.", language="ko")
        feed_asr(asr, voiced(1.0))
        (final,) = asr.flush()
        assert final.language == "ko"

    def test_emitted_at_is_read_from_the_clock(self) -> None:
        asr, _, clock = make_asr()
        feed_asr(asr, voiced(1.0))
        clock.set(42.5)
        (final,) = asr.flush()
        assert final.emitted_at == 42.5

    def test_a_text_without_final_punctuation_is_not_a_sentence_end(self) -> None:
        asr, _, _ = make_asr("안녕하세요 여러분")
        feed_asr(asr, voiced(1.0))
        (final,) = asr.flush()
        assert not final.is_sentence_end

    def test_flush_without_audio_returns_nothing(self) -> None:
        asr, recognizer, _ = make_asr()
        assert asr.flush() == []
        assert recognizer.streams == []

    def test_a_second_flush_has_nothing_left_to_close(self) -> None:
        asr, _, _ = make_asr()
        feed_asr(asr, voiced(1.0))
        assert len(asr.flush()) == 1
        assert asr.flush() == []

    def test_every_segment_is_decoded_on_its_own_with_a_new_id(self) -> None:
        asr, recognizer, _ = make_asr("一つ目。", "二つ目。")
        first_audio, second_audio = voiced(1.0), voiced(1.5)
        first = feed_asr(asr, first_audio) + asr.flush()
        second = feed_asr(asr, second_audio, t0=4.0) + asr.flush()
        assert [(e.segment_id, e.text) for e in first + second] == [(0, "一つ目。"), (1, "二つ目。")]
        assert second[0].t_start == 4.0
        np.testing.assert_array_equal(recognizer.decoded[0], first_audio)
        np.testing.assert_array_equal(recognizer.decoded[1], second_audio)

    def test_digital_silence_is_not_decoded_and_does_not_use_up_an_id(self) -> None:
        asr, recognizer, _ = make_asr()
        assert feed_asr(asr, silence(2.0)) == []
        assert asr.flush() == []
        assert recognizer.streams == []
        events = feed_asr(asr, voiced(1.0), t0=2.0) + asr.flush()
        assert [e.segment_id for e in events] == [0]

    def test_a_segment_without_text_gives_no_event_and_does_not_use_up_an_id(self) -> None:
        asr, recognizer, _ = make_asr("", "二つ目。")
        feed_asr(asr, voiced(1.0))
        assert asr.flush() == []
        events = feed_asr(asr, voiced(1.0), t0=2.0) + asr.flush()
        assert [(e.segment_id, e.text) for e in events] == [(0, "二つ目。")]
        assert len(recognizer.decoded) == 2

    @pytest.mark.parametrize("text", [".", "。", "…?", " , "])
    def test_a_text_with_only_loose_punctuation_is_dropped(self, text: str) -> None:
        asr, _, _ = make_asr(text, "二つ目。")
        feed_asr(asr, voiced(1.0))
        assert asr.flush() == []
        events = feed_asr(asr, voiced(1.0), t0=2.0) + asr.flush()
        assert [(e.segment_id, e.text) for e in events] == [(0, "二つ目。")]

    def test_the_text_is_stripped(self) -> None:
        asr, _, _ = make_asr("  こんにちは。 \n")
        feed_asr(asr, voiced(1.0))
        (final,) = asr.flush()
        assert final.text == "こんにちは。"


# --------------------------------------------------------------------------------------------------
# Corte forzado
# --------------------------------------------------------------------------------------------------


class TestForcedCut:
    def test_it_cuts_at_the_quietest_frame_of_the_last_1_5_seconds(self) -> None:
        asr, recognizer, _ = make_asr("前半。", "後半。", max_segment_s=2.0)
        audio = speech_with_gap(2.0, gap_at_s=0.94)
        events: list[AsrEvent] = []
        emitted_at_chunk: list[int] = []
        for index, chunk in enumerate(to_chunks(audio)):
            new = asr.accept(chunk)
            events.extend(new)
            if new:
                emitted_at_chunk.append(index)
        assert emitted_at_chunk == [99], "el corte sale al llegar a los 2 s (100 chunks de 20 ms)"
        (first,) = events
        cut = round(0.95 * CAPTURE_RATE)  # el centro de la trama de silencio
        assert (first.kind, first.text, first.segment_id, first.revision) == (FINAL, "前半。", 0, 0)
        assert (first.t_start, first.t_end) == (0.0, pytest.approx(0.95))
        np.testing.assert_array_equal(recognizer.decoded[0], audio[:cut])
        # El resto sigue como comienzo del segmento siguiente.
        (second,) = asr.flush()
        assert (second.text, second.segment_id) == ("後半。", 1)
        assert (second.t_start, second.t_end) == (pytest.approx(0.95), pytest.approx(2.0))
        np.testing.assert_array_equal(recognizer.decoded[1], audio[cut:])

    def test_a_gap_older_than_1_5_seconds_is_ignored(self) -> None:
        asr, recognizer, _ = make_asr(max_segment_s=3.0)
        audio = speech_with_gap(3.0, gap_at_s=0.5)  # fuera de los últimos 1,5 s
        events = feed_asr(asr, audio)
        (event,) = events
        assert event.t_end > 1.5, "el hueco de 0,5 s queda fuera de la ventana"
        assert len(recognizer.decoded[0]) > round(1.5 * CAPTURE_RATE)

    def test_continuous_speech_is_cut_every_max_segment_and_no_audio_is_lost_or_repeated(self) -> None:
        asr, recognizer, _ = make_asr(max_segment_s=3.0)
        audio = voiced(10.0)
        events = feed_asr(asr, audio, t0=7.0) + asr.flush()
        assert len(events) >= 3
        assert [e.segment_id for e in events] == list(range(len(events)))
        np.testing.assert_array_equal(np.concatenate(recognizer.decoded), audio)
        # Los segmentos son contiguos en el reloj de audio y cubren todo el audio.
        assert events[0].t_start == 7.0
        for before, after in zip(events, events[1:], strict=False):
            assert after.t_start == pytest.approx(before.t_end)
        assert events[-1].t_end == pytest.approx(17.0)
        # Ningún segmento supera el máximo de habla continua (con la trama de corte de margen).
        assert all(len(part) <= 3.0 * CAPTURE_RATE for part in recognizer.decoded)

    def test_after_a_cut_the_next_segment_can_still_be_closed_by_flush(self) -> None:
        asr, recognizer, _ = make_asr(max_segment_s=2.0)
        events = feed_asr(asr, voiced(2.5))
        assert len(events) == 1
        (tail,) = asr.flush()
        assert tail.segment_id == 1
        assert tail.t_start == pytest.approx(events[0].t_end)
        assert len(recognizer.decoded) == 2

    def test_a_short_max_segment_still_terminates(self) -> None:
        asr, recognizer, _ = make_asr(max_segment_s=0.5)
        audio = voiced(3.0)
        events = feed_asr(asr, audio) + asr.flush()
        assert events
        np.testing.assert_array_equal(np.concatenate(recognizer.decoded), audio)

    def test_a_cut_in_a_trailing_silence_decodes_the_voice_and_drops_the_silent_rest(self) -> None:
        asr, recognizer, _ = make_asr(max_segment_s=2.0)
        audio = np.concatenate([voiced(0.5), silence(1.5)])
        events = feed_asr(asr, audio) + asr.flush()
        # El corte cae en la cola de silencio: el tramo con voz se decodifica y el resto, mudo, se descarta.
        assert [e.segment_id for e in events] == [0]
        assert len(recognizer.decoded) == 1

    def test_a_failure_while_cutting_drops_the_segment(self) -> None:
        asr, recognizer, _ = make_asr(max_segment_s=1.0)
        recognizer.fail_on_decode = RuntimeError("fallo de sherpa")
        with pytest.raises(EngineError, match="fallo de sherpa"):
            feed_asr(asr, voiced(1.5))
        recognizer.fail_on_decode = None
        assert asr.flush() == []


class TestQuietestCut:
    def test_it_picks_the_center_of_the_quietest_frame(self) -> None:
        audio = voiced(2.0)
        audio[round(1.2 * CAPTURE_RATE) : round(1.22 * CAPTURE_RATE)] = 0.0
        assert quietest_cut(audio) == round(1.2 * CAPTURE_RATE) + 160

    def test_among_equally_quiet_frames_the_latest_wins(self) -> None:
        audio = voiced(2.0)
        audio[round(1.0 * CAPTURE_RATE) : round(1.02 * CAPTURE_RATE)] = 0.0
        audio[round(1.6 * CAPTURE_RATE) : round(1.62 * CAPTURE_RATE)] = 0.0
        assert quietest_cut(audio) == round(1.6 * CAPTURE_RATE) + 160

    def test_the_search_is_limited_to_the_window(self) -> None:
        audio = voiced(4.0)
        audio[round(1.0 * CAPTURE_RATE) : round(1.02 * CAPTURE_RATE)] = 0.0  # fuera de los últimos 1,5 s
        cut = quietest_cut(audio)
        assert cut >= round(2.5 * CAPTURE_RATE)
        assert cut != round(1.0 * CAPTURE_RATE) + 160

    def test_the_cut_is_always_inside_the_audio(self) -> None:
        for n in (2, 100, 639, 640, 641, 4_000):
            assert 1 <= quietest_cut(np.ones(n, dtype=np.float32)) <= n - 1
        assert quietest_cut(np.zeros(32_000, dtype=np.float32)) < 32_000


# --------------------------------------------------------------------------------------------------
# reset(), close() y errores
# --------------------------------------------------------------------------------------------------


class TestLifecycle:
    def test_reset_discards_the_segment_without_events_and_keeps_counting_ids(self) -> None:
        asr, recognizer, _ = make_asr("a。", "b。")
        feed_asr(asr, voiced(1.0))
        asr.reset()
        assert asr.flush() == []
        assert recognizer.streams == []
        events = feed_asr(asr, voiced(1.0), t0=5.0) + asr.flush()
        assert [e.text for e in events] == ["a。"]
        # Tras un FINAL, el id sigue subiendo aunque haya reset.
        asr.reset()
        more = feed_asr(asr, voiced(1.0), t0=9.0) + asr.flush()
        assert [e.segment_id for e in more] == [1]

    def test_close_is_idempotent_and_the_engine_stops_answering(self) -> None:
        asr, _, _ = make_asr()
        feed_asr(asr, voiced(1.0))
        asr.close()
        asr.close()
        assert feed_asr(asr, voiced(8.0)) == []
        assert asr.flush() == []

    def test_a_failure_of_the_recognizer_is_a_recoverable_engine_error_and_drops_the_segment(self) -> None:
        asr, recognizer, _ = make_asr()
        feed_asr(asr, voiced(1.0))
        recognizer.fail_on_decode = RuntimeError("fallo de sherpa")
        with pytest.raises(EngineError, match="fallo de sherpa") as info:
            asr.flush()
        assert info.value.recoverable is True
        assert info.value.engine == "sensevoice-small-ja"
        recognizer.fail_on_decode = None  # con el reconocedor sano, el motor sigue
        assert asr.flush() == []
        events = feed_asr(asr, voiced(1.0), t0=5.0) + asr.flush()
        assert [e.kind for e in events] == [FINAL]


# --------------------------------------------------------------------------------------------------
# Carga del modelo real: create_recognizer
# --------------------------------------------------------------------------------------------------


class TestCreateRecognizer:
    @pytest.mark.parametrize("language", ["ja", "ko"])
    def test_it_asks_sherpa_for_sensevoice_with_the_language_fixed_and_itn(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, language: str
    ) -> None:
        import sherpa_onnx

        for name in MODEL_FILES:
            (tmp_path / name).write_bytes(b"x")
        captured: dict[str, Any] = {}
        sentinel = object()

        def fake_from_sense_voice(**kwargs: Any) -> object:
            captured.update(kwargs)
            return sentinel

        monkeypatch.setattr(sherpa_onnx.OfflineRecognizer, "from_sense_voice", fake_from_sense_voice)
        assert create_recognizer(language, tmp_path) is sentinel
        assert captured == {
            "model": str(tmp_path / "model.int8.onnx"),
            "tokens": str(tmp_path / "tokens.txt"),
            "num_threads": 2,
            "language": language,
            "use_itn": True,
        }

    def test_the_model_files_are_the_two_of_sensevoice(self) -> None:
        assert MODEL_FILES == ("model.int8.onnx", "tokens.txt")

    @pytest.mark.parametrize("language", ["en", "zh", "auto"])
    def test_other_languages_are_refused(self, tmp_path: Path, language: str) -> None:
        with pytest.raises(ValueError, match="ja, ko"):
            create_recognizer(language, tmp_path)

    def test_missing_files_are_a_non_recoverable_error_that_points_to_preparar(self, tmp_path: Path) -> None:
        (tmp_path / "tokens.txt").write_bytes(b"x")
        with pytest.raises(EngineError, match="preparar") as info:
            create_recognizer("ko", tmp_path)
        assert info.value.recoverable is False
        assert info.value.engine == "sensevoice-small-ko"
        assert "model.int8.onnx" in str(info.value)

    def test_a_model_sherpa_cannot_load_is_a_non_recoverable_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import sherpa_onnx

        for name in MODEL_FILES:
            (tmp_path / name).write_bytes(b"x")

        def failing(**_: Any) -> object:
            raise RuntimeError("modelo corrupto")

        monkeypatch.setattr(sherpa_onnx.OfflineRecognizer, "from_sense_voice", failing)
        with pytest.raises(EngineError, match="modelo corrupto") as info:
            create_recognizer("ja", tmp_path)
        assert info.value.recoverable is False

    def test_by_default_it_looks_in_the_models_folder_of_the_app(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("INSTANTTRADUCTOR_HOME", str(tmp_path))
        with pytest.raises(EngineError, match="sensevoice-small") as info:
            create_recognizer("ja")
        assert str(tmp_path / "models" / "sensevoice-small") in str(info.value)
