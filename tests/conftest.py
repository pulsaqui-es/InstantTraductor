"""Configuración común de pytest para InstantTraductor."""

from __future__ import annotations

import pytest

# Marcadores de los tests que usan componentes reales (GPU, modelos o dispositivos).
_HARDWARE_MARKERS = ("gpu", "model", "device")


@pytest.fixture(autouse=True)
def _isolated_home(
    request: pytest.FixtureRequest,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Aísla INSTANTTRADUCTOR_HOME en un directorio temporal, salvo en los tests con hardware real."""
    if any(request.node.get_closest_marker(marker) for marker in _HARDWARE_MARKERS):
        return
    home = tmp_path_factory.mktemp("instanttraductor_home")
    monkeypatch.setenv("INSTANTTRADUCTOR_HOME", str(home))
