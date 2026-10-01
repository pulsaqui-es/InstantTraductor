"""Tests de `ThresholdDelayController` (T028): la suite `DelayControllerContract` y las reglas propias.

Política (FR-012 a FR-014, `contracts/pipeline.md`): velocidad lineal de 1,0 (con retraso =
`accelerate_after_s`) a `max_speed` (con retraso = `concise_after_s`); CONCISE cuando el retraso supera
`concise_after_s`, con histéresis hasta que baje de `accelerate_after_s` y solo si `allow_concise`;
`drop_oldest_pending` cuando el retraso supera `drop_after_s`.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import replace

import pytest

from instanttraductor.contracts import DelayController, DelayDecision, DelayPolicy, TranslationMode
from instanttraductor.pipeline.delay import ThresholdDelayController
from tests.contract.test_scheduling_contract import DelayControllerContract

NORMAL = TranslationMode.NORMAL
CONCISE = TranslationMode.CONCISE

#: Política por defecto de la spec: 3 s, 5 s y 8 s, velocidad máxima 1,25.
DEFAULT = DelayPolicy()


class TestThresholdDelayControllerContract(DelayControllerContract):
    @pytest.fixture
    def make_impl(self) -> Callable[[DelayPolicy], DelayController]:
        return ThresholdDelayController


# --------------------------------------------------------------------------------------------------
# Velocidad (FR-012)
# --------------------------------------------------------------------------------------------------


class TestSpeed:
    def test_is_exactly_one_up_to_the_first_threshold(self) -> None:
        controller = ThresholdDelayController(DEFAULT)
        assert controller.decide(0.0).speed == 1.0
        assert controller.decide(DEFAULT.accelerate_after_s).speed == 1.0

    def test_is_linear_between_the_first_and_second_thresholds(self) -> None:
        controller = ThresholdDelayController(DEFAULT)  # 3 s -> 1,0 y 5 s -> 1,25
        assert controller.decide(3.5).speed == pytest.approx(1.0625)
        assert controller.decide(4.0).speed == pytest.approx(1.125)
        assert controller.decide(4.5).speed == pytest.approx(1.1875)

    def test_is_exactly_max_speed_from_the_second_threshold(self) -> None:
        controller = ThresholdDelayController(DEFAULT)
        assert controller.decide(DEFAULT.concise_after_s).speed == DEFAULT.max_speed
        assert controller.decide(DEFAULT.drop_after_s + 10.0).speed == DEFAULT.max_speed

    def test_follows_the_thresholds_of_the_policy_not_fixed_numbers(self) -> None:
        policy = DelayPolicy(accelerate_after_s=1.0, max_speed=1.5, concise_after_s=3.0, drop_after_s=10.0)
        controller = ThresholdDelayController(policy)
        assert controller.decide(1.0).speed == 1.0
        assert controller.decide(2.0).speed == pytest.approx(1.25)
        assert controller.decide(3.0).speed == 1.5

    def test_a_max_speed_of_one_never_accelerates(self) -> None:
        controller = ThresholdDelayController(replace(DEFAULT, max_speed=1.0))
        assert [controller.decide(lag).speed for lag in (0.0, 4.0, 6.0, 20.0)] == [1.0] * 4

    def test_a_negative_lag_does_not_accelerate(self) -> None:
        assert ThresholdDelayController(DEFAULT).decide(-2.0) == DelayDecision(1.0, NORMAL, False)

    def test_an_infinite_lag_gives_max_speed_and_drops(self) -> None:
        decision = ThresholdDelayController(DEFAULT).decide(math.inf)
        assert decision == DelayDecision(DEFAULT.max_speed, CONCISE, True)

    def test_a_lag_that_is_not_a_number_is_neutral_and_keeps_the_state(self) -> None:
        controller = ThresholdDelayController(DEFAULT)
        assert controller.decide(math.nan) == DelayDecision(1.0, NORMAL, False)
        assert controller.decide(DEFAULT.concise_after_s + 1.0).mode is CONCISE
        assert controller.decide(math.nan).mode is CONCISE  # no cuenta como «retraso bajo el umbral»


# --------------------------------------------------------------------------------------------------
# Resumir (FR-013)
# --------------------------------------------------------------------------------------------------


class TestConcise:
    def test_needs_the_lag_to_exceed_the_second_threshold(self) -> None:
        controller = ThresholdDelayController(DEFAULT)
        assert controller.decide(DEFAULT.concise_after_s).mode is NORMAL  # igual al umbral: aún no
        assert controller.decide(DEFAULT.concise_after_s + 0.01).mode is CONCISE

    def test_keeps_summarising_while_the_lag_stays_at_or_above_the_first_threshold(self) -> None:
        controller = ThresholdDelayController(DEFAULT)
        controller.decide(6.0)
        for lag in (5.0, 4.0, DEFAULT.accelerate_after_s):
            assert controller.decide(lag).mode is CONCISE, f"con retraso {lag}"

    def test_stops_summarising_only_below_the_first_threshold(self) -> None:
        controller = ThresholdDelayController(DEFAULT)
        controller.decide(6.0)
        decision = controller.decide(DEFAULT.accelerate_after_s - 0.01)
        assert decision.mode is NORMAL
        assert decision.speed == 1.0

    def test_can_summarise_again_after_recovering(self) -> None:
        controller = ThresholdDelayController(DEFAULT)
        for lag, expected in ((6.0, CONCISE), (1.0, NORMAL), (4.0, NORMAL), (6.0, CONCISE), (4.0, CONCISE)):
            assert controller.decide(lag).mode is expected, f"con retraso {lag}"

    def test_a_lag_of_zero_clears_the_summary_state(self) -> None:
        controller = ThresholdDelayController(DEFAULT)
        controller.decide(7.0)
        assert controller.decide(0.0).mode is NORMAL  # la cola se vació: no queda nada que resumir

    def test_summarising_continues_while_dropping(self) -> None:
        decision = ThresholdDelayController(DEFAULT).decide(DEFAULT.drop_after_s + 1.0)
        assert decision.mode is CONCISE
        assert decision.drop_oldest_pending is True


class TestConciseNotAllowed:
    """Con `allow_concise=False` (reserva 1.8B) se salta la fase de resumir y se pasa a descartar."""

    @pytest.fixture
    def controller(self) -> ThresholdDelayController:
        return ThresholdDelayController(replace(DEFAULT, allow_concise=False))

    def test_never_asks_for_a_summary_at_any_lag(self, controller: ThresholdDelayController) -> None:
        lags = [0.0, 2.0, 3.0, 4.0, 5.0, 5.5, 7.0, 8.0, 9.0, 30.0, math.inf, 6.0, 1.0, 0.0]
        assert {controller.decide(lag).mode for lag in lags} == {NORMAL}

    def test_still_accelerates_up_to_max_speed(self, controller: ThresholdDelayController) -> None:
        assert controller.decide(4.0).speed == pytest.approx(1.125)
        assert controller.decide(6.0).speed == DEFAULT.max_speed

    def test_goes_from_accelerating_straight_to_dropping(self, controller: ThresholdDelayController) -> None:
        decision = controller.decide(DEFAULT.drop_after_s + 0.5)
        assert decision == DelayDecision(DEFAULT.max_speed, NORMAL, True)

    def test_stops_dropping_when_the_lag_falls(self, controller: ThresholdDelayController) -> None:
        controller.decide(DEFAULT.drop_after_s + 0.5)
        assert controller.decide(DEFAULT.drop_after_s - 0.5).drop_oldest_pending is False

    def test_the_default_policy_allows_summaries(self) -> None:
        assert DEFAULT.allow_concise is True
        assert ThresholdDelayController(DEFAULT).decide(6.0).mode is CONCISE


# --------------------------------------------------------------------------------------------------
# Descartar (FR-014)
# --------------------------------------------------------------------------------------------------


class TestDrop:
    def test_needs_the_lag_to_exceed_the_third_threshold(self) -> None:
        controller = ThresholdDelayController(DEFAULT)
        assert controller.decide(DEFAULT.drop_after_s).drop_oldest_pending is False  # igual al umbral: aún no
        assert controller.decide(DEFAULT.drop_after_s + 0.01).drop_oldest_pending is True

    def test_has_no_memory_of_the_previous_drop(self) -> None:
        controller = ThresholdDelayController(DEFAULT)
        flags = [controller.decide(lag).drop_oldest_pending for lag in (9.0, 7.0, 9.0, 9.0, 7.9)]
        assert flags == [True, False, True, True, False]

    def test_always_goes_with_the_maximum_speed(self) -> None:
        controller = ThresholdDelayController(DEFAULT)
        for lag in (8.01, 9.0, 12.0, 100.0):
            decision = controller.decide(lag)
            assert decision.drop_oldest_pending is True
            assert decision.speed == DEFAULT.max_speed


# --------------------------------------------------------------------------------------------------
# Estado, determinismo y política
# --------------------------------------------------------------------------------------------------


class TestStateAndPolicy:
    def test_each_controller_has_its_own_hysteresis_state(self) -> None:
        first, second = ThresholdDelayController(DEFAULT), ThresholdDelayController(DEFAULT)
        first.decide(6.0)
        assert first.decide(4.0).mode is CONCISE
        assert second.decide(4.0).mode is NORMAL

    def test_a_repeated_lag_gives_the_same_decision(self) -> None:
        controller = ThresholdDelayController(DEFAULT)
        controller.decide(6.0)
        assert controller.decide(4.0) == controller.decide(4.0)

    def test_decisions_are_immutable_values_that_compare_by_content(self) -> None:
        controller = ThresholdDelayController(DEFAULT)
        assert controller.decide(1.0) == DelayDecision(1.0, NORMAL, False)

    def test_exposes_its_policy(self) -> None:
        policy = replace(DEFAULT, max_speed=1.4)
        assert ThresholdDelayController(policy).policy == policy

    @pytest.mark.parametrize(
        "policy",
        [
            DelayPolicy(accelerate_after_s=5.0, concise_after_s=5.0),  # deben crecer estrictamente
            DelayPolicy(accelerate_after_s=6.0, concise_after_s=5.0),
            DelayPolicy(concise_after_s=8.0, drop_after_s=8.0),
            DelayPolicy(concise_after_s=9.0, drop_after_s=8.0),
            DelayPolicy(accelerate_after_s=-1.0),
            DelayPolicy(accelerate_after_s=0.0),  # con 0 la histéresis no podría soltarse nunca
            DelayPolicy(max_speed=0.9),
            DelayPolicy(accelerate_after_s=math.nan),
            DelayPolicy(drop_after_s=math.inf),
            DelayPolicy(max_speed=math.nan),
        ],
    )
    def test_rejects_an_invalid_policy(self, policy: DelayPolicy) -> None:
        with pytest.raises(ValueError, match="Política de retraso no válida"):
            ThresholdDelayController(policy)

    def test_accepts_a_max_speed_of_exactly_one(self) -> None:
        assert ThresholdDelayController(replace(DEFAULT, max_speed=1.0)).decide(4.0).speed == 1.0
