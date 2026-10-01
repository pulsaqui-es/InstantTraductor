"""Segmentador en unidades de traducción: `PauseClauseSegmenter`, que implementa `Segmenter` (R6).

Recibe los eventos del VAD y del ASR en el orden en que los produce la sesión (START, parciales, END del
VAD y FINAL del ASR tras el vaciado) y devuelve unidades de traducción:

- **Una unidad por enunciado.** Se cierra con la pausa del VAD (`SPEECH_END`) y el FINAL del ASR: al llegar
  el FINAL sale lo que quede del segmento, con `is_sentence_end=True`. La puntuación no cierra frases:
  Nemotron casi nunca pone punto final (1 % de los finales).
- **Habla larga: cortes por cláusulas.** Mientras el habla sigue, se corta en una coma o antes de una
  conjunción (`CLAUSE_CONJUNCTIONS`) si el fragmento tiene al menos `MIN_CLAUSE_WORDS` (6) palabras. La coma
  ha de estar en una palabra estable y la conjunción, además, no ser la última palabra del texto. Esas
  unidades llevan `is_sentence_end=False`.
- **Corte forzado.** Si el habla sin traducir supera `max_untranslated_s` (6 s por defecto), se corta en la
  última palabra completa estable (FR-004, FR-005). Se mide en el reloj de audio, desde el final de la unidad
  anterior (o desde el inicio del segmento) hasta el final del audio que lleva el último parcial.
- **Solo texto estable.** Una palabra sale cuando el parcial ya la da por estable (`stable_len`, que no
  parte palabras) o con el FINAL, que es definitivo. Nada se retracta, solapa ni repite: se cuentan las
  palabras ya emitidas del segmento, así que un FINAL que corrige la última palabra solo cambia lo que
  aún no salió.
- **Tiempos.** Sin tiempos por palabra, el final de un corte se estima por la proporción de caracteres
  sobre el intervalo del segmento. La última unidad de un enunciado acaba en el `SPEECH_END` del VAD, que
  es el final real del habla (la base del retardo de frase); sin él, en el final del audio del FINAL. Las
  unidades no se solapan: cada una empieza donde acaba la anterior.
- **`ready_at`** es el reloj de sesión (`Clock` inyectado) cuando se cierra la unidad.

`flush()` cierra lo pendiente emitiendo solo el texto estable: la sesión debe vaciar antes el ASR
(`asr.flush()`) y pasarle el FINAL, para no perder la última palabra. Un segmento nuevo cuyo anterior nunca
tuvo FINAL cierra al anterior igual que `flush()`. No es seguro entre hilos: lo usa un único hilo (el de la
sesión que une VAD, ASR y planificador).
"""

from __future__ import annotations

import math
from typing import Final

from instanttraductor.contracts import (
    AsrEvent,
    AsrEventKind,
    Clock,
    TranslationUnit,
    VadEvent,
    VadEventKind,
)

MIN_CLAUSE_WORDS: Final = 6  # palabras mínimas de un fragmento para cortarlo en una coma o conjunción
CLAUSE_CONJUNCTIONS: Final = frozenset({"and", "but", "because", "so", "which", "when", "while", "if"})
MIN_UNIT_S: Final = 0.05  # una unidad dura al menos esto: `t_start < t_end` siempre
_WORD_PUNCTUATION: Final = ".,;:!?\"'()"


def _is_conjunction(word: str) -> bool:
    return word.lower().strip(_WORD_PUNCTUATION) in CLAUSE_CONJUNCTIONS


def _stable_words(text: str, stable_len: int) -> int:
    """Palabras completas entre los `stable_len` primeros caracteres: una partida por la mitad no cuenta."""
    prefix = text[:stable_len]
    words = prefix.split()
    if prefix and stable_len < len(text) and not prefix[-1].isspace() and not text[stable_len].isspace():
        words = words[:-1]
    return len(words)


