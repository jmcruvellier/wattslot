"""Lot 3.6 (2) : CO₂ (intensité du réseau lue dans HA), ménagement de la batterie, compromis de
la maison de référence (autoconsommation autant que le coût)."""

from dataclasses import replace
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tests.v1_oracle import STATES, load
from wattslot import configuration
from wattslot.configuration import Configuration
from wattslot.objective_settings import ObjectiveSettings, Preset, Weights, problems
from wattslot.planning.co2_sources import Co2Context, co2_context
from wattslot.planning.engine import Goal, Objective, plan_day
from wattslot.planning.inputs import from_v1
from wattslot.planning.plan import Indicators
from wattslot.planning.problem import Problem, from_input
from wattslot.planning.runner import goal
from wattslot.storage.graph import GraphStore

IDS = [p.stem for p in STATES]
PARIS = ZoneInfo("Europe/Paris")
DAY = date(2026, 10, 16)
# Intensité du réseau : faible en milieu de journée (solaire), forte le soir (gaz).
CLEAN_MIDDAY = {h: 60.0 if 10 <= h < 16 else 450.0 for h in range(24)}


def problem(index: int) -> Problem:
    state, _ = load(STATES[index])
    return from_input(from_v1(state))


def indicators(found: Problem, objective: Goal) -> Indicators:
    day = plan_day(found, objective).day
    assert day.indicators is not None
    return day.indicators


def test_intensity_from_the_forecast_or_the_current_value() -> None:
    state = {
        "entity_id": "sensor.co2",
        "state": "120",
        "attributes": {
            "forecast": [
                {"datetime": "2026-10-16T10:00:00+02:00", "carbon_intensity": 50},
                {"datetime": "2026-10-16T10:30:00+02:00", "carbon_intensity": 70},
            ]
        },
    }

    found = co2_context([state], "sensor.co2", PARIS).hourly(DAY)

    assert found[10] == 60 and found[9] == 120 and len(found) == 24
    assert co2_context([state], "sensor.other", PARIS) == Co2Context()
    unknown = {**state, "state": "unavailable", "attributes": {}}
    assert co2_context([unknown], "sensor.co2", PARIS).hourly(DAY) == {}


def test_objective_settings_with_co2_and_battery(tmp_path: Path) -> None:
    assert problems(ObjectiveSettings(preset=Preset.CO2)) == [("objective_co2_without_entity", {})]
    carbon = Weights(cost=1, co2=1)
    assert problems(ObjectiveSettings(preset=Preset.CUSTOM, weights=carbon)) == [
        ("objective_co2_without_entity", {})
    ]
    assert problems(ObjectiveSettings(preset=Preset.CO2, co2_entity="sensor.co2")) == []
    graph = GraphStore(tmp_path)
    saved = Configuration(
        objective=ObjectiveSettings(
            preset=Preset.CUSTOM,
            weights=Weights(cost=1, co2=0.5, battery=0.2),
            co2_entity="sensor.co2",
        )
    )
    configuration.save(graph, saved)
    assert configuration.load(graph) == saved
    assert goal(Configuration(objective=ObjectiveSettings(preset=Preset.CO2)), Objective.COST) is (
        Objective.CO2
    )


def test_the_co2_preset_imports_when_the_grid_is_cleanest() -> None:
    # Journée couverte, lessive à placer : le soutirage se déplace vers les heures propres.
    found = replace(problem(10), co2_g_kwh=CLEAN_MIDDAY)

    co2 = indicators(found, Objective.CO2)
    cost = indicators(found, Objective.COST)

    assert co2.co2_kg is not None and cost.co2_kg is not None
    assert co2.co2_kg < cost.co2_kg - 0.05  # moins de CO₂…
    assert co2.cost_eur > cost.cost_eur  # … au prix d'une facture un peu plus haute
    assert indicators(problem(10), Objective.COST).co2_kg is None  # sans intensité


@pytest.mark.parametrize("index", range(len(STATES)), ids=IDS)
def test_battery_care_lowers_the_energy_through_the_battery(index: int) -> None:
    found = problem(index)

    plain = indicators(found, Weights(cost=1))
    careful = indicators(found, Weights(cost=1, battery=1))

    assert careful.battery_throughput_kwh <= plain.battery_throughput_kwh + 1e-3


@pytest.mark.parametrize("index", range(len(STATES)), ids=IDS)
def test_the_reference_compromise_self_consumption_as_much_as_cost(index: int) -> None:
    """Maison de référence : autoconsommation autant que le coût. Le compromis à poids égaux
    autoconsomme au moins autant que le préréglage coût, pour un coût à 1 centime près (en
    octobre, l'injection est déjà presque nulle : peu de marge entre les deux)."""
    found = problem(index)

    cost = indicators(found, Objective.COST)
    compromise = indicators(found, Weights(cost=1, grid_export=1))

    assert compromise.cost_eur <= cost.cost_eur + 0.01
    if cost.self_consumption_percent is not None:
        assert compromise.self_consumption_percent is not None
        assert compromise.self_consumption_percent + 1e-6 >= cost.self_consumption_percent
