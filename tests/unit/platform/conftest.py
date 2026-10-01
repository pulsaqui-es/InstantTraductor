"""Fixtures comunes de los tests de la capa de plataforma."""

from __future__ import annotations

import sys
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _close_shared_job() -> Iterator[None]:
    """Cierra el job único tras cada test: no queda ningún hijo vivo ni estado compartido."""
    yield
    if sys.platform == "win32":
        from instanttraductor.platform import windows

        windows.close_job()
