"""Tests de los contratos del pipeline (T005).

Comprueban que `instanttraductor.contracts` coincide con `specs/001-espina-dorsal/contracts/pipeline.md`
campo por campo: nombres y orden de los campos, valores por defecto, inmutabilidad (`frozen` y `slots`),
`eq=False` en los datos con arrays de audio, propiedades derivadas, enumeraciones, miembros de los
Protocols y `EngineError`.
"""

from __future__ import annotations

import dataclasses
import enum
import importlib
import inspect
from collections.abc import Callable
from types import ModuleType
from typing import Any

import numpy as np
import pytest

import instanttraductor.contracts as contracts
from instanttraductor.contracts import (
    CAPTURE_RATE,
    PLAYBACK_RATE,
    AsrCapabilities,
    AsrEngine,
    AsrEvent,
    AsrEventKind,
    AudioChunk,
    AudioSink,
    AudioSource,
    Clock,
    DelayController,
    DelayDecision,
    DelayPolicy,
    EngineError,
    GlossaryEntry,
    Outcome,
    PlaybackEvent,
    PlaybackEventKind,
    Segmenter,
    SourceLanguage,
    SpeechPiece,
    StageTimings,
    SynthesisRequest,
    SynthesizedChunk,
    Synthesizer,
    TranslationMode,
    TranslationRequest,
    TranslationResult,
    TranslationUnit,
    Translator,
    UtteranceRecord,
    Vad,
    VadEvent,
    VadEventKind,
    VoiceInfo,
    VoiceRef,
    Word,
)


def _samples(n: int = 160) -> np.ndarray:
    return np.zeros(n, dtype=np.float32)


def _unit() -> TranslationUnit:
    return TranslationUnit(
        unit_id=1, source_text="hello there", t_start=0.0, t_end=1.0, is_sentence_end=True, ready_at=1.5
    )


def _timings(**kwargs: Any) -> StageTimings:
    return StageTimings(t_start_audio=1.0, t_end_audio=2.0, unit_ready_at=2.5, **kwargs)


# Una instancia válida de cada dataclass del contrato.
FACTORIES: dict[type, Callable[[], Any]] = {
    AudioChunk: lambda: AudioChunk(samples=_samples(), sample_rate=CAPTURE_RATE, t_start=0.0),
    SpeechPiece: lambda: SpeechPiece(unit_id=1, samples=_samples(), is_last=True),
    PlaybackEvent: lambda: PlaybackEvent(unit_id=1, kind=PlaybackEventKind.STARTED, at=0.5),
    VadEvent: lambda: VadEvent(kind=VadEventKind.SPEECH_START, t=0.1),
    Word: lambda: Word(text="hi", t_start=0.0, t_end=0.2),
    AsrEvent: lambda: AsrEvent(
        kind=AsrEventKind.PARTIAL,
        segment_id=1,
        revision=0,
        text="hello",
        stable_len=0,
        t_start=0.0,
        t_end=0.5,
        is_sentence_end=False,
        emitted_at=0.6,
    ),
    AsrCapabilities: lambda: AsrCapabilities(
        native_streaming=True,
        partials=True,
        punctuation=False,
        word_timestamps=False,
        languages=frozenset({"en"}),
        device="cpu",
        est_vram_mb=0,
    ),
    TranslationUnit: _unit,
    GlossaryEntry: lambda: GlossaryEntry(source="juice", target="zumo"),
    TranslationRequest: lambda: TranslationRequest(
        unit=_unit(), context=(("a", "b"),), glossary=(), mode=TranslationMode.NORMAL
    ),
    TranslationResult: lambda: TranslationResult(
        unit_id=1, text="hola", mode=TranslationMode.NORMAL, started_at=1.0, finished_at=1.2
    ),
    VoiceRef: lambda: VoiceRef(voice_id="es-m-tux"),
    VoiceInfo: lambda: VoiceInfo(
        voice_id="es-m-tux", name="Tux", gender="m", source="LibriVox", license="PD"
    ),
    SynthesisRequest: lambda: SynthesisRequest(unit_id=1, text="hola", voice=VoiceRef("es-m-tux")),
    SynthesizedChunk: lambda: SynthesizedChunk(
        unit_id=1, samples=_samples(), sample_rate=24_000, is_last=True
    ),
    DelayPolicy: DelayPolicy,
    DelayDecision: lambda: DelayDecision(speed=1.0, mode=TranslationMode.NORMAL, drop_oldest_pending=False),
    StageTimings: _timings,
    UtteranceRecord: lambda: UtteranceRecord(
        unit_id=1,
        source_text="hello",
        translated_text="hola",
        mode=TranslationMode.NORMAL,
        speed=1.0,
        outcome=Outcome.SPOKEN,
        reason=None,
        timings=_timings(),
    ),
}

