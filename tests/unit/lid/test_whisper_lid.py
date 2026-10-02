"""Tests de `WhisperLanguageVerifier` (T015) sin modelo: las sesiones de onnxruntime son dobles.

`FakeEncoder` y `FakeDecoder` imitan la interfaz de los ONNX de Whisper de sherpa-onnx: el codificador
trae los metadatos (`all_language_tokens`...) y devuelve claves y valores cruzados; el decodificador
devuelve los logits de todo el vocabulario con los valores que el test fije para cada idioma.
`LanguageVerifierContract` se concreta aquí con ellos; con el modelo real, en
`tests/integration/test_asr_multilang_model.py` (marcador `model`).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from instanttraductor.contracts import (
    CAPTURE_RATE,
    VERIFIER_LANGUAGES,
    EngineError,
    LanguageVerdict,
    LanguageVerifier,
    SourceLanguage,
)
from instanttraductor.lid.whisper_lid import (
    DECODER_FILE,
    ENCODER_FILE,
    MODEL_FILES,
    WhisperLanguageVerifier,
    create_sessions,
    log_mel,
)
from tests.contract.helpers import assert_implements
from tests.contract.test_language_contract import LanguageVerifierContract, tone

# Los 8 primeros idiomas de Whisper y sus tokens (los ids reales empiezan en 50259, `en`).
CODES = ["en", "zh", "de", "es", "ru", "ko", "fr", "ja"]
TOKENS = [50259 + i for i in range(len(CODES))]
SOT = 50258
VOCAB = 50300
N_LAYER, N_STATE = 2, 4

METADATA = {
    "all_language_tokens": ",".join(str(t) for t in TOKENS),
    "all_language_codes": ",".join(CODES),
    "sot": str(SOT),
    "n_text_layer": str(N_LAYER),
    "n_text_state": str(N_STATE),
}


class FakeEncoder:
    def __init__(self, metadata: dict[str, str] | None = None) -> None:
        self.metadata = dict(METADATA if metadata is None else metadata)
        self.calls: list[dict[str, Any]] = []
        self.fail_with: Exception | None = None

    def get_modelmeta(self) -> SimpleNamespace:
        return SimpleNamespace(custom_metadata_map=self.metadata)

    def run(self, output_names: Any, input_feed: dict[str, Any]) -> list[Any]:
        if self.fail_with is not None:
            raise self.fail_with
        self.calls.append(input_feed)
        assert output_names is None
        cross = np.full((N_LAYER, 1, 3, N_STATE), 0.5, dtype=np.float32)
        return [cross, cross + 1]


class FakeDecoder:
    def __init__(self, scores: dict[str, float] | None = None) -> None:
        self.scores = scores if scores is not None else {"en": 5.0}
        self.calls: list[dict[str, Any]] = []
        self.fail_with: Exception | None = None

    def run(self, output_names: Any, input_feed: dict[str, Any]) -> list[Any]:
        if self.fail_with is not None:
            raise self.fail_with
        self.calls.append(input_feed)
        logits = np.full((1, 1, VOCAB), -50.0, dtype=np.float32)
        for code, value in self.scores.items():
            logits[0, -1, TOKENS[CODES.index(code)]] = value
        return [logits]


def make_verifier(
    scores: dict[str, float] | None = None,
) -> tuple[WhisperLanguageVerifier, FakeEncoder, FakeDecoder]:
    encoder, decoder = FakeEncoder(), FakeDecoder(scores)
    return WhisperLanguageVerifier(encoder=encoder, decoder=decoder), encoder, decoder


# --------------------------------------------------------------------------------------------------
# Contrato con sesiones falsas
# --------------------------------------------------------------------------------------------------


class TestWhisperLanguageVerifierContract(LanguageVerifierContract):
    @pytest.fixture
    def verifier(self) -> WhisperLanguageVerifier:
        return make_verifier({"en": 4.0, "es": 1.0})[0]


class TestWhisperLanguageVerifierContractWhenTheChosenLanguageIsNotTheWinner(LanguageVerifierContract):
    @pytest.fixture
    def verifier(self) -> WhisperLanguageVerifier:
        return make_verifier({"es": 3.0, "ja": 1.0})[0]


def test_it_implements_the_protocol() -> None:
    verifier, _, _ = make_verifier()
    assert verifier.name == "whisper-base-lid"
    assert_implements(verifier, LanguageVerifier)


# --------------------------------------------------------------------------------------------------
# La decisión
# --------------------------------------------------------------------------------------------------


class TestDecision:
    @pytest.mark.parametrize("winner", VERIFIER_LANGUAGES)
    def test_the_winner_among_the_five_languages_is_detected(self, winner: str) -> None:
        verifier, _, _ = make_verifier({winner: 6.0, "fr": 0.0})
        verdict = verifier.verify(tone(220.0), CAPTURE_RATE, SourceLanguage.EN)
        assert isinstance(verdict, LanguageVerdict)
        assert verdict.detected == winner
        assert verdict.accepted is (winner == "en")

    @pytest.mark.parametrize("language", list(SourceLanguage))
    def test_it_accepts_only_if_the_chosen_language_wins(self, language: SourceLanguage) -> None:
        verifier, _, _ = make_verifier({"ja": 5.0, "en": 1.0})
        verdict = verifier.verify(tone(220.0), CAPTURE_RATE, language)
        assert verdict.detected == "ja"
        assert verdict.accepted is (language is SourceLanguage.JA)

    def test_spanish_is_rejected_whatever_language_was_chosen(self) -> None:
        verifier, _, _ = make_verifier({"es": 5.0, "en": 4.0, "ja": 2.0})
        for language in SourceLanguage:
            verdict = verifier.verify(tone(220.0), CAPTURE_RATE, language)
            assert (verdict.detected, verdict.accepted) == ("es", False)

    def test_languages_outside_the_five_are_ignored_even_if_they_score_higher(self) -> None:
        # Whisper pondría el alemán y el francés por encima, pero el verificador solo decide entre los cinco.
        verifier, _, _ = make_verifier({"de": 20.0, "fr": 15.0, "ru": 12.0, "ko": 2.0, "en": 1.0})
        verdict = verifier.verify(tone(220.0), CAPTURE_RATE, SourceLanguage.KO)
        assert (verdict.detected, verdict.accepted) == ("ko", True)

    def test_the_probability_is_a_softmax_over_the_five_languages_only(self) -> None:
        scores = {"en": 2.0, "es": 1.0, "ja": 0.0, "zh": -1.0, "ko": -2.0, "de": 30.0}
        verifier, _, _ = make_verifier(scores)
        verdict = verifier.verify(tone(220.0), CAPTURE_RATE, SourceLanguage.EN)
        values = np.array([scores[code] for code in VERIFIER_LANGUAGES])
        expected = float(np.exp(values.max()) / np.exp(values).sum())
        assert verdict.probability == pytest.approx(expected)
        assert 0.0 < verdict.probability < 1.0

    def test_a_clear_winner_has_a_probability_close_to_one(self) -> None:
        verifier, _, _ = make_verifier({"zh": 30.0})
        verdict = verifier.verify(tone(220.0), CAPTURE_RATE, SourceLanguage.ZH)
        assert verdict.probability > 0.999

    def test_elapsed_time_is_measured(self) -> None:
        verifier, _, _ = make_verifier()
        assert verifier.verify(tone(220.0), CAPTURE_RATE, SourceLanguage.EN).elapsed_s > 0.0


# --------------------------------------------------------------------------------------------------
# Qué se entrega a las sesiones
# --------------------------------------------------------------------------------------------------


class TestSessionInputs:
    @pytest.mark.parametrize("seconds", [0.5, 1.0, 3.0, 6.0, 8.0])
    def test_the_encoder_always_gets_a_six_second_log_mel(self, seconds: float) -> None:
        verifier, encoder, _ = make_verifier()
        verifier.verify(tone(220.0, seconds), CAPTURE_RATE, SourceLanguage.EN)
        (call,) = encoder.calls
        assert set(call) == {"mel"}
        assert call["mel"].shape == (1, 80, 600)
        assert call["mel"].dtype == np.float32

    def test_a_short_input_is_padded_with_zeros_on_the_right(self) -> None:
        short = tone(220.0, 1.0)
        padded = np.concatenate([short, np.zeros(5 * CAPTURE_RATE, dtype=np.float32)])
        verifier, encoder, _ = make_verifier()
        verifier.verify(short, CAPTURE_RATE, SourceLanguage.EN)
        verifier.verify(padded, CAPTURE_RATE, SourceLanguage.EN)
        np.testing.assert_array_equal(encoder.calls[0]["mel"], encoder.calls[1]["mel"])

    def test_a_longer_input_keeps_the_last_six_seconds(self) -> None:
        long = np.concatenate([tone(880.0, 2.0), tone(220.0, 6.0)])
        verifier, encoder, _ = make_verifier()
        verifier.verify(long, CAPTURE_RATE, SourceLanguage.EN)
        verifier.verify(tone(220.0, 6.0), CAPTURE_RATE, SourceLanguage.EN)
        np.testing.assert_array_equal(encoder.calls[0]["mel"], encoder.calls[1]["mel"])

    def test_the_decoder_starts_from_the_sot_token_with_an_empty_cache_and_the_encoder_output(self) -> None:
        verifier, encoder, decoder = make_verifier()
        verifier.verify(tone(220.0), CAPTURE_RATE, SourceLanguage.EN)
        (call,) = decoder.calls
        assert set(call) == {
            "tokens",
            "in_n_layer_self_k_cache",
            "in_n_layer_self_v_cache",
            "n_layer_cross_k",
            "n_layer_cross_v",
            "offset",
        }
        np.testing.assert_array_equal(call["tokens"], [[SOT]])
        assert call["tokens"].dtype == np.int64
        np.testing.assert_array_equal(call["offset"], [0])
        for key in ("in_n_layer_self_k_cache", "in_n_layer_self_v_cache"):
            assert call[key].shape == (N_LAYER, 1, 448, N_STATE)
            assert not call[key].any()
        np.testing.assert_array_equal(call["n_layer_cross_k"], 0.5)
        np.testing.assert_array_equal(call["n_layer_cross_v"], 1.5)

    def test_the_input_array_is_not_modified(self) -> None:
        verifier, _, _ = make_verifier()
        audio = tone(220.0, 2.0)
        before = audio.copy()
        verifier.verify(audio, CAPTURE_RATE, SourceLanguage.EN)
        np.testing.assert_array_equal(audio, before)

    def test_only_16_khz_audio_is_accepted(self) -> None:
        verifier, encoder, _ = make_verifier()
        with pytest.raises(ValueError, match="16000"):
            verifier.verify(tone(220.0), 48_000, SourceLanguage.EN)
        assert encoder.calls == []


# --------------------------------------------------------------------------------------------------
# Errores y ciclo de vida
# --------------------------------------------------------------------------------------------------


class TestLifecycleAndErrors:
    @pytest.mark.parametrize("which", ["encoder", "decoder"])
    def test_a_failing_session_is_a_recoverable_engine_error(self, which: str) -> None:
        verifier, encoder, decoder = make_verifier()
        {"encoder": encoder, "decoder": decoder}[which].fail_with = RuntimeError("fallo de onnxruntime")
        with pytest.raises(EngineError, match="fallo de onnxruntime") as info:
            verifier.verify(tone(220.0), CAPTURE_RATE, SourceLanguage.EN)
        assert info.value.recoverable is True
        assert info.value.engine == "whisper-base-lid"
        # El verificador sigue vivo: con la sesión sana, vuelve a decidir.
        encoder.fail_with = decoder.fail_with = None
        assert verifier.verify(tone(220.0), CAPTURE_RATE, SourceLanguage.EN).accepted

    def test_close_is_idempotent_and_verify_fails_afterwards(self) -> None:
        verifier, _, _ = make_verifier()
        verifier.close()
        verifier.close()
        with pytest.raises(EngineError, match="cerrado"):
            verifier.verify(tone(220.0), CAPTURE_RATE, SourceLanguage.EN)

    def test_both_sessions_or_none_must_be_injected(self) -> None:
        with pytest.raises(ValueError, match="a la vez"):
            WhisperLanguageVerifier(encoder=FakeEncoder())
        with pytest.raises(ValueError, match="a la vez"):
            WhisperLanguageVerifier(decoder=FakeDecoder())

    @pytest.mark.parametrize("missing", ["all_language_tokens", "sot", "n_text_layer"])
    def test_a_model_without_the_expected_metadata_is_a_non_recoverable_error(self, missing: str) -> None:
        metadata = {key: value for key, value in METADATA.items() if key != missing}
        with pytest.raises(EngineError, match="metadatos") as info:
            WhisperLanguageVerifier(encoder=FakeEncoder(metadata), decoder=FakeDecoder())
        assert info.value.recoverable is False

    def test_a_model_without_one_of_the_five_languages_is_a_non_recoverable_error(self) -> None:
        metadata = {
            **METADATA,
            "all_language_codes": ",".join(["en", "zh", "de", "es", "ru", "ko", "fr", "pt"]),
        }
        with pytest.raises(EngineError, match="ja"):
            WhisperLanguageVerifier(encoder=FakeEncoder(metadata), decoder=FakeDecoder())


# --------------------------------------------------------------------------------------------------
# log-mel
# --------------------------------------------------------------------------------------------------


class TestLogMel:
    def test_the_shape_follows_the_window(self) -> None:
        assert log_mel(tone(220.0, 2.0)).shape == (80, 600)
        assert log_mel(tone(220.0, 2.0), window_s=30.0).shape == (80, 3000)

    def test_values_are_finite_and_normalized_like_whisper(self) -> None:
        for audio in (tone(220.0, 3.0), np.zeros(CAPTURE_RATE, dtype=np.float32)):
            mel = log_mel(audio)
            assert np.isfinite(mel).all()
            # (log10 + 4) / 4 con un suelo de 8 décadas bajo el máximo: el rango es de 2 unidades.
            assert mel.max() - mel.min() <= 2.0 + 1e-5

    def test_a_low_tone_lights_up_low_bands_and_a_high_tone_high_bands(self) -> None:
        low = log_mel(tone(300.0, 2.0))[:, :150].mean(axis=1)
        high = log_mel(tone(5_000.0, 2.0))[:, :150].mean(axis=1)
        assert int(np.argmax(low)) < 20
        assert int(np.argmax(high)) > 60

    def test_it_does_not_modify_its_input(self) -> None:
        audio = tone(220.0, 2.0)
        before = audio.copy()
        log_mel(audio)
        np.testing.assert_array_equal(audio, before)


# --------------------------------------------------------------------------------------------------
# Carga de las sesiones reales: create_sessions
# --------------------------------------------------------------------------------------------------


class TestCreateSessions:
    def test_the_model_files_are_the_int8_encoder_and_decoder(self) -> None:
        assert MODEL_FILES == ("base-encoder.int8.onnx", "base-decoder.int8.onnx")
        assert (ENCODER_FILE, DECODER_FILE) == MODEL_FILES

    def test_it_opens_both_models_on_the_cpu_with_one_thread(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import onnxruntime

        for name in MODEL_FILES:
            (tmp_path / name).write_bytes(b"x")
        opened: list[tuple[str, Any, list[str]]] = []

        def fake_session(path: str, options: Any, providers: list[str]) -> object:
            opened.append((path, options, providers))
            return object()

        monkeypatch.setattr(onnxruntime, "InferenceSession", fake_session)
        encoder, decoder = create_sessions(tmp_path)
        assert encoder is not decoder
        assert [Path(path).name for path, _, _ in opened] == list(MODEL_FILES)
        for _, options, providers in opened:
            assert providers == ["CPUExecutionProvider"]
            assert options.intra_op_num_threads == 1
            assert options.inter_op_num_threads == 1

    def test_missing_files_are_a_non_recoverable_error_that_points_to_preparar(self, tmp_path: Path) -> None:
        (tmp_path / ENCODER_FILE).write_bytes(b"x")
        with pytest.raises(EngineError, match="preparar") as info:
            create_sessions(tmp_path)
        assert info.value.recoverable is False
        assert DECODER_FILE in str(info.value)
        assert ENCODER_FILE not in str(info.value)

    def test_a_model_onnxruntime_cannot_load_is_a_non_recoverable_error(self, tmp_path: Path) -> None:
        for name in MODEL_FILES:
            (tmp_path / name).write_bytes(b"no es un onnx")
        with pytest.raises(EngineError, match="No se pudo cargar") as info:
            create_sessions(tmp_path)
        assert info.value.recoverable is False

    def test_by_default_it_looks_in_the_models_folder_of_the_app(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("INSTANTTRADUCTOR_HOME", str(tmp_path))
        with pytest.raises(EngineError, match="whisper-base-lid") as info:
            WhisperLanguageVerifier()
        assert str(tmp_path / "models" / "whisper-base-lid") in str(info.value)
