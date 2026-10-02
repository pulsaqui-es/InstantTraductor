"""Planificador de frases: estados, orden FIFO, retraso, descartes y registro de cada frase (T029).

El `Scheduler` es lógica pura: no tiene hilos ni E/S propios. Lo mueven las llamadas de la sesión, con el
reloj inyectado, y solo habla con el mundo por tres sitios: el `DelayController` (que decide), el
`AudioSink` (solo `cancel_pending()`) y los *callbacks* `on_record` y `on_lag_sample`.

Estados de una frase (`UnitState`, de `data-model.md`)
------------------------------------------------------
::

    PENDING ─► TRANSLATING ─► SYNTHESIZING ─► QUEUED ─► PLAYING ─► SPOKEN
       └───────────┴──────────────┴────────────┴──► DROPPED   (retraso, parada o cancelada por el sink)
    cualquier estado abierto ─────────────────────► FAILED    (error de un motor tras el reintento)
    TRANSLATING ──────────────────────────────────► REJECTED  (la traducción no pasó los filtros)

Una frase nunca vuelve a un estado anterior. Cada una se traduce una sola vez, y las frases pasan a sonar en
orden estricto de `unit_id` (FR-008): `next_translation()` entrega siempre la más antigua que sigue
pendiente, y el resto de etapas son secuenciales (un hilo de traducción y uno de voz) y el sink reproduce en
FIFO. Cada frase que se cierra produce exactamente un `UtteranceRecord` con su `reason`.

Retraso (`lag`)
---------------
`lag` = `clock.now() − t_end` de la frase abierta más antigua **que aún no ha empezado a sonar**, o 0 si no
hay ninguna. Cuentan, por tanto, `PENDING`, `TRANSLATING`, `SYNTHESIZING` y `QUEUED`, y no `PLAYING`: así no
cuenta el tiempo mientras suena una frase, que daría aceleraciones espurias. `tick()` lo calcula, lo guarda
en una serie (una muestra cada 0,5 s como mínimo) y se lo pasa al `DelayController`.

`tick()` y los descartes (FR-014)
---------------------------------
Una sola decisión por `tick()` mientras no haya descartes. Si la decisión pide `drop_oldest_pending`, se
descarta la frase más antigua que no ha empezado a sonar y se vuelve a decidir con el retraso nuevo;
así se repite, de más antigua a más reciente, mientras el controlador siga pidiendo descartar. En la práctica
cae toda frase pendiente más vieja que el tercer umbral. Lo que devuelve `tick()` es la decisión **vigente
después de los descartes**, y es la que usan `next_translation()` (el `mode`) y `on_translation()` (la
`speed`) hasta el siguiente `tick()`.

- Una frase `PENDING`, `TRANSLATING` o `SYNTHESIZING` se cierra sin más (su resultado, si llega tarde, se
  ignora; la voz debe consultar `is_open()` entre trozo y trozo para dejar de sintetizarla).
- Una frase `QUEUED` está ya en el sink, así que se llama a `sink.cancel_pending()`. Ese método descarta
  **todo** lo que no ha empezado (no solo la más antigua), y el planificador cierra como descartadas todas
  las que el sink devuelve. Si el sink no cancela la unidad (porque justo ha empezado a sonar), se deja el
  descarte para el siguiente `tick()`.
- Nunca se descarta una frase `PLAYING`.

Hilos
-----
Todos los métodos son seguros entre hilos (un `RLock`). El cerrojo **no** se mantiene al llamar al sink ni a
los *callbacks*: así un sink que entregue sus eventos desde su hilo de audio, o un `on_record` lento, no
pueden provocar un interbloqueo. Los registros se entregan de uno en uno y en el orden en que se cerraron.

Orden de llamadas recomendado a la sesión
-----------------------------------------
- Arranque: `sink.start(scheduler.on_playback_event)`.
- Segmentador: `add_unit(unit, asr_final_at=..., captured_at=...)`.
- Hilo de traducción: `next_translation()` → `translator.translate(request)` → `on_translation(result)`; si la
  traducción lanza `EngineError` tras el reintento, `on_failure(unit_id, motivo)`.
- Hilo de voz, con cada `SynthesisRequest`: `on_tts_started` → con el primer trozo, `on_tts_first_audio` → con
  el último, `on_tts_finished`; cada llamada **antes** de `sink.enqueue()` de ese trozo (el sink puede
  emitir STARTED desde dentro de `enqueue`). Entre trozos, comprobar `is_open(unit_id)`.
- Hilo de control: `tick()` unas 2–4 veces por segundo.
- Parada: `scheduler.stop()` y después `sink.stop()` (los CANCELLED que emite el sink ya no cuentan).
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from instanttraductor.contracts import (
    AudioSink,
    Clock,
    DelayController,
    DelayDecision,
    DelayPolicy,
    GlossaryEntry,
    Outcome,
    PlaybackEvent,
    PlaybackEventKind,
    SourceLanguage,
    StageTimings,
    SynthesisRequest,
    TranslationMode,
    TranslationRequest,
    TranslationResult,
    TranslationUnit,
    UtteranceRecord,
    VoiceRef,
)
from instanttraductor.pipeline.delay import speed_for_lag

__all__ = [
    "CANCELLED_REASON",
    "CUT_REASON",
    "DROP_REASON_LAG",
    "LAG_SAMPLE_INTERVAL_S",
    "LANGUAGE_REJECTED_REASON",
    "REJECTED_REASON",
    "STOP_REASON",
    "Scheduler",
    "UnitState",
]

logger = logging.getLogger(__name__)

#: Lo que se suma al retraso previsto al traducir: la traducción y el primer audio de la voz (≈ 0,5 s).
PREDICTION_MARGIN_S: Final = 0.5
LAG_SAMPLE_INTERVAL_S: Final = 0.5  # una muestra de retraso cada 0,5 s (contracts/informe.md)
DROP_REASON_LAG: Final = "retraso excesivo"  # FR-014: descartada por la política de retraso
STOP_REASON: Final = "parada"  # lo pendiente al detener la sesión
REJECTED_REASON: Final = "traducción rechazada por los filtros de salida"
LANGUAGE_REJECTED_REASON: Final = "idioma"  # spec 002: el verificador dice que no es el idioma elegido
CUT_REASON: Final = "cortada mientras sonaba"  # el sink canceló la frase que estaba sonando
CANCELLED_REASON: Final = "cancelada antes de sonar"  # el sink canceló una frase que esperaba

_SAMPLE_TOLERANCE_S: Final = 1e-9
_NEUTRAL: Final = DelayDecision(speed=1.0, mode=TranslationMode.NORMAL, drop_oldest_pending=False)


class UnitState(StrEnum):
    """Estado de una frase (`data-model.md`). Los valores son los nombres de la spec."""

    PENDING = "pendiente"
    TRANSLATING = "traduciendo"
    SYNTHESIZING = "sintetizando"
    QUEUED = "en_cola"  # con audio en la cola del sink, esperando su turno
    PLAYING = "sonando"
    SPOKEN = "pronunciada"
    DROPPED = "descartada"
    REJECTED = "rechazada"
    FAILED = "fallida"


#: Frases que aún no han empezado a sonar: las que cuentan para el retraso y las que se pueden descartar.
_NOT_STARTED: Final = frozenset(
    {UnitState.PENDING, UnitState.TRANSLATING, UnitState.SYNTHESIZING, UnitState.QUEUED}
)
#: Frases con la traducción hecha, para las que tienen sentido los avisos de la voz.
_IN_VOICE_STAGES: Final = frozenset({UnitState.SYNTHESIZING, UnitState.QUEUED, UnitState.PLAYING})
_OUTCOMES: Final = {
    UnitState.SPOKEN: Outcome.SPOKEN,
    UnitState.DROPPED: Outcome.DROPPED,
    UnitState.REJECTED: Outcome.REJECTED,
    UnitState.FAILED: Outcome.FAILED,
}


@dataclass(slots=True)
class _Phrase:
    """Una frase abierta y lo que se sabe de su recorrido (mutable; solo la toca el planificador)."""

    unit: TranslationUnit
    asr_final_at: float | None
    captured_at: float | None
    state: UnitState = UnitState.PENDING
    mode: TranslationMode = TranslationMode.NORMAL
    speed: float = 1.0
    translated_text: str | None = None
    mt_started_at: float | None = None
    mt_finished_at: float | None = None
    tts_started_at: float | None = None
    tts_first_audio_at: float | None = None
    tts_finished_at: float | None = None
    play_started_at: float | None = None
    play_finished_at: float | None = None
    lid_done_at: float | None = None

    def timings(self) -> StageTimings:
        unit = self.unit
        return StageTimings(
            t_start_audio=unit.t_start,
            t_end_audio=unit.t_end,
            unit_ready_at=unit.ready_at,
            captured_at=self.captured_at,
            asr_final_at=self.asr_final_at,
            mt_started_at=self.mt_started_at,
            mt_finished_at=self.mt_finished_at,
            tts_started_at=self.tts_started_at,
            tts_first_audio_at=self.tts_first_audio_at,
            tts_finished_at=self.tts_finished_at,
            play_started_at=self.play_started_at,
            play_finished_at=self.play_finished_at,
            lid_done_at=self.lid_done_at,
        )


class Scheduler:
    """Cola de frases en FIFO con su máquina de estados, el control del retraso y el registro por frase.

    - `clock`: reloj de sesión (para el retraso y para los tiempos que no se pasan explícitos).
    - `delay_controller`: decide velocidad, modo y descartes a partir del retraso.
    - `sink`: solo se usa `cancel_pending()`, para descartar frases que ya están en su cola. El `start()`
      del sink lo hace la sesión: `sink.start(scheduler.on_playback_event)`.
    - `voice`: voz de las peticiones de síntesis (`VoiceRef` o su id).
    - `context_utterances`: cuántas frases ya pronunciadas van como contexto de cada traducción.
    - `glossary`: pares (inglés, español) del usuario, como `GlossaryEntry` o como tuplas.
    - `on_record`: recibe el `UtteranceRecord` de cada frase al cerrarse, de uno en uno y en orden, fuera
      del cerrojo y desde el hilo que la cerró. Una excepción suya se registra y no afecta al planificador.
    - `on_lag_sample`: recibe `(t, lag)` cada vez que se guarda una muestra de la serie de retraso.
    - `lag_interval_s`: separación mínima entre muestras de la serie (0,5 s).
    """

    def __init__(
        self,
        clock: Clock,
        delay_controller: DelayController,
        sink: AudioSink,
        *,
        voice: VoiceRef | str,
        context_utterances: int = 4,
        glossary: Iterable[GlossaryEntry | tuple[str, str]] = (),
        on_record: Callable[[UtteranceRecord], None] | None = None,
        on_lag_sample: Callable[[float, float], None] | None = None,
        lag_interval_s: float = LAG_SAMPLE_INTERVAL_S,
        source_language: SourceLanguage = SourceLanguage.EN,
    ) -> None:
        if context_utterances < 0:
            raise ValueError(f"context_utterances no puede ser negativo (recibido: {context_utterances}).")
        if not lag_interval_s > 0:
            raise ValueError(f"lag_interval_s debe ser positivo (recibido: {lag_interval_s}).")
        self._clock = clock
        self._delay_controller = delay_controller
        self._sink = sink
        self._voice = VoiceRef(voice) if isinstance(voice, str) else voice
        self._glossary = tuple(
            entry if isinstance(entry, GlossaryEntry) else GlossaryEntry(*entry) for entry in glossary
        )
        self._on_record = on_record
        self._on_lag_sample = on_lag_sample
        self._lag_interval_s = lag_interval_s
        self._source_language = SourceLanguage(source_language)

        self._lock = threading.RLock()
        self._open: dict[int, _Phrase] = {}  # frases sin cerrar, en orden de unit_id
        self._final_states: dict[int, UnitState] = {}  # estado de las cerradas
        self._context: deque[tuple[str, str]] = deque(maxlen=context_utterances)
        self._last_unit_id: int | None = None
        self._decision = _NEUTRAL
        self._lag_series: list[tuple[float, float]] = []
        self._last_sample_at: float | None = None
        self._stopped = False
        self._stop_reason = STOP_REASON
        self._sink_cancel_reason: str | None = None  # motivo de los CANCELLED provocados por nosotros
        self._outbox: deque[UtteranceRecord] = deque()
        self._delivering = False

    # --- entrada de frases y traducción ----------------------------------------------------------------

    def add_unit(
        self,
        unit: TranslationUnit,
        *,
        asr_final_at: float | None = None,
        captured_at: float | None = None,
    ) -> None:
        """Añade una frase nueva en estado `PENDING`.

        `unit_id` debe crecer estrictamente (`ValueError` si no). `asr_final_at` y `captured_at` (reloj de
        sesión) son los tiempos que solo conoce la sesión y que van al `StageTimings`. Tras `stop()`, la frase
        se registra directamente como descartada por la parada.
        """
        with self._lock:
            if self._last_unit_id is not None and unit.unit_id <= self._last_unit_id:
                raise ValueError(
                    f"unit_id debe crecer estrictamente: llega {unit.unit_id} "
                    f"después de {self._last_unit_id}."
                )
            self._last_unit_id = unit.unit_id
            phrase = _Phrase(unit, asr_final_at=asr_final_at, captured_at=captured_at)
            self._open[unit.unit_id] = phrase
            if self._stopped:
                self._close_locked(phrase, UnitState.DROPPED, self._stop_reason)
        self._deliver()

    def next_translation(self) -> TranslationRequest | None:
        """La petición de traducción de la frase `PENDING` más antigua, que pasa a `TRANSLATING`.

        El `mode` es el de la última decisión de retraso. El contexto son los pares (original, traducción) de
        las últimas `context_utterances` frases **ya pronunciadas**, de la más antigua a la más reciente.
        Devuelve `None` si no hay nada pendiente o si el planificador está parado.
        """
        pending_audio = self._sink_pending_seconds()  # fuera del cerrojo: el sink tiene el suyo
        with self._lock:
            if self._stopped:
                return None
            phrase = next((p for p in self._open.values() if p.state is UnitState.PENDING), None)
            if phrase is None:
                return None
            phrase.state = UnitState.TRANSLATING
            phrase.mode = self._decision.mode
            # Retraso previsto (validación de la 002): lo que ya espera la frase más el audio pendiente en el
            # sink, que tiene que sonar antes. Si eso ya pasa del umbral de resumir, se resume desde ahora.
            policy = self._policy()
            predicted = max(0.0, self._clock.now() - phrase.unit.t_end) + pending_audio + PREDICTION_MARGIN_S
            if policy is not None and policy.allow_concise and predicted > policy.concise_after_s:
                phrase.mode = TranslationMode.CONCISE
            phrase.mt_started_at = self._clock.now()
            return TranslationRequest(
                unit=phrase.unit,
                context=tuple(self._context),
                glossary=self._glossary,
                mode=phrase.mode,
                source_language=self._source_language,
            )

    def on_translation(self, result: TranslationResult) -> SynthesisRequest | None:
        """Recibe la traducción de una frase `TRANSLATING`.

        - Rechazada (o vacía): la frase se cierra como `REJECTED` y no hay síntesis.
        - Aceptada: pasa a `SYNTHESIZING` y se devuelve su `SynthesisRequest`, con la velocidad de la última
          decisión de retraso (queda fijada para esta frase).
        - Frase desconocida, ya cerrada (descartada o fallida mientras traducía) o ya traducida: `None`.
        """
        request: SynthesisRequest | None = None
        with self._lock:
            phrase = self._open.get(result.unit_id)
            if phrase is None or phrase.state is not UnitState.TRANSLATING:
                return None
            phrase.mt_started_at = result.started_at
            phrase.mt_finished_at = result.finished_at
            phrase.mode = result.mode
            if result.rejected or not result.text.strip():
                self._close_locked(phrase, UnitState.REJECTED, REJECTED_REASON)
            else:
                phrase.translated_text = result.text
                phrase.speed = self._decision.speed
                phrase.state = UnitState.SYNTHESIZING
                request = SynthesisRequest(
                    unit_id=phrase.unit.unit_id,
                    text=result.text,
                    voice=self._voice,
                    speed=phrase.speed,
                )
        self._deliver()
        return request

    # --- síntesis y reproducción -----------------------------------------------------------------------

    def on_tts_started(self, unit_id: int, at: float | None = None) -> None:
        """La voz empieza a sintetizar la frase (`at`: reloj de sesión; por defecto, ahora)."""
        with self._lock:
            phrase = self._voice_phrase_locked(unit_id)
            if phrase is not None and phrase.tts_started_at is None:
                phrase.tts_started_at = self._now_or(at)

    def on_tts_first_audio(self, unit_id: int, at: float | None = None) -> None:
        """Sale el primer audio de la frase: `SYNTHESIZING` pasa a `QUEUED`. Solo cuenta la primera vez."""
        with self._lock:
            phrase = self._voice_phrase_locked(unit_id)
            if phrase is None:
                return
            if phrase.tts_first_audio_at is None:
                phrase.tts_first_audio_at = self._now_or(at)
            if phrase.state is UnitState.SYNTHESIZING:
                phrase.state = UnitState.QUEUED

    def on_tts_finished(self, unit_id: int, at: float | None = None) -> None:
        """La voz termina de sintetizar la frase (el último trozo ya salió)."""
        with self._lock:
            phrase = self._voice_phrase_locked(unit_id)
            if phrase is not None and phrase.tts_finished_at is None:
                phrase.tts_finished_at = self._now_or(at)

    def on_playback_event(self, event: PlaybackEvent) -> None:
        """Evento del sink: STARTED → `PLAYING`; FINISHED → `SPOKEN`; CANCELLED → `DROPPED`.

        Los eventos de frases desconocidas o ya cerradas se ignoran. Es el *callback* de `sink.start()`.
        """
        with self._lock:
            phrase = self._open.get(event.unit_id)
            if phrase is not None:
                if event.kind is PlaybackEventKind.STARTED:
                    self._on_started_locked(phrase, event.at)
                elif event.kind is PlaybackEventKind.FINISHED:
                    self._on_finished_locked(phrase, event.at)
                else:
                    self._on_cancelled_locked(phrase)
        self._deliver()

    def _policy(self) -> DelayPolicy | None:
        """La política del controlador, si la expone (`ThresholdDelayController` sí)."""
        return getattr(self._delay_controller, "policy", None)

    def _sink_pending_seconds(self) -> float:
        try:
            return max(0.0, float(self._sink.pending_seconds()))
        except Exception:  # un sink raro no debe tumbar al planificador
            return 0.0

    def refresh_speed(self, unit_id: int) -> float:
        """Velocidad de la frase justo antes de sintetizarla (FR-012).

        Es la mayor entre la que se fijó al traducirla y la de la última decisión de retraso, y queda anotada
        para el informe. 1,0 si la frase ya no está abierta.
        """
        pending_audio = self._sink_pending_seconds()  # fuera del cerrojo: el sink tiene el suyo
        with self._lock:
            phrase = self._open.get(unit_id)
            if phrase is None:
                return 1.0
            speed = max(phrase.speed, self._decision.speed)
            policy = self._policy()
            if policy is not None:
                predicted = max(0.0, self._clock.now() - phrase.unit.t_end) + pending_audio
                speed = max(speed, speed_for_lag(policy, predicted))
            phrase.speed = speed
            return phrase.speed

    @property
    def source_language(self) -> SourceLanguage:
        return self._source_language

    def on_language_checked(self, unit_id: int, *, accepted: bool) -> None:
        """Resultado del verificador de idioma (spec 002) para una frase `TRANSLATING`.

        Anota cuándo acabó y, si no es el idioma elegido, la cierra como `REJECTED` con el motivo «idioma»:
        no se traduce ni suena.
        """
        with self._lock:
            phrase = self._open.get(unit_id)
            if phrase is not None:
                phrase.lid_done_at = self._clock.now()
                if not accepted:
                    self._close_locked(phrase, UnitState.REJECTED, LANGUAGE_REJECTED_REASON)
        self._deliver()

    def on_failure(self, unit_id: int, reason: str) -> None:
        """Un motor falló con esta frase (tras el reintento): se cierra como `FAILED` con el motivo."""
        with self._lock:
            phrase = self._open.get(unit_id)
            if phrase is not None:
                self._close_locked(phrase, UnitState.FAILED, reason)
        self._deliver()

    # --- retraso, descartes y parada --------------------------------------------------------------------

    def tick(self) -> DelayDecision:
        """Mide el retraso, decide y aplica los descartes. Devuelve la decisión vigente tras los descartes.

        Guarda una muestra `(t, lag)` en la serie si pasaron al menos `lag_interval_s` desde la anterior
        (el retraso medido antes de descartar) y la envía a `on_lag_sample`.
        """
        with self._lock:
            now = self._clock.now()
            lag = self._lag_locked(now)
            sample = self._take_sample_locked(now, lag)
            self._decision = self._delay_controller.decide(lag)
        if sample is not None:
            self._emit_sample(sample)
        self._apply_drops()
        with self._lock:
            return self._decision

    def lag(self) -> float:
        """Retraso actual en segundos (0 si no hay ninguna frase esperando para sonar)."""
        with self._lock:
            return self._lag_locked(self._clock.now())

    def stop(self, reason: str = STOP_REASON) -> None:
        """Cierra como `DROPPED` (con `reason`) todo lo que sigue abierto, incluso lo que suena. Idempotente.

        No toca el sink: la sesión llama después a `sink.stop()`. Tras la parada no se reparte más trabajo.
        """
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            self._stop_reason = reason
            for phrase in list(self._open.values()):
                self._close_locked(phrase, UnitState.DROPPED, reason)
        self._deliver()

    # --- consultas -------------------------------------------------------------------------------------

    @property
    def decision(self) -> DelayDecision:
        """La última decisión de retraso (neutra antes del primer `tick()`): velocidad, modo y descarte."""
        with self._lock:
            return self._decision

    @property
    def open_count(self) -> int:
        """Frases sin cerrar (todavía sin resultado). Con 0, la sesión puede darse por vaciada."""
        with self._lock:
            return len(self._open)

    @property
    def stopped(self) -> bool:
        with self._lock:
            return self._stopped

    def is_open(self, unit_id: int) -> bool:
        """True si la frase existe y no se ha cerrado: la voz deja de sintetizar cuando pasa a False."""
        with self._lock:
            return unit_id in self._open

    def state_of(self, unit_id: int) -> UnitState | None:
        """Estado de la frase (abierta o cerrada), o `None` si no se conoce."""
        with self._lock:
            phrase = self._open.get(unit_id)
            return phrase.state if phrase is not None else self._final_states.get(unit_id)

    def lag_series(self) -> tuple[tuple[float, float], ...]:
        """Copia de la serie de retraso: pares `(t, lag)` en el reloj de sesión."""
        with self._lock:
            return tuple(self._lag_series)

    # --- internos: transiciones (con el cerrojo tomado) ---------------------------------------------------

    def _now_or(self, at: float | None) -> float:
        return self._clock.now() if at is None else at

    def _voice_phrase_locked(self, unit_id: int) -> _Phrase | None:
        phrase = self._open.get(unit_id)
        return phrase if phrase is not None and phrase.state in _IN_VOICE_STAGES else None

    def _on_started_locked(self, phrase: _Phrase, at: float) -> None:
        if phrase.state in (UnitState.SYNTHESIZING, UnitState.QUEUED):
            phrase.state = UnitState.PLAYING
            phrase.play_started_at = at

    def _on_finished_locked(self, phrase: _Phrase, at: float) -> None:
        if phrase.state in _IN_VOICE_STAGES:
            phrase.play_finished_at = at
            self._close_locked(phrase, UnitState.SPOKEN, None)

    def _on_cancelled_locked(self, phrase: _Phrase) -> None:
        if phrase.state is UnitState.PLAYING:
            reason = CUT_REASON
        elif self._sink_cancel_reason is not None:
            reason = self._sink_cancel_reason  # la cancelación la provocó un descarte nuestro
        else:
            reason = CANCELLED_REASON
        self._close_locked(phrase, UnitState.DROPPED, reason)

    def _close_locked(self, phrase: _Phrase, state: UnitState, reason: str | None) -> None:
        """Cierra la frase: la saca de las abiertas y deja su `UtteranceRecord` en la salida."""
        unit = phrase.unit
        phrase.state = state
        self._open.pop(unit.unit_id, None)
        self._final_states[unit.unit_id] = state
        if state is UnitState.SPOKEN and phrase.translated_text is not None:
            self._context.append((unit.source_text, phrase.translated_text))
        self._outbox.append(
            UtteranceRecord(
                unit_id=unit.unit_id,
                source_text=unit.source_text,
                translated_text=phrase.translated_text,
                mode=phrase.mode,
                speed=phrase.speed,
                outcome=_OUTCOMES[state],
                reason=reason,
                timings=phrase.timings(),
            )
        )

    # --- internos: retraso y descartes ----------------------------------------------------------------

    def _oldest_not_started_locked(self) -> _Phrase | None:
        return next((p for p in self._open.values() if p.state in _NOT_STARTED), None)

    def _lag_locked(self, now: float) -> float:
        oldest = self._oldest_not_started_locked()
        return 0.0 if oldest is None else max(0.0, now - oldest.unit.t_end)

    def _take_sample_locked(self, now: float, lag: float) -> tuple[float, float] | None:
        last = self._last_sample_at
        if last is not None and now - last < self._lag_interval_s - _SAMPLE_TOLERANCE_S:
            return None
        self._last_sample_at = now
        sample = (now, lag)
        self._lag_series.append(sample)
        return sample

    def _emit_sample(self, sample: tuple[float, float]) -> None:
        if self._on_lag_sample is None:
            return
        try:
            self._on_lag_sample(*sample)
        except Exception:
            logger.exception("Falló el callback on_lag_sample")

    def _apply_drops(self) -> None:
        """Descarta, de más antigua a más reciente, mientras la decisión pida descartar (ver el módulo)."""
        while True:
            with self._lock:
                if not self._decision.drop_oldest_pending:
                    break
                victim = self._oldest_not_started_locked()
                if victim is None:
                    break
                victim_id = victim.unit.unit_id
                in_sink = victim.state is UnitState.QUEUED
                if in_sink:
                    self._sink_cancel_reason = DROP_REASON_LAG
                else:
                    self._close_locked(victim, UnitState.DROPPED, DROP_REASON_LAG)
            if in_sink and not self._cancel_in_sink(victim_id):
                break  # el sink no la canceló (acaba de empezar a sonar): se reintenta en el siguiente tick
            with self._lock:
                self._decision = self._delay_controller.decide(self._lag_locked(self._clock.now()))
        self._deliver()

    def _cancel_in_sink(self, victim_id: int) -> bool:
        """Llama a `sink.cancel_pending()` sin el cerrojo y cierra lo que cancela; True si cae `victim_id`."""
        cancelled: list[int] = []
        try:
            cancelled = self._sink.cancel_pending()
        finally:
            with self._lock:
                for unit_id in cancelled:
                    phrase = self._open.get(unit_id)
                    if phrase is not None and phrase.state is not UnitState.PLAYING:
                        self._close_locked(phrase, UnitState.DROPPED, DROP_REASON_LAG)
                self._sink_cancel_reason = None
                dropped = victim_id not in self._open
        return dropped

    # --- internos: entrega de registros ----------------------------------------------------------------

    def _deliver(self) -> None:
        """Entrega los registros pendientes, fuera del cerrojo, de uno en uno y en orden.

        Si otro hilo (o un *callback* que vuelve a entrar) ya está entregando, los registros nuevos los
        entrega ese mismo bucle cuando acabe el *callback* en curso.
        """
        with self._lock:
            if self._delivering:
                return
            self._delivering = True
        try:
            while True:
                with self._lock:
                    if not self._outbox:
                        self._delivering = False
                        return
                    record = self._outbox.popleft()
                self._emit_record(record)
        except BaseException:
            with self._lock:
                self._delivering = False
            raise

    def _emit_record(self, record: UtteranceRecord) -> None:
        if self._on_record is None:
            return
        try:
            self._on_record(record)
        except Exception:
            logger.exception("Falló el callback on_record (frase %s)", record.unit_id)