# Campos de cada dataclass, en el orden exacto de pipeline.md.
EXPECTED_FIELDS: dict[type, tuple[str, ...]] = {
    AudioChunk: ("samples", "sample_rate", "t_start"),
    SpeechPiece: ("unit_id", "samples", "is_last"),
    PlaybackEvent: ("unit_id", "kind", "at"),
    VadEvent: ("kind", "t"),
    Word: ("text", "t_start", "t_end"),
    AsrEvent: (
        "kind",
        "segment_id",
        "revision",
        "text",
        "stable_len",
        "t_start",
        "t_end",
        "is_sentence_end",
        "emitted_at",
        "language",
        "words",
    ),
    AsrCapabilities: (
        "native_streaming",
        "partials",
        "punctuation",
        "word_timestamps",
        "languages",
        "device",
        "est_vram_mb",
    ),
    TranslationUnit: (
        "unit_id",
        "source_text",
        "t_start",
        "t_end",
        "is_sentence_end",
        "ready_at",
        "language",
    ),
    GlossaryEntry: ("source", "target"),
    TranslationRequest: ("unit", "context", "glossary", "mode", "source_language"),
    TranslationResult: ("unit_id", "text", "mode", "started_at", "finished_at", "rejected"),
    VoiceRef: ("voice_id",),
    VoiceInfo: ("voice_id", "name", "gender", "source", "license"),
    SynthesisRequest: ("unit_id", "text", "voice", "speed"),
    SynthesizedChunk: ("unit_id", "samples", "sample_rate", "is_last"),
    DelayPolicy: ("accelerate_after_s", "max_speed", "concise_after_s", "drop_after_s", "allow_concise"),
    DelayDecision: ("speed", "mode", "drop_oldest_pending"),
    StageTimings: (
        "t_start_audio",
        "t_end_audio",
        "unit_ready_at",
        "captured_at",
        "asr_final_at",
        "mt_started_at",
        "mt_finished_at",
        "tts_started_at",
        "tts_first_audio_at",
        "tts_finished_at",
        "play_started_at",
        "play_finished_at",
        "lid_done_at",
    ),
    UtteranceRecord: (
        "unit_id",
        "source_text",
        "translated_text",
        "mode",
        "speed",
        "outcome",
        "reason",
        "timings",
    ),
}

# Campos con valor por defecto y ese valor.
EXPECTED_DEFAULTS: dict[type, dict[str, Any]] = {
    AsrEvent: {"language": "en", "words": ()},
    TranslationUnit: {"language": "en"},
    TranslationResult: {"rejected": False},
    TranslationRequest: {"source_language": SourceLanguage.EN},  # contratos-002-v1
    SynthesisRequest: {"speed": 1.0},
    DelayPolicy: {
        "accelerate_after_s": 3.0,
        "max_speed": 1.25,
        "concise_after_s": 5.0,
        "drop_after_s": 8.0,
        "allow_concise": True,
    },
    StageTimings: {
        "captured_at": None,
        "asr_final_at": None,
        "mt_started_at": None,
        "mt_finished_at": None,
        "tts_started_at": None,
        "tts_first_audio_at": None,
        "tts_finished_at": None,
        "play_started_at": None,
        "play_finished_at": None,
        "lid_done_at": None,  # contratos-002-v1
    },
}

# Los datos con arrays de audio no comparan por valor: `==` sobre arrays no da un booleano.
AUDIO_ARRAY_CLASSES = (AudioChunk, SpeechPiece, SynthesizedChunk)

# Miembros de cada Protocol, según pipeline.md.
EXPECTED_PROTOCOL_MEMBERS: dict[type, set[str]] = {
    Clock: {"now"},
    AudioSource: {"sample_rate", "start", "read", "exhausted", "stop"},
    AudioSink: {"sample_rate", "start", "enqueue", "cancel_pending", "set_volume", "pending_seconds", "stop"},
    Vad: {"accept", "in_speech", "reset"},
    AsrEngine: {"name", "capabilities", "accept", "flush", "reset", "close"},
    Segmenter: {"accept", "flush"},
    Translator: {"name", "supports_concise", "translate", "close"},
    Synthesizer: {"name", "sample_rate", "supports_speed", "synthesize", "list_voices", "close"},
    DelayController: {"decide"},
}

# Módulos del paquete y los nombres públicos que cada uno debe definir (todos reexportados en el paquete).
CONTRACT_MODULES = (
    "clock",
    "errors",
    "audio",
    "speech",
    "units",
    "translation",
    "synthesis",
    "scheduling",
    "metrics",
)

