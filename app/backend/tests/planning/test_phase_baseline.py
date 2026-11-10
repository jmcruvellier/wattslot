"""Maison en triphasé : capteurs du réseau par phase et consommation de base de chaque phase."""

from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from tests.planning.test_past import PARIS, TODAY, FakeReader, days_back
from tests.planning.test_phase_limit import CHEAP_HOUR, phase_warnings, problem, starts, task
from wattslot import home_model
from wattslot.detection import DeviceKind, Role
from wattslot.home_model import HomeDevice, HomeModel, HomeSensor, Phase, Supply, counted_sensors
from wattslot.planning import past
from wattslot.planning.past import baseline, baseline_by_phase
from wattslot.storage.graph import GraphStore


def sensor(entity_id: str, role: Role, phase: Phase | None = None) -> HomeSensor:
    return HomeSensor(entity_id=entity_id, role=role, phase=phase)


def device(key: str, kind: DeviceKind, phase: Phase | None, *sensors: HomeSensor) -> HomeDevice:
    return HomeDevice(key=key, kind=kind, name=key, phase=phase, sensors=list(sensors))


GRID = device(
    "grid",
    DeviceKind.GRID,
    None,
    sensor("sensor.imp", Role.ENERGY_IMPORTED),
    sensor("sensor.exp", Role.ENERGY_EXPORTED),
    *(
        sensor(f"sensor.{name}_{number}", role, line)
        for number, line in enumerate(home_model.LINES, start=1)
        for name, role in (("imp", Role.ENERGY_IMPORTED), ("exp", Role.ENERGY_EXPORTED))
    ),
)
HOME = HomeModel(
    supply=Supply.THREE,
    devices=[
        GRID,
        device("roof", DeviceKind.SOLAR, Phase.L2, sensor("sensor.pv", Role.ENERGY_PRODUCED)),
        device(
            "battery",
            DeviceKind.BATTERY,
            Phase.L2,
            sensor("sensor.chg", Role.ENERGY_CHARGED),
            sensor("sensor.dis", Role.ENERGY_DISCHARGED),
        ),
        device(
            "heater", DeviceKind.WATER_HEATER, Phase.L1, sensor("sensor.wh", Role.ENERGY_CONSUMED)
        ),
        device(
            "charger", DeviceKind.OTHER_LOAD, Phase.ALL, sensor("sensor.ev", Role.ENERGY_CONSUMED)
        ),
    ],
)
# Une heure type : ce que mesure chaque capteur (kWh).
HOUR = {
    "sensor.imp": 3.3,
    "sensor.exp": 0.0,
    "sensor.imp_1": 2.0,  # dont 1,5 kWh de chauffe-eau et 0,3 kWh de borne
    "sensor.exp_1": 0.0,
    "sensor.imp_2": 0.5,
    "sensor.exp_2": 0.2,
    "sensor.imp_3": 1.0,  # dont 0,3 kWh de borne
    "sensor.exp_3": 0.0,
    "sensor.pv": 1.0,
    "sensor.chg": 0.4,
    "sensor.dis": 0.0,
    "sensor.wh": 1.5,
    "sensor.ev": 0.9,
}


def reader_of(values: dict[str, float] = HOUR, days: int = 21) -> FakeReader:
    reader = FakeReader()
    for day in days_back(days):
        for hour in range(24):
            for entity_id, kwh in values.items():
                reader.add(entity_id, day, hour, energy_kwh=kwh)
    return reader


# --- Capteurs par phase ---------------------------------------------------------------------------


def test_the_phase_of_a_grid_sensor_round_trips_through_rdf(tmp_path: Path) -> None:
    graph = GraphStore(tmp_path)

    home_model.save(graph, HOME)

    read = home_model.load(graph)
    measured = {s.entity_id: s.phase for d in read.devices for s in d.sensors}
    assert measured == {s.entity_id: s.phase for d in HOME.devices for s in d.sensors}
    assert measured["sensor.imp"] is None and measured["sensor.exp_3"] is Phase.L3
    assert {d.key: d.phase for d in read.devices} == {d.key: d.phase for d in HOME.devices}


