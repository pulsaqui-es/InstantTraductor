"""Suite de contrato de `DelayController`.

Sale de «Tests de contrato obligatorios», en `specs/001-espina-dorsal/contracts/pipeline.md`.
`DelayControllerContract` es una clase base que pytest no recoge por sí sola: un adaptador la concreta con
una subclase `TestXxx...` que sobrescribe `make_impl`.

Todos los tests corren con dos políticas (la de por defecto y otra con umbrales distintos), así que el
controlador no puede tener los números clavados.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import pytest

from instanttraductor.contracts import (
    DelayController,
    DelayDecision,
    DelayPolicy,
    TranslationMode,
)
from tests.contract.helpers import assert_implements
from tests.fakes.fake_scheduling import ScriptedDelayController

POLICIES = {
    "por-defecto": DelayPolicy(),
    "umbrales-propios": DelayPolicy(
        accelerate_after_s=2.0, max_speed=1.5, concise_after_s=4.0, drop_after_s=6.0
    ),
}
EPSILON = 1e-9


def sweep(start: float, stop: float, step: float = 0.25) -> list[float]:
    """Retrasos de `start` a `stop` (incluidos), de `step` en `step`; en orden descendente si start > stop."""
    count = round(abs(stop - start) / step)
    sign = 1 if stop >= start else -1
    return [start + sign * step * i for i in range(count + 1)]


class DelayControllerContract:
    """Contrato de `DelayController`.

    Monótono con el retraso, con histéresis y con `drop_oldest_pending` solo por encima de `drop_after_s`.

    Para concretarla, sobrescribe `make_impl` (obligatorio): fábrica de un controlador nuevo para la
    política que recibe, `(policy) -> DelayController`.
    """

    @pytest.fixture
    def make_impl(self) -> Callable[[DelayPolicy], DelayController]:
        raise NotImplementedError("Sobrescribe el fixture `make_impl` en la subclase de la suite.")

    @pytest.fixture(params=list(POLICIES.values()), ids=list(POLICIES))
    def policy(self, request: pytest.FixtureRequest) -> DelayPolicy:
        return request.param

    @pytest.fixture
    def controller(
        self, make_impl: Callable[[DelayPolicy], DelayController], policy: DelayPolicy
    ) -> DelayController:
        return make_impl(policy)

    def test_implements_the_protocol(self, controller: DelayController) -> None:
        assert_implements(controller, DelayController)

    def test_decisions_stay_within_the_policy_range(
        self, controller: DelayController, policy: DelayPolicy
    ) -> None:
        top = policy.drop_after_s + 3.0
        for lag in sweep(0.0, top) + sweep(top, 0.0):
            decision = controller.decide(lag)
            assert isinstance(decision, DelayDecision)
            assert 1.0 - EPSILON <= decision.speed <= policy.max_speed + EPSILON
            assert isinstance(decision.mode, TranslationMode)

    def test_does_not_accelerate_below_the_first_threshold(
        self, controller: DelayController, policy: DelayPolicy
    ) -> None:
        for lag in (0.0, policy.accelerate_after_s / 2, policy.accelerate_after_s - 0.1):
            decision = controller.decide(lag)
            assert decision.speed == pytest.approx(1.0)
            assert decision.mode is TranslationMode.NORMAL
            assert decision.drop_oldest_pending is False

    def test_speed_grows_with_the_lag_up_to_max_speed(
        self, controller: DelayController, policy: DelayPolicy
    ) -> None:
        speeds = [controller.decide(lag).speed for lag in sweep(0.0, policy.drop_after_s + 3.0)]
        assert speeds == sorted(speeds), "la velocidad no debe bajar mientras el retraso sube"

    def test_speed_is_gradual_between_the_first_and_second_thresholds(
        self, make_impl: Callable[[DelayPolicy], DelayController], policy: DelayPolicy
    ) -> None:
        middle = (policy.accelerate_after_s + policy.concise_after_s) / 2
        speed = make_impl(policy).decide(middle).speed
        assert 1.0 < speed < policy.max_speed

    def test_speed_is_max_speed_from_the_second_threshold(
        self, controller: DelayController, policy: DelayPolicy
    ) -> None:
        for lag in sweep(policy.concise_after_s + 0.5, policy.drop_after_s + 3.0, 0.5):
            assert controller.decide(lag).speed == pytest.approx(policy.max_speed)

    def test_summarises_only_above_the_second_threshold(
        self, controller: DelayController, policy: DelayPolicy
    ) -> None:
        for lag in sweep(0.0, policy.concise_after_s - 0.1, 0.25):
            assert controller.decide(lag).mode is TranslationMode.NORMAL
        assert controller.decide(policy.concise_after_s + 0.5).mode is TranslationMode.CONCISE

    def test_hysteresis_keeps_summarising_until_the_lag_falls_below_the_first_threshold(
        self, controller: DelayController, policy: DelayPolicy
    ) -> None:
        assert controller.decide(policy.concise_after_s + 0.5).mode is TranslationMode.CONCISE
        middle = (policy.accelerate_after_s + policy.concise_after_s) / 2
        for lag in (middle, policy.accelerate_after_s + 0.1):
            assert controller.decide(lag).mode is TranslationMode.CONCISE, f"con retraso {lag}"
        recovered = controller.decide(policy.accelerate_after_s - 0.5)
        assert recovered.mode is TranslationMode.NORMAL
        assert recovered.speed == pytest.approx(1.0)
        # Recuperado el retraso, volver a una zona intermedia ya no resume.
        assert controller.decide(middle).mode is TranslationMode.NORMAL

    def test_never_summarises_when_concise_is_not_allowed(
        self, make_impl: Callable[[DelayPolicy], DelayController], policy: DelayPolicy
    ) -> None:
        controller = make_impl(replace(policy, allow_concise=False))
        top = policy.drop_after_s + 3.0
        for lag in sweep(0.0, top) + sweep(top, 0.0):
            assert controller.decide(lag).mode is TranslationMode.NORMAL

    def test_drops_only_above_the_third_threshold(
        self, controller: DelayController, policy: DelayPolicy
    ) -> None:
        for lag in sweep(0.0, policy.drop_after_s - 0.5):
            assert controller.decide(lag).drop_oldest_pending is False, f"con retraso {lag}"
        dropping = controller.decide(policy.drop_after_s + 0.5)
        assert dropping.drop_oldest_pending is True
        assert dropping.speed == pytest.approx(policy.max_speed)

    def test_drop_is_not_requested_again_once_the_lag_is_back_under_the_threshold(
        self, controller: DelayController, policy: DelayPolicy
    ) -> None:
        assert controller.decide(policy.drop_after_s + 0.5).drop_oldest_pending is True
        assert controller.decide(policy.drop_after_s - 0.5).drop_oldest_pending is False

    def test_still_drops_without_summarising_when_concise_is_not_allowed(
        self, make_impl: Callable[[DelayPolicy], DelayController], policy: DelayPolicy
    ) -> None:
        controller = make_impl(replace(policy, allow_concise=False))
        decision = controller.decide(policy.drop_after_s + 0.5)
        assert decision.mode is TranslationMode.NORMAL
        assert decision.drop_oldest_pending is True

    def test_is_deterministic(
        self, make_impl: Callable[[DelayPolicy], DelayController], policy: DelayPolicy
    ) -> None:
        top = policy.drop_after_s + 3.0
        lags = sweep(0.0, top) + sweep(top, 0.0) + sweep(0.0, top / 2)
        first, second = make_impl(policy), make_impl(policy)
        assert [first.decide(lag) for lag in lags] == [second.decide(lag) for lag in lags]


# --------------------------------------------------------------------------------------------------
# Dobles
# --------------------------------------------------------------------------------------------------


class _ReferenceDecisions:
    """Implementación de referencia, mínima y solo para esta suite: aplica la política de `contracts`.

    Valida que los tests de arriba son coherentes con `pipeline.md` y con T028 (velocidad lineal de 1.0
    en `accelerate_after_s` a `max_speed` en `concise_after_s`; resumir por encima de `concise_after_s`
    con histéresis hasta bajar de `accelerate_after_s`; descartar por encima de `drop_after_s`).
    El controlador real es `ThresholdDelayController` (T028), que pasa esta misma suite.
    """

    def __init__(self, policy: DelayPolicy) -> None:
        self._policy = policy
        self._concise = False

    def __call__(self, lag_s: float) -> DelayDecision:
        policy = self._policy
        if lag_s <= policy.accelerate_after_s:
            speed = 1.0
        elif lag_s >= policy.concise_after_s:
            speed = policy.max_speed
        else:
            span = policy.concise_after_s - policy.accelerate_after_s
            speed = 1.0 + (policy.max_speed - 1.0) * (lag_s - policy.accelerate_after_s) / span
        if policy.allow_concise:
            if lag_s > policy.concise_after_s:
                self._concise = True
            elif lag_s < policy.accelerate_after_s:
                self._concise = False
        mode = TranslationMode.CONCISE if self._concise else TranslationMode.NORMAL
        return DelayDecision(speed=speed, mode=mode, drop_oldest_pending=lag_s > policy.drop_after_s)


class TestDelayControllerFake(DelayControllerContract):
    """`ScriptedDelayController` con una función de referencia como guion."""

    @pytest.fixture
    def make_impl(self) -> Callable[[DelayPolicy], DelayController]:
        return lambda policy: ScriptedDelayController(_ReferenceDecisions(policy))
