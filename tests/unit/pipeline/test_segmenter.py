"""Tests de `PauseClauseSegmenter` (T020): la suite de contrato `SegmenterContract` y las reglas de R6.

R6: una unidad por enunciado (se cierra con `SPEECH_END` y el FINAL del ASR); con habla larga se corta en una
coma o una conjunción estable si el fragmento tiene al menos 6 palabras; corte forzado en la última palabra
completa estable al pasar `max_untranslated_s`; solo texto estable; `t_end` por la proporción de caracteres.
"""

from __future__ import annotations

import random
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
from instanttraductor.pipeline.clock import ManualClock
from instanttraductor.pipeline.segmenter import CLAUSE_CONJUNCTIONS, MIN_CLAUSE_WORDS, PauseClauseSegmenter
from tests.contract.test_units_contract import (
    LONG_SENTENCE,
    SLACK_S,
    Event,
    SegmenterContract,
    assert_covers_once,
    assert_well_formed,
    run,
    words_of,
)

START = VadEventKind.SPEECH_START
END = VadEventKind.SPEECH_END
PARTIAL = AsrEventKind.PARTIAL
FINAL = AsrEventKind.FINAL


class TestPauseClauseSegmenterContract(SegmenterContract):
    @pytest.fixture
    def make_impl(self, max_untranslated_s: float) -> Callable[[], Segmenter]:
        return lambda: PauseClauseSegmenter(ManualClock(), max_untranslated_s=max_untranslated_s)


# --------------------------------------------------------------------------------------------------
# Ayudantes
# --------------------------------------------------------------------------------------------------


def make(
    max_untranslated_s: float = 6.0, *, min_tail_words: int = 1
) -> tuple[PauseClauseSegmenter, ManualClock]:
    """Segmentador de prueba. Por defecto con cola mínima 1 (la mecánica de cortes de la 001); la cola mínima
    de la spec 002 se prueba en `TestMinimumTail`."""
    clock = ManualClock()
    segmenter = PauseClauseSegmenter(
        clock, max_untranslated_s=max_untranslated_s, min_tail_words=min_tail_words
    )
    return segmenter, clock


def utterance(
    text: str,
    t_start: float,
    t_end: float,
    *,
    segment_id: int = 0,
    step: int = 1,
    vad: bool = True,
    final_t_end: float | None = None,
    final_text: str | None = None,
    language: str = "en",
) -> list[Event]:
    """Eventos de un enunciado con `step` palabras nuevas por parcial (como un reconocedor por trozos)."""
    words = text.split()
    events: list[Event] = []
    if vad:
        events.append(VadEvent(START, t_start))
    revision = 0
    shown = 0
    while shown < len(words):
        shown = min(len(words), shown + step)
        events.append(
            AsrEvent(
                kind=PARTIAL,
                segment_id=segment_id,
                revision=revision,
                text=" ".join(words[:shown]),
                stable_len=len(" ".join(words[: shown - 1])),
                t_start=t_start,
                t_end=t_start + (t_end - t_start) * shown / len(words),
                is_sentence_end=False,
                emitted_at=0.0,
                language=language,
            )
        )
        revision += 1
    if vad:
        events.append(VadEvent(END, t_end))
    final = final_text if final_text is not None else text
    events.append(
        AsrEvent(
            kind=FINAL,
            segment_id=segment_id,
            revision=revision,
            text=final,
            stable_len=len(final),
            t_start=t_start,
            t_end=final_t_end if final_t_end is not None else t_end,
            is_sentence_end=False,
            emitted_at=0.0,
            language=language,
        )
    )
    return events


def feed(segmenter: Segmenter, events: list[Event]) -> list[list[TranslationUnit]]:
    """Unidades que produce cada evento (para ver CUÁNDO sale cada una)."""
    return [segmenter.accept(event) for event in events]


def texts(units: list[TranslationUnit]) -> list[str]:
    return [u.source_text for u in units]


def split_words(text: str) -> list[str]:
    return text.split()


def asr_event(
    segment_id: int,
    text: str,
    stable_len: int,
    t_end: float,
    *,
    t_start: float = 0.0,
    kind: AsrEventKind = PARTIAL,
) -> AsrEvent:
    return AsrEvent(
        kind=kind,
        segment_id=segment_id,
        revision=0,
        text=text,
        stable_len=stable_len,
        t_start=t_start,
        t_end=t_end,
        is_sentence_end=False,
        emitted_at=0.0,
    )


