"""Équipements identifiés par la configuration (lot 3.4) : tâches, cycles, ligne de base."""

import pytest

from tests.planning.test_past import MODEL as PAST_MODEL
from tests.planning.test_past import PARIS, TODAY, FakeReader, days_back, house
from wattslot import configuration
from wattslot.configuration import Behavior, Configuration, DeviceSettings
from wattslot.detection import DeviceKind, Role
from wattslot.home_model import HomeDevice, HomeModel, HomeSensor
from wattslot.planning.assemble import appliance_for
from wattslot.planning.inputs import TaskRequest
from wattslot.planning.journal import appliances, cycle_appliances
from wattslot.planning.past import baseline


def device(key: str, kind: DeviceKind, name: str) -> HomeDevice:
    return HomeDevice(
        key=key,
        kind=kind,
        name=name,
        sensors=[HomeSensor(entity_id=f"sensor.{key}_power", role=Role.POWER_CONSUMED)],
    )


HOME = HomeModel(
    devices=[
        device("kitchen", DeviceKind.DISHWASHER, "Lave-vaisselle cuisine"),
        device("garage", DeviceKind.DISHWASHER, "Lave-vaisselle garage"),
        device("washer", DeviceKind.WASHING_MACHINE, "Machine à laver"),
        device("dryer", DeviceKind.DRYER, "Sèche-linge"),
        device("dehumidifier", DeviceKind.OTHER_LOAD, "Déshumidificateur"),
        device("fridge", DeviceKind.OTHER_LOAD, "Réfrigérateur"),
    ]
)


def task(name: str) -> TaskRequest:
    return TaskRequest(name=name, uid=None, due=None, on_demand=True)


def test_a_task_goes_to_the_device_of_its_name_then_of_its_kind() -> None:
    every = appliances(HOME, frozenset(DeviceKind))

    def key(name: str) -> str | None:
        found = appliance_for(task(name), every)
        return found.key if found else None

    assert key("Lave-vaisselle garage") == "garage"
    assert key("lave vaisselle CUISINE") == "kitchen"  # casse, accents, séparateurs
    assert key("Lave-vaisselle") is None  # deux lave-vaisselle : lequel ?
    assert key("Lave-linge") == "washer"  # seul équipement de ce type
    assert key("Sèche-linge") == "dryer"
    assert key("Déshumidificateur") == "dehumidifier"  # « autre consommation » nommée
    assert key("Aspirateur") is None


def test_cycle_devices_follow_the_configuration() -> None:
    assert [a.key for a in cycle_appliances(HOME, None)] == ["kitchen", "garage", "washer", "dryer"]

    settings = Configuration(
        devices=[
            DeviceSettings(key="dehumidifier", behavior=Behavior.CYCLE),
            DeviceSettings(key="dryer", behavior=Behavior.UNCONTROLLED),
            DeviceSettings(key="garage", behavior=Behavior.CYCLE, planned=False),
        ]
    )
    found = [a.key for a in cycle_appliances(HOME, settings)]
    assert found == ["kitchen", "washer", "dehumidifier"]
    assert configuration.keys_with(HOME, settings, configuration.SCHEDULED) == set(found)


def test_the_baseline_removes_the_devices_planned_by_the_configuration() -> None:
    reader = FakeReader()
    for day in days_back(14):
        house(reader, day, 10, 0.5)  # chauffe-eau 0,3 compté hors de la base
        reader.add("sensor.tv", day, 10, energy_kwh=0.1)

    def at_ten(planned: set[str] | None) -> float:
        return baseline(PAST_MODEL, reader, TODAY, TODAY, PARIS, planned=planned)[10]

    assert at_ten(None) == pytest.approx(0.5)  # types planifiés de la phase 2
    assert at_ten({"heater"}) == pytest.approx(0.5)
    assert at_ten({"tv"}) == pytest.approx(0.5 + 0.3 - 0.1)  # chauffe-eau dans la base
    assert at_ten(set()) == pytest.approx(0.8)
