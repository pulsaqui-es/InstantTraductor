"""Tests de `ParakeetJaSegmentAsr` sin modelo: el `OfflineRecognizer` de sherpa es el doble de SenseVoice.

La lógica por segmento (acumular, `flush()`, corte forzado) es la de `SegmentAsr`, ya cubierta en
`test_sensevoice.py`. Aquí: la suite de contrato, la declaración, la limpieza de `<unk>` y la carga.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from instanttraductor.asr.parakeet_ja import MODEL_FILES, ParakeetJaSegmentAsr, clean_text, create_recognizer
from instanttraductor.contracts import AsrCapabilities, AsrEngine, AsrEventKind, AudioChunk, EngineError
from instanttraductor.pipeline.clock import ManualClock
from tests.contract.helpers import assert_implements, voiced
from tests.contract.test_speech_contract import AsrEngineContract
from tests.unit.asr.test_sensevoice import FakeRecognizer


def make_asr(*texts: str) -> tuple[ParakeetJaSegmentAsr, FakeRecognizer]:
    recognizer = FakeRecognizer(*texts, default="テスト")
    return ParakeetJaSegmentAsr(ManualClock(), recognizer=recognizer), recognizer


class TestParakeetJaContract(AsrEngineContract):
    @pytest.fixture
    def make_impl(self) -> Callable[[], AsrEngine]:
        return lambda: make_asr()[0]


class TestDeclaration:
    def test_it_is_a_japanese_per_segment_engine_without_punctuation(self) -> None:
        asr, _ = make_asr()
        assert asr.name == "parakeet-ja"
        assert asr.capabilities == AsrCapabilities(
            native_streaming=False,
            partials=False,
            punctuation=False,
            word_timestamps=False,
            languages=frozenset({"ja"}),
            device="cpu",
            est_vram_mb=0,
        )
        assert asr.max_segment_s == 6.0
        assert_implements(asr, AsrEngine)

    def test_max_segment_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="max_segment_s"):
            ParakeetJaSegmentAsr(ManualClock(), recognizer=FakeRecognizer(), max_segment_s=0.0)


class TestUnknownTokens:
    def test_clean_text_removes_the_unknown_token(self) -> None:
        assert clean_text("<unk>態をさらしてしまって") == "態をさらしてしまって"

    def test_the_final_text_comes_without_unknown_tokens(self) -> None:
        asr, _ = make_asr("<unk>態をさらしてしまってすまない")
        asr.accept(AudioChunk(voiced(1.0), 16000, 0.0))
        (event,) = asr.flush()
        assert event.kind is AsrEventKind.FINAL
        assert event.text == "態をさらしてしまってすまない"
        assert event.language == "ja"

    def test_a_segment_with_only_unknown_tokens_gives_nothing(self) -> None:
        asr, _ = make_asr("<unk><unk>")
        asr.accept(AudioChunk(voiced(1.0), 16000, 0.0))
        assert asr.flush() == []


class TestCreateRecognizer:
    def test_missing_files_are_a_non_recoverable_error_that_points_to_preparar(self, tmp_path: Path) -> None:
        with pytest.raises(EngineError, match="preparar") as info:
            create_recognizer(tmp_path)
        assert info.value.recoverable is False
        for name in MODEL_FILES:
            assert name in str(info.value)

    def test_it_loads_the_ctc_model_with_sherpa(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import sherpa_onnx

        calls: list[dict[str, Any]] = []
        monkeypatch.setattr(
            sherpa_onnx.OfflineRecognizer, "from_nemo_ctc", lambda **kwargs: calls.append(kwargs) or "reco"
        )
        for name in MODEL_FILES:
            (tmp_path / name).write_bytes(b"x")
        assert create_recognizer(tmp_path, num_threads=3) == "reco"
        assert calls == [
            {
                "model": str(tmp_path / "model.int8.onnx"),
                "tokens": str(tmp_path / "tokens.txt"),
                "num_threads": 3,
            }
        ]