# --------------------------------------------------------------------------------------------------
# Una unidad por enunciado
# --------------------------------------------------------------------------------------------------


class TestUtterances:
    def test_the_unit_is_closed_by_the_final_with_the_vad_end_as_its_end(self) -> None:
        segmenter, _ = make()
        units = run(segmenter, utterance("the weather is nice today", 1.0, 3.4, final_t_end=3.9))
        (unit,) = units
        assert unit.source_text == "the weather is nice today"
        assert unit.t_start == 1.0
        assert unit.t_end == 3.4, "el fin real del habla (SPEECH_END), no el del audio entregado al ASR"
        assert unit.is_sentence_end is True

    def test_without_a_vad_end_the_unit_ends_where_the_final_ends(self) -> None:
        segmenter, _ = make()
        (unit,) = run(segmenter, utterance("the weather is nice today", 1.0, 3.4, vad=False, final_t_end=3.9))
        assert unit.t_end == 3.9

    def test_nothing_comes_out_at_the_vad_end_only_at_the_final(self) -> None:
        segmenter, _ = make()
        events = utterance("the weather is nice today", 0.0, 2.4)
        produced = feed(segmenter, events)
        emitting = [i for i, units in enumerate(produced) if units]
        assert emitting == [len(events) - 1], "solo el FINAL cierra la unidad"

    def test_a_final_without_earlier_partials_is_a_unit_by_itself(self) -> None:
        segmenter, _ = make()
        final = asr_event(0, "Okay.", 5, 1.0, t_start=0.4, kind=FINAL)
        (unit,) = segmenter.accept(final)
        assert (unit.source_text, unit.t_start, unit.t_end, unit.is_sentence_end) == ("Okay.", 0.4, 1.0, True)

    def test_an_empty_final_makes_no_unit(self) -> None:
        segmenter, _ = make()
        assert segmenter.accept(asr_event(0, "", 0, 1.0, kind=FINAL)) == []

    def test_the_unit_text_is_the_final_text_with_single_spaces(self) -> None:
        segmenter, _ = make()
        (unit,) = run(segmenter, utterance("a  b   c", 0.0, 1.0, final_text="Hello,  world.   Bye"))
        assert unit.source_text == "Hello, world. Bye"

    def test_the_language_of_the_asr_is_kept(self) -> None:
        segmenter, _ = make()
        (unit,) = run(segmenter, utterance("konnichiwa minna san", 0.0, 1.5, language="ja"))
        assert unit.language == "ja"

    def test_ready_at_is_the_session_clock_when_the_unit_is_closed(self) -> None:
        segmenter, clock = make()
        clock.set(7.5)
        events = utterance("the weather is nice today", 0.0, 2.4)
        for event in events[:-1]:
            segmenter.accept(event)
        clock.set(9.25)
        (unit,) = segmenter.accept(events[-1])
        assert unit.ready_at == 9.25

    def test_unit_times_never_overlap_the_previous_unit(self) -> None:
        segmenter, _ = make()
        first = utterance("the weather is nice today", 0.0, 2.4)
        second = utterance(
            "I think we should go now", 2.0, 4.0, segment_id=1
        )  # arranca antes de que acabe la primera
        units = run(segmenter, first + second)
        assert_well_formed(units)
        assert units[1].t_start == units[0].t_end == 2.4

    def test_a_unit_always_has_positive_duration_even_if_the_vad_end_comes_early(self) -> None:
        segmenter, _ = make()
        events = utterance("the weather is nice today", 5.0, 7.4)
        events[-2] = VadEvent(END, 4.0)  # un SPEECH_END anterior al inicio del habla
        (unit,) = run(segmenter, events)
        assert unit.t_start < unit.t_end

    def test_vad_events_alone_never_make_units(self) -> None:
        segmenter, _ = make()
        events: list[Event] = [
            VadEvent(START, 1.0),
            VadEvent(END, 1.4),
            VadEvent(START, 5.0),
            VadEvent(END, 5.2),
        ]
        assert run(segmenter, events) == []


