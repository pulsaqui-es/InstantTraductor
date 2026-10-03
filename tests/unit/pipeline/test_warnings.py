"""Tests de `Warnings`: avisos recientes para la interfaz, sin inundar el log."""

from __future__ import annotations

import logging

import pytest

from instanttraductor.pipeline.clock import ManualClock
from instanttraductor.pipeline.session import WARNING_TTL_S, Warnings

SILENT = "No llega audio del origen (¿app silenciada o contenido protegido?)."


def test_a_repeated_warning_is_logged_once_while_it_lasts(caplog: pytest.LogCaptureFixture) -> None:
    clock = ManualClock()
    warnings = Warnings(clock)
    with caplog.at_level(logging.WARNING, logger="instanttraductor.pipeline.session"):
        for _ in range(40):  # 10 s repitiéndose cada 250 ms, como el bucle de control
            warnings.add(SILENT)
            clock.advance(0.25)
    assert [r.getMessage() for r in caplog.records] == [SILENT]
    assert warnings.current() == (SILENT,)


def test_it_is_logged_again_when_it_comes_back_after_expiring(caplog: pytest.LogCaptureFixture) -> None:
    clock = ManualClock()
    warnings = Warnings(clock)
    with caplog.at_level(logging.WARNING, logger="instanttraductor.pipeline.session"):
        warnings.add(SILENT)
        clock.advance(WARNING_TTL_S + 1)
        assert warnings.current() == ()
        warnings.add(SILENT)
    assert len(caplog.records) == 2


def test_a_repeated_warning_does_not_push_out_the_others() -> None:
    clock = ManualClock()
    warnings = Warnings(clock)
    warnings.add("Se ha detectado la propia voz en la captura (eco).")
    for _ in range(50):
        warnings.add(SILENT)
    assert warnings.current() == ("Se ha detectado la propia voz en la captura (eco).", SILENT)