DATACLASSES = list(EXPECTED_FIELDS)


def test_factories_and_tables_cover_the_same_dataclasses() -> None:
    assert set(FACTORIES) == set(EXPECTED_FIELDS)
    assert set(EXPECTED_DEFAULTS) <= set(EXPECTED_FIELDS)


@pytest.mark.parametrize("cls", DATACLASSES, ids=lambda c: c.__name__)
class TestEveryDataclass:
    def test_is_a_dataclass_with_the_contract_fields_in_order(self, cls: type) -> None:
        assert dataclasses.is_dataclass(cls)
        assert tuple(f.name for f in dataclasses.fields(cls)) == EXPECTED_FIELDS[cls]

    def test_has_only_the_contract_defaults(self, cls: type) -> None:
        defaults = {
            f.name: f.default
            for f in dataclasses.fields(cls)
            if f.default is not dataclasses.MISSING or f.default_factory is not dataclasses.MISSING
        }
        assert defaults == EXPECTED_DEFAULTS.get(cls, {})

    def test_is_frozen_and_uses_slots(self, cls: type) -> None:
        assert cls.__dataclass_params__.frozen is True  # type: ignore[attr-defined]
        assert "__slots__" in vars(cls)
        assert not hasattr(FACTORIES[cls](), "__dict__")

    def test_cannot_be_mutated(self, cls: type) -> None:
        obj = FACTORIES[cls]()
        first_field = dataclasses.fields(cls)[0].name
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(obj, first_field, getattr(obj, first_field))
        # Un atributo nuevo tampoco se puede añadir: con `slots=True`, CPython 3.12 lanza TypeError
        # y las versiones posteriores, FrozenInstanceError (que es un AttributeError).
        with pytest.raises((AttributeError, TypeError)):
            obj.new_attribute = 1

    def test_eq_is_disabled_only_for_audio_array_classes(self, cls: type) -> None:
        expected_eq = cls not in AUDIO_ARRAY_CLASSES
        assert cls.__dataclass_params__.eq is expected_eq  # type: ignore[attr-defined]


@pytest.mark.parametrize("cls", AUDIO_ARRAY_CLASSES, ids=lambda c: c.__name__)
class TestAudioArrayClasses:
    def test_equality_is_identity_and_never_raises(self, cls: type) -> None:
        """Con `eq=True`, comparar dos instancias con arrays de más de un elemento lanzaría ValueError."""
        a, b = FACTORIES[cls](), FACTORIES[cls]()
        assert (a == b) is False
        assert (a == a) is True

    def test_is_hashable_by_identity(self, cls: type) -> None:
        obj = FACTORIES[cls]()
        assert hash(obj) == hash(obj)


@pytest.mark.parametrize(
    "cls",
    [c for c in DATACLASSES if c not in AUDIO_ARRAY_CLASSES],
    ids=lambda c: c.__name__,
)
def test_value_dataclasses_compare_and_hash_by_value(cls: type) -> None:
    """Los demás datos son comparables por valor y se pueden usar como claves."""
    a, b = FACTORIES[cls](), FACTORIES[cls]()
    assert a == b
    assert hash(a) == hash(b)


class TestAudioChunk:
    def test_duration_is_samples_over_sample_rate(self) -> None:
        chunk = AudioChunk(samples=_samples(320), sample_rate=CAPTURE_RATE, t_start=1.0)
        assert chunk.duration == pytest.approx(0.02)

    def test_t_end_is_t_start_plus_duration(self) -> None:
        chunk = AudioChunk(samples=_samples(320), sample_rate=CAPTURE_RATE, t_start=1.0)
        assert chunk.t_end == pytest.approx(1.02)

    def test_empty_chunk_has_zero_duration(self) -> None:
        chunk = AudioChunk(samples=_samples(0), sample_rate=CAPTURE_RATE, t_start=3.5)
        assert chunk.duration == 0.0
        assert chunk.t_end == 3.5

    def test_duration_uses_its_own_sample_rate(self) -> None:
        chunk = AudioChunk(samples=_samples(48_000), sample_rate=PLAYBACK_RATE, t_start=0.0)
        assert chunk.duration == pytest.approx(1.0)