# --------------------------------------------------------------------------------------------------
# Cortes por coma y por conjunción
# --------------------------------------------------------------------------------------------------


class TestClauseCuts:
    def test_the_minimum_fragment_is_six_words(self) -> None:
        assert MIN_CLAUSE_WORDS == 6
        assert {"and", "but", "because", "so", "which", "when", "while", "if"} == set(CLAUSE_CONJUNCTIONS)

    def test_a_comma_cuts_when_the_fragment_has_six_words_or_more(self) -> None:
        segmenter, _ = make()
        units = run(segmenter, utterance("I really like it a lot, you know what I mean", 0.0, 4.0))
        assert texts(units) == ["I really like it a lot,", "you know what I mean"]
        assert [u.is_sentence_end for u in units] == [False, True]

    def test_a_comma_with_fewer_than_six_words_does_not_cut(self) -> None:
        segmenter, _ = make()
        units = run(segmenter, utterance("I really like it, you know what I mean", 0.0, 4.0))
        assert texts(units) == ["I really like it, you know what I mean"]

    def test_the_comma_of_the_last_word_never_leaves_an_empty_closing_unit(self) -> None:
        segmenter, _ = make()
        units = run(segmenter, utterance("I really like it a lot,", 0.0, 3.0))
        assert texts(units) == ["I really like it a lot,"]
        assert units[0].is_sentence_end is True

    @pytest.mark.parametrize("conjunction", sorted(CLAUSE_CONJUNCTIONS))
    def test_a_conjunction_cuts_before_itself_when_the_fragment_has_six_words(self, conjunction: str) -> None:
        segmenter, _ = make()
        text = f"the old man walked home slowly {conjunction} the rain kept falling"
        units = run(segmenter, utterance(text, 0.0, 4.0))
        assert texts(units) == ["the old man walked home slowly", f"{conjunction} the rain kept falling"]
        assert [u.is_sentence_end for u in units] == [False, True]

    def test_a_conjunction_with_fewer_than_six_words_before_it_does_not_cut(self) -> None:
        segmenter, _ = make()
        units = run(segmenter, utterance("the old man walked home and the rain kept falling", 0.0, 4.0))
        assert len(units) == 1

    def test_the_conjunction_is_found_whatever_its_case_or_punctuation(self) -> None:
        segmenter, _ = make()
        units = run(
            segmenter, utterance("the old man walked home slowly But, the rain kept falling", 0.0, 4.0)
        )
        assert texts(units) == ["the old man walked home slowly", "But, the rain kept falling"]

    def test_other_words_are_not_conjunctions(self) -> None:
        segmenter, _ = make()
        units = run(
            segmenter, utterance("the old man walked home slowly then the rain kept falling", 0.0, 4.0)
        )
        assert len(units) == 1

    def test_a_dangling_conjunction_at_the_end_stays_with_its_fragment(self) -> None:
        segmenter, _ = make()
        units = run(segmenter, utterance("the old man walked home slowly and", 0.0, 3.0))
        assert texts(units) == ["the old man walked home slowly and"]

    def test_the_cut_waits_until_the_conjunction_is_stable(self) -> None:
        segmenter, _ = make()
        events = utterance("the old man walked home slowly and then slept", 0.0, 4.0)
        produced = feed(segmenter, events)
        partials = [e for e in events if isinstance(e, AsrEvent) and e.kind is PARTIAL]
        # La conjunción es la palabra 7 (índice 6): con ella como última palabra sigue sin ser estable.
        with_conjunction_last = next(i for i, e in enumerate(events) if e is partials[6])
        assert partials[6].text.endswith("and")
        assert produced[with_conjunction_last] == []
        (unit,) = produced[with_conjunction_last + 1]
        assert unit.source_text == "the old man walked home slowly"
        assert unit.is_sentence_end is False

    def test_the_cut_waits_until_the_comma_word_is_stable(self) -> None:
        segmenter, _ = make()
        events = utterance("I really like it a lot, you know what I mean", 0.0, 4.0)
        produced = feed(segmenter, events)
        partials = [e for e in events if isinstance(e, AsrEvent) and e.kind is PARTIAL]
        comma_last = next(i for i, e in enumerate(events) if e is partials[5])
        assert partials[5].text.endswith("lot,")
        assert produced[comma_last] == []
        assert texts(produced[comma_last + 1]) == ["I really like it a lot,"]

    def test_a_cut_is_made_while_the_speaker_goes_on_not_at_the_pause(self) -> None:
        segmenter, _ = make()
        events = utterance(LONG_SENTENCE, 0.0, 6.0)
        end = next(i for i, e in enumerate(events) if isinstance(e, VadEvent) and e.kind is END)
        before_the_pause = [u for units in feed(segmenter, events[:end]) for u in units]
        assert texts(before_the_pause) == [
            "when I got home yesterday, my brother told me that the old car had finally stopped working,",
            "and we laughed about it for a long time",
        ]

    def test_the_long_sentence_is_cut_into_three_clauses_that_cover_it_once(self) -> None:
        segmenter, _ = make()
        units = run(segmenter, utterance(LONG_SENTENCE, 0.0, 6.0))
        assert len(units) == 3
        assert [u.is_sentence_end for u in units] == [False, False, True]
        assert_well_formed(units)
        assert_covers_once(units, LONG_SENTENCE)

    def test_several_cut_points_that_become_stable_together_are_all_applied_in_order(self) -> None:
        segmenter, _ = make()
        words = split_words(
            "one two three four five six, seven eight nine ten eleven twelve, thirteen fourteen fifteen"
        )
        text = " ".join(words)
        # Un solo parcial que ya trae las dos comas y todo estable salvo la última palabra.
        event = asr_event(0, text, len(" ".join(words[:-1])), 5.0)
        units = segmenter.accept(event)
        assert texts(units) == ["one two three four five six,", "seven eight nine ten eleven twelve,"]
        assert [u.unit_id for u in units] == [0, 1]
        assert_well_formed(units)

    def test_a_final_text_is_also_cut_into_clauses(self) -> None:
        segmenter, _ = make()
        text = "I told my brother about the plan, but he did not listen"
        units = segmenter.accept(asr_event(0, text, len(text), 6.0, kind=FINAL))
        assert texts(units) == ["I told my brother about the plan,", "but he did not listen"]
        assert [u.is_sentence_end for u in units] == [False, True]

    def test_the_final_corrects_only_what_was_not_emitted(self) -> None:
        segmenter, _ = make()
        text = "I told my brother about the plan, but he did not listen to the sea"
        events = utterance(
            text, 0.0, 5.0, final_text="I told my brother about the plan, but he did not listen to the see"
        )
        units = run(segmenter, events)
        assert texts(units) == ["I told my brother about the plan,", "but he did not listen to the see"]


