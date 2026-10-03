"""Tests de la fábrica de ASR por idioma (T014) sin modelos: sherpa-onnx se sustituye por dobles."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from instanttraductor.asr import parakeet_ja, sensevoice, xasr_zh
from instanttraductor.asr.factory import MODEL_FOLDERS, create_asr, load_recognizer
from instanttraductor.asr.parakeet_ja import ParakeetJaSegmentAsr
from instanttraductor.asr.sensevoice import SenseVoiceSegmentAsr
from instanttraductor.asr.sherpa_streaming import MODEL_FILES as NEMOTRON_FILES
from instanttraductor.asr.sherpa_streaming import NemotronStreamingAsr
from instanttraductor.asr.xasr_zh import XAsrZhStreaming
from instanttraductor.contracts import AsrEngine, EngineError, SourceLanguage
from instanttraductor.pipeline.clock import ManualClock
from tests.contract.helpers import assert_implements

FILES_BY_FOLDER = {
    "nemotron-en": NEMOTRON_FILES,
    "x-asr-zh": xasr_zh.MODEL_FILES,
    "sensevoice-small": sensevoice.MODEL_FILES,
    "parakeet-ja": parakeet_ja.MODEL_FILES,
}


@pytest.fixture
def models_dir(tmp_path: Path) -> Path:
    """Una carpeta de modelos con los ficheros (vacíos) de los cuatro componentes."""
    for folder, names in FILES_BY_FOLDER.items():
        (tmp_path / folder).mkdir()
        for name in names:
            (tmp_path / folder / name).write_bytes(b"x")
    return tmp_path


@pytest.fixture
def sherpa(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[dict[str, Any]]]:
    """Sustituye las fábricas de sherpa-onnx; anota los argumentos de cada llamada (CTC aparte)."""
    import sherpa_onnx

    calls: dict[str, list[dict[str, Any]]] = {"online": [], "offline": [], "ctc": []}

    class FakeOnline:
        def __init__(self, kwargs: dict[str, Any]) -> None:
            self.kwargs = kwargs

        def create_stream(self) -> None: ...

    class FakeOffline(FakeOnline):
        pass

    def from_transducer(**kwargs: Any) -> FakeOnline:
        calls["online"].append(kwargs)
        return FakeOnline(kwargs)

    def from_sense_voice(**kwargs: Any) -> FakeOffline:
        calls["offline"].append(kwargs)
        return FakeOffline(kwargs)

    def from_nemo_ctc(**kwargs: Any) -> FakeOffline:
        calls["ctc"].append(kwargs)
        return FakeOffline(kwargs)

    monkeypatch.setattr(sherpa_onnx.OnlineRecognizer, "from_transducer", from_transducer)
    monkeypatch.setattr(sherpa_onnx.OfflineRecognizer, "from_nemo_ctc", from_nemo_ctc)
    monkeypatch.setattr(sherpa_onnx.OfflineRecognizer, "from_sense_voice", from_sense_voice)
    return calls


class TestCreateAsr:
    @pytest.mark.parametrize(
        ("language", "engine_class", "name"),
        [
            ("en", NemotronStreamingAsr, "nemotron-streaming-en"),
            ("zh", XAsrZhStreaming, "x-asr-zh-streaming"),
            ("ja", ParakeetJaSegmentAsr, "parakeet-ja"),
            ("ko", SenseVoiceSegmentAsr, "sensevoice-small-ko"),
        ],
    )
    def test_each_language_gets_its_engine(
        self,
        models_dir: Path,
        sherpa: dict[str, list[dict[str, Any]]],
        language: str,
        engine_class: type,
        name: str,
    ) -> None:
        asr = create_asr(language, ManualClock(), models_dir=models_dir)
        assert type(asr) is engine_class
        assert asr.name == name
        assert asr.capabilities.languages == frozenset({language})
        assert_implements(asr, AsrEngine)

    def test_the_language_can_be_a_source_language_or_its_code(
        self, models_dir: Path, sherpa: dict[str, list[dict[str, Any]]]
    ) -> None:
        by_enum = create_asr(SourceLanguage.JA, ManualClock(), models_dir=models_dir)
        by_code = create_asr("ja", ManualClock(), models_dir=models_dir)
        assert by_enum.name == by_code.name == "parakeet-ja"

    def test_the_engines_report_the_expected_streaming_capabilities(
        self, models_dir: Path, sherpa: dict[str, list[dict[str, Any]]]
    ) -> None:
        partials = {
            lang: create_asr(lang, ManualClock(), models_dir=models_dir).capabilities.partials
            for lang in ("en", "zh", "ja", "ko")
        }
        assert partials == {"en": True, "zh": True, "ja": False, "ko": False}

    def test_max_segment_s_reaches_the_per_segment_engines(
        self, models_dir: Path, sherpa: dict[str, list[dict[str, Any]]]
    ) -> None:
        default = create_asr("ja", ManualClock(), models_dir=models_dir)
        custom = create_asr("ko", ManualClock(), models_dir=models_dir, max_segment_s=9.5)
        assert isinstance(default, ParakeetJaSegmentAsr) and default.max_segment_s == 6.0
        assert isinstance(custom, SenseVoiceSegmentAsr) and custom.max_segment_s == 9.5

    def test_an_unknown_language_is_refused(self, models_dir: Path) -> None:
        with pytest.raises(ValueError):
            create_asr("es", ManualClock(), models_dir=models_dir)
        with pytest.raises(ValueError):
            create_asr("auto", ManualClock(), models_dir=models_dir)

    def test_a_preloaded_recognizer_is_used_without_touching_the_models(self, tmp_path: Path) -> None:
        sentinel = object()
        asr = create_asr("zh", ManualClock(), models_dir=tmp_path, recognizer=sentinel)  # tmp_path: vacía
        assert isinstance(asr, XAsrZhStreaming)
        assert asr._recognizer is sentinel
        asr_ja = create_asr("ja", ManualClock(), models_dir=tmp_path, recognizer=sentinel)
        assert isinstance(asr_ja, ParakeetJaSegmentAsr)
        assert asr_ja._recognizer is sentinel

    def test_without_a_preloaded_recognizer_the_model_is_loaded_once_per_engine(
        self, models_dir: Path, sherpa: dict[str, list[dict[str, Any]]]
    ) -> None:
        create_asr("ja", ManualClock(), models_dir=models_dir)
        assert len(sherpa["ctc"]) == 1 and sherpa["online"] == sherpa["offline"] == []

    @pytest.mark.parametrize("language", ["en", "zh", "ja", "ko"])
    def test_missing_models_are_a_non_recoverable_error_that_points_to_preparar(
        self, tmp_path: Path, language: str
    ) -> None:
        with pytest.raises(EngineError, match="preparar") as info:
            create_asr(language, ManualClock(), models_dir=tmp_path)
        assert info.value.recoverable is False
        assert str(tmp_path / MODEL_FOLDERS[SourceLanguage(language)]) in str(info.value)

    def test_by_default_the_models_come_from_the_models_folder_of_the_app(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("INSTANTTRADUCTOR_HOME", str(tmp_path))
        for language, folder in (
            ("en", "nemotron-en"),
            ("zh", "x-asr-zh"),
            ("ja", "parakeet-ja"),
            ("ko", "sensevoice-small"),
        ):
            with pytest.raises(EngineError) as info:
                create_asr(language, ManualClock())
            assert str(tmp_path / "models" / folder) in str(info.value)


class TestLoadRecognizer:
    def test_the_model_folders_are_the_component_ids(self) -> None:
        assert MODEL_FOLDERS == {
            SourceLanguage.EN: "nemotron-en",
            SourceLanguage.ZH: "x-asr-zh",
            SourceLanguage.JA: "parakeet-ja",
            SourceLanguage.KO: "sensevoice-small",
        }

    def test_english_loads_the_nemotron_streaming_transducer(
        self, models_dir: Path, sherpa: dict[str, list[dict[str, Any]]]
    ) -> None:
        load_recognizer("en", models_dir)
        (call,) = sherpa["online"]
        assert call["encoder"] == str(models_dir / "nemotron-en" / "encoder.int8.onnx")
        assert call["feature_dim"] == 128
        assert sherpa["offline"] == []

    def test_chinese_loads_the_x_asr_transducer(
        self, models_dir: Path, sherpa: dict[str, list[dict[str, Any]]]
    ) -> None:
        load_recognizer(SourceLanguage.ZH, models_dir)
        (call,) = sherpa["online"]
        assert call["encoder"] == str(models_dir / "x-asr-zh" / "encoder.int8.onnx")
        assert call["decoder"] == str(models_dir / "x-asr-zh" / "decoder.onnx")
        assert call["modeling_unit"] == "cjkchar+bpe"
        assert sherpa["offline"] == []

    def test_korean_loads_sensevoice_with_its_language_fixed(
        self, models_dir: Path, sherpa: dict[str, list[dict[str, Any]]]
    ) -> None:
        load_recognizer("ko", models_dir)
        (call,) = sherpa["offline"]
        assert call["model"] == str(models_dir / "sensevoice-small" / "model.int8.onnx")
        assert (call["language"], call["use_itn"]) == ("ko", True)
        assert sherpa["online"] == sherpa["ctc"] == []

    def test_japanese_loads_the_parakeet_ctc_model(
        self, models_dir: Path, sherpa: dict[str, list[dict[str, Any]]]
    ) -> None:
        load_recognizer("ja", models_dir)
        (call,) = sherpa["ctc"]
        assert call["model"] == str(models_dir / "parakeet-ja" / "model.int8.onnx")
        assert call["tokens"] == str(models_dir / "parakeet-ja" / "tokens.txt")
        assert sherpa["online"] == sherpa["offline"] == []

    def test_an_unknown_language_is_refused(self, models_dir: Path) -> None:
        with pytest.raises(ValueError):
            load_recognizer("es", models_dir)

    def test_the_loaded_recognizer_goes_into_the_engine(
        self, models_dir: Path, sherpa: dict[str, list[dict[str, Any]]]
    ) -> None:
        recognizer = load_recognizer("ko", models_dir)
        asr = create_asr("ko", ManualClock(), models_dir=models_dir, recognizer=recognizer)
        assert isinstance(asr, SenseVoiceSegmentAsr)
        assert asr._recognizer is recognizer
        assert len(sherpa["offline"]) == 1, "el modelo no se vuelve a cargar"
