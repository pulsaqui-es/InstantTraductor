"""Contrato del reloj de sesión.

Los componentes reciben un `Clock` en su constructor. Ninguno llama a `time.time()` ni a
`time.monotonic()` directamente, salvo `SessionClock` (`instanttraductor.pipeline.clock`).
"""

from typing import Protocol


class Clock(Protocol):
    """Reloj de sesión: mide cuándo ocurre cada cosa (evento emitido, audio que empieza a sonar)."""

    def now(self) -> float:
        """Segundos desde el inicio de la sesión; monotónico y no decreciente."""
        ...