# --------------------------------------------------------------------------------------------------
# Corte forzado por tiempo
# --------------------------------------------------------------------------------------------------

WORDS_12 = split_words("alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima")


class TestForcedCut:
    def test_the_default_limit_is_six_seconds(self) -> None:
        segmenter = PauseClauseSegmenter(ManualClock())
        units = run(segmenter, utterance(" ".join(f"w{i:02d}" for i in range(40)), 0.0, 15.0))
        assert len(units) >= 2
        assert all(u.t_end - u.t_start <= 6.0 + SLACK_S for u in units)

    def test_it_cuts_at_the_last_stable_word_as_soon_as_the_limit_is_passed(self) -> None:
        segmenter, _ = make(max_untranslated_s=2.0)
        events = utterance(
            " ".join(WORDS_12), 0.0, 6.0
        )  # media palabra por segundo: parcial k acaba en 0,5 · k
        produced = feed(segmenter, events)
        partials = [e for e in events if isinstance(e, AsrEvent) and e.kind is PARTIAL]
        first = next(i for i, units in enumerate(produced) if units)
        assert events[first] is partials[4], "con 2,5 s sobre el origen se pasa de 2,0 s: es el parcial 5"
        (unit,) = produced[first]
        assert unit.source_text == "alpha bravo charlie delta", "hasta la última palabra completa estable"
        assert unit.is_sentence_end is False

    def test_the_end_of_a_forced_cut_is_estimated_by_the_proportion_of_characters(self) -> None:
        segmenter, _ = make(max_untranslated_s=2.0)
        events = utterance(" ".join(WORDS_12), 0.0, 6.0)
        unit = next(u for units in feed(segmenter, events) for u in units)
        # El parcial 5 (2,5 s) dice "alpha bravo charlie delta echo"; el corte deja fuera "echo".
        shown = "alpha bravo charlie delta echo"
        kept = "alpha bravo charlie delta"
        assert unit.t_start == 0.0
        assert unit.t_end == pytest.approx(2.5 * len(kept) / len(shown))

    def test_the_next_limit_is_counted_from_the_end_of_the_previous_unit(self) -> None:
        segmenter, _ = make(max_untranslated_s=2.0)
        events = utterance(" ".join(f"w{i:02d}" for i in range(30)), 0.0, 15.0)
        units = []
        for event in events[:-2]:
            units.extend(segmenter.accept(event))
        assert len(units) >= 5
        for earlier, later in zip(units, units[1:], strict=False):
            assert later.t_start == earlier.t_end
            assert later.t_end - later.t_start <= 2.0 + SLACK_S

    def test_a_clause_cut_resets_the_time_limit(self) -> None:
        segmenter, _ = make(max_untranslated_s=3.0)
        words = split_words(
            "one two three four five six, seven eight nine ten eleven twelve thirteen fourteen fifteen"
        )
        # Media palabra por segundo: el parcial k acaba en 0,5 · k.
        events = utterance(" ".join(words), 0.0, 7.5)
        produced = feed(segmenter, events[:-2])  # hasta el último parcial
        emitting = [i for i, units in enumerate(produced) if units]
        # Corte de coma con el parcial 7 (3,5 s): la palabra «six,» ya es estable. El siguiente, por tiempo,
        # no sale con el parcial 8, aunque ya van 4,0 s desde el inicio, sino cuando pasan 3 s desde el final
        # de la primera unidad (2,88 s): con el parcial 12 (6,0 s).
        assert emitting == [7, 12]
        first, second = (u for units in produced for u in units)
        assert first.source_text == "one two three four five six,"
        assert second.source_text == "seven eight nine ten eleven"
        assert second.t_start == first.t_end

    def test_there_is_no_cut_while_nothing_is_stable(self) -> None:
        segmenter, _ = make(max_untranslated_s=2.0)
        assert segmenter.accept(asr_event(0, "extraordinarily", 0, 30.0)) == []

    def test_a_partial_whose_stable_len_cuts_a_word_in_half_does_not_count_that_word(self) -> None:
        segmenter, _ = make(max_untranslated_s=2.0)
        text = "alpha bravo charlie"
        # `stable_len` 14 cae dentro de "charlie": solo "alpha bravo" es completo.
        (unit,) = segmenter.accept(asr_event(0, text, 14, 3.0))
        assert unit.source_text == "alpha bravo"

    def test_a_clause_cut_goes_first_and_then_the_forced_cut_if_the_limit_is_still_passed(self) -> None:
        segmenter, _ = make(max_untranslated_s=2.0)
        words = split_words("one two three four five six, seven eight")
        # Todo estable salvo la última palabra. La coma corta primero (en 9,0 · 28/40 = 6,3 s) y como aún
        # quedan 2,7 s sin traducir, el corte forzado se lleva «seven».
        units = segmenter.accept(asr_event(0, " ".join(words), len(" ".join(words[:-1])), 9.0))
        assert texts(units) == ["one two three four five six,", "seven"]
        assert units[0].t_end == pytest.approx(9.0 * 28 / 40)