def test_only_grid_sensors_measure_one_phase(tmp_path: Path) -> None:
    graph = GraphStore(tmp_path)
    plug = device(
        "plug", DeviceKind.OTHER_LOAD, None, sensor("sensor.plug", Role.ENERGY_CONSUMED, Phase.L1)
    )
    whole = device(
        "grid", DeviceKind.GRID, None, sensor("sensor.imp", Role.ENERGY_IMPORTED, Phase.ALL)
    )

    home_model.save(graph, HomeModel(devices=[plug, whole]))

    assert [s.phase for d in home_model.load(graph).devices for s in d.sensors] == [None, None]


def test_phase_sensors_are_not_counted_twice_in_the_totals() -> None:
    assert [s.entity_id for s in counted_sensors(GRID)] == ["sensor.imp", "sensor.exp"]
    assert past.sensors(HOME, [Role.ENERGY_IMPORTED]) == ["sensor.imp"]
    # Sans capteur du total, les trois phases le font ensemble.
    only_phases = replace_sensors(GRID, [s for s in GRID.sensors if s.phase is not None])
    assert len(counted_sensors(only_phases)) == 6


def replace_sensors(target: HomeDevice, sensors: list[HomeSensor]) -> HomeDevice:
    return target.model_copy(update={"sensors": sensors})


def test_the_home_baseline_ignores_the_phase_sensors() -> None:
    reader = reader_of()

    whole = baseline(HOME, reader, TODAY, TODAY, PARIS, planned=["heater", "charger"])

    # 1 produit + 3,3 soutirés - 0,4 chargés - 2,4 d'équipements planifiés.
    assert whole[12] == pytest.approx(1.5)


# --- Consommation de base par phase ---------------------------------------------------------------


def test_each_phase_has_its_own_baseline() -> None:
    found = baseline_by_phase(HOME, reader_of(), TODAY, TODAY, PARIS, planned=["heater", "charger"])

    # Phase 1 : 2 soutirés - 1,5 de chauffe-eau - un tiers de la borne.
    assert found[Phase.L1][12] == pytest.approx(0.2)
    # Phase 2 : 1 produit + 0,5 soutiré - 0,2 injecté - 0,4 chargé - un tiers de la borne.
    assert found[Phase.L2][12] == pytest.approx(0.6)
    # Phase 3 : 1 soutiré - un tiers de la borne.
    assert found[Phase.L3][12] == pytest.approx(0.7)
    # Les trois phases font la maison.
    assert sum(found[line][12] for line in home_model.LINES) == pytest.approx(1.5)


def test_no_phase_baseline_when_it_cannot_be_measured() -> None:
    reader = reader_of()
    single = HOME.model_copy(update={"supply": Supply.SINGLE})
    two_phases = HOME.model_copy(
        update={
            "devices": [
                replace_sensors(GRID, [s for s in GRID.sensors if s.phase is not Phase.L3]),
                *HOME.devices[1:],
            ]
        }
    )
    solar_unknown = HOME.model_copy(
        update={
            "devices": [
                d.model_copy(update={"phase": None}) if d.key == "roof" else d for d in HOME.devices
            ]
        }
    )

    for model in (single, two_phases, solar_unknown):
        assert baseline_by_phase(model, reader, TODAY, TODAY, PARIS) == {}


# --- Dans la limite par phase ---------------------------------------------------------------------


def test_the_baseline_of_the_phase_counts_in_its_limit() -> None:
    alone = problem(task("heater", 3), phases={"heater": Phase.L1})
    # 1,5 kWh de consommation de base sur la phase à l'heure bon marché : 3 + 1,5 dépassent 4.
    loaded = replace(alone, base_by_phase={Phase.L1: {CHEAP_HOUR: 1.5}})
    elsewhere = replace(alone, base_by_phase={Phase.L2: {CHEAP_HOUR: 1.5}})

    assert starts(alone) == {"heater": CHEAP_HOUR}
    assert starts(loaded)["heater"] != CHEAP_HOUR
    assert starts(elsewhere) == {"heater": CHEAP_HOUR}


def test_the_baseline_alone_is_not_reported() -> None:
    # 5 kWh de consommation de base à midi sur la phase 1 : au-delà de sa part, sans appareil.
    found = problem(
        task("heater", 3),
        phases={"heater": Phase.L1},
        base_by_phase={Phase.L1: {12: 5.0}},
    )

    assert starts(found) == {"heater": CHEAP_HOUR}
    assert phase_warnings(found) == []


def test_the_day_of_the_calculation_is_set() -> None:
    assert date(2026, 10, 16) == TODAY
