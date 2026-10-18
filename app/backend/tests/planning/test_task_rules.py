"""Lot 3.5 (2) : « démarre après la fin de », plancher de batterie par plage, report toléré."""

from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from tests.planning.test_assemble import MODEL, TODAY
from tests.v1_oracle import STATES, load
from wattslot import configuration
from wattslot.battery_settings import (
    BatterySettings,
    FloorRange,
    covers,
    floor_percent_at,
    problems,
)
from wattslot.configuration import Automation, Behavior, Configuration, DeviceSettings
from wattslot.detection import DeviceKind, Role
from wattslot.home_model import HomeDevice, HomeModel, HomeSensor
from wattslot.planning.assemble import configured
from wattslot.planning.assignment import decide
from wattslot.planning.engine import plan_day
from wattslot.planning.inputs import PlanningInput, TaskRequest, from_v1
from wattslot.planning.plan import BatteryPlan
from wattslot.planning.problem import from_input
from wattslot.planning.simulation import simulate
from wattslot.storage.graph import GraphStore

DRYER = HomeDevice(
    key="dryer",
    kind=DeviceKind.DRYER,
    name="Sèche-linge",
    sensors=[HomeSensor(entity_id="sensor.dryer_power", role=Role.POWER_CONSUMED)],
)
HOME = HomeModel(devices=[*MODEL.devices, DRYER])
WASHING = TaskRequest(name="Lave-linge", uid="w", on_demand=True)
DRYING = TaskRequest(name="Sèche-linge", uid="d", on_demand=True)


def state() -> PlanningInput:
    data, _ = load(STATES[0])
    return from_v1(data)


def cycle(key: str, **values: object) -> DeviceSettings:
    return DeviceSettings(key=key, behavior=Behavior.CYCLE, **values)  # type: ignore[arg-type]


# --- Plancher de batterie par plage ----------------------------------------------------------


def test_floor_ranges_raise_the_floor_where_they_apply() -> None:
    assert covers(22, 6, 23) and covers(22, 6, 5) and not covers(22, 6, 6)
    assert covers(0, 6, 5) and not covers(5, 5, 5)
    ranges = ((0, 6, 20.0), (5, 7, 30.0))
    assert [floor_percent_at(10.0, ranges, h) for h in (4, 5, 6, 7)] == [20.0, 30.0, 30.0, 10.0]
    bad = BatterySettings(floor_ranges=[FloorRange(start_hour=3, end_hour=3, percent=20)])
    assert [code for code, _ in problems(bad)] == ["battery_floor_range_empty"]


def test_floor_ranges_are_saved(tmp_path: Path) -> None:
    graph = GraphStore(tmp_path)
    saved = Configuration(
        battery=BatterySettings(
            floor_ranges=[
                FloorRange(start_hour=0, end_hour=6, percent=20),
                FloorRange(start_hour=22, end_hour=24, percent=15),
            ]
        )
    )
    configuration.save(graph, saved)
    assert configuration.load(graph) == saved


def test_the_simulated_battery_keeps_the_floor_of_each_hour() -> None:
    run = simulate(
        {0: -1.0, 1: -1.0},
        stored_kwh=3.0,
        capacity_kwh=5.0,
        charge_max_kw=2.0,
        discharge_max_kw=2.0,
        active_from=0,
        active_to=24,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        floor_kwh=0.0,
        floor_by_hour={0: 3.0},
    )
    assert [(m.hour, m.action) for m in run.movements] == [(1, "decharge")]


def test_the_plan_does_not_discharge_below_a_higher_floor() -> None:
    data = state()
    held = replace(data, battery=replace(data.battery, floor_ranges=((0, 24, 100.0),)))

    problem = from_input(held)
    result = plan_day(problem)

    assert problem.battery.floor_at(12) == problem.battery.capacity_kwh
    battery = next(i for i in result.day.items if isinstance(i, BatteryPlan))
    assert not [m for m in battery.movements if m.action == "decharge"]


# --- « Démarre après la fin de » -------------------------------------------------------------


def test_a_task_starts_after_the_configured_device() -> None:
    data = replace(state(), waiting_tasks=(WASHING, replace(DRYING, depends_on=None)))
    settings = Configuration(devices=[cycle("dryer", after="washer")])

    found = {t.name: t for t in configured(data, HOME, settings).waiting_tasks}
    alone = configured(replace(data, waiting_tasks=(DRYING,)), HOME, settings).waiting_tasks

    assert found["Sèche-linge"].depends_on == "Lave-linge"
    assert alone[0].depends_on is None  # pas de lessive en attente : rien à suivre


def test_without_setting_the_task_description_still_applies() -> None:
    data = replace(state(), waiting_tasks=(WASHING, replace(DRYING, depends_on="Lave-linge")))

    found = configured(data, HOME, Configuration()).waiting_tasks

    assert found[1].depends_on == "Lave-linge"


def test_task_rules_validation_and_saved_settings(tmp_path: Path) -> None:
    settings = Configuration(
        devices=[
            cycle("dryer", after="washer", max_delay_days=1),
            DeviceSettings(
                key="solar",
                behavior=Behavior.PRODUCTION,
                automation=Automation.INFORM,
                after="washer",
                max_delay_days=3,
            ),
            cycle("washer", after="nowhere"),
        ]
    )
    found = [(i.code, i.device) for i in configuration.validate(HOME, settings)]
    assert found == [
        ("after_not_used", "solar"),
        ("delay_not_used", "solar"),
        ("after_unknown", "washer"),
    ]
    graph = GraphStore(tmp_path)
    saved = Configuration(devices=[cycle("dryer", after="washer", max_delay_days=0)])
    configuration.save(graph, saved)
    assert configuration.load(graph) == saved


# --- Tolérance de report ---------------------------------------------------------------------


def test_the_postponement_tolerance_of_each_device() -> None:
    data = replace(state(), waiting_tasks=(WASHING,))
    settings = Configuration(devices=[cycle("washer", max_delay_days=0)])
    assert configured(data, HOME, settings).max_delay_days == {"Lave-linge": 0}

    tomorrow = TODAY + timedelta(days=1)
    surplus = {TODAY: {}, tomorrow: {h: 3.0 for h in range(10, 16)}}

    def day(delays: dict[str, int] | None) -> object:
        found, _ = decide(
            [WASHING], surplus, TODAY, 8, {WASHING.name: (1.0, 90.0)}, {}, set(), delays=delays
        )
        return found["w"].day

    assert day(None) == tomorrow  # reportée au jour ensoleillé, dans la tolérance de 2 jours
    assert day({WASHING.name: 0}) == TODAY