# --------------------------------------------------------------------------------------------------
# Segmentos del ASR y flush()
# --------------------------------------------------------------------------------------------------


class TestSegmentsAndFlush:
    def test_flush_emits_only_the_stable_text_and_closes_the_sentence(self) -> None:
        segmenter, _ = make()
        events = utterance("the weather is nice today", 0.0, 2.4)
        last_partial = max(i for i, e in enumerate(events) if isinstance(e, AsrEvent) and e.kind is PARTIAL)
        for event in events[: last_partial + 1]:
            assert segmenter.accept(event) == []
        (unit,) = segmenter.flush()
        assert unit.source_text == "the weather is nice", (
            "«today» es la última palabra y puede estar a medias"
        )
        assert unit.is_sentence_end is True
        assert segmenter.flush() == []

    def test_flush_ends_the_unit_at_the_vad_end_when_there_was_one(self) -> None:
        segmenter, _ = make()
        events = utterance("the weather is nice today", 0.0, 2.4)
        for event in events[:-1]:  # hasta SPEECH_END, sin el FINAL
            segmenter.accept(event)
        (unit,) = segmenter.flush()
        assert unit.t_end == 2.4

    def test_flush_estimates_the_end_when_there_is_no_vad_end(self) -> None:
        segmenter, _ = make()
        segmenter.accept(asr_event(0, "the weather is nice today", len("the weather is nice"), 2.5))
        (unit,) = segmenter.flush()
        assert unit.t_end == pytest.approx(
            2.5 * len("the weather is nice") / len("the weather is nice today")
        )

    def test_flush_after_a_final_has_nothing_left(self) -> None:
        segmenter, _ = make()
        assert run(segmenter, utterance("the weather is nice today", 0.0, 2.4), flush=False)
        assert segmenter.flush() == []

    def test_flush_continues_the_numbering(self) -> None:
        segmenter, _ = make()
        first = run(segmenter, utterance("the weather is nice today", 0.0, 2.4))
        second = run(segmenter, utterance("I think we should go now", 3.4, 6.0, segment_id=1))
        assert [u.unit_id for u in first + second] == [0, 1]

    def test_the_vad_end_of_an_utterance_without_text_is_not_used_for_the_next_one(self) -> None:
        segmenter, _ = make()
        # Un enunciado de 0,4 s que el ASR no reconoce: SPEECH_START y SPEECH_END, sin texto ni FINAL.
        segmenter.accept(VadEvent(START, 1.0))
        segmenter.accept(VadEvent(END, 1.4))
        events = utterance("the weather is nice today", 3.4, 5.8)
        last_partial = max(i for i, e in enumerate(events) if isinstance(e, AsrEvent) and e.kind is PARTIAL)
        for event in events[: last_partial + 1]:
            segmenter.accept(event)
        (unit,) = segmenter.flush()  # el segundo enunciado no llegó a tener SPEECH_END
        assert unit.t_end == pytest.approx(
            3.4 + 2.4 * len("the weather is nice") / len("the weather is nice today")
        )

    def test_a_new_segment_closes_the_previous_one_that_never_got_its_final(self) -> None:
        segmenter, _ = make()
        old = utterance("the weather is nice today", 0.0, 2.4)
        last_partial = max(i for i, e in enumerate(old) if isinstance(e, AsrEvent) and e.kind is PARTIAL)
        for event in old[: last_partial + 1]:
            segmenter.accept(event)
        new = utterance("I think we should go now", 3.4, 6.0, segment_id=1)
        units = [u for event in new for u in segmenter.accept(event)]
        assert texts(units) == ["the weather is nice", "I think we should go now"]
        assert [u.is_sentence_end for u in units] == [True, True]
        assert_well_formed(units)

    def test_a_repeated_partial_does_not_repeat_text(self) -> None:
        segmenter, _ = make(max_untranslated_s=2.0)
        doubled: list[Event] = []
        for event in utterance(" ".join(WORDS_12), 0.0, 6.0):
            doubled.append(event)
            if isinstance(event, AsrEvent) and event.kind is PARTIAL:
                doubled.append(event)
        units = run(segmenter, doubled)
        assert_covers_once(units, " ".join(WORDS_12))

    def test_a_segment_id_that_starts_over_after_an_engine_restart_is_a_new_segment(self) -> None:
        segmenter, _ = make()
        first = run(segmenter, utterance("the weather is nice today", 0.0, 2.4, segment_id=7))
        second = run(segmenter, utterance("I think we should go now", 3.4, 6.0, segment_id=0))
        assert_covers_once(first + second, "the weather is nice today I think we should go now")


