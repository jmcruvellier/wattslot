"""Lot 3.5 (3) : récurrences dans la configuration, reprise des descriptions JSON de la v1, états
de test des contraintes (bruit la nuit, linge terminé avant 18 h, eau chaude à 7 h)."""

from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from tests.test_health import _settings
from tests.v1_oracle import STATES, load
from wattslot import configuration, profiles
from wattslot.configuration import Behavior, Configuration, DeviceSettings
from wattslot.energy_need import EnergyNeed
from wattslot.main import create_app
from wattslot.planning.assemble import configured, recurring_tasks, rules_from_tasks
from wattslot.planning.engine import plan_day
from wattslot.planning.horizon import next_day_input
from wattslot.planning.inputs import PlanningInput, TaskRequest, from_v1
from wattslot.planning.plan import Plan, Slot
from wattslot.planning.problem import from_input
from wattslot.recurrence_settings import Recurrence, next_due, problems
from wattslot.storage.graph import GraphStore
from wattslot.time_constraints import ConstraintKind, TimeConstraint

REFERENCE = profiles.load("reference")
HOME = REFERENCE.home
DAY = date(2026, 10, 16)  # vendredi
EVERY_OTHER_DAY = Recurrence(rule="FREQ=DAILY;INTERVAL=2")
TUESDAY_FRIDAY = Recurrence(rule="FREQ=WEEKLY;BYDAY=TU,FR")


def state(index: int) -> PlanningInput:
    data, _ = load(STATES[index])
    return from_v1(data)


def settings(**devices: DeviceSettings) -> Configuration:
    """Configuration de référence, avec ces équipements réglés autrement."""
    return REFERENCE.configuration.model_copy(
        update={"devices": [devices.get(d.key, d) for d in REFERENCE.configuration.devices]}
    )


def reference(key: str) -> DeviceSettings:
    found = REFERENCE.configuration.of(key)
    assert found is not None
    return found


def slots(day: Plan, name: str) -> list[Slot]:
    return [i for i in day.items if isinstance(i, Slot) and i.device == name]


# --- Échéances -------------------------------------------------------------------------------


def test_every_other_day_counts_from_the_last_cycle() -> None:
    assert next_due(EVERY_OTHER_DAY, DAY - timedelta(days=1), DAY) == DAY + timedelta(days=1)
    assert next_due(EVERY_OTHER_DAY, DAY - timedelta(days=2), DAY) == DAY
    assert next_due(EVERY_OTHER_DAY, DAY - timedelta(days=5), DAY) == DAY  # rattrapage
    assert next_due(EVERY_OTHER_DAY, None, DAY) == DAY  # jamais vu tourner


def test_weekly_days_follow_the_calendar_with_catch_up() -> None:
    thursday = DAY - timedelta(days=1)
    assert next_due(TUESDAY_FRIDAY, thursday, DAY) == DAY  # vendredi
    assert next_due(TUESDAY_FRIDAY, DAY - timedelta(days=4), DAY + timedelta(days=1)) == (
        DAY + timedelta(days=1)  # vendredi manqué : rattrapé samedi
    )
    assert next_due(TUESDAY_FRIDAY, DAY, DAY + timedelta(days=1)) == DAY + timedelta(days=4)
    ended = Recurrence(rule="FREQ=DAILY;UNTIL=20261001")
    assert next_due(ended, None, DAY) is None


def test_recurrence_validation_and_saved_settings(tmp_path: Path) -> None:
    assert problems(EVERY_OTHER_DAY) == []
    assert [code for code, _ in problems(Recurrence(rule="FREQ=MONTHLY"))] == ["recurrence_rule"]
    graph = GraphStore(tmp_path)
    weekly = TUESDAY_FRIDAY.model_copy(update={"start": DAY})
    saved = Configuration(
        devices=[DeviceSettings(key="dishwasher", behavior=Behavior.CYCLE, recurrence=weekly)]
    )
    configuration.save(graph, saved)
    assert configuration.load(graph) == saved
    misplaced = settings(pool=reference("pool").model_copy(update={"recurrence": EVERY_OTHER_DAY}))
    found = [(i.code, i.device) for i in configuration.validate(HOME, misplaced)]
    assert found == [("recurrence_not_used", "pool")]


# --- Tâches dues -----------------------------------------------------------------------------


