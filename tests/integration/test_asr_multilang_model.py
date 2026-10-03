"""Reconocedores por idioma y verificador de idioma con los modelos reales (T016).

Marcador `model`: solo lo ejecuta el orquestador. Se salta solo si falta el corpus del spike S5 o un modelo.

- **Corpus:** FLEURS del spike S5 (`%LOCALAPPDATA%\\InstantTraductor\\spikes\\idiomas\\corpus`;
  referencias en `spikes/idiomas/corpus_manifest.json`). `clean/<idioma>/<id>.wav` son frases enteras
  (11-24 s) y `lid/<idioma>/<id>.wav`, recortes de 1-6 s para el verificador.
- **Modelos:** los componentes instalados por `preparar` (`x-asr-zh`, `sensevoice-small`, `whisper-base-lid`
  en `AppPaths().models`) y, si no están, los del spike S5 (mismos ficheros, en
  `%LOCALAPPDATA%\\InstantTraductor\\spikes\\idiomas\\models`).
- **CER:** de las 10 primeras frases de cada idioma, ≤ 1,5 × el de S5 (que usó 50 frases y no cortó los
  segmentos). Los motores por segmento (ja y ko) se miden primero sin corte forzado, como en S5, y después con
  el corte forzado de producción (`max_segment_s=6`), con un margen mayor: cortar el habla leída sin pausas
  en mitad de una palabra empeora el CER y es lo que cuesta cumplir el máximo de habla sin traducir.
- **Verificador:** acepta ≥ 9 de 10 recortes del idioma correcto y rechaza ≥ 9 de 10 de español.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

from instanttraductor.asr import parakeet_ja, sensevoice, xasr_zh
from instanttraductor.config import AppPaths
from instanttraductor.contracts import (
    CAPTURE_RATE,
    AsrEngine,
    AsrEventKind,
    AudioChunk,
    SourceLanguage,
)
from instanttraductor.lid import whisper_lid
from instanttraductor.pipeline.clock import ManualClock

pytestmark = pytest.mark.model

Samples = npt.NDArray[np.float32]

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "spikes" / "idiomas" / "corpus_manifest.json"
SPIKE_HOME = Path(os.environ.get("LOCALAPPDATA", "")) / "InstantTraductor" / "spikes" / "idiomas"
CORPUS = SPIKE_HOME / "corpus"

PHRASES = 10  # frases (y recortes) por idioma
#: CER de S5 sin música (README del spike S5, tabla de ASR por idioma).
S5_CER = {"zh": 0.0487, "ja": 0.0832, "ko": 0.0714}
#: CER de Parakeet-ja en S5 (alternativa del japonés de R2; motor del japonés desde la validación de la 002).
S5_CER_PARAKEET_JA = 0.0531
CER_FACTOR = 1.5
#: Margen del corte forzado de 6 s con habla leída sin pausas (ver el docstring del módulo).
FORCED_CUT_CER_FACTOR = 2.0
MIN_ACCEPTED = 9  # de 10, del idioma correcto
MIN_REJECTED = 9  # de 10, de español

#: Carpeta de cada modelo en el spike S5 (mismos ficheros que el componente).
SPIKE_MODEL_FOLDERS = {
    "x-asr-zh": "sherpa-onnx-x-asr-960ms-streaming-zipformer-transducer-zh-en-punct-int8-2026-06-05",
    "sensevoice-small": "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17",
    "parakeet-ja": "sherpa-onnx-nemo-parakeet-tdt_ctc-0.6b-ja-35000-int8",
    "whisper-base-lid": "sherpa-onnx-whisper-base",
}


# --------------------------------------------------------------------------------------------------
# Corpus y modelos
# --------------------------------------------------------------------------------------------------


def model_dir(component: str, files: tuple[str, ...]) -> Path:
    """Carpeta del modelo: la del componente instalado o, si no, la del spike. Salta el test si no hay."""
    for candidate in (AppPaths().models / component, SPIKE_HOME / "models" / SPIKE_MODEL_FOLDERS[component]):
        if all((candidate / name).is_file() for name in files):
            return candidate
    pytest.skip(f"Falta el modelo {component} (ejecuta «instanttraductor preparar» o el spike S5).")


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    if not MANIFEST.is_file() or not CORPUS.is_dir():
        pytest.skip(f"Falta el corpus del spike S5 ({CORPUS}).")
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def read_wav(path: Path) -> Samples:
    import soundfile

    samples, rate = soundfile.read(path, dtype="float32")
    assert rate == CAPTURE_RATE, f"{path} debería estar a 16 kHz"
    return np.asarray(samples, dtype=np.float32)


def phrases(manifest: dict[str, Any], language: str) -> list[tuple[str, Samples]]:
    """Las `PHRASES` primeras frases del idioma: (texto de referencia, audio de la frase entera)."""
    items = manifest["phrases"][language]["items"][:PHRASES]
    return [(item["ref"], read_wav(CORPUS / "clean" / language / f"{item['id']}.wav")) for item in items]


def crops(manifest: dict[str, Any], language: str) -> list[Samples]:
    """Los `PHRASES` primeros recortes de 1-6 s del idioma, para el verificador."""
    items = manifest["lid"][language]["items"][:PHRASES]
    return [read_wav(CORPUS / "lid" / language / f"{item['id']}.wav") for item in items]


# --------------------------------------------------------------------------------------------------
# CER (misma normalización que `spikes/idiomas/idiomas/text.py`, sin jiwer)
# --------------------------------------------------------------------------------------------------

_DIGITS = {"〇": 0, "零": 0, "一": 1, "二": 2, "两": 2, "兩": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7}
_DIGITS |= {"八": 8, "九": 9}
_SMALL = {"十": 10, "百": 100, "千": 1000}
_BIG = {"万": 10_000, "萬": 10_000, "億": 100_000_000, "亿": 100_000_000}
_NUMERAL_RUN = re.compile("[" + "".join([*_DIGITS, *_SMALL, *_BIG]) + "]+")


def _numeral_to_digits(run: str) -> str:
    """`二〇一一` → 2011; `千九百六十七` → 1967."""
    if not any(c in _SMALL or c in _BIG for c in run):
        return "".join(str(_DIGITS[c]) for c in run)
    total, section, digit = 0, 0, 0
    for c in run:
        if c in _DIGITS:
            digit = _DIGITS[c]
        elif c in _SMALL:
            section += (digit or 1) * _SMALL[c]
            digit = 0
        else:
            total += (section + digit or 1) * _BIG[c]
            section = digit = 0
    return str(total + section + digit)


def normalize(text: str, language: str) -> str:
    """NFKC, minúsculas, sin puntuación ni espacios y, en ja y zh, numerales de ideogramas en cifras."""
    text = unicodedata.normalize("NFKC", text).lower()
    if language in ("ja", "zh"):
        text = _NUMERAL_RUN.sub(lambda m: _numeral_to_digits(m.group(0)), text)
    return "".join(c for c in text if unicodedata.category(c)[0] not in "PSZC")


def edit_distance(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        current = [i]
        for j, char_b in enumerate(b, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (char_a != char_b)))
        previous = current
    return previous[-1]


def corpus_cer(references: list[str], hypotheses: list[str], language: str) -> float:
    """Errores de carácter de todo el corpus / caracteres de referencia (tras normalizar)."""
    pairs = [
        (normalize(r, language), normalize(h, language)) for r, h in zip(references, hypotheses, strict=True)
    ]
    return sum(edit_distance(r, h) for r, h in pairs) / sum(len(r) for r, _ in pairs)


def transcribe(asr: AsrEngine, samples: Samples) -> str:
    """Entrega la frase al motor en chunks de 20 ms, lo vacía y une el texto de todos los FINAL."""
    size = round(0.02 * CAPTURE_RATE)
    events = []
    for start in range(0, len(samples), size):
        events.extend(
            asr.accept(AudioChunk(samples[start : start + size], CAPTURE_RATE, start / CAPTURE_RATE))
        )
    events.extend(asr.flush())
    return " ".join(event.text for event in events if event.kind is AsrEventKind.FINAL)


def cer_of(make_asr: Callable[[], AsrEngine], manifest: dict[str, Any], language: str) -> float:
    pairs = phrases(manifest, language)
    hypotheses = []
    for _, samples in pairs:
        asr = make_asr()
        hypotheses.append(transcribe(asr, samples))
        asr.close()
    cer = corpus_cer([ref for ref, _ in pairs], hypotheses, language)
    print(f"CER {language}: {cer:.2%} (S5: {S5_CER[language]:.2%}) con {len(pairs)} frases")
    return cer


# --------------------------------------------------------------------------------------------------
# Reconocedores
# --------------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def zh_recognizer() -> xasr_zh.Recognizer:
    return xasr_zh.create_recognizer(model_dir("x-asr-zh", xasr_zh.MODEL_FILES))


@pytest.fixture(scope="module", params=["ja", "ko"])
def sensevoice_recognizer(request: pytest.FixtureRequest) -> tuple[str, sensevoice.Recognizer]:
    language: str = request.param
    return language, sensevoice.create_recognizer(
        language, model_dir("sensevoice-small", sensevoice.MODEL_FILES)
    )


class TestChinese:
    def test_cer_is_within_1_5_times_the_one_of_s5(
        self, manifest: dict[str, Any], zh_recognizer: xasr_zh.Recognizer
    ) -> None:
        cer = cer_of(lambda: xasr_zh.XAsrZhStreaming(ManualClock(), recognizer=zh_recognizer), manifest, "zh")
        assert cer <= CER_FACTOR * S5_CER["zh"]

    def test_the_engine_gives_partials_and_one_final_per_sentence(
        self, manifest: dict[str, Any], zh_recognizer: xasr_zh.Recognizer
    ) -> None:
        asr = xasr_zh.XAsrZhStreaming(ManualClock(), recognizer=zh_recognizer)
        _, samples = phrases(manifest, "zh")[0]
        size = round(0.02 * CAPTURE_RATE)
        events = []
        for start in range(0, len(samples), size):
            events.extend(
                asr.accept(AudioChunk(samples[start : start + size], CAPTURE_RATE, start / CAPTURE_RATE))
            )
        events.extend(asr.flush())
        assert [e.kind for e in events].count(AsrEventKind.FINAL) == 1
        assert any(e.kind is AsrEventKind.PARTIAL for e in events)
        assert {e.language for e in events} == {"zh"}
        assert events[-1].kind is AsrEventKind.FINAL


@pytest.fixture(scope="module")
def parakeet_recognizer() -> parakeet_ja.Recognizer:
    return parakeet_ja.create_recognizer(model_dir("parakeet-ja", parakeet_ja.MODEL_FILES))


class TestParakeetJapanese:
    def test_cer_without_forced_cut_is_within_1_5_times_the_one_of_s5(
        self, manifest: dict[str, Any], parakeet_recognizer: parakeet_ja.Recognizer
    ) -> None:
        cer = cer_of(
            lambda: parakeet_ja.ParakeetJaSegmentAsr(
                ManualClock(), recognizer=parakeet_recognizer, max_segment_s=60.0
            ),
            manifest,
            "ja",
        )
        assert cer <= CER_FACTOR * S5_CER_PARAKEET_JA

    def test_cer_with_the_production_forced_cut_stays_close(
        self, manifest: dict[str, Any], parakeet_recognizer: parakeet_ja.Recognizer
    ) -> None:
        cer = cer_of(
            lambda: parakeet_ja.ParakeetJaSegmentAsr(
                ManualClock(), recognizer=parakeet_recognizer, max_segment_s=6.0
            ),
            manifest,
            "ja",
        )
        assert cer <= FORCED_CUT_CER_FACTOR * S5_CER_PARAKEET_JA


class TestJapaneseAndKorean:
    def test_cer_without_forced_cut_is_within_1_5_times_the_one_of_s5(
        self, manifest: dict[str, Any], sensevoice_recognizer: tuple[str, sensevoice.Recognizer]
    ) -> None:
        language, recognizer = sensevoice_recognizer
        cer = cer_of(
            lambda: sensevoice.SenseVoiceSegmentAsr(
                language, ManualClock(), recognizer=recognizer, max_segment_s=60.0
            ),
            manifest,
            language,
        )
        assert cer <= CER_FACTOR * S5_CER[language]

    def test_cer_with_the_production_forced_cut_stays_close(
        self, manifest: dict[str, Any], sensevoice_recognizer: tuple[str, sensevoice.Recognizer]
    ) -> None:
        language, recognizer = sensevoice_recognizer
        cer = cer_of(
            lambda: sensevoice.SenseVoiceSegmentAsr(
                language, ManualClock(), recognizer=recognizer, max_segment_s=6.0
            ),
            manifest,
            language,
        )
        assert cer <= FORCED_CUT_CER_FACTOR * S5_CER[language]

    def test_the_forced_cut_splits_a_long_sentence_and_loses_no_audio(
        self, manifest: dict[str, Any], sensevoice_recognizer: tuple[str, sensevoice.Recognizer]
    ) -> None:
        language, recognizer = sensevoice_recognizer
        asr = sensevoice.SenseVoiceSegmentAsr(
            language, ManualClock(), recognizer=recognizer, max_segment_s=6.0
        )
        _, samples = max(phrases(manifest, language), key=lambda pair: len(pair[1]))
        assert len(samples) > 8 * CAPTURE_RATE
        size = round(0.02 * CAPTURE_RATE)
        events = []
        for start in range(0, len(samples), size):
            events.extend(
                asr.accept(AudioChunk(samples[start : start + size], CAPTURE_RATE, start / CAPTURE_RATE))
            )
        events.extend(asr.flush())
        assert len(events) >= 2
        assert all(e.language == language and e.kind is AsrEventKind.FINAL for e in events)
        assert [e.segment_id for e in events] == list(range(len(events)))
        for before, after in zip(events, events[1:], strict=False):
            assert after.t_start == pytest.approx(before.t_end)
        assert all(e.t_end - e.t_start <= 6.0 + 1e-6 for e in events)


# --------------------------------------------------------------------------------------------------
# Verificador de idioma
# --------------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def verifier() -> whisper_lid.WhisperLanguageVerifier:
    base = model_dir("whisper-base-lid", whisper_lid.MODEL_FILES)
    return whisper_lid.WhisperLanguageVerifier(model_dir=base)


class TestLanguageVerifier:
    @pytest.mark.parametrize("language", ["ja", "zh", "ko", "en"])
    def test_it_accepts_the_right_language(
        self, manifest: dict[str, Any], verifier: whisper_lid.WhisperLanguageVerifier, language: str
    ) -> None:
        verdicts = [
            verifier.verify(x, CAPTURE_RATE, SourceLanguage(language)) for x in crops(manifest, language)
        ]
        accepted = sum(v.accepted for v in verdicts)
        print(
            f"{language}: aceptados {accepted}/{len(verdicts)}; detectados {[v.detected for v in verdicts]}"
        )
        assert accepted >= MIN_ACCEPTED

    @pytest.mark.parametrize("chosen", ["ja", "zh", "ko", "en"])
    def test_it_rejects_spanish_whatever_language_was_chosen(
        self, manifest: dict[str, Any], verifier: whisper_lid.WhisperLanguageVerifier, chosen: str
    ) -> None:
        verdicts = [verifier.verify(x, CAPTURE_RATE, SourceLanguage(chosen)) for x in crops(manifest, "es")]
        rejected = sum(not v.accepted for v in verdicts)
        print(f"es con idioma {chosen}: rechazados {rejected}/{len(verdicts)}")
        assert rejected >= MIN_REJECTED

    def test_each_decision_takes_well_under_a_second_on_one_thread(
        self, manifest: dict[str, Any], verifier: whisper_lid.WhisperLanguageVerifier
    ) -> None:
        elapsed = sorted(
            verifier.verify(x, CAPTURE_RATE, SourceLanguage.JA).elapsed_s for x in crops(manifest, "ja")
        )
        median = elapsed[len(elapsed) // 2]
        print(f"filtro de idioma: mediana {median * 1000:.0f} ms, máx. {elapsed[-1] * 1000:.0f} ms")
        assert median < 0.5  # S5: p50 de 96 ms con la máquina libre
