"""Relojes de sesión: `SessionClock` (el real) y `ManualClock` (el de los tests).

Los dos cumplen el contrato `instanttraductor.contracts.Clock`: `now()` devuelve los segundos desde el
inicio de la sesión, de forma monotónica y no decreciente. Los componentes reciben un `Clock` en su
constructor y nunca llaman a `time.time()` ni a `time.monotonic()` directamente; `SessionClock` es la
única excepción.
"""

import math
import threading
import time
from collections.abc import Callable


class SessionClock:
    """Reloj de sesión real: segundos desde que se construye, medidos con `time.monotonic()`.

    El reloj de sesión y el de audio comparten origen: el instante en que arranca la captura
    (data-model.md). Por eso la sesión lo construye **al arrancar la captura**, después de arrancar los
    motores. Como `time.monotonic()` no retrocede, `now()` es no decreciente y nunca es negativo.

    `time_source` solo se sustituye en los tests, para controlar el tiempo.
    """

    def __init__(self, time_source: Callable[[], float] = time.monotonic) -> None:
        self._time_source = time_source
        self._origin = time_source()

    def now(self) -> float:
        """Segundos transcurridos desde la construcción del reloj."""
        return self._time_source() - self._origin


class ManualClock:
    """Reloj manual para los tests: solo se mueve con `set` y `advance`, y nunca retrocede.

    Es seguro entre hilos: todas las lecturas y escrituras van bajo un cerrojo.
    """

    def __init__(self, start: float = 0.0) -> None:
        _require_finite(start, "start")
        self._now = float(start)
        self._lock = threading.Lock()

    def now(self) -> float:
        """Segundos actuales del reloj manual."""
        with self._lock:
            return self._now

    def set(self, t: float) -> None:
        """Fija el reloj en el instante absoluto `t`. Lanza `ValueError` si `t` es anterior al actual."""
        _require_finite(t, "t")
        with self._lock:
            if t < self._now:
                raise ValueError(f"El reloj no puede retroceder: ahora={self._now}, pedido={t}.")
            self._now = float(t)

    def advance(self, dt: float) -> None:
        """Avanza el reloj `dt` segundos. Lanza `ValueError` si `dt` es negativo."""
        _require_finite(dt, "dt")
        if dt < 0:
            raise ValueError(f"El reloj no puede retroceder: dt={dt}.")
        with self._lock:
            self._now += dt


def _require_finite(value: float, name: str) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{name} debe ser un número finito (recibido: {value}).")
