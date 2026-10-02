"""Tests de `XAsrZhStreaming` (T012) sin modelo: el `OnlineRecognizer` de sherpa es un doble.

`FakeRecognizer` imita el ritmo de X-ASR: decodifica un trozo de 960 ms cada vez y descubre unos símbolos del
guion de su *stream* por trozo, pero solo si ha oído algo (el silencio digital no produce texto). Al vaciar
(`input_finished`), el resto del guion sale de golpe. Cada `create_stream()` toma el guion siguiente.

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

from instanttraductor.asr.xasr_zh import (
    CHUNK_S,
    MODEL_FILES,
    TAIL_PADDING_S,
    XAsrZhStreaming,
    create_recognizer,
    stable_length,
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

CHUNK_SAMPLES = round(CHUNK_S * CAPTURE_RATE)  # 15 360 muestras: un trozo del modelo
PARTIAL = AsrEventKind.PARTIAL
FINAL = AsrEventKind.FINAL

SCRIPT_ONE = ["今天", "天气", "很好，", "我们", "去公园。"]
SCRIPT_TWO = ["你好吗？"]


class FakeStream:
    def __init__(self, symbols: list[str]) -> None:
        self.symbols = symbols
        self.received = 0  # muestras recibidas
        self.decoded = 0  # muestras ya decodificadas
        self.visible = 0  # símbolos del guion que ya se ven en el resultado
        self.heard = False  # ha llegado algo que no es silencio
        self.finished = 0  # veces que se llamó a `input_finished`
        self.waveforms: list[tuple[float, Samples]] = []

    def accept_waveform(self, sample_rate: float, waveform: Samples) -> None:
        self.waveforms.append((sample_rate, np.array(waveform, copy=True)))
        self.received += len(waveform)
        if len(waveform) and float(np.max(np.abs(waveform))) > 1e-3:
            self.heard = True

    def input_finished(self) -> None:
        self.finished += 1


class FakeRecognizer:
    """Doble de `sherpa_onnx.OnlineRecognizer`: cada *stream* transcribe el siguiente guion."""

    def __init__(self, *scripts: list[str], per_chunk: int = 2) -> None:
        self._scripts = list(scripts)
        self._per_chunk = per_chunk
        self.streams: list[FakeStream] = []
        self.fail_on_decode: Exception | None = None

    def create_stream(self) -> FakeStream:
        script = self._scripts[len(self.streams)] if len(self.streams) < len(self._scripts) else []
        stream = FakeStream(script)
        self.streams.append(stream)
        return stream

    def is_ready(self, stream: FakeStream) -> bool:
        pending = stream.received - stream.decoded
        return pending >= CHUNK_SAMPLES or (stream.finished > 0 and pending > 0)

    def decode_stream(self, stream: FakeStream) -> None:
        if self.fail_on_decode is not None:
            raise self.fail_on_decode
        stream.decoded = min(stream.received, stream.decoded + CHUNK_SAMPLES)
        if stream.heard:
            stream.visible = min(len(stream.symbols), stream.visible + self._per_chunk)
            if stream.finished and stream.decoded >= stream.received:
                stream.visible = len(stream.symbols)

    def get_result_all(self, stream: FakeStream) -> SimpleNamespace:
        return SimpleNamespace(text="".join(stream.symbols[: stream.visible]))


def make_asr(
    *scripts: list[str], clock: ManualClock | None = None, per_chunk: int = 2
) -> tuple[XAsrZhStreaming, FakeRecognizer, ManualClock]:
    recognizer = FakeRecognizer(*(scripts or (SCRIPT_ONE, SCRIPT_TWO)), per_chunk=per_chunk)
    clock = clock if clock is not None else ManualClock()
    return XAsrZhStreaming(clock, recognizer=recognizer), recognizer, clock


# --------------------------------------------------------------------------------------------------
# Suite de contrato con el doble
# --------------------------------------------------------------------------------------------------


class TestXAsrZhContract(AsrEngineContract):
    @pytest.fixture
    def make_impl(self) -> Callable[[], AsrEngine]:
        return lambda: make_asr()[0]


# --------------------------------------------------------------------------------------------------
# Declaración y parciales
# --------------------------------------------------------------------------------------------------


class TestPartials:
    def test_it_declares_what_task_t012_asks_for(self) -> None:
        asr, _, _ = make_asr()
        assert asr.name == "x-asr-zh-streaming"
        assert asr.capabilities == AsrCapabilities(
            native_streaming=True,
            partials=True,
            punctuation=True,
            word_timestamps=False,
            languages=frozenset({"zh"}),
            device="cpu",
            est_vram_mb=0,
        )
        assert_implements(asr, AsrEngine)

    def test_the_chunk_is_960_ms(self) -> None:
        assert CHUNK_S == 0.96
        assert TAIL_PADDING_S == CHUNK_S

    def test_there_are_no_events_until_the_model_decodes_a_whole_chunk(self) -> None:
        asr, _, _ = make_asr()
        assert feed_asr(asr, voiced(0.94)) == []  # 47 chunks de 20 ms: falta uno para los 960 ms

    def test_partials_grow_by_one_revision_and_stay_in_one_segment(self) -> None:
        asr, _, _ = make_asr()
        events = feed_asr(asr, voiced(3.0))
        assert [e.kind for e in events] == [PARTIAL] * len(events)
        assert [e.revision for e in events] == [0, 1, 2]
        assert {e.segment_id for e in events} == {0}
        assert [e.text for e in events] == ["今天天气", "今天天气很好，我们", "今天天气很好，我们去公园。"]

    def test_chinese_text_is_all_stable_but_a_trailing_latin_word(self) -> None:
        asr, _, _ = make_asr(["我用", "iPh", "one"], per_chunk=1)
        events = feed_asr(asr, voiced(3.0))
        assert [(e.text, e.text[: e.stable_len]) for e in events] == [
            ("我用", "我用"),
            ("我用iPh", "我用"),
            ("我用iPhone", "我用"),
        ]

    def test_stable_len_never_decreases(self) -> None:
        asr, _, _ = make_asr()
        stable = [e.stable_len for e in feed_asr(asr, voiced(4.5))]
        assert stable == sorted(stable)

    def test_a_partial_is_only_emitted_when_the_text_changes(self) -> None:
        asr, recognizer, _ = make_asr(["你好"], per_chunk=2)
        events = feed_asr(asr, voiced(3.0))  # tres decodificaciones; el texto cambia en la primera
        assert [e.text for e in events] == ["你好"]
        assert sum(stream.decoded // CHUNK_SAMPLES for stream in recognizer.streams) == 3

    def test_times_are_in_the_audio_clock(self) -> None:
        asr, _, _ = make_asr()
        events = [e for chunk in to_chunks(voiced(2.0), t0=12.0) for e in asr.accept(chunk)]
        first, second = events
        assert first.t_start == second.t_start == 12.0
        assert first.t_end == pytest.approx(12.0 + 0.96)
        assert second.t_end == pytest.approx(12.0 + 1.92)

    def test_emitted_at_is_read_from_the_clock(self) -> None:
        asr, _, clock = make_asr()
        emitted: list[AsrEvent] = []
        for chunk in to_chunks(voiced(2.0)):
            clock.set(100.0 + chunk.t_end)
            emitted.extend(asr.accept(chunk))
        assert [e.emitted_at for e in emitted] == pytest.approx([100.96, 101.92])

    def test_the_language_is_chinese_and_there_are_no_word_times(self) -> None:
        asr, _, _ = make_asr()
        events = feed_asr(asr, voiced(1.0)) + asr.flush()
        assert {e.language for e in events} == {"zh"}
        assert all(e.words == () for e in events)

    def test_audio_goes_to_the_recognizer_at_16_khz_without_changes(self) -> None:
        asr, recognizer, _ = make_asr()
        audio = voiced(0.1)
        for chunk in to_chunks(audio):
            asr.accept(chunk)
        (stream,) = recognizer.streams
        assert {rate for rate, _ in stream.waveforms} == {16_000}
        np.testing.assert_array_equal(np.concatenate([w for _, w in stream.waveforms]), audio)

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("今天天气很好。", True),
            ("你好吗？", True),
            ("太好了！", True),
            ("It works.", True),
            ("他说“好。”", True),  # las comillas de cierre no cuentan
            ("今天天气很好，", False),
            ("今天", False),
        ],
    )
    def test_sentence_end_follows_the_final_punctuation(self, text: str, expected: bool) -> None:
        asr, _, _ = make_asr([text], per_chunk=1)
        (event, *_) = feed_asr(asr, voiced(1.0))
        assert event.text == text
        assert event.is_sentence_end is expected


# --------------------------------------------------------------------------------------------------
# flush(): un segmento por tramo
# --------------------------------------------------------------------------------------------------


class TestFlush:
    def test_flush_emits_a_final_with_all_the_text_stable(self) -> None:
        asr, _, _ = make_asr()
        partials = feed_asr(asr, voiced(1.0))
        (final,) = asr.flush()
        assert final.kind is FINAL
        assert final.text == "".join(SCRIPT_ONE), "el vaciado saca el resto del texto"
        assert final.stable_len == len(final.text)
        assert final.is_sentence_end
        assert final.segment_id == partials[-1].segment_id
        assert final.revision == partials[-1].revision + 1
        assert final.t_start == partials[0].t_start

    def test_the_final_ends_where_the_audio_fed_ends_not_at_the_padding(self) -> None:
        asr, _, _ = make_asr()
        feed_asr(asr, voiced(1.0), t0=3.0)
        (final,) = asr.flush()
        assert final.t_end == pytest.approx(3.0 + 1.0)

    def test_flush_pads_with_one_chunk_of_zeros_and_then_signals_the_end_of_the_input(self) -> None:
        asr, recognizer, _ = make_asr()
        feed_asr(asr, voiced(1.0))
        asr.flush()
        (stream,) = recognizer.streams
        rate, padding = stream.waveforms[-1]
        assert rate == 16_000
        assert len(padding) == round(TAIL_PADDING_S * CAPTURE_RATE) == CHUNK_SAMPLES
        assert not padding.any()
        assert stream.finished == 1

    def test_flush_gives_a_final_even_if_there_was_no_partial(self) -> None:
        asr, _, _ = make_asr()
        assert feed_asr(asr, voiced(0.3)) == []  # menos de un trozo: el modelo aún no ha dicho nada
        (final,) = asr.flush()
        assert (final.kind, final.revision, final.segment_id) == (FINAL, 0, 0)
        assert final.text == "".join(SCRIPT_ONE)

    def test_flush_without_audio_returns_nothing(self) -> None:
        asr, recognizer, _ = make_asr()
        assert asr.flush() == []
        assert recognizer.streams == []

    def test_flush_with_silence_only_returns_nothing_and_does_not_use_up_a_segment_id(self) -> None:
        asr, _, _ = make_asr()
        assert feed_asr(asr, silence(1.0)) == []
        assert asr.flush() == []
        events = feed_asr(asr, voiced(1.0), t0=1.0) + asr.flush()
        assert {e.segment_id for e in events} == {0}

    def test_a_second_flush_has_nothing_left_to_close(self) -> None:
        asr, _, _ = make_asr()
        feed_asr(asr, voiced(1.0))
        assert len(asr.flush()) == 1
        assert asr.flush() == []

    def test_every_segment_gets_a_new_stream_and_a_new_id(self) -> None:
        asr, recognizer, _ = make_asr()
        first = feed_asr(asr, voiced(1.0)) + asr.flush()
        second = feed_asr(asr, voiced(1.0), t0=5.0) + asr.flush()
        assert len(recognizer.streams) == 2
        assert {e.segment_id for e in first} == {0}
        assert {e.segment_id for e in second} == {1}
        assert second[0].revision == 0, "la revisión empieza de nuevo en cada segmento"
        assert second[0].t_start == 5.0
        assert second[-1].text == "".join(SCRIPT_TWO), "el segundo segmento no arrastra el texto del primero"

    def test_flush_keeps_the_last_partial_if_the_recognizer_returns_no_text(self) -> None:
        asr, recognizer, _ = make_asr()
        feed_asr(asr, voiced(1.0))
        (stream,) = recognizer.streams
        stream.symbols = []  # si pasara, no se pierde lo ya dicho
        (final,) = asr.flush()
        assert final.text == "今天天气"


# --------------------------------------------------------------------------------------------------
# reset(), close() y errores
# --------------------------------------------------------------------------------------------------


class TestLifecycle:
    def test_reset_discards_the_segment_without_events_and_keeps_counting_ids(self) -> None:
        asr, recognizer, _ = make_asr()
        feed_asr(asr, voiced(1.0))
        asr.reset()
        assert asr.flush() == []
        events = feed_asr(asr, voiced(1.0), t0=5.0) + asr.flush()
        assert len(recognizer.streams) == 2
        assert {e.segment_id for e in events} == {1}

    def test_close_is_idempotent_and_the_engine_stops_answering(self) -> None:
        asr, _, _ = make_asr()
        feed_asr(asr, voiced(1.0))
        asr.close()
        asr.close()
        assert feed_asr(asr, voiced(1.0)) == []
        assert asr.flush() == []

    def test_a_chunk_that_is_not_16_khz_is_rejected(self) -> None:
        asr, _, _ = make_asr()
        with pytest.raises(ValueError, match="16000"):
            asr.accept(AudioChunk(np.zeros(480, dtype=np.float32), 48_000, 0.0))

    def test_empty_chunks_are_ignored(self) -> None:
        asr, recognizer, _ = make_asr()
        assert asr.accept(AudioChunk(np.zeros(0, dtype=np.float32), CAPTURE_RATE, 0.0)) == []
        assert recognizer.streams == []

    def test_a_failure_of_the_recognizer_is_a_recoverable_engine_error_and_drops_the_segment(self) -> None:
        asr, recognizer, _ = make_asr()
        recognizer.fail_on_decode = RuntimeError("fallo de sherpa")
        with pytest.raises(EngineError, match="fallo de sherpa") as info:
            feed_asr(asr, voiced(1.2))
        assert info.value.recoverable is True
        assert info.value.engine == "x-asr-zh-streaming"
        recognizer.fail_on_decode = None  # con el reconocedor sano, el motor sigue
        events = feed_asr(asr, voiced(1.2), t0=5.0) + asr.flush()
        assert events and events[-1].kind is FINAL

    def test_a_failure_while_flushing_is_a_recoverable_engine_error(self) -> None:
        asr, recognizer, _ = make_asr()
        feed_asr(asr, voiced(0.3))
        recognizer.fail_on_decode = RuntimeError("fallo al vaciar")
        with pytest.raises(EngineError, match="fallo al vaciar"):
            asr.flush()
        assert asr.flush() == []


# --------------------------------------------------------------------------------------------------
# stable_length
# --------------------------------------------------------------------------------------------------


class TestStableLength:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("", 0),
            ("你好", 2),
            ("你好，", 3),
            ("我用iPh", 2),
            ("我用 iPhone", 2),
            ("hello", 0),
            ("hello wor", 5),
            ("你好。hello", 3),
            ("你好 hello world, how", 15),
        ],
    )
    def test_everything_but_a_trailing_latin_word(self, text: str, expected: int) -> None:
        assert stable_length(text) == expected


# --------------------------------------------------------------------------------------------------
# Carga del modelo real: create_recognizer
# --------------------------------------------------------------------------------------------------


class TestCreateRecognizer:
    def test_it_asks_sherpa_for_the_zh_en_streaming_transducer(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import sherpa_onnx

        for name in MODEL_FILES:
            (tmp_path / name).write_bytes(b"x")
        captured: dict[str, Any] = {}
        sentinel = object()

        def fake_from_transducer(**kwargs: Any) -> object:
            captured.update(kwargs)
            return sentinel

        monkeypatch.setattr(sherpa_onnx.OnlineRecognizer, "from_transducer", fake_from_transducer)
        assert create_recognizer(tmp_path) is sentinel
        assert captured["tokens"] == str(tmp_path / "tokens.txt")
        assert captured["encoder"] == str(tmp_path / "encoder.int8.onnx")
        assert captured["decoder"] == str(tmp_path / "decoder.onnx")
        assert captured["joiner"] == str(tmp_path / "joiner.int8.onnx")
        assert captured["modeling_unit"] == "cjkchar+bpe"
        assert captured["bpe_vocab"] == str(tmp_path / "bpe.model")
        assert captured["num_threads"] == 2
        assert captured["enable_endpoint_detection"] is False

    def test_missing_files_are_a_non_recoverable_error_that_points_to_preparar(self, tmp_path: Path) -> None:
        (tmp_path / "tokens.txt").write_bytes(b"x")
        with pytest.raises(EngineError, match="preparar") as info:
            create_recognizer(tmp_path)
        assert info.value.recoverable is False
        assert info.value.engine == "x-asr-zh-streaming"
        assert "encoder.int8.onnx" in str(info.value)
        assert "tokens.txt" not in str(info.value)

    def test_a_model_sherpa_cannot_load_is_a_non_recoverable_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import sherpa_onnx

        for name in MODEL_FILES:
            (tmp_path / name).write_bytes(b"x")

        def failing(**_: Any) -> object:
            raise RuntimeError("modelo corrupto")

        monkeypatch.setattr(sherpa_onnx.OnlineRecognizer, "from_transducer", failing)
        with pytest.raises(EngineError, match="modelo corrupto") as info:
            create_recognizer(tmp_path)
        assert info.value.recoverable is False

    def test_by_default_it_looks_in_the_models_folder_of_the_app(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("INSTANTTRADUCTOR_HOME", str(tmp_path))
        with pytest.raises(EngineError, match="x-asr-zh") as info:
            create_recognizer()
        assert str(tmp_path / "models" / "x-asr-zh") in str(info.value)
