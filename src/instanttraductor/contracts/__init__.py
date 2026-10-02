"""Contratos entre etapas del pipeline.

Congelados con `contratos-001-v1` y ampliados de forma aditiva en `contratos-002-v1`. Fuente de verdad:
`specs/001-espina-dorsal/contracts/pipeline.md` y `specs/002-idiomas-y-peliculas/contracts/pipeline-002.md`.
Cambiar estos módulos exige un ADR (constitución, Principio III).
"""

from instanttraductor.contracts.audio import (
    CAPTURE_RATE,
    PLAYBACK_RATE,
    AudioChunk,
    AudioSink,
    AudioSource,
    PlaybackEvent,
    PlaybackEventKind,
    SpeechPiece,
)
from instanttraductor.contracts.clock import Clock
from instanttraductor.contracts.errors import EngineError
from instanttraductor.contracts.language import (
    VERIFIER_LANGUAGES,
    LanguageVerdict,
    LanguageVerifier,
    SourceLanguage,
)
from instanttraductor.contracts.metrics import Outcome, StageTimings, UtteranceRecord
from instanttraductor.contracts.scheduling import DelayController, DelayDecision, DelayPolicy
from instanttraductor.contracts.speech import (
    AsrCapabilities,
    AsrEngine,
    AsrEvent,
    AsrEventKind,
    Vad,
    VadEvent,
    VadEventKind,
    Word,
)
from instanttraductor.contracts.synthesis import (
    SynthesisRequest,
    SynthesizedChunk,
    Synthesizer,
    VoiceInfo,
    VoiceRef,
)
from instanttraductor.contracts.translation import (
    GlossaryEntry,
    TranslationMode,
    TranslationRequest,
    TranslationResult,
    Translator,
)
from instanttraductor.contracts.units import Segmenter, TranslationUnit

__all__ = [
    "VERIFIER_LANGUAGES",
    "LanguageVerdict",
    "LanguageVerifier",
    "SourceLanguage",
    "CAPTURE_RATE",
    "PLAYBACK_RATE",
    "AsrCapabilities",
    "AsrEngine",
    "AsrEvent",
    "AsrEventKind",
    "AudioChunk",
    "AudioSink",
    "AudioSource",
    "Clock",
    "DelayController",
    "DelayDecision",
    "DelayPolicy",
    "EngineError",
    "GlossaryEntry",
    "Outcome",
    "PlaybackEvent",
    "PlaybackEventKind",
    "Segmenter",
    "SpeechPiece",
    "StageTimings",
    "SynthesisRequest",
    "SynthesizedChunk",
    "Synthesizer",
    "TranslationMode",
    "TranslationRequest",
    "TranslationResult",
    "TranslationUnit",
    "Translator",
    "UtteranceRecord",
    "Vad",
    "VadEvent",
    "VadEventKind",
    "VoiceInfo",
    "VoiceRef",
    "Word",
]
