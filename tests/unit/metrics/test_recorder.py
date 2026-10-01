"""Tests de `MetricsRecorder` (T030): registros, serie de retraso, memoria y `diagnostics` de informe.md."""

from __future__ import annotations

import contextlib
import math
import os
import subprocess
import sys
import threading
import time
from collections.abc import Iterable, Iterator

import psutil
import pytest

from instanttraductor.contracts import Outcome, StageTimings, TranslationMode, UtteranceRecord
from instanttraductor.metrics.recorder import (
    MEMORY_REFERENCE_S,
    MemorySample,
    MetricsRecorder,
    longest_streak_above,
    max_lag,
    process_rss_mb,
    process_tree_rss_mb,
)

DIAGNOSTICS_KEYS = [
    "startup_s",
    "rss_mb_min5",
    "rss_mb_end",
    "rss_children_mb_min5",
    "rss_children_mb_end",
    "max_lag_s",
    "lag_over_drop_max_streak_s",
    "echo_events",
    "component_restarts",
    "underruns",
    "mt_model",
]


def record(unit_id: int, outcome: Outcome = Outcome.SPOKEN, text: str = "hello") -> UtteranceRecord:
    return UtteranceRecord(
        unit_id=unit_id,
        source_text=text,
        translated_text="hola" if outcome is Outcome.SPOKEN else None,
        mode=TranslationMode.NORMAL,
        speed=1.0,
        outcome=outcome,
        reason=None if outcome is Outcome.SPOKEN else "motivo",
        timings=StageTimings(t_start_audio=0.0, t_end_audio=1.0, unit_ready_at=1.1),
    )


class FakeMemory:
    """Sondas de memoria falsas: devuelven lo que se les indica y apuntan con qué PID se las llamó."""

    def __init__(self, core: float = 100.0, children: float = 1000.0) -> None:
        self.core = core
        self.children = children
        self.child_calls: list[list[int]] = []

    def core_rss_mb(self) -> float:
        return self.core

    def children_rss_mb(self, pids: Iterable[int]) -> float:
        self.child_calls.append(list(pids))
        return self.children


def make_recorder(memory: FakeMemory | None = None, **kwargs: float) -> tuple[MetricsRecorder, FakeMemory]:
    memory = memory or FakeMemory()
    recorder = MetricsRecorder(
        core_rss_mb=memory.core_rss_mb, children_rss_mb=memory.children_rss_mb, **kwargs
    )
    return recorder, memory


# --------------------------------------------------------------------------------------------------
# Registros
# --------------------------------------------------------------------------------------------------