# --------------------------------------------------------------------------------------------------
# Parámetros
# --------------------------------------------------------------------------------------------------


class TestParameters:
    @pytest.mark.parametrize("limit", [0.0, -1.0, float("nan"), float("inf")])
    def test_the_limit_must_be_a_positive_finite_number(self, limit: float) -> None:
        with pytest.raises(ValueError, match="max_untranslated_s"):
            PauseClauseSegmenter(ManualClock(), max_untranslated_s=limit)


# --------------------------------------------------------------------------------------------------
# Flujos aleatorios: nunca se pierde ni se repite texto y el límite se respeta
# --------------------------------------------------------------------------------------------------

VOCABULARY = split_words(
    "the a of to in is it you that he was for on are with as I his they at be this have from or one had by "
    "word but not what all were we when your can said there use an each which she do how their if will up "
    "other about out many then them these so some her would make like him into time has look two more write "
    "go see number no way could people my than first water been call who oil its now find long down day did "
    "get come made may part"
)
EXTRA_CLAUSE_WORDS = ["and", "but", "because", "so", "which", "when", "while", "if"]


def random_transcript(rng: random.Random) -> list[str]:
    words = [rng.choice(VOCABULARY) for _ in range(rng.randint(1, 70))]
    for index in range(len(words)):
        roll = rng.random()
        if roll < 0.08:
            words[index] += ","
        elif roll < 0.16:
            words[index] = rng.choice(EXTRA_CLAUSE_WORDS)
    return words


