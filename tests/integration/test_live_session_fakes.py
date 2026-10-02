"""`LiveSession` con motores y dispositivos falsos (T033): autotest, fallos de motores y parada.

Los dispositivos son dobles de `LiveDevices`: la captura es el diálogo de pruebas leído a ritmo real
(`FileSource`) y la reproducción, una pista (`TimelineSink`). El reloj corre `SPEED` veces más rápido.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import pytest

from instanttraductor.audio.file_sink import TimelineSink
from instanttraductor.audio.file_source import FileSource
from instanttraductor.config import AppPaths, Settings
from instanttraductor.contracts import AudioSink, AudioSource, Clock
from instanttraductor.pipeline.clock import SessionClock
from instanttraductor.pipeline.live import LiveSession
from instanttraductor.pipeline.session import EXIT_ERROR, EXIT_SELFTEST, SessionError, Warnings
from tests.fakes.fake_engines import FakeEngines
from tests.integration.test_file_mode_fakes import DIALOGUE, dialogue_script

SPEED = 10.0


def fast_clock() -> SessionClock:
    return SessionClock(lambda: time.perf_counter() * SPEED)


class FakeDevices:
    """`LiveDevices` sin hardware. `selftest_error`: lo que lanza el autotest (None = pasa)."""

    def __init__(self, selftest_error: SessionError | None = None) -> None:
        self.selftest_error = selftest_error
        self.selftests = 0

    def selftest(self) -> float:
        self.selftests += 1
        if self.selftest_error is not None:
            raise self.selftest_error
        return 0.8

    def echo_monitor(self, threshold: float, warnings: Warnings) -> Any:
        return None

    def sink(self, clock: Clock, warnings: Warnings, echo: Any) -> AudioSink:
        return TimelineSink(clock, duration_s=None)

    def source(self, clock: Clock, *, on_reopen: Any, on_warning: Any) -> AudioSource:
        return FileSource(clock, DIALOGUE)


def make_session(tmp_path: Path, engines: FakeEngines, devices: FakeDevices) -> LiveSession:
    return LiveSession(
        Settings(),
        paths=AppPaths(tmp_path),
        report_dir=tmp_path / "informes",
        engines=engines,
        devices=devices,
        clock_factory=fast_clock,
    )


def test_a_failing_selftest_exits_with_code_4_and_stops_the_engines(tmp_path: Path) -> None:
    engines = FakeEngines(dialogue_script())
    devices = FakeDevices(SessionError("se oye a sí mismo", exit_code=EXIT_SELFTEST))
    session = make_session(tmp_path, engines, devices)

    with pytest.raises(SessionError) as raised:
        session.start()

    assert raised.value.exit_code == EXIT_SELFTEST
    assert engines.stopped
    assert session.stop() is None  # no llegó a arrancar: no hay informe


@pytest.mark.timeout(60)
def test_an_engine_that_fails_once_is_restarted_and_a_second_failure_stops_cleanly(tmp_path: Path) -> None:
    engines = FakeEngines(dialogue_script(), failures=[("voz: terminó", True), ("voz: terminó", False)])
    session = make_session(tmp_path, engines, FakeDevices())
    session.start()
    try:
        session.run_until(threading.Event())  # vuelve sola cuando el segundo fallo no se recupera
    finally:
        report = session.stop()

    assert engines.restarts == 1
    fatal = session.fatal_error
    assert fatal is not None and fatal.exit_code == EXIT_ERROR
    assert report is not None and report["diagnostics"]["component_restarts"] == 1
    assert engines.stopped
    assert list((tmp_path / "informes").glob("*/informe.json"))  # el informe se guarda igualmente


@pytest.mark.timeout(60)
def test_stop_takes_under_2_s_while_speaking(tmp_path: Path) -> None:
    session = make_session(tmp_path, FakeEngines(dialogue_script()), FakeDevices())
    session.start()
    stop = threading.Event()
    threading.Timer(1.5, stop.set).start()  # 15 s de sesión: ya hay frases traducidas y sonando
    session.run_until(stop)

    t0 = time.perf_counter()
    report = session.stop()
    assert time.perf_counter() - t0 < 2.0
    assert report is not None and report["mode"] == "directo"
    assert report["summary"]["utterances"] >= 1
    assert session.fatal_error is None