class TestRecords:
    def test_starts_empty(self) -> None:
        assert MetricsRecorder().records == ()

    def test_keeps_the_records_in_unit_order(self) -> None:
        recorder = MetricsRecorder()
        for unit_id in (3, 1, 2):
            recorder.add_record(record(unit_id))
        assert [r.unit_id for r in recorder.records] == [1, 2, 3]

    def test_a_repeated_unit_replaces_the_previous_record(self) -> None:
        recorder = MetricsRecorder()
        recorder.add_record(record(1, Outcome.FAILED))
        recorder.add_record(record(1, Outcome.SPOKEN))
        assert [(r.unit_id, r.outcome) for r in recorder.records] == [(1, Outcome.SPOKEN)]

    def test_works_as_the_record_callback_of_several_threads(self) -> None:
        recorder = MetricsRecorder()

        def add_block(start: int) -> None:
            for unit_id in range(start, start + 100):
                recorder.add_record(record(unit_id))

        threads = [threading.Thread(target=add_block, args=(start,)) for start in (0, 100, 200, 300)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert [r.unit_id for r in recorder.records] == list(range(400))

    def test_the_tuple_returned_is_a_snapshot(self) -> None:
        recorder = MetricsRecorder()
        recorder.add_record(record(1))
        snapshot = recorder.records
        recorder.add_record(record(2))
        assert len(snapshot) == 1 and len(recorder.records) == 2


# --------------------------------------------------------------------------------------------------
# Serie de retraso
# --------------------------------------------------------------------------------------------------


def series(*pairs: tuple[float, float]) -> tuple[tuple[float, float], ...]:
    return tuple(pairs)


class TestMaxLag:
    def test_is_zero_without_samples(self) -> None:
        assert max_lag(()) == 0.0

    def test_is_the_largest_sample(self) -> None:
        assert max_lag(series((0.0, 1.0), (0.5, 7.4), (1.0, 3.0))) == 7.4


class TestLongestStreak:
    def test_is_zero_without_samples_or_without_crossing_the_threshold(self) -> None:
        assert longest_streak_above((), 8.0) == 0.0
        assert (
            longest_streak_above(series((0.0, 1.0), (0.5, 7.9), (1.0, 8.0)), 8.0) == 0.0
        )  # 8,0 no la supera

    def test_each_sample_holds_until_the_next_one(self) -> None:
        samples = series((0.0, 2.0), (0.5, 9.0), (1.0, 9.5), (1.5, 8.5), (2.0, 3.0))
        assert longest_streak_above(samples, 8.0) == pytest.approx(1.5)  # de 0,5 a 2,0

    def test_a_single_sample_above_counts_one_interval(self) -> None:
        samples = series((0.0, 1.0), (0.5, 8.5), (1.0, 1.0))
        assert longest_streak_above(samples, 8.0) == pytest.approx(0.5)

    def test_picks_the_longest_of_several_streaks(self) -> None:
        samples = series(
            (0.0, 9.0), (0.5, 1.0),  # 0,5 s
            (1.0, 9.0), (1.5, 9.0), (2.0, 9.0), (2.5, 1.0),  # 1,5 s
            (3.0, 9.0), (3.5, 9.0), (4.0, 1.0),  # 1,0 s
        )  # fmt: skip
        assert longest_streak_above(samples, 8.0) == pytest.approx(1.5)

    def test_a_streak_that_is_still_open_ends_one_interval_after_the_last_sample(self) -> None:
        samples = series((0.0, 1.0), (0.5, 9.0), (1.0, 9.0))
        assert longest_streak_above(samples, 8.0) == pytest.approx(1.0)  # 0,5 → 1,0 + 0,5

    def test_a_streak_that_is_still_open_ends_at_end_t_if_given(self) -> None:
        samples = series((0.0, 1.0), (0.5, 9.0), (1.0, 9.0))
        assert longest_streak_above(samples, 8.0, end_t=4.5) == pytest.approx(4.0)

    def test_an_end_t_before_the_last_sample_is_ignored(self) -> None:
        samples = series((0.0, 1.0), (0.5, 9.0), (1.0, 9.0))
        assert longest_streak_above(samples, 8.0, end_t=0.2) == pytest.approx(1.0)

    def test_uses_a_custom_interval_for_an_open_streak(self) -> None:
        assert longest_streak_above(series((0.0, 9.0)), 8.0, interval_s=2.0) == pytest.approx(2.0)

    def test_samples_that_are_not_finite_are_ignored(self) -> None:
        recorder = MetricsRecorder()
        for t, lag in ((math.nan, 1.0), (1.0, math.nan), (2.0, math.inf), (math.inf, 3.0)):
            recorder.add_lag_sample(t, lag)
        recorder.add_lag_sample(4.0, 5.0)
        assert recorder.lag_series == ((4.0, 5.0),)

    def test_the_recorder_computes_it_from_its_series_and_its_threshold(self) -> None:
        recorder = MetricsRecorder(drop_after_s=5.0)
        for t, lag in ((0.0, 1.0), (0.5, 6.0), (1.0, 7.0), (1.5, 2.0)):
            recorder.add_lag_sample(t, lag)
        assert recorder.lag_series == ((0.0, 1.0), (0.5, 6.0), (1.0, 7.0), (1.5, 2.0))
        diagnostics = recorder.diagnostics()
        assert diagnostics["lag_over_drop_max_streak_s"] == pytest.approx(1.0)
        assert diagnostics["max_lag_s"] == 7.0

    def test_diagnostics_close_the_open_streak_at_end_t(self) -> None:
        recorder = MetricsRecorder(drop_after_s=8.0)
        recorder.add_lag_sample(10.0, 9.0)
        assert recorder.diagnostics(end_t=14.0)["lag_over_drop_max_streak_s"] == pytest.approx(4.0)


# --------------------------------------------------------------------------------------------------
# Memoria
# --------------------------------------------------------------------------------------------------


class TestMemory:
    def test_the_reference_is_minute_five(self) -> None:
        assert MEMORY_REFERENCE_S == 300.0

    def test_samples_the_core_and_the_children(self) -> None:
        recorder, memory = make_recorder(FakeMemory(core=812.0, children=7900.0))
        sample = recorder.sample_memory(60.0, child_pids=[101, 202])
        assert sample == MemorySample(t=60.0, core_mb=812.0, children_mb=7900.0)
        assert recorder.memory_samples == (sample,)
        assert memory.child_calls == [[101, 202]]

    def test_ignores_children_without_a_pid(self) -> None:
        recorder, memory = make_recorder()
        recorder.sample_memory(0.0, child_pids=[None, 7, None])
        assert memory.child_calls == [[7]]

    def test_minute_five_is_the_first_sample_from_300_s_and_the_end_is_the_last(self) -> None:
        recorder, memory = make_recorder(memory_interval_s=1.0)
        for t, core, children in (
            (60.0, 700.0, 7000.0),
            (299.0, 790.0, 7800.0),
            (300.0, 812.4, 7900.4),
            (900.0, 820.0, 7950.0),
            (1800.0, 830.2, 8050.6),
        ):
            memory.core, memory.children = core, children
            recorder.sample_memory(t)
        diagnostics = recorder.diagnostics()
        assert diagnostics["rss_mb_min5"] == 812
        assert diagnostics["rss_children_mb_min5"] == 7900
        assert diagnostics["rss_mb_end"] == 830
        assert diagnostics["rss_children_mb_end"] == 8051

    def test_a_session_shorter_than_five_minutes_has_no_minute_five(self) -> None:
        recorder, memory = make_recorder(FakeMemory(core=500.0, children=3000.0))
        recorder.sample_memory(0.0)
        recorder.sample_memory(120.0, force=True)
        diagnostics = recorder.diagnostics()
        assert diagnostics["rss_mb_min5"] is None
        assert diagnostics["rss_children_mb_min5"] is None
        assert diagnostics["rss_mb_end"] == 500
        assert diagnostics["rss_children_mb_end"] == 3000

    def test_memory_values_are_whole_megabytes(self) -> None:
        recorder, _ = make_recorder(FakeMemory(core=99.6, children=0.4))
        recorder.sample_memory(0.0)
        diagnostics = recorder.diagnostics()
        assert diagnostics["rss_mb_end"] == 100 and isinstance(diagnostics["rss_mb_end"], int)
        assert diagnostics["rss_children_mb_end"] == 0

    def test_skips_samples_that_come_too_soon_unless_forced(self) -> None:
        recorder, _ = make_recorder(memory_interval_s=10.0)
        assert recorder.sample_memory(0.0) is not None
        assert recorder.sample_memory(4.0) is None
        assert recorder.sample_memory(9.99) is None
        assert recorder.sample_memory(10.0) is not None
        assert recorder.sample_memory(11.0, force=True) is not None
        assert [s.t for s in recorder.memory_samples] == [0.0, 10.0, 11.0]

    def test_a_failing_probe_skips_the_sample_without_raising(self) -> None:
        def broken() -> float:
            raise psutil.AccessDenied(1)

        recorder = MetricsRecorder(core_rss_mb=broken, children_rss_mb=lambda pids: 0.0)
        assert recorder.sample_memory(0.0) is None
        assert recorder.memory_samples == ()
        assert recorder.diagnostics()["rss_mb_end"] is None

    def test_a_failure_does_not_consume_the_interval(self) -> None:
        calls = {"n": 0}

        def flaky() -> float:
            calls["n"] += 1
            if calls["n"] == 1:
                raise psutil.NoSuchProcess(1)
            return 50.0

        recorder = MetricsRecorder(
            core_rss_mb=flaky, children_rss_mb=lambda pids: 0.0, memory_interval_s=10.0
        )
        assert recorder.sample_memory(0.0) is None
        assert recorder.sample_memory(1.0) is not None  # el anterior falló: no cuenta para el intervalo

    def test_real_probes_give_a_plausible_value_for_this_process(self) -> None:
        recorder = MetricsRecorder()
        sample = recorder.sample_memory(0.0, child_pids=[])
        assert sample is not None
        assert 10.0 < sample.core_mb < 100_000.0
        assert sample.children_mb == 0.0


@pytest.fixture(scope="module")
def process_tree() -> Iterator[psutil.Process]:
    """Un proceso que lanza otro: devuelve el padre con sus descendientes ya en marcha (uno por módulo)."""
    code = (
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        "time.sleep(120)\n"
    )
    proc = subprocess.Popen([sys.executable, "-c", code])
    root = psutil.Process(proc.pid)
    try:
        previous, stable_since = -1, time.monotonic()
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline:
            count = len(root.children(recursive=True))
            if count != previous:
                previous, stable_since = count, time.monotonic()
            elif count >= 1 and time.monotonic() - stable_since > 0.7:
                break  # hay descendientes y el árbol ya no cambia
            time.sleep(0.1)
        assert root.children(recursive=True), "el proceso hijo no llegó a arrancar"
        yield root
    finally:
        for child in root.children(recursive=True):
            with contextlib.suppress(psutil.Error):
                child.kill()
        proc.kill()
        proc.wait(timeout=10)


class TestRealProbes:
    def test_the_current_process_rss_is_positive(self) -> None:
        assert 10.0 < process_rss_mb() < 100_000.0
        assert process_rss_mb(os.getpid()) == pytest.approx(process_rss_mb(), rel=0.2)

    def test_a_process_tree_adds_the_descendants(self, process_tree: psutil.Process) -> None:
        members = [process_tree, *process_tree.children(recursive=True)]
        expected = sum(p.memory_info().rss for p in members) / (1024 * 1024)
        assert len(members) >= 2
        assert process_tree_rss_mb([process_tree.pid]) == pytest.approx(expected, abs=5.0)
        assert process_tree_rss_mb([process_tree.pid]) > process_rss_mb(process_tree.pid)

    def test_a_descendant_is_not_counted_twice(self, process_tree: psutil.Process) -> None:
        descendant = process_tree.children(recursive=True)[-1]
        alone = process_tree_rss_mb([process_tree.pid])
        both = process_tree_rss_mb([process_tree.pid, descendant.pid])
        assert both == pytest.approx(alone, abs=5.0)

    def test_several_roots_are_added_up(self, process_tree: psutil.Process) -> None:
        children = process_tree.children(recursive=True)
        total = process_tree_rss_mb([c.pid for c in children])
        assert total == pytest.approx(sum(c.memory_info().rss for c in children) / (1024 * 1024), abs=5.0)

    def test_a_process_that_does_not_exist_counts_as_zero(self) -> None:
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait(timeout=30)
        assert process_tree_rss_mb([proc.pid]) == 0.0
        assert process_tree_rss_mb([]) == 0.0


# --------------------------------------------------------------------------------------------------
# Diagnostics
# --------------------------------------------------------------------------------------------------


class TestDiagnostics:
    def test_have_exactly_the_keys_of_the_report_contract_in_order(self) -> None:
        assert list(MetricsRecorder().diagnostics()) == DIAGNOSTICS_KEYS

    def test_defaults_of_an_empty_session(self) -> None:
        assert MetricsRecorder().diagnostics() == {
            "startup_s": None,
            "rss_mb_min5": None,
            "rss_mb_end": None,
            "rss_children_mb_min5": None,
            "rss_children_mb_end": None,
            "max_lag_s": 0.0,
            "lag_over_drop_max_streak_s": 0.0,
            "echo_events": 0,
            "component_restarts": 0,
            "underruns": 0,
            "mt_model": None,
        }

    def test_stores_the_values_the_session_reports(self) -> None:
        recorder = MetricsRecorder()
        recorder.set_startup_s(34.2004)
        recorder.set_mt_model("hy-mt2-7b-q4")
        recorder.set_underruns(2)
        diagnostics = recorder.diagnostics()
        assert diagnostics["startup_s"] == 34.2  # tres decimales
        assert diagnostics["mt_model"] == "hy-mt2-7b-q4"
        assert diagnostics["underruns"] == 2

    @pytest.mark.parametrize("value", [math.nan, math.inf])
    def test_a_startup_time_that_is_not_finite_is_reported_as_null(self, value: float) -> None:
        recorder = MetricsRecorder()
        recorder.set_startup_s(value)
        assert recorder.diagnostics()["startup_s"] is None

    def test_echo_events_and_restarts_accumulate(self) -> None:
        recorder = MetricsRecorder()
        recorder.count_echo_event()
        recorder.count_echo_event()
        recorder.count_component_restart()
        recorder.count_echo_event(3)
        diagnostics = recorder.diagnostics()
        assert diagnostics["echo_events"] == 5
        assert diagnostics["component_restarts"] == 1

    def test_the_underruns_are_the_last_total_reported(self) -> None:
        recorder = MetricsRecorder()
        recorder.set_underruns(3)
        recorder.set_underruns(5)
        assert recorder.diagnostics()["underruns"] == 5

    def test_rejects_negative_counts(self) -> None:
        recorder = MetricsRecorder()
        with pytest.raises(ValueError, match="eco"):
            recorder.count_echo_event(-1)
        with pytest.raises(ValueError, match="reinicio"):
            recorder.count_component_restart(-1)
        with pytest.raises(ValueError, match="underruns"):
            recorder.set_underruns(-1)

    def test_rejects_a_non_positive_drop_threshold(self) -> None:
        with pytest.raises(ValueError, match="drop_after_s"):
            MetricsRecorder(drop_after_s=0.0)
