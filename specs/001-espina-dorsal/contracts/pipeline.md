# Contrato: etapas del pipeline (Python)

Fuente de verdad para `src/instanttraductor/contracts/`. En la fase Foundational se implementa **exactamente** así y se congela con el tag `contratos-001-v1`. Cambiarlo después exige un ADR (constitución, Principio III).

Reglas comunes:
- Todos los datos que cruzan etapas son `@dataclass(frozen=True, slots=True)`. Los arrays de audio no se mutan después de crearlos.
- Audio: `numpy.ndarray` de `float32`, mono, en el rango [-1, 1].
- Tiempos: `float` en segundos. «Reloj de audio» y «reloj de sesión» se definen en [data-model.md](../data-model.md).
- Los componentes reciben un `Clock` en su constructor. Ninguno llama a `time.time()` ni a `time.monotonic()` directamente, salvo `SessionClock`.
- Ningún método del contrato debe lanzar excepciones por un caso esperado (sin voz, fin de fichero, cola vacía). Los errores de motor se lanzan como `EngineError`.

```python
# contracts/clock.py
from typing import Protocol

class Clock(Protocol):
    def now(self) -> float: ...   # segundos desde el inicio de la sesión; monotónico y no decreciente


# contracts/errors.py
class EngineError(RuntimeError):
    """Fallo de un motor (ASR, traducción, voz, audio). `recoverable` indica si vale la pena reintentar."""
    def __init__(self, message: str, *, engine: str, recoverable: bool = True) -> None: ...


# contracts/audio.py
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Protocol
import numpy as np
import numpy.typing as npt

CAPTURE_RATE: Final = 16_000     # Hz, entrada de VAD y ASR
PLAYBACK_RATE: Final = 48_000    # Hz, salida hacia el dispositivo o la pista

@dataclass(frozen=True, slots=True)
class AudioChunk:
    samples: npt.NDArray[np.float32]   # mono
    sample_rate: int
    t_start: float                     # reloj de audio
    @property
    def duration(self) -> float: ...  # len(samples) / sample_rate
    @property
    def t_end(self) -> float: ...      # t_start + duration

@dataclass(frozen=True, slots=True)
class SpeechPiece:
    unit_id: int
    samples: npt.NDArray[np.float32]   # mono, YA a la frecuencia del sink
    is_last: bool                      # último trozo de esta unidad

class PlaybackEventKind(StrEnum):
    STARTED = "started"       # primera muestra de la unidad entregada al dispositivo o a la pista
    FINISHED = "finished"     # última muestra entregada
    CANCELLED = "cancelled"   # descartada antes de empezar, o cortada por una parada

@dataclass(frozen=True, slots=True)
class PlaybackEvent:
    unit_id: int
    kind: PlaybackEventKind
    at: float                 # reloj de sesión

class AudioSource(Protocol):
    sample_rate: int                                    # siempre CAPTURE_RATE
    def start(self) -> None: ...
    def read(self, timeout: float) -> AudioChunk | None: ...
    # Bloquea hasta `timeout` s. Devuelve None si no hay datos. Los chunks son contiguos:
    # chunk[i+1].t_start == chunk[i].t_end, con los silencios de la captura rellenados con ceros.
    @property
    def exhausted(self) -> bool: ...                    # True cuando ya no llegarán más datos (fin de fichero o stop)
    def stop(self) -> None: ...                         # idempotente

class AudioSink(Protocol):
    sample_rate: int                                    # siempre PLAYBACK_RATE
    def start(self, on_event: Callable[[PlaybackEvent], None]) -> None: ...
    def enqueue(self, piece: SpeechPiece) -> None: ...
    # No bloquea. Las unidades suenan en orden FIFO y los trozos de una unidad, contiguos.
    # Una unidad empieza a sonar en cuanto llega su primer trozo, si el sink está libre.
    def cancel_pending(self) -> list[int]: ...          # descarta las unidades que no han empezado; devuelve sus unit_id
    def set_volume(self, gain: float) -> None: ...      # 0.0–2.0; solo la voz en español
    def pending_seconds(self) -> float: ...             # audio encolado sin reproducir
    def stop(self) -> None: ...                         # corta lo que suena, vacía la cola y emite CANCELLED; idempotente


# contracts/speech.py
class VadEventKind(StrEnum):
    SPEECH_START = "speech_start"
    SPEECH_END = "speech_end"

@dataclass(frozen=True, slots=True)
class VadEvent:
    kind: VadEventKind
    t: float                  # reloj de audio

class Vad(Protocol):
    def accept(self, chunk: AudioChunk) -> list[VadEvent]: ...
    @property
    def in_speech(self) -> bool: ...
    def reset(self) -> None: ...

class AsrEventKind(StrEnum):
    PARTIAL = "partial"       # hipótesis provisional: puede cambiar después de stable_len
    FINAL = "final"           # texto definitivo del segmento

@dataclass(frozen=True, slots=True)
class Word:
    text: str
    t_start: float            # reloj de audio
    t_end: float

@dataclass(frozen=True, slots=True)
class AsrEvent:
    kind: AsrEventKind
    segment_id: int           # único en la sesión y creciente
    revision: int             # +1 en cada evento del mismo segmento
    text: str                 # hipótesis completa del segmento
    stable_len: int           # caracteres de `text` que ya no cambiarán (FINAL: len(text))
    t_start: float            # reloj de audio
    t_end: float
    is_sentence_end: bool     # el texto termina en fin de oración
    emitted_at: float         # reloj de sesión
    language: str = "en"
    words: tuple[Word, ...] = ()   # vacío si el motor no da tiempos por palabra

@dataclass(frozen=True, slots=True)
class AsrCapabilities:
    native_streaming: bool
    partials: bool
    punctuation: bool
    word_timestamps: bool
    languages: frozenset[str]
    device: str               # "cpu" | "cuda"
    est_vram_mb: int

class AsrEngine(Protocol):
    name: str
    capabilities: AsrCapabilities
    def accept(self, chunk: AudioChunk) -> list[AsrEvent]: ...   # procesa el audio y devuelve los eventos nuevos
    def flush(self) -> list[AsrEvent]: ...                       # cierra el segmento en curso (→ FINAL si había texto)
    def reset(self) -> None: ...
    def close(self) -> None: ...


# contracts/units.py
@dataclass(frozen=True, slots=True)
class TranslationUnit:
    unit_id: int              # estrictamente creciente
    source_text: str          # no vacío; solo texto estable
    t_start: float            # reloj de audio
    t_end: float              # reloj de audio; base del retardo de frase
    is_sentence_end: bool     # False = fragmento de una frase larga
    ready_at: float           # reloj de sesión
    language: str = "en"

class Segmenter(Protocol):
    # Una unidad por enunciado: se cierra con la pausa del VAD (SPEECH_END) y el FINAL del ASR.
    # El ASR casi nunca pone punto final, así que no se cierra por puntuación (research.md R6).
    # Habla larga: se corta en una coma o conjunción estable si el fragmento tiene ≥ 6 palabras.
    # Nunca más de `max_untranslated_s` de habla sin emitir unidad (FR-004, FR-005).
    def accept(self, event: AsrEvent | VadEvent) -> list[TranslationUnit]: ...
    def flush(self) -> list[TranslationUnit]: ...      # cierra lo pendiente (fin de sesión o de fichero)


# contracts/translation.py
class TranslationMode(StrEnum):
    NORMAL = "normal"
    CONCISE = "conciso"       # resumida a lo esencial (FR-013)

@dataclass(frozen=True, slots=True)
class GlossaryEntry:
    source: str
    target: str

@dataclass(frozen=True, slots=True)
class TranslationRequest:
    unit: TranslationUnit
    context: tuple[tuple[str, str], ...]   # (original, traducción) de las unidades previas, de la más antigua a la más reciente
    glossary: tuple[GlossaryEntry, ...]
    mode: TranslationMode

@dataclass(frozen=True, slots=True)
class TranslationResult:
    unit_id: int
    text: str                 # español; vacío si rejected
    mode: TranslationMode
    started_at: float         # reloj de sesión
    finished_at: float
    rejected: bool = False    # True si los filtros de salida la descartaron (muletillas, idioma, longitud)

class Translator(Protocol):
    name: str
    def translate(self, request: TranslationRequest) -> TranslationResult: ...   # EngineError si falla
    def close(self) -> None: ...


# contracts/synthesis.py
from collections.abc import Iterator
from typing import Literal

@dataclass(frozen=True, slots=True)
class VoiceRef:
    voice_id: str

@dataclass(frozen=True, slots=True)
class VoiceInfo:
    voice_id: str
    name: str
    gender: Literal["f", "m"]
    source: str
    license: str

@dataclass(frozen=True, slots=True)
class SynthesisRequest:
    unit_id: int
    text: str
    voice: VoiceRef
    speed: float = 1.0        # 1.0–1.5; si el motor no lo soporta, el núcleo aplica time-stretch

@dataclass(frozen=True, slots=True)
class SynthesizedChunk:
    unit_id: int
    samples: npt.NDArray[np.float32]   # mono, a `sample_rate` del motor
    sample_rate: int
    is_last: bool

class Synthesizer(Protocol):
    name: str
    sample_rate: int
    supports_speed: bool
    def synthesize(self, request: SynthesisRequest) -> Iterator[SynthesizedChunk]: ...  # streaming; EngineError si falla
    def list_voices(self) -> tuple[VoiceInfo, ...]: ...
    def close(self) -> None: ...


# contracts/scheduling.py
@dataclass(frozen=True, slots=True)
class DelayPolicy:
    accelerate_after_s: float = 3.0
    max_speed: float = 1.25
    concise_after_s: float = 5.0
    drop_after_s: float = 8.0

@dataclass(frozen=True, slots=True)
class DelayDecision:
    speed: float                      # 1.0–max_speed, gradual según el retraso
    mode: TranslationMode             # CONCISE mientras el retraso no vuelva bajo accelerate_after_s
    drop_oldest_pending: bool         # True solo si lag > drop_after_s a velocidad máxima

class DelayController(Protocol):
    def decide(self, lag_s: float) -> DelayDecision: ...   # con estado (histéresis); determinista


# contracts/metrics.py
class Outcome(StrEnum):
    SPOKEN = "pronunciada"
    DROPPED = "descartada"
    FAILED = "fallida"

@dataclass(frozen=True, slots=True)
class StageTimings:
    t_start_audio: float
    t_end_audio: float
    unit_ready_at: float
    asr_final_at: float | None = None
    mt_started_at: float | None = None
    mt_finished_at: float | None = None
    tts_started_at: float | None = None
    tts_first_audio_at: float | None = None
    tts_finished_at: float | None = None
    play_started_at: float | None = None
    play_finished_at: float | None = None
    @property
    def sentence_delay(self) -> float | None: ...   # play_started_at - t_end_audio

@dataclass(frozen=True, slots=True)
class UtteranceRecord:
    unit_id: int
    source_text: str
    translated_text: str | None
    mode: TranslationMode
    speed: float
    outcome: Outcome
    reason: str | None            # motivo de descarte o fallo
    timings: StageTimings
```

## Tests de contrato obligatorios (`tests/contract/`)
Cada adaptador real se prueba con la misma suite que su doble (el real, con los marcadores que corresponda):
- `AudioSource`: chunks contiguos (`t_start` encadenado), a `CAPTURE_RATE`, `stop()` idempotente y `exhausted` al terminar.
- `AudioSink`: FIFO por unidad, STARTED antes que FINISHED, `cancel_pending` solo toca lo no empezado, `stop()` emite CANCELLED y no deja nada sonando.
- `Vad` y `AsrEngine`: `segment_id` creciente, `revision` creciente, `stable_len` no decrece, FINAL después de `flush()` si había texto, sin eventos con silencio.
- `Segmenter`: `unit_id` creciente, unidades sin solapes, sin texto repetido, ninguna con más de `max_untranslated_s` de habla.
- `Translator`: `unit_id` preservado, `mode` respetado, `rejected` coherente con `text` vacío.
- `Synthesizer`: al menos un trozo, un único `is_last` al final, `sample_rate` constante.
- `DelayController`: monótono con el retraso, histéresis correcta y `drop_oldest_pending` solo por encima de `drop_after_s`.