class TestStageTimings:
    def test_sentence_delay_is_play_started_minus_t_end_audio(self) -> None:
        timings = _timings(play_started_at=4.25)
        assert timings.sentence_delay == pytest.approx(2.25)

    def test_sentence_delay_is_none_without_play_started_at(self) -> None:
        assert _timings().sentence_delay is None
        assert _timings(captured_at=2.1, play_finished_at=9.0).sentence_delay is None

    def test_sentence_delay_with_play_started_at_zero_is_not_none(self) -> None:
        timings = StageTimings(t_start_audio=0.0, t_end_audio=0.0, unit_ready_at=0.0, play_started_at=0.0)
        assert timings.sentence_delay == 0.0

    def test_captured_at_is_optional_and_independent(self) -> None:
        assert _timings().captured_at is None
        assert _timings(captured_at=2.1).captured_at == 2.1


ENUM_VALUES: dict[type[enum.StrEnum], dict[str, str]] = {
    PlaybackEventKind: {"STARTED": "started", "FINISHED": "finished", "CANCELLED": "cancelled"},
    VadEventKind: {"SPEECH_START": "speech_start", "SPEECH_END": "speech_end"},
    AsrEventKind: {"PARTIAL": "partial", "FINAL": "final"},
    TranslationMode: {"NORMAL": "normal", "CONCISE": "conciso"},
    Outcome: {
        "SPOKEN": "pronunciada",
        "DROPPED": "descartada",
        "REJECTED": "rechazada",
        "FAILED": "fallida",
    },
}


class TestEnums:
    @pytest.mark.parametrize("enum_cls", list(ENUM_VALUES), ids=lambda c: c.__name__)
    def test_members_and_values(self, enum_cls: type[enum.StrEnum]) -> None:
        assert issubclass(enum_cls, enum.StrEnum)
        assert {m.name: m.value for m in enum_cls} == ENUM_VALUES[enum_cls]

    def test_members_behave_as_strings(self) -> None:
        assert Outcome.REJECTED == "rechazada"
        assert f"{TranslationMode.CONCISE}" == "conciso"


class TestConstants:
    def test_sample_rates(self) -> None:
        assert CAPTURE_RATE == 16_000
        assert PLAYBACK_RATE == 48_000


class TestEngineError:
    def test_is_a_runtime_error_with_engine_and_recoverable(self) -> None:
        error = EngineError("fallo del motor", engine="asr")
        assert isinstance(error, RuntimeError)
        assert str(error) == "fallo del motor"
        assert error.engine == "asr"
        assert error.recoverable is True

    def test_recoverable_can_be_disabled(self) -> None:
        assert EngineError("sin VRAM", engine="mt", recoverable=False).recoverable is False

    def test_engine_and_recoverable_are_keyword_only(self) -> None:
        with pytest.raises(TypeError):
            EngineError("fallo", "asr")  # type: ignore[misc]
        with pytest.raises(TypeError):
            EngineError("fallo")  # type: ignore[call-arg]

    def test_can_be_raised_and_caught_as_runtime_error(self) -> None:
        with pytest.raises(RuntimeError, match="boom") as info:
            raise EngineError("boom", engine="tts")
        assert info.value.engine == "tts"


@pytest.mark.parametrize("protocol", list(EXPECTED_PROTOCOL_MEMBERS), ids=lambda p: p.__name__)
def test_protocol_members_match_the_contract(protocol: type) -> None:
    assert set(protocol.__protocol_attrs__) == EXPECTED_PROTOCOL_MEMBERS[protocol]  # type: ignore[attr-defined]


def test_protocol_properties_are_declared_as_properties() -> None:
    assert isinstance(AudioSource.exhausted, property)
    assert isinstance(Vad.in_speech, property)


def _public_names(module: ModuleType) -> set[str]:
    """Clases definidas en el módulo y constantes en mayúsculas (CAPTURE_RATE, PLAYBACK_RATE)."""
    names: set[str] = set()
    for name, value in vars(module).items():
        if name.startswith("_"):
            continue
        if inspect.isclass(value):
            if value.__module__ == module.__name__:
                names.add(name)
        elif name.isupper() and not inspect.ismodule(value):
            names.add(name)
    return names


@pytest.mark.parametrize("module_name", CONTRACT_MODULES)
def test_package_reexports_the_public_names_of_every_module(module_name: str) -> None:
    module = importlib.import_module(f"instanttraductor.contracts.{module_name}")
    public = _public_names(module)
    assert public, f"{module_name} no define nombres públicos"
    missing = {name for name in public if getattr(contracts, name, None) is not getattr(module, name)}
    assert not missing, f"faltan en el paquete: {sorted(missing)}"
    assert public <= set(contracts.__all__)


def test_all_lists_only_existing_names() -> None:
    assert all(hasattr(contracts, name) for name in contracts.__all__)
    assert len(contracts.__all__) == len(set(contracts.__all__))