class PauseClauseSegmenter:
    """`Segmenter` por pausas del VAD, cláusulas (coma o conjunción) y límite de habla sin traducir."""

    def __init__(self, clock: Clock, *, max_untranslated_s: float = 6.0) -> None:
        if not 0.0 < max_untranslated_s < math.inf:
            raise ValueError(
                f"max_untranslated_s debe ser un número positivo; recibido: {max_untranslated_s}."
            )
        self._clock = clock
        self._max_untranslated_s = max_untranslated_s
        self._next_unit_id = 0
        self._last_unit_end = -math.inf  # fin de la última unidad emitida: la siguiente no empieza antes
        self._vad_end_t: float | None = None  # `SPEECH_END` del enunciado en curso, a la espera de su FINAL
        # Segmento del ASR en curso:
        self._segment_id: int | None
        self._words: list[str]  # palabras de la última hipótesis
        self._n_stable: int  # cuántas de ellas son estables
        self._n_emitted: int  # cuántas ya salieron en alguna unidad
        self._seg_start: float  # `t_start` del segmento (reloj de audio)
        self._audio_end: float  # fin del audio entregado al ASR hasta el último evento
        self._cut_t: float  # hasta dónde llega lo ya traducido: empieza la siguiente unidad
        self._language: str
        self._clear_segment()

    def accept(self, event: AsrEvent | VadEvent) -> list[TranslationUnit]:
        if isinstance(event, VadEvent):
            # El FINAL llega después del `SPEECH_END` y es quien cierra la unidad: aquí solo se anota el fin.
            if event.kind is VadEventKind.SPEECH_END:
                self._vad_end_t = event.t
            return []
        return self._accept_asr(event)

    def flush(self) -> list[TranslationUnit]:
        """Cierra lo pendiente con el texto estable. Una segunda llamada no tiene nada que cerrar."""
        return self._close_pending()

    # ------------------------------------------------------------------ ASR

    def _accept_asr(self, event: AsrEvent) -> list[TranslationUnit]:
        units: list[TranslationUnit] = []
        if self._segment_id is not None and event.segment_id != self._segment_id:
            units.extend(self._close_pending())  # el segmento anterior no llegó a tener FINAL
        if self._segment_id is None:
            if self._vad_end_t is not None and self._vad_end_t <= event.t_start:
                self._vad_end_t = None  # es el fin de un enunciado anterior
            self._segment_id = event.segment_id
            self._seg_start = event.t_start
            self._cut_t = max(event.t_start, self._last_unit_end)
            self._language = event.language

        final = event.kind is AsrEventKind.FINAL
        self._words = event.text.split()
        stable = (
            len(self._words) if final else max(self._n_stable, _stable_words(event.text, event.stable_len))
        )
        self._n_stable = min(stable, len(self._words))
        self._audio_end = max(self._audio_end, event.t_end)

        units.extend(self._cut_clauses(final=final))
        if final:
            if self._n_emitted < len(self._words):
                t_end = self._vad_end_t if self._vad_end_t is not None else self._audio_end
                units.append(self._emit(len(self._words), sentence_end=True, t_end=t_end))
            self._end_segment()
        return units

    def _cut_clauses(self, *, final: bool) -> list[TranslationUnit]:
        """Emite los fragmentos completos: por coma o conjunción y, si se pasa del tiempo, el corte forzado.

        Con el FINAL (todo estable) solo se cortan cláusulas, y siempre queda al menos la última palabra
        para la unidad que cierra el enunciado.
        """
        units: list[TranslationUnit] = []
        limit = len(self._words) if final else self._n_stable  # palabras que se pueden emitir
        while self._n_emitted < limit:
            cut = self._clause_cut(limit, final=final)
            if cut is None and not final and self._audio_end - self._cut_t > self._max_untranslated_s:
                cut = limit  # la última palabra completa estable
            if cut is None:
                break
            units.append(self._emit(cut, sentence_end=False))
        return units

    def _clause_cut(self, limit: int, *, final: bool) -> int | None:
        """Primer corte de cláusula entre las palabras pendientes: hasta qué palabra llega el fragmento."""
        start = self._n_emitted
        words = self._words
        max_cut = limit - 1 if final else limit
        for i in range(start, limit):
            # Antes de una conjunción, con una palabra detrás (si no, se quedaría sola).
            if i - start >= MIN_CLAUSE_WORDS and i < len(words) - 1 and _is_conjunction(words[i]):
                return i
            # Tras una coma.
            if words[i].endswith(",") and i + 1 - start >= MIN_CLAUSE_WORDS and i + 1 <= max_cut:
                return i + 1
        return None

    # ------------------------------------------------------------------ unidades

    def _emit(self, cut: int, *, sentence_end: bool, t_end: float | None = None) -> TranslationUnit:
        """Unidad con las palabras pendientes hasta `cut` (exclusive)."""
        t_start = self._cut_t
        end = max(t_end if t_end is not None else self._estimate_time(cut), t_start + MIN_UNIT_S)
        unit = TranslationUnit(
            unit_id=self._next_unit_id,
            source_text=" ".join(self._words[self._n_emitted : cut]),
            t_start=t_start,
            t_end=end,
            is_sentence_end=sentence_end,
            ready_at=self._clock.now(),
            language=self._language,
        )
        self._next_unit_id += 1
        self._n_emitted = cut
        self._cut_t = end
        self._last_unit_end = end
        return unit

    def _estimate_time(self, cut: int) -> float:
        """Sin tiempos por palabra: dónde acaba el corte `cut`, por la proporción de caracteres del texto."""
        total = len(" ".join(self._words))
        if total == 0:
            return self._audio_end
        spoken = len(" ".join(self._words[:cut]))
        return self._seg_start + (self._audio_end - self._seg_start) * spoken / total

    def _close_pending(self) -> list[TranslationUnit]:
        """Fin del segmento sin FINAL: se emite solo lo estable, como cierre de enunciado."""
        units: list[TranslationUnit] = []
        if self._segment_id is not None and self._n_stable > self._n_emitted:
            t_end = self._vad_end_t if self._vad_end_t is not None else self._estimate_time(self._n_stable)
            units.append(self._emit(self._n_stable, sentence_end=True, t_end=t_end))
        self._end_segment()
        return units

    def _end_segment(self) -> None:
        self._clear_segment()
        self._vad_end_t = None

    def _clear_segment(self) -> None:
        self._segment_id = None
        self._words = []
        self._n_stable = 0
        self._n_emitted = 0
        self._seg_start = 0.0
        self._audio_end = 0.0
        self._cut_t = 0.0
        self._language = "en"
