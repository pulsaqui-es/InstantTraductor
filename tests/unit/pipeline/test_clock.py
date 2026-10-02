"""Tests de los relojes de sesión (T006): `SessionClock` y `ManualClock`."""

from __future__ import annotations

import contextlib
import math
import sys
import threading
import time
from collections.abc import Callable, Iterator

import pytest

from instanttraductor.contracts import Clock
from instanttraductor.pipeline.clock import ManualClock, SessionClock


def _satisfies_clock_contract(obj: object) -> bool:
    return all(callable(getattr(obj, name, None)) for name in Clock.__protocol_attrs__)  # type: ignore[attr-defined]


class _FakeTime:
    """Fuente de tiempo controlada: sustituye a `time.monotonic` en los tests de `SessionClock`."""

    def __init__(self, t: float) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


class TestSessionClock:
    def test_origin_is_the_construction_instant(self) -> None:
        source = _FakeTime(100.0)
        clock = SessionClock(time_source=source)
        assert clock.now() == 0.0
        source.t = 103.5
        assert clock.now() == pytest.approx(3.5)

    def test_each_clock_has_its_own_origin(self) -> None:
        source = _FakeTime(10.0)
        first = SessionClock(time_source=source)
        source.t = 14.0
        second = SessionClock(time_source=source)
        source.t = 15.0
        assert first.now() == pytest.approx(5.0)
        assert second.now() == pytest.approx(1.0)

    def test_default_source_starts_near_zero(self) -> None:
        clock = SessionClock()
        assert 0.0 <= clock.now() < 1.0

    def test_default_source_is_non_decreasing(self) -> None:
        clock = SessionClock()
        values = [clock.now() for _ in range(5_000)]
        assert values == sorted(values)
        assert values[0] >= 0.0

    def test_default_source_measures_real_time(self) -> None:
        clock = SessionClock()
        time.sleep(0.05)
        assert clock.now() >= 0.03

    def test_is_non_decreasing_across_threads(self) -> None:
        clock = SessionClock()
        violations: list[tuple[float, float]] = []

        def read_many() -> None:
            last = clock.now()
            for _ in range(2_000):
                current = clock.now()
                if current < last:
                    violations.append((last, current))
                last = current

        threads = [threading.Thread(target=read_many) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert violations == []

    def test_satisfies_the_clock_contract(self) -> None:
        assert _satisfies_clock_contract(SessionClock())


class TestManualClock:
    def test_starts_at_zero_by_default(self) -> None:
        assert ManualClock().now() == 0.0

    def test_can_start_at_a_given_time(self) -> None:
        assert ManualClock(start=12.5).now() == 12.5

    def test_now_does_not_move_on_its_own(self) -> None:
        clock = ManualClock()
        first = clock.now()
        time.sleep(0.02)
        assert clock.now() == first

    def test_set_moves_to_an_absolute_time(self) -> None:
        clock = ManualClock()
        clock.set(4.25)
        assert clock.now() == 4.25
        clock.set(10.0)
        assert clock.now() == 10.0

    def test_set_to_the_same_time_is_allowed(self) -> None:
        clock = ManualClock(start=2.0)
        clock.set(2.0)
        assert clock.now() == 2.0

    def test_set_cannot_go_backwards(self) -> None:
        clock = ManualClock(start=5.0)
        with pytest.raises(ValueError, match="retroceder"):
            clock.set(4.9)
        assert clock.now() == 5.0

    def test_advance_adds_to_the_current_time(self) -> None:
        clock = ManualClock(start=1.0)
        clock.advance(0.5)
        clock.advance(2.0)
        assert clock.now() == pytest.approx(3.5)

    def test_advance_zero_is_allowed(self) -> None:
        clock = ManualClock(start=1.0)
        clock.advance(0.0)
        assert clock.now() == 1.0

    def test_advance_cannot_go_backwards(self) -> None:
        clock = ManualClock(start=5.0)
        with pytest.raises(ValueError, match="retroceder"):
            clock.advance(-0.001)
        assert clock.now() == 5.0

    @pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
    def test_rejects_non_finite_values(self, bad: float) -> None:
        clock = ManualClock(start=1.0)
        with pytest.raises(ValueError, match="finito"):
            clock.set(bad)
        with pytest.raises(ValueError, match="finito"):
            clock.advance(bad)
        with pytest.raises(ValueError, match="finito"):
            ManualClock(start=bad)
        assert clock.now() == 1.0

    def test_satisfies_the_clock_contract(self) -> None:
        assert _satisfies_clock_contract(ManualClock())


class _YieldingFloat(float):
    """`float` que cede el hilo dentro de sus operadores.

    En CPython 3.12 no hay puntos de cambio de hilo entre cargar y guardar `self._now += dt`, así que una
    carrera real casi nunca se manifestaría. Con este valor, el operador (que es código Python) abre la
    ventana: sin cerrojo, otro hilo se cuela y el reloj pierde avances o retrocede.
    """

    def __radd__(self, other: float) -> float:
        time.sleep(0)
        return float(other) + float(self)

    def __lt__(self, other: float) -> bool:
        time.sleep(0)
        return float(self) < float(other)


@contextlib.contextmanager
def _fast_thread_switching() -> Iterator[None]:
    """Intervalo de cambio de hilo diminuto: hace muy probable que un acceso sin cerrojo se estropee."""
    previous = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        yield
    finally:
        sys.setswitchinterval(previous)


def _run_in_threads(targets: list[Callable[[], None]]) -> None:
    with _fast_thread_switching():
        threads = [threading.Thread(target=target) for target in targets]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()


class _RegressionWatcher:
    """Hilos que leen el reloj sin parar y anotan cada vez que el tiempo retrocede."""

    def __init__(self, clock: ManualClock, count: int = 2) -> None:
        self.violations: list[tuple[float, float]] = []
        self._clock = clock
        self._stop = threading.Event()
        self._threads = [threading.Thread(target=self._watch) for _ in range(count)]

    def _watch(self) -> None:
        last = self._clock.now()
        while not self._stop.is_set():
            current = self._clock.now()
            if current < last:
                self.violations.append((last, current))
            last = current

    def __enter__(self) -> _RegressionWatcher:
        for thread in self._threads:
            thread.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join()


class TestManualClockThreadSafety:
    def test_concurrent_advances_lose_no_updates(self) -> None:
        clock = ManualClock()
        workers, per_worker = 8, 300

        def work() -> None:
            for _ in range(per_worker):
                clock.advance(_YieldingFloat(1.0))

        _run_in_threads([work] * workers)
        assert clock.now() == workers * per_worker

    def test_readers_never_see_time_going_backwards_during_advances(self) -> None:
        clock = ManualClock()
        with _RegressionWatcher(clock, count=3) as watcher:
            for _ in range(5_000):
                clock.advance(0.001)
        assert watcher.violations == []

    def test_concurrent_sets_never_move_time_backwards(self) -> None:
        clock = ManualClock()
        bases = [i * 10_000.0 for i in range(6)]

        def make_worker(base: float) -> Callable[[], None]:
            def work() -> None:
                for i in range(300):
                    try:
                        clock.set(_YieldingFloat(base + i))
                    except ValueError:
                        continue  # otro hilo ya había avanzado más: es lo esperado

            return work

        with _fast_thread_switching(), _RegressionWatcher(clock) as watcher:
            _run_in_threads([make_worker(base) for base in bases])

        assert watcher.violations == []
        # El valor más alto que se intentó fijar siempre se acepta, y el tiempo no vuelve atrás de él.
        assert clock.now() == max(bases) + 299
