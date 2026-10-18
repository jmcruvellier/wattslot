"""Objectifs (lot 3.6) : réglage dans la configuration, objectif pondéré, indicateurs des plans."""

from pathlib import Path

import pytest

from tests.v1_oracle import STATES, load
from wattslot import configuration
from wattslot.configuration import Configuration
from wattslot.objective_settings import ObjectiveSettings, Preset, Weights, problems
from wattslot.planning.engine import Objective, plan_day
from wattslot.planning.inputs import from_v1
from wattslot.planning.plan import Indicators, Plan
from wattslot.planning.problem import Problem, from_input
from wattslot.planning.runner import goal
from wattslot.storage.graph import GraphStore

IDS = [p.stem for p in STATES]


def problem(index: int) -> Problem:
    state, _ = load(STATES[index])
    return from_input(from_v1(state))


def indicators(found: Problem, objective: Objective | Weights) -> Indicators:
    day = plan_day(found, objective).day
    assert day.indicators is not None
    return day.indicators


def test_objective_settings_validation_and_saved(tmp_path: Path) -> None:
    assert problems(ObjectiveSettings()) == []
    assert problems(ObjectiveSettings(preset=Preset.CUSTOM)) == [("objective_weights_missing", {})]
    zero = Weights(cost=0, grid_import=0, grid_export=0)
    assert problems(ObjectiveSettings(preset=Preset.CUSTOM, weights=zero)) == [
        ("objective_weights_missing", {})
    ]
    assert problems(ObjectiveSettings(weights=Weights())) == [("objective_weights_unused", {})]
    graph = GraphStore(tmp_path)
    custom = ObjectiveSettings(
        preset=Preset.CUSTOM, weights=Weights(cost=1, grid_import=0.5, grid_export=0.5)
    )
    for objective in (custom, ObjectiveSettings(preset=Preset.AUTONOMY)):
        saved = Configuration(objective=objective)
        configuration.save(graph, saved)
        assert configuration.load(graph) == saved


def test_the_objective_of_the_configuration_wins_over_the_planning_setting() -> None:
    assert goal(None, Objective.IMPORT) is Objective.IMPORT
    assert goal(Configuration(), Objective.IMPORT) is Objective.IMPORT  # pas encore réglé
    autonomy = Configuration(objective=ObjectiveSettings(preset=Preset.AUTONOMY))
    assert goal(autonomy, Objective.COST) is Objective.IMPORT
    weights = Weights(cost=1, grid_export=2)
    custom = Configuration(objective=ObjectiveSettings(preset=Preset.CUSTOM, weights=weights))
    assert goal(custom, Objective.COST) == weights


@pytest.mark.parametrize("index", range(len(STATES)), ids=IDS)
def test_indicators_follow_the_simulated_exchanges(index: int) -> None:
    found = problem(index)
    day = plan_day(found).day

    assert day.indicators is not None
    residual = day.residual_kwh
    assert day.indicators.import_kwh == pytest.approx(
        sum(-v for v in residual.values() if v < 0), abs=1e-3
    )
    assert day.indicators.export_kwh == pytest.approx(
        sum(v for v in residual.values() if v > 0), abs=1e-3
    )
    percent = day.indicators.self_consumption_percent
    assert percent is None or 0 <= percent <= 100
    assert Plan.from_v1(day.to_v1()).indicators == day.indicators  # gardés avec le plan


@pytest.mark.parametrize("index", range(len(STATES)), ids=IDS)
def test_each_preset_is_the_best_on_its_own_criterion(index: int) -> None:
    found = problem(index)
    cost = indicators(found, Objective.COST)
    autonomy = indicators(found, Objective.IMPORT)
    self_consumption = indicators(found, Objective.SELF_CONSUMPTION)

    assert cost.cost_eur <= min(autonomy.cost_eur, self_consumption.cost_eur) + 1e-3
    assert autonomy.import_kwh <= min(cost.import_kwh, self_consumption.import_kwh) + 1e-3
    assert self_consumption.export_kwh <= min(cost.export_kwh, autonomy.export_kwh) + 1e-3


def test_free_weights_trade_one_criterion_for_another() -> None:
    found = problem(11)  # journée ensoleillée, lessive à placer
    cost_only = indicators(found, Weights(cost=1))
    export_heavy = indicators(found, Weights(cost=1, grid_export=5))

    assert cost_only.cost_eur == pytest.approx(indicators(found, Objective.COST).cost_eur, abs=0.01)
    assert export_heavy.export_kwh <= cost_only.export_kwh + 1e-3
