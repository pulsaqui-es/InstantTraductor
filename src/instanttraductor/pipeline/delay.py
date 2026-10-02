"""Política de retraso: acelerar, resumir y descartar (FR-012, FR-013 y FR-014).

`ThresholdDelayController` implementa `DelayController` con los tres umbrales de `DelayPolicy`. Decide a
partir del retraso actual (`lag`, definido en `data-model.md`) y es una función pura del retraso y de un
único bit de estado, la histéresis del modo resumen:

- **Acelerar (FR-012).** La velocidad sube de forma lineal de 1,0 (con retraso = `accelerate_after_s`) a
  `max_speed` (con retraso = `concise_after_s`). Por debajo del primer umbral es 1,0 y desde el segundo es
  `max_speed`.
- **Resumir (FR-013).** `CONCISE` cuando el retraso supera `concise_after_s`, es decir, cuando ni siquiera
  la velocidad máxima alcanza. Se mantiene (histéresis) hasta que el retraso baja de `accelerate_after_s`.
  Solo si `allow_concise`: con el traductor de reserva (1.8B), que no sabe resumir, no hay fase de
  resumen y se pasa de acelerar a descartar.
- **Descartar (FR-014).** `drop_oldest_pending` cuando el retraso supera `drop_after_s`, siempre a
  velocidad máxima. No tiene memoria: se pide mientras el retraso siga por encima.

Las comparaciones con los umbrales son estrictas donde el contrato dice «supera» y «baja de». Un retraso
negativo equivale a 0 y uno que no es un número (NaN) no cambia nada: velocidad 1,0, sin descartar y sin
tocar la histéresis. No es seguro entre hilos: lo usa el planificador, que lo llama desde un solo sitio.
"""

from __future__ import annotations

import math

from instanttraductor.contracts import DelayDecision, DelayPolicy, TranslationMode


def _validate(policy: DelayPolicy) -> None:
    """Lanza `ValueError` si la política no tiene sentido: umbrales que no crecen o velocidad menor que 1."""
    numbers = (
        policy.accelerate_after_s,
        policy.concise_after_s,
        policy.drop_after_s,
        policy.max_speed,
    )
    if not all(math.isfinite(value) for value in numbers):
        raise ValueError(f"Política de retraso no válida: todos los valores deben ser finitos ({policy}).")
    if not 0.0 < policy.accelerate_after_s < policy.concise_after_s < policy.drop_after_s:
        raise ValueError(
            "Política de retraso no válida: los umbrales deben cumplir "
            "0 < accelerate_after_s < concise_after_s < drop_after_s "
            f"(recibidos {policy.accelerate_after_s:g}, {policy.concise_after_s:g} "
            f"y {policy.drop_after_s:g})."
        )
    if policy.max_speed < 1.0:
        raise ValueError(
            f"Política de retraso no válida: max_speed debe ser al menos 1,0 (recibido {policy.max_speed:g})."
        )


def speed_for_lag(policy: DelayPolicy, lag_s: float) -> float:
    """Velocidad de la política para un retraso: 1,0 hasta el primer umbral, lineal hasta `max_speed` en el
    segundo y `max_speed` a partir de ahí (FR-012)."""
    if not math.isfinite(lag_s) or lag_s <= policy.accelerate_after_s:
        return 1.0
    if lag_s >= policy.concise_after_s:
        return policy.max_speed
    fraction = (lag_s - policy.accelerate_after_s) / (policy.concise_after_s - policy.accelerate_after_s)
    return min(policy.max_speed, 1.0 + (policy.max_speed - 1.0) * fraction)


class ThresholdDelayController:
    """`DelayController` por umbrales: velocidad lineal, resumen con histéresis y descarte."""

    def __init__(self, policy: DelayPolicy) -> None:
        _validate(policy)
        self._policy = policy
        self._span = policy.concise_after_s - policy.accelerate_after_s
        self._concise = False  # histéresis: True desde que el retraso supera `concise_after_s`

    @property
    def policy(self) -> DelayPolicy:
        """La política con la que se construyó."""
        return self._policy

    def decide(self, lag_s: float) -> DelayDecision:
        policy = self._policy
        if lag_s >= policy.concise_after_s:
            speed = policy.max_speed
        elif lag_s > policy.accelerate_after_s:
            fraction = (lag_s - policy.accelerate_after_s) / self._span
            speed = min(policy.max_speed, 1.0 + (policy.max_speed - 1.0) * fraction)
        else:
            speed = 1.0

        if policy.allow_concise:
            if lag_s > policy.concise_after_s:
                self._concise = True
            elif lag_s < policy.accelerate_after_s:
                self._concise = False
        mode = TranslationMode.CONCISE if self._concise else TranslationMode.NORMAL

        return DelayDecision(speed=speed, mode=mode, drop_oldest_pending=lag_s > policy.drop_after_s)
