"""Profils de maisons : la maison de référence exprimée dans le modèle de personnalisation."""

from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest

from tests.v1_oracle import STATES, load
from wattslot import configuration, profiles
from wattslot.detection import DeviceKind
from wattslot.planning.assemble import configured, recurring_tasks
from wattslot.planning.engine import plan_day
from wattslot.planning.inputs import PlanningInput, from_v1
from wattslot.planning.problem import from_input

REFERENCE = profiles.load("reference")


def test_the_reference_profile_is_valid_and_complete() -> None:
    assert "reference" in profiles.names()
    home, settings = REFERENCE.home, REFERENCE.configuration

    assert configuration.validate(home, settings) == []
    effective = configuration.effective(home, settings)
    appliances = [d for d in home.devices if d.kind not in (DeviceKind.SOLAR, DeviceKind.GRID)]
    assert all(
        not effective.of(d.key).default  # type: ignore[union-attr]
        for d in appliances
        if d.kind is not DeviceKind.BATTERY
    )
    # Aucune donnée d'une installation réelle : des entités génériques.
    entities = [s.entity_id for d in home.devices for s in d.sensors]
    assert all(e.startswith("sensor.") for e in entities) and len(set(entities)) == len(entities)


@pytest.mark.parametrize("path", STATES, ids=[p.stem for p in STATES])
def test_the_reference_configuration_changes_no_plan(path: Path) -> None:
    """Critère du lot 3.1 : la maison de référence configurée calcule les plans de la phase 2."""
    state, _ = load(path)
    data = from_v1(state)
    # Les puissances de la batterie ont changé dans la v1 entre deux captures : on reprend
    # celles de la capture, le reste de la configuration de référence étant inchangé.
    assert REFERENCE.configuration.battery is not None
    battery = REFERENCE.configuration.battery.model_copy(
        update={
            "charge_max_w": data.battery.charge_max_w,
            "discharge_max_w": data.battery.discharge_max_w,
        }
    )
    reference = REFERENCE.configuration.model_copy(update={"battery": battery})

    plain = plan_day(from_input(data))
    # Récurrence du chauffe-eau réglée (lot 3.5) : la tâche de HA est remplacée par l'échéance
    # tirée du dernier cycle, celui que la règle suppose d'après l'échéance capturée.
    tasks = recurring_tasks(
        data.due_tasks, REFERENCE.home, reference, {"water_heater": last_cycle(data)}, data.day
    )
    assert all(t.uid == "recurrence:water_heater" for t in tasks if t.name == "Chauffe-eau")
    configured_data = configured(replace(data, due_tasks=tuple(tasks)), REFERENCE.home, reference)
    with_reference = plan_day(from_input(configured_data))

    assert with_reference.output == plain.output


def last_cycle(data: PlanningInput) -> date:
    """Dernier cycle du chauffe-eau (tous les 2 jours) d'après sa tâche capturée ; sans tâche :
    la veille, échéance le lendemain."""
    due = next((t.due for t in data.due_tasks if t.name == "Chauffe-eau" and t.due), None)
    return due - timedelta(days=2) if due is not None else data.day - timedelta(days=1)


def test_a_device_left_out_of_the_reference_changes_the_plan() -> None:
    """Le test précédent n'est pas vide : la configuration agit bien sur ces états."""
    state, _ = load(STATES[0])
    data = from_v1(state)
    without_pool = REFERENCE.configuration.model_copy(
        update={
            "devices": [
                d.model_copy(update={"planned": False}) if d.key == "pool" else d
                for d in REFERENCE.configuration.devices
            ]
        }
    )

    result = plan_day(from_input(configured(data, REFERENCE.home, without_pool)))

    assert result.day.runtimes == []
