"""Tests de `NemotronStreamingAsr` (T019) sin modelo: el `OnlineRecognizer` de sherpa es un doble.

`FakeRecognizer` imita el ritmo de Nemotron: decodifica un trozo de 560 ms cada vez y descubre unas palabras
del guion de su *stream* por trozo, pero solo si ha oído algo (el silencio digital no produce texto). Al
vaciar (`input_finished`), el resto del guion sale de golpe. Cada `create_stream()` toma el guion siguiente.

La suite `AsrEngineContract` se concreta aquí con ese doble; con el modelo real, en
`tests/integration/test_nemotron_model.py` (marcador `model`).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

from instanttraductor.asr.sherpa_streaming import (
    CHUNK_S,
    TAIL_PADDING_S,
    NemotronStreamingAsr,
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

CHUNK_SAMPLES = round(CHUNK_S * CAPTURE_RATE)  # 8 960 muestras: un trozo del modelo
PARTIAL = AsrEventKind.PARTIAL
FINAL = AsrEventKind.FINAL


class FakeStream:
    def __init__(self, words: list[str]) -> None:
        self.words = words
        self.received = 0  # muestras recibidas
        self.decoded = 0  # muestras ya decodificadas
        self.visible = 0  # palabras del guion que ya se ven en el resultado
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

    def __init__(self, *scripts: str, words_per_chunk: int = 2) -> None:
        self._scripts = list(scripts)
        self._words_per_chunk = words_per_chunk
        self.streams: list[FakeStream] = []
        self.fail_on_decode: Exception | None = None

    def create_stream(self) -> FakeStream:
        script = self._scripts[len(self.streams)] if len(self.streams) < len(self._scripts) else ""
        stream = FakeStream(script.split())
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
            stream.visible = min(len(stream.words), stream.visible + self._words_per_chunk)
            if stream.finished and stream.decoded >= stream.received:
                stream.visible = len(stream.words)

    def get_result_all(self, stream: FakeStream) -> SimpleNamespace:
        return SimpleNamespace(text=" ".join(stream.words[: stream.visible]))


SCRIPT_ONE = "hello there my friend how are you today"
SCRIPT_TWO = "I am doing fine thanks for asking"


def make_asr(
    *scripts: str, clock: ManualClock | None = None, words_per_chunk: int = 2
) -> tuple[NemotronStreamingAsr, FakeRecognizer, ManualClock]:
    recognizer = FakeRecognizer(*(scripts or (SCRIPT_ONE, SCRIPT_TWO)), words_per_chunk=words_per_chunk)
    clock = clock if clock is not None else ManualClock()
    return NemotronStreamingAsr(clock, recognizer=recognizer), recognizer, clock


# --------------------------------------------------------------------------------------------------
# Suite de contrato con el doble
# --------------------------------------------------------------------------------------------------


class TestNemotronStreamingAsrContract(AsrEngineContract):
    @pytest.fixture
    def make_impl(self) -> Callable[[], AsrEngine]:
        return lambda: make_asr()[0]


# --------------------------------------------------------------------------------------------------
# Eventos parciales
# --------------------------------------------------------------------------------------------------


class TestPartials:
    def test_it_declares_what_task_t019_asks_for(self) -> None:
        asr, _, _ = make_asr()
        assert asr.name == "nemotron-streaming-en"
        assert asr.capabilities == AsrCapabilities(
            native_streaming=True,
            partials=True,
            punctuation=True,
            word_timestamps=False,
            languages=frozenset({"en"}),
            device="cpu",
            est_vram_mb=0,
        )
        assert_implements(asr, AsrEngine)

    def test_there_are_no_events_until_the_model_decodes_a_whole_chunk(self) -> None:
        asr, _, _ = make_asr()
        # 27 chunks de 20 ms son 540 ms: todavía no hay un trozo de 560 ms.
        assert feed_asr(asr, voiced(0.54)) == []

    def test_partials_grow_by_one_revision_and_stay_in_one_segment(self) -> None:
        asr, _, _ = make_asr()
        events = feed_asr(asr, voiced(2.4))
        assert [e.kind for e in events] == [PARTIAL] * len(events)
        assert len(events) == 4  # 2,4 s son cuatro trozos de 560 ms
        assert [e.revision for e in events] == [0, 1, 2, 3]
        assert {e.segment_id for e in events} == {0}
        texts = [e.text for e in events]
        assert texts == ["hello there", "hello there my friend", "hello there my friend how are", SCRIPT_ONE]

    def test_stable_len_reaches_the_last_complete_word(self) -> None:
        asr, _, _ = make_asr()
        events = feed_asr(asr, voiced(2.4))
        for event in events:
            stable = event.text[: event.stable_len]
            # Todas las palabras menos la última, que puede estar a medias.
            assert event.text.split()[:-1] == stable.split()
        assert [e.stable_len for e in events] == [5, 14, 25, 33]

    def test_a_single_word_has_nothing_stable_yet(self) -> None:
        asr, _, _ = make_asr("hello", words_per_chunk=1)
        (event,) = feed_asr(asr, voiced(0.6))
        assert (event.text, event.stable_len) == ("hello", 0)

    def test_stable_len_never_decreases(self) -> None:
        asr, _, _ = make_asr()
        stable = [e.stable_len for e in feed_asr(asr, voiced(4.5))]
        assert stable == sorted(stable)

    def test_a_partial_is_only_emitted_when_the_text_changes(self) -> None:
        asr, recognizer, _ = make_asr("hello there", words_per_chunk=1)
        events = feed_asr(asr, voiced(2.4))  # cuatro decodificaciones; el texto cambia en las dos primeras
        assert [e.text for e in events] == ["hello", "hello there"]
        assert sum(stream.decoded // CHUNK_SAMPLES for stream in recognizer.streams) == 4

    def test_times_are_in_the_audio_clock(self) -> None:
        asr, _, _ = make_asr()
        chunks = to_chunks(voiced(1.2), t0=12.0)
        events = [e for chunk in chunks for e in asr.accept(chunk)]
        first, second = events
        assert first.t_start == second.t_start == 12.0
        # El trozo de 560 ms se completa con el chunk 28 (28 · 20 ms) y el de 1 120 ms con el 56.
        assert first.t_end == pytest.approx(12.0 + 0.56)
        assert second.t_end == pytest.approx(12.0 + 1.12)

    def test_emitted_at_is_read_from_the_clock(self) -> None:
        asr, _, clock = make_asr()
        emitted: list[AsrEvent] = []
        for chunk in to_chunks(voiced(1.2)):
            clock.set(100.0 + chunk.t_end)
            emitted.extend(asr.accept(chunk))
        assert [e.emitted_at for e in emitted] == pytest.approx([100.56, 101.12])

    def test_the_language_is_english_and_there_are_no_word_times(self) -> None:
        asr, _, _ = make_asr()
        (event, *_) = feed_asr(asr, voiced(0.6))
        assert event.language == "en"
        assert event.words == ()

    def test_audio_goes_to_the_recognizer_at_16_khz_without_changes(self) -> None:
        asr, recognizer, _ = make_asr()
        audio = voiced(0.1)
        for chunk in to_chunks(audio):
            asr.accept(chunk)
        (stream,) = recognizer.streams
        assert {rate for rate, _ in stream.waveforms} == {16_000}
        np.testing.assert_array_equal(np.concatenate([w for _, w in stream.waveforms]), audio)

    def test_sentence_end_follows_the_final_punctuation(self) -> None:
        asr, _, _ = make_asr("hello there. how are you?", words_per_chunk=2)
        events = feed_asr(asr, voiced(2.4)) + asr.flush()
        assert [(e.text, e.is_sentence_end) for e in events] == [
            ("hello there.", True),
            ("hello there. how are", False),
            ("hello there. how are you?", True),
            ("hello there. how are you?", True),
        ]


# --------------------------------------------------------------------------------------------------
# flush(): un segmento por tramo
# --------------------------------------------------------------------------------------------------


class TestFlush:
    def test_flush_emits_a_final_with_all_the_text_stable(self) -> None:
        asr, _, _ = make_asr()
        partials = feed_asr(asr, voiced(1.2))
        (final,) = asr.flush()
        assert final.kind is FINAL
        assert final.text == SCRIPT_ONE, "el vaciado saca el resto del texto"
        assert final.stable_len == len(final.text)
        assert final.segment_id == partials[-1].segment_id
        assert final.revision == partials[-1].revision + 1
        assert final.t_start == partials[0].t_start

    def test_the_final_ends_where_the_audio_fed_ends_not_at_the_padding(self) -> None:
        asr, _, _ = make_asr()
        feed_asr(asr, voiced(1.2), t0=3.0)
        (final,) = asr.flush()
        assert final.t_end == pytest.approx(3.0 + 1.2)

    def test_flush_pads_with_one_chunk_of_zeros_and_then_signals_the_end_of_the_input(self) -> None:
        asr, recognizer, _ = make_asr()
        feed_asr(asr, voiced(1.2))
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
        assert final.text == SCRIPT_ONE

    def test_flush_without_audio_returns_nothing(self) -> None:
        asr, recognizer, _ = make_asr()
        assert asr.flush() == []
        assert recognizer.streams == []

    def test_flush_with_silence_only_returns_nothing_and_does_not_use_up_a_segment_id(self) -> None:
        asr, _, _ = make_asr()
        assert feed_asr(asr, silence(1.0)) == []
        assert asr.flush() == []
        events = feed_asr(asr, voiced(1.2), t0=1.0) + asr.flush()
        assert {e.segment_id for e in events} == {0}

    def test_a_second_flush_has_nothing_left_to_close(self) -> None:
        asr, _, _ = make_asr()
        feed_asr(asr, voiced(1.2))
        assert len(asr.flush()) == 1
        assert asr.flush() == []

    def test_every_segment_gets_a_new_stream_and_a_new_id(self) -> None:
        asr, recognizer, _ = make_asr()
        first = feed_asr(asr, voiced(1.2)) + asr.flush()
        second = feed_asr(asr, voiced(1.2), t0=5.0) + asr.flush()
        assert len(recognizer.streams) == 2
        assert {e.segment_id for e in first} == {0}
        assert {e.segment_id for e in second} == {1}
        assert second[0].revision == 0, "la revisión empieza de nuevo en cada segmento"
        assert second[0].t_start == 5.0
        assert second[-1].text == SCRIPT_TWO, "el segundo segmento no arrastra el texto del primero"
        assert recognizer.streams[0] is not recognizer.streams[1]

    def test_flush_keeps_the_last_partial_if_the_recognizer_returns_no_text(self) -> None:
        asr, recognizer, _ = make_asr()
        feed_asr(asr, voiced(1.2))
        (stream,) = recognizer.streams
        stream.words = []  # no ocurre con Nemotron; si pasara, no se pierde lo ya dicho
        (final,) = asr.flush()
        assert final.text == "hello there my friend"


# --------------------------------------------------------------------------------------------------
# reset(), close() y errores
# --------------------------------------------------------------------------------------------------


class TestLifecycle:
    def test_reset_discards_the_segment_without_events_and_keeps_counting_ids(self) -> None:
        asr, recognizer, _ = make_asr()
        feed_asr(asr, voiced(1.2))
        asr.reset()
        assert asr.flush() == []
        events = feed_asr(asr, voiced(1.2), t0=5.0) + asr.flush()
        assert len(recognizer.streams) == 2
        assert {e.segment_id for e in events} == {1}

    def test_close_is_idempotent_and_the_engine_stops_answering(self) -> None:
        asr, _, _ = make_asr()
        feed_asr(asr, voiced(1.2))
        asr.close()
        asr.close()
        assert feed_asr(asr, voiced(1.2)) == []
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
        assert info.value.engine == "nemotron-streaming-en"
        # El segmento roto se descarta: con el reconocedor sano, el motor sigue.
        recognizer.fail_on_decode = None
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
            ("hello", 0),
            ("hello wor", 5),
            ("hello world", 5),
            ("hello world, how", 12),
            ("a b c", 3),
            ("It's", 0),
        ],
    )
    def test_everything_but_the_last_word(self, text: str, expected: int) -> None:
        assert stable_length(text) == expected
        assert text[: stable_length(text)] == " ".join(text.split()[:-1])


# --------------------------------------------------------------------------------------------------
# Carga del modelo real: create_recognizer
# --------------------------------------------------------------------------------------------------

MODEL_FILES = ("tokens.txt", "encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx")


class TestCreateRecognizer:
    def test_it_asks_sherpa_for_the_streaming_transducer_with_the_r5_settings(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import sherpa_onnx

        for name in MODEL_FILES:
            (tmp_path / name).write_bytes(b"x")
        captured: dict[str, Any] = {}

        def from_transducer(cls: Any, **kwargs: Any) -> str:
            captured.update(kwargs)
            return "recognizer"

        monkeypatch.setattr(sherpa_onnx.OnlineRecognizer, "from_transducer", classmethod(from_transducer))
        assert create_recognizer(tmp_path) == "recognizer"
        assert captured == {
            "tokens": str(tmp_path / "tokens.txt"),
            "encoder": str(tmp_path / "encoder.int8.onnx"),
            "decoder": str(tmp_path / "decoder.int8.onnx"),
            "joiner": str(tmp_path / "joiner.int8.onnx"),
            "num_threads": 2,
            "sample_rate": 16_000,
            "feature_dim": 128,
            "decoding_method": "greedy_search",
            "blank_penalty": 1.0,
            "enable_endpoint_detection": False,
        }

    def test_the_model_comes_from_the_nemotron_component_by_default(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import sherpa_onnx

        monkeypatch.setenv("INSTANTTRADUCTOR_HOME", str(tmp_path))
        model_dir = tmp_path / "models" / "nemotron-en"
        model_dir.mkdir(parents=True)
        for name in MODEL_FILES:
            (model_dir / name).write_bytes(b"x")
        captured: dict[str, Any] = {}

        def from_transducer(cls: Any, **kwargs: Any) -> str:
            captured.update(kwargs)
            return "recognizer"

        monkeypatch.setattr(sherpa_onnx.OnlineRecognizer, "from_transducer", classmethod(from_transducer))
        create_recognizer()
        assert captured["tokens"] == str(model_dir / "tokens.txt")

    def test_missing_files_are_a_non_recoverable_engine_error_that_names_them(self, tmp_path: Path) -> None:
        (tmp_path / "tokens.txt").write_bytes(b"x")
        with pytest.raises(EngineError) as info:
            create_recognizer(tmp_path)
        assert info.value.recoverable is False
        assert info.value.engine == "nemotron-streaming-en"
        message = str(info.value)
        assert "encoder.int8.onnx" in message and "joiner.int8.onnx" in message
        assert "tokens.txt" not in message, "solo se nombran los que faltan"
        assert "preparar" in message

    def test_the_engine_without_a_recognizer_needs_the_model_on_disk(self) -> None:
        # La carpeta de datos de los tests es temporal y está vacía: no hay modelo.
        with pytest.raises(EngineError) as info:
            NemotronStreamingAsr(ManualClock())
        assert info.value.recoverable is False

    def test_sherpa_failing_to_load_is_a_non_recoverable_engine_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import sherpa_onnx

        for name in MODEL_FILES:
            (tmp_path / name).write_bytes(b"x")

        def from_transducer(cls: Any, **kwargs: Any) -> None:
            raise RuntimeError("modelo ilegible")

        monkeypatch.setattr(sherpa_onnx.OnlineRecognizer, "from_transducer", classmethod(from_transducer))
        with pytest.raises(EngineError, match="modelo ilegible") as info:
            create_recognizer(tmp_path)
        assert info.value.recoverable is False
