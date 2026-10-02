"""Dobles de la escucha de una aplicación: lista de apps y tabla de procesos por guion."""

from __future__ import annotations

from collections.abc import Sequence

from instanttraductor.audio.app_types import AppIdentity, AudioApp
from instanttraductor.contracts import Clock


def app(exe_path: str, *, name: str | None = None, pid: int = 1000, create_time: float = 1.0) -> AppIdentity:
    """Identidad de prueba; el nombre visible por defecto sale del nombre del ejecutable."""
    stem = exe_path.replace("\\", "/").rsplit("/", 1)[-1].removesuffix(".exe")
    return AppIdentity(exe_path, name or stem.capitalize(), pid, create_time)


class FakeAppEnumerator:
    """Devuelve la lista de apps que se le dé (o la última fijada con `set`). Cuenta las llamadas."""

    def __init__(self, apps: Sequence[AudioApp] = ()) -> None:
        self._apps = list(apps)
        self.calls = 0

    def set(self, apps: Sequence[AudioApp]) -> None:
        self._apps = list(apps)

    def __call__(self, *, probe_s: float = 0.6) -> list[AudioApp]:
        self.calls += 1
        return list(self._apps)


class FakeProcessTable:
    """`ProcessTable` con vidas por guion: cada entrada es (identidad, vive_desde, vive_hasta) en el reloj.

    `vive_hasta=None` = sigue viva. Un reinicio se modela con dos entradas de la misma ruta y PID distintos.
    """

    def __init__(self, clock: Clock, lives: Sequence[tuple[AppIdentity, float, float | None]] = ()) -> None:
        self._clock = clock
        self._lives = list(lives)

    def add(self, identity: AppIdentity, start: float, end: float | None = None) -> None:
        self._lives.append((identity, start, end))

    def _alive_now(self) -> list[AppIdentity]:
        now = self._clock.now()
        return [ident for ident, start, end in self._lives if start <= now and (end is None or now < end)]

    def find_roots(self, exe_path: str) -> list[AppIdentity]:
        return [ident for ident in self._alive_now() if ident.exe_path.lower() == exe_path.lower()]

    def is_alive(self, pid: int, create_time: float) -> bool:
        return any(i.root_pid == pid and i.create_time == create_time for i in self._alive_now())
