"""Suite de contrato de `Segmenter`.

Sale de «Tests de contrato obligatorios», en `specs/001-espina-dorsal/contracts/pipeline.md`:
`unit_id` creciente, unidades sin solapes, sin texto repetido y ninguna con más de `max_untranslated_s`
de habla.

`SegmenterContract` es una clase base que pytest no recoge por sí sola, y aquí **no hay subclase**: la
concreta T020 con `PauseClauseSegmenter` (`tests/unit/pipeline/test_segmenter.py`).
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable

import pytest

from instanttraductor.contracts import (
    AsrEvent,
    AsrEventKind,
    Segmenter,
    TranslationUnit,
    VadEvent,
    VadEventKind,
)
from tests.contract.helpers import assert_implements

Event = AsrEvent | VadEvent

# El segmentador solo corta en palabras estables y recibe parciales cada ~560 ms: puede pasarse del límite
# por un parcial y una palabra antes de poder cortar. Más que eso es un fallo del segmentador.
SLACK_S = 1.0
ORDER_TOLERANCE_S = 1e-6


def words_of(text: str) -> list[str]:
    """Palabras en minúsculas y sin puntuación: así no importa dónde deje las comas el segmentador."""
    return re.findall(r"[\w']+", text.lower())


def spoken(
    segment_id: int,
    text: str,
    t_start: float,
    t_end: float,
    *,
    partial_lag_s: float = 0.4,
    final_lag_s: float = 0.7,
    final_text: str | None = None,
) -> list[Event]:
    """Eventos que recibe el segmentador por un enunciado, en el orden en que los produce el pipeline.

    SPEECH_START del VAD, un PARTIAL por palabra (estable hasta la última palabra completa), SPEECH_END
    del VAD (con `t` = fin del habla) y el FINAL del ASR, que llega tras el vaciado. Los parciales y el
    FINAL llevan en `emitted_at` el instante de sesión en que se emitieron.
    """
    words = text.split()
    events: list[Event] = [VadEvent(VadEventKind.SPEECH_START, t_start)]
    for count in range(1, len(words) + 1):
        t = t_start + (t_end - t_start) * count / len(words)
        events.append(
            AsrEvent(
                kind=AsrEventKind.PARTIAL,
                segment_id=segment_id,
                revision=count - 1,
                text=" ".join(words[:count]),
                stable_len=len(" ".join(words[: count - 1])),
                t_start=t_start,
                t_end=t,
                is_sentence_end=False,
                emitted_at=t + partial_lag_s,
            )
        )
    events.append(VadEvent(VadEventKind.SPEECH_END, t_end))
    final = final_text if final_text is not None else text
    events.append(
        AsrEvent(
            kind=AsrEventKind.FINAL,
            segment_id=segment_id,
            revision=len(words),
            text=final,
            stable_len=len(final),
            t_start=t_start,
            t_end=t_end,
            is_sentence_end=False,
            emitted_at=t_end + final_lag_s,
        )
    )
    return events


def run(segmenter: Segmenter, events: list[Event], *, flush: bool = True) -> list[TranslationUnit]:
    units: list[TranslationUnit] = []
    for event in events:
        units.extend(segmenter.accept(event))
    if flush:
        units.extend(segmenter.flush())
    return units


def assert_well_formed(units: list[TranslationUnit]) -> None:
    """`unit_id` estrictamente creciente, texto no vacío, `t_start < t_end` y sin solapes."""
    for unit in units:
        assert isinstance(unit, TranslationUnit)
        assert unit.source_text.strip(), "una unidad no puede tener el texto vacío"
        assert unit.t_start < unit.t_end, (
            f"unidad {unit.unit_id}: t_start {unit.t_start} >= t_end {unit.t_end}"
        )
        assert math.isfinite(unit.ready_at)
    ids = [u.unit_id for u in units]
    assert all(b > a for a, b in zip(ids, ids[1:], strict=False)), f"`unit_id` no es creciente: {ids}"
    for previous, current in zip(units, units[1:], strict=False):
        assert current.t_start >= previous.t_end - ORDER_TOLERANCE_S, (
            f"las unidades {previous.unit_id} y {current.unit_id} se solapan: "
            f"{previous.t_start:.2f}-{previous.t_end:.2f} y {current.t_start:.2f}-{current.t_end:.2f}"
        )


def assert_covers_once(units: list[TranslationUnit], transcript: str) -> None:
    """Todo lo dicho se emite una sola vez y en orden: sin texto repetido ni perdido."""
    assert words_of(" ".join(u.source_text for u in units)) == words_of(transcript)


LONG_WORDS = [
    f"word{i:02d}" for i in range(40)
]  # sin comas ni conjunciones: solo puede cortar el límite de tiempo
LONG_TEXT = " ".join(LONG_WORDS)
LONG_SENTENCE = (
    "when I got home yesterday, my brother told me that the old car had finally stopped working, "
    "and we laughed about it for a long time because nobody expected that"
)


class SegmenterContract:
    """Contrato de `Segmenter`.

    Para concretarla, sobrescribe:
    - `make_impl` (obligatorio): fábrica de un segmentador nuevo, construido con
      `max_untranslated_s` igual al fixture del mismo nombre (6,0 s por defecto).
    - `max_untranslated_s` (opcional): el límite de habla continua sin emitir unidad.
    """

    @pytest.fixture
    def max_untranslated_s(self) -> float:
        return 6.0

    @pytest.fixture
    def make_impl(self, max_untranslated_s: float) -> Callable[[], Segmenter]:
        raise NotImplementedError("Sobrescribe el fixture `make_impl` en la subclase de la suite.")

    def test_implements_the_protocol(self, make_impl: Callable[[], Segmenter]) -> None:
        assert_implements(make_impl(), Segmenter)

    def test_without_speech_there_are_no_units(self, make_impl: Callable[[], Segmenter]) -> None:
        segmenter = make_impl()
        assert segmenter.flush() == []
        # Un VAD que salta sin que el ASR reconozca nada tampoco produce unidades.
        events: list[Event] = [
            VadEvent(VadEventKind.SPEECH_START, 1.0),
            VadEvent(VadEventKind.SPEECH_END, 1.4),
        ]
        assert run(segmenter, events) == []

    def test_accept_returns_a_list(self, make_impl: Callable[[], Segmenter]) -> None:
        assert isinstance(make_impl().accept(VadEvent(VadEventKind.SPEECH_START, 0.0)), list)

    def test_a_short_utterance_is_one_unit(self, make_impl: Callable[[], Segmenter]) -> None:
        utterances = [
            ("the weather is nice today", 0.0, 2.4),
            ("I think we should go now", 3.4, 6.0),
            ("please close the door behind you", 7.0, 9.0),
        ]
        events: list[Event] = []
        for segment_id, (text, t_start, t_end) in enumerate(utterances):
            events += spoken(segment_id, text, t_start, t_end)
        units = run(make_impl(), events)

        assert_well_formed(units)
        assert len(units) == len(utterances), "una unidad por enunciado: se cierra con la pausa y el FINAL"
        for unit, (text, t_start, t_end) in zip(units, utterances, strict=True):
            assert words_of(unit.source_text) == words_of(text)
            assert unit.t_start == pytest.approx(t_start, abs=0.5)
            assert unit.t_end == pytest.approx(t_end, abs=0.5)
            assert unit.is_sentence_end is True
            assert unit.language == "en"

    def test_a_short_utterance_is_not_emitted_before_the_pause(
        self, make_impl: Callable[[], Segmenter]
    ) -> None:
        """Sin comas, sin conjunciones y sin pasar del límite, nada sale mientras el habla sigue."""
        events = spoken(0, "the weather is nice today", 0.0, 2.4)
        pause = next(
            i for i, e in enumerate(events) if isinstance(e, VadEvent) and e.kind is VadEventKind.SPEECH_END
        )
        assert run(make_impl(), events[:pause], flush=False) == []

    def test_unit_ids_are_strictly_increasing_across_calls(self, make_impl: Callable[[], Segmenter]) -> None:
        segmenter = make_impl()
        first = run(
            segmenter,
            spoken(0, "the weather is nice today", 0.0, 2.4) + spoken(1, "I think we should go", 3.4, 5.4),
        )
        second = run(segmenter, spoken(2, "please close the door behind you", 7.0, 9.0))
        assert first and second
        assert_well_formed(first + second)

    def test_there_is_no_repeated_or_lost_text(self, make_impl: Callable[[], Segmenter]) -> None:
        texts = [
            ("the weather is nice today", 0.0, 2.4),
            (LONG_SENTENCE, 3.4, 9.4),
            ("okay see you tomorrow", 10.4, 12.0),
        ]
        events: list[Event] = []
        for segment_id, (text, t_start, t_end) in enumerate(texts):
            events += spoken(segment_id, text, t_start, t_end)
        units = run(make_impl(), events)
        assert_well_formed(units)
        assert_covers_once(units, " ".join(text for text, _, _ in texts))

    def test_long_speech_never_goes_over_max_untranslated_s_without_a_unit(
        self, make_impl: Callable[[], Segmenter], max_untranslated_s: float
    ) -> None:
        events = spoken(0, LONG_TEXT, 0.0, 15.0)
        segmenter = make_impl()
        units: list[TranslationUnit] = []
        for event in events:
            units.extend(segmenter.accept(event))
            if isinstance(event, AsrEvent) and event.kind is AsrEventKind.PARTIAL:
                covered = units[-1].t_end if units else 0.0
                assert event.t_end - covered <= max_untranslated_s + SLACK_S, (
                    f"con el habla en {event.t_end:.2f} s, lo traducido llega solo a {covered:.2f} s"
                )
        units.extend(segmenter.flush())

        assert_well_formed(units)
        assert_covers_once(units, LONG_TEXT)
        assert len(units) >= 2, "15 s de habla seguida no pueden ser una sola unidad"
        for unit in units:
            assert unit.t_end - unit.t_start <= max_untranslated_s + SLACK_S, (
                f"la unidad {unit.unit_id} tiene {unit.t_end - unit.t_start:.2f} s de habla"
            )
        assert [u.is_sentence_end for u in units] == [False] * (len(units) - 1) + [True]

    def test_only_stable_text_is_emitted(self, make_impl: Callable[[], Segmenter]) -> None:
        """La última palabra del parcial es inestable: el FINAL la corrige y la unidad lleva la corregida."""
        events = spoken(0, "I went to the sea", 0.0, 2.0, final_text="I went to the store")
        units = run(make_impl(), events)
        assert_well_formed(units)
        emitted = words_of(" ".join(u.source_text for u in units))
        assert "sea" not in emitted
        assert emitted == ["i", "went", "to", "the", "store"]

    def test_flush_closes_the_pending_speech_once(self, make_impl: Callable[[], Segmenter]) -> None:
        """Si la sesión acaba en mitad del habla, `flush()` emite lo pendiente (y solo una vez)."""
        segmenter = make_impl()
        events = spoken(0, "the weather is nice today", 0.0, 2.4)
        partials = [e for e in events if isinstance(e, AsrEvent) and e.kind is AsrEventKind.PARTIAL]
        until_the_last_partial = events[: events.index(partials[-1]) + 1]
        before = run(segmenter, until_the_last_partial, flush=False)
        flushed = segmenter.flush()
        units = before + flushed

        assert_well_formed(units)
        emitted = words_of(" ".join(u.source_text for u in units))
        stable = words_of(partials[-1].text[: partials[-1].stable_len])
        everything = words_of(partials[-1].text)
        assert emitted[: len(stable)] == stable, "se perdió texto estable"
        assert emitted == everything[: len(emitted)], "se emitió texto que no es un prefijo de lo dicho"
        assert segmenter.flush() == []

    def test_ids_keep_increasing_after_a_flush(self, make_impl: Callable[[], Segmenter]) -> None:
        segmenter = make_impl()
        first = run(segmenter, spoken(0, "the weather is nice today", 0.0, 2.4))
        second = run(segmenter, spoken(1, "I think we should go now", 3.4, 6.0))
        assert first and second
        assert second[0].unit_id > first[-1].unit_id
