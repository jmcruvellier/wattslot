"""Besoin d'énergie avant une échéance (lot 3.4) : réglages, calcul, assemblage."""

from dataclasses import replace
from pathlib import Path

import pytest

from tests.planning.test_assemble import MODEL
from tests.v1_oracle import STATES, load
from wattslot import configuration
from wattslot.configuration import Behavior, Configuration, DeviceSettings
from wattslot.detection import DeviceKind, Role
from wattslot.energy_need import EnergyNeed, problems
from wattslot.home_model import HomeDevice, HomeModel, HomeSensor
from wattslot.planning.assemble import configured
from wattslot.planning.engine import plan_day
from wattslot.planning.horizon import next_day_input
from wattslot.planning.inputs import Need, PlanningInput, from_v1
from wattslot.planning.plan import Slot
from wattslot.planning.problem import from_input
from wattslot.storage.graph import GraphStore

CAR = Need(name="Voiture", energy_kwh=10, earliest_hour=0, deadline_hour=24, max_kw=3)
WATER_HEATER = HomeDevice(
    key="water_heater",
    kind=DeviceKind.WATER_HEATER,
    name="Chauffe-eau",
    sensors=[HomeSensor(entity_id="sensor.water_heater_power", role=Role.POWER_CONSUMED)],
)
HEATING = EnergyNeed(energy_kwh=3, earliest_hour=10, deadline_hour=18, max_kw=2)


def state() -> PlanningInput:
    data, _ = load(STATES[0])
    return from_v1(data)


def slot(data: PlanningInput, name: str) -> Slot:
    found = [i for i in plan_day(from_input(data)).day.items if i.device == name]
    assert len(found) == 1 and isinstance(found[0], Slot)
    return found[0]


def test_problems_and_saved_settings(tmp_path: Path) -> None:
    assert problems(HEATING) == []
    assert problems(HEATING.model_copy(update={"deadline_hour": 10})) == [("need_window_empty", {})]
    assert problems(HEATING.model_copy(update={"energy_kwh": 20})) == [
        ("need_too_large", {"hours": "8"})
    ]
    graph = GraphStore(tmp_path)
    saved = Configuration(
        devices=[
            DeviceSettings(key="water_heater", behavior=Behavior.ENERGY_BY_DEADLINE, energy=HEATING)
        ]
    )
    configuration.save(graph, saved)
    assert configuration.load(graph) == saved
    misplaced = Configuration(
        devices=[DeviceSettings(key="water_heater", behavior=Behavior.CYCLE, energy=HEATING)]
    )
    home = HomeModel(devices=[WATER_HEATER])
    assert [i.code for i in configuration.validate(home, misplaced)] == ["need_not_used"]


def test_an_unset_water_heater_is_a_cycle_to_start() -> None:
    found = configuration.effective(HomeModel(devices=[WATER_HEATER]), Configuration())
    settings = found.of("water_heater")
    assert settings is not None and settings.behavior is Behavior.CYCLE


def test_the_energy_is_delivered_before_the_deadline() -> None:
    data = replace(state(), needs=(replace(CAR, earliest_hour=8, deadline_hour=20),))

    found = slot(data, "Voiture")

    assert found.energy_kwh == 10 and found.hourly_kwh is not None
    assert sum(found.hourly_kwh.values()) == pytest.approx(10, abs=1e-9)
    assert all(8 <= hour < 20 and kwh <= 3 for hour, kwh in found.hourly_kwh.items())


def test_in_steps_each_hour_is_all_or_nothing() -> None:
    data = replace(state(), needs=(replace(CAR, energy_kwh=6, steps=True),))

    found = slot(data, "Voiture")

    assert found.hourly_kwh is not None and sorted(found.hourly_kwh.values()) == [3, 3]


def test_a_need_that_no_longer_fits_is_reported() -> None:
    data = state()  # calcul à partir de 6 h
    too_late = replace(CAR, deadline_hour=6)
    short = replace(CAR, energy_kwh=10, deadline_hour=8)  # 2 h à 3 kW : 6 kWh au plus

    passed = plan_day(from_input(replace(data, needs=(too_late,)))).day
    partial = plan_day(from_input(replace(data, needs=(short,)))).day

    assert not [i for i in passed.items if i.device == "Voiture"]
    codes = [w["code"] for w in passed.warnings if isinstance(w, dict)]
    assert "heures_insuffisantes_du" in codes
    assert any(
        isinstance(w, dict) and w["params"].get("equipement") == "Voiture" for w in partial.warnings
    )
    delivered = [i for i in partial.items if i.device == "Voiture"]
    assert isinstance(delivered[0], Slot) and delivered[0].energy_kwh == 6


def test_configured_needs_daily_or_asked_by_a_task() -> None:
    data = state()  # tâche « Chauffe-eau » due
    home = HomeModel(devices=[*MODEL.devices, WATER_HEATER])

    def settings(need: EnergyNeed) -> Configuration:
        return Configuration(
            devices=[
                DeviceSettings(
                    key="water_heater", behavior=Behavior.ENERGY_BY_DEADLINE, energy=need
                )
            ]
        )

    daily = configured(data, home, settings(HEATING))
    asked = configured(data, home, settings(HEATING.model_copy(update={"daily": False})))
    unasked = configured(
        replace(data, due_tasks=()), home, settings(HEATING.model_copy(update={"daily": False}))
    )

    assert [n.name for n in daily.needs] == ["Chauffe-eau"] and daily.due_tasks == ()
    assert [n.name for n in asked.needs] == ["Chauffe-eau"] and asked.due_tasks == ()
    assert unasked.needs == ()
    # Sans besoin réglé : cycle à démarrer, comme la v1.
    unset = configured(data, home, Configuration())
    assert unset.needs == () and [t.name for t in unset.due_tasks] == ["Chauffe-eau"]


def test_only_daily_needs_go_on_to_the_next_days() -> None:
    data = replace(state(), needs=(CAR, replace(CAR, name="Ballon", daily=False)))
    forecast = type("F", (), {"net_kwh": {}, "production_kwh": {}, "warnings": []})()

    following = next_day_input(data, data.day, forecast, 1.0)

    assert [n.name for n in following.needs] == ["Voiture"]