def test_the_recurrence_replaces_the_recurring_task_of_home_assistant() -> None:
    ha = [
        TaskRequest(name="Chauffe-eau", uid="ha", due=DAY, rule="FREQ=DAILY;INTERVAL=3"),
        TaskRequest(name="Chauffe-eau", uid="once", due=DAY + timedelta(days=3)),
        TaskRequest(name="Lave-vaisselle", uid="dw", due=DAY, rule="FREQ=DAILY"),
    ]
    last = {"water_heater": DAY - timedelta(days=1)}

    found = recurring_tasks(ha, HOME, REFERENCE.configuration, last, DAY)

    assert [(t.uid, t.due) for t in found] == [
        ("once", DAY + timedelta(days=3)),  # demande ponctuelle : gardée
        ("dw", DAY),  # équipement sans récurrence réglée : tâche de HA
        ("recurrence:water_heater", DAY + timedelta(days=1)),
    ]
    tomorrow = recurring_tasks(
        [], HOME, REFERENCE.configuration, {"water_heater": None}, DAY, DAY + timedelta(days=1)
    )
    assert tomorrow[0].due == DAY + timedelta(days=2)  # due aujourd'hui, supposée faite


def test_the_following_days_assume_each_due_cycle_is_done() -> None:
    data = replace(
        state(0),
        due_tasks=tuple(
            recurring_tasks([], HOME, REFERENCE.configuration, {"water_heater": None}, DAY)
        ),
        day=DAY,
    )
    forecast = type("F", (), {"net_kwh": {}, "production_kwh": {}, "warnings": []})()

    due = {
        offset: [
            t.name
            for t in next_day_input(data, DAY + timedelta(days=offset), forecast, 0).due_tasks
        ]
        for offset in (1, 2)
    }

    assert due == {1: [], 2: ["Chauffe-eau"]}


# --- Reprise des descriptions JSON de la v1 --------------------------------------------------


def test_rules_from_the_task_descriptions() -> None:
    tasks = [*state(4).due_tasks, *state(11).waiting_tasks]

    found = {r.key: r for r in rules_from_tasks(tasks, HOME)}

    assert set(found) == {"water_heater", "dryer"}
    assert found["water_heater"].recurrence == Recurrence(
        rule="FREQ=DAILY;INTERVAL=2", start=date(2025, 10, 16)
    )
    assert found["dryer"].after == "washing_machine" and found["dryer"].recurrence is None


# --- États de test des contraintes -----------------------------------------------------------


def test_no_dryer_at_night() -> None:
    """Bruit : pas de sèche-linge de 22 h à 7 h, même quand la nuit serait moins chère."""
    night = TimeConstraint(kind=ConstraintKind.FORBIDDEN, start_hour=22, end_hour=7)
    rules = settings(dryer=reference("dryer").model_copy(update={"constraints": [night]}))

    day = plan_day(from_input(configured(state(11), HOME, rules))).day

    dryer = slots(day, "Sèche-linge")
    assert dryer and all(s.start_min >= 7 * 60 and s.end_min <= 22 * 60 for s in dryer)  # type: ignore[operator]


def test_laundry_finished_before_six_pm() -> None:
    finish = TimeConstraint(kind=ConstraintKind.FINISH_BEFORE, end_hour=18)
    rules = settings(
        washing_machine=reference("washing_machine").model_copy(update={"constraints": [finish]}),
        dryer=reference("dryer").model_copy(update={"constraints": [finish]}),
    )

    day = plan_day(from_input(configured(state(11), HOME, rules))).day

    laundry = slots(day, "Lave-linge") + slots(day, "Sèche-linge")
    assert len(laundry) == 2 and all(s.end_min <= 18 * 60 for s in laundry)  # type: ignore[operator]


def test_hot_water_by_seven() -> None:
    """Eau chaude à 7 h : le chauffe-eau en besoin d'énergie, fourni avant 7 h."""
    need = EnergyNeed(energy_kwh=3, deadline_hour=7, max_kw=2.4)
    rules = settings(
        water_heater=DeviceSettings(
            key="water_heater", behavior=Behavior.ENERGY_BY_DEADLINE, energy=need
        )
    )

    day = plan_day(from_input(configured(state(11), HOME, rules))).day

    (heater,) = slots(day, "Chauffe-eau")
    assert heater.energy_kwh == 3 and heater.hourly_kwh
    assert max(heater.hourly_kwh) < 7


def test_rules_proposal_route_needs_home_assistant(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as api:
        assert api.get("/api/configuration/task-rules-proposal").status_code == 503