@pytest.mark.parametrize("seed", range(40))
def test_random_streams_cover_the_text_once_and_respect_the_time_limit(seed: int) -> None:
    rng = random.Random(seed)
    limit = rng.choice([2.0, 4.0, 6.0, 9.0])
    segmenter, _ = make(limit)
    events: list[Event] = []
    transcript: list[str] = []
    t = rng.uniform(0.0, 3.0)
    for segment_id in range(rng.randint(1, 4)):
        words = random_transcript(rng)
        transcript += words
        step = rng.choice([1, 2])
        duration = len(words) * rng.uniform(0.25, 0.45)
        events += utterance(" ".join(words), t, t + duration, segment_id=segment_id, step=step)
        t += duration + rng.uniform(0.6, 2.0)

    units: list[TranslationUnit] = []
    for event in events:
        units.extend(segmenter.accept(event))
        if isinstance(event, AsrEvent) and event.kind is PARTIAL:
            covered = max([u.t_end for u in units] + [event.t_start])
            # Un parcial puede traer dos palabras (hasta ~0,9 s): cabe en la holgura del contrato.
            assert event.t_end - covered <= limit + SLACK_S, (
                f"seed {seed}: habla sin traducir en {event.t_end:.2f} s"
            )
    units.extend(segmenter.flush())

    assert_well_formed(units)
    assert_covers_once(units, " ".join(transcript))
    assert units[-1].is_sentence_end
    for unit in units:
        assert unit.t_end - unit.t_start <= limit + SLACK_S, (
            f"seed {seed}: la unidad {unit.unit_id} es muy larga"
        )
        assert words_of(unit.source_text), "texto vacío"


class TestMinimumTail:
    """Spec 002, R7: no se corta por cláusula si detrás quedarían menos de 4 palabras."""

    def test_the_default_minimum_tail_is_four_words(self) -> None:
        from instanttraductor.pipeline.segmenter import MIN_TAIL_WORDS

        assert MIN_TAIL_WORDS == 4
        segmenter = PauseClauseSegmenter(ManualClock())
        units = [
            u
            for batch in feed(
                segmenter, utterance("I really did not want to go there, she said sadly", 0.0, 4.0)
            )
            for u in batch
        ]
        assert texts(units) == ["I really did not want to go there, she said sadly"]

    def test_a_long_enough_tail_still_cuts_at_the_comma(self) -> None:
        segmenter, _ = make(min_tail_words=4)
        events = utterance("I really did not want to go there, but we had no other choice", 0.0, 5.0)
        units = [u for batch in feed(segmenter, events) for u in batch]
        assert texts(units) == ["I really did not want to go there,", "but we had no other choice"]

    def test_with_partials_the_cut_waits_for_the_tail(self) -> None:
        segmenter, _ = make(min_tail_words=4)
        events = utterance("I really did not want to go there, but we had no other choice", 0.0, 5.0)
        produced = feed(segmenter, events)
        first_cut = next(i for i, batch in enumerate(produced) if batch)
        # La coma está en la palabra 8; el corte no sale hasta que hay al menos 4 palabras estables detrás.
        partial = events[first_cut]
        assert isinstance(partial, AsrEvent)
        assert len(partial.text.split()) >= 8 + 4

    def test_the_minimum_tail_must_be_positive(self) -> None:
        with pytest.raises(ValueError):
            PauseClauseSegmenter(ManualClock(), min_tail_words=0)
