"""Batterie générique (lot 3.3) : réglages, enregistrement, effet sur le calcul, maison sans."""

from dataclasses import replace
from pathlib import Path

import pytest

from tests.planning.test_assemble import MODEL
from tests.planning.test_configured_run import plans
from tests.v1_oracle import STATES, load
from wattslot import configuration
from wattslot.battery_settings import DEFAULT, BatterySettings, problems
from wattslot.configuration import Configuration
from wattslot.detection import DeviceKind
from wattslot.home_model import HomeModel
from wattslot.planning.assemble import configured
from wattslot.planning.inputs import RecentHistory, from_v1
from wattslot.planning.problem import from_input
from wattslot.storage.graph import GraphStore

CUSTOM = BatterySettings(
    charge_max_w=3000,
    discharge_max_w=1500,
    floor_percent=20,
    active_from_hour=8,
    active_to_hour=22,
    full_charge_every_days=None,
)


def test_powers_default_to_half_the_capacity_per_hour() -> None:
    assert DEFAULT.powers_w(5.12) == (2560.0, 2560.0)
    assert DEFAULT.powers_w(0.0) == (0.0, 0.0)
    assert CUSTOM.powers_w(5.12) == (3000, 1500)
    assert BatterySettings(charge_max_w=1000).powers_w(4.0) == (1000, 2000.0)


def test_problems() -> None:
    assert problems(DEFAULT) == [] and problems(CUSTOM) == []
    empty = BatterySettings(active_from_hour=10, active_to_hour=10)
    assert problems(empty) == [("battery_active_range_empty", {})]


def test_saved_and_read_back(tmp_path: Path) -> None:
    graph = GraphStore(tmp_path)
    for settings in (DEFAULT, CUSTOM):
        configuration.save(graph, Configuration(battery=settings))
        assert configuration.load(graph).battery == settings
    configuration.save(graph, Configuration())
    assert configuration.battery_of(configuration.load(graph)) == DEFAULT


def test_the_problem_follows_the_battery_settings() -> None:
    state, _ = load(STATES[0])
    data = from_v1(state)
    # Sans les plannings de la batterie Marstek (entrée de la v1) : la plage active réglée.
    data = replace(data, battery=replace(data.battery, schedules=()))
    capacity = data.battery.capacity_kwh

    battery = from_input(configured(data, MODEL, Configuration(battery=CUSTOM))).battery

    assert (battery.charge_max_kw, battery.discharge_max_kw) == (3.0, 1.5)
    assert battery.floor_kwh == pytest.approx(capacity * 0.20)
    assert (battery.active_from, battery.active_to) == (8, 22)
    assert battery.full_priority is False  # pas de charge complète périodique

    weekly = CUSTOM.model_copy(update={"full_charge_every_days": 1})
    # Aucune charge complète sur 30 jours d'historique : la journée la vise en priorité.
    with_history = replace(data, history=RecentHistory(last_full_charge=None, days=30))
    due = from_input(configured(with_history, MODEL, Configuration(battery=weekly))).battery
    assert due.full_priority is True


def test_a_home_without_battery(tmp_path: Path) -> None:
    without = HomeModel(devices=[d for d in MODEL.devices if d.kind is not DeviceKind.BATTERY])

    found = plans(tmp_path, without, Configuration())

    for plan in found:
        assert plan.battery is not None and plan.battery.movements == []
        assert plan.battery.start_kwh == 0 and plan.battery.end_kwh == 0
