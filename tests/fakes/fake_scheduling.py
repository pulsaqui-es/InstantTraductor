"""Doble de la política de retraso: `ScriptedDelayController`, con decisiones programadas."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from instanttraductor.contracts import DelayDecision, TranslationMode

_NEUTRAL = DelayDecision(speed=1.0, mode=TranslationMode.NORMAL, drop_oldest_pending=False)


class ScriptedDelayController:
    """`DelayController` cuyas decisiones se programan desde el test, sin aplicar ninguna política.

    - **Secuencia** de `DelayDecision`: cada llamada a `decide` devuelve la siguiente, y la última se repite.
      Sirve para comprobar cómo reacciona el planificador a una decisión concreta (acelerar, resumir,
      descartar) sin depender de los umbrales.
    - **Función** `lag_s -> DelayDecision`: decide a partir del retraso que recibe.
    - Sin guion (o con la secuencia vacía): siempre velocidad 1.0, modo NORMAL y sin descartar.
    - Registra en `lags` los retrasos recibidos y en `decisions` lo devuelto.
    """

    def __init__(self, script: Sequence[DelayDecision] | Callable[[float], DelayDecision] = ()) -> None:
        self._function: Callable[[float], DelayDecision] | None = script if callable(script) else None
        self._sequence: tuple[DelayDecision, ...] = () if callable(script) else tuple(script)
        self._next = 0
        self.lags: list[float] = []
        self.decisions: list[DelayDecision] = []

    def decide(self, lag_s: float) -> DelayDecision:
        self.lags.append(lag_s)
        if self._function is not None:
            decision = self._function(lag_s)
        elif self._sequence:
            decision = self._sequence[min(self._next, len(self._sequence) - 1)]
            self._next += 1
        else:
            decision = _NEUTRAL
        self.decisions.append(decision)
        return decision
