"""Contraintes horaires (lot 3.5) : réglages, calcul, assemblage ; compteur par équipement."""

from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from tests.planning.test_assemble import MODEL, PARIS, TODAY, Reader, local
from tests.planning.test_runtimes import DEHUMIDIFIER
from tests.v1_oracle import STATES, load
from wattslot import configuration
from wattslot.aggregation import HOUR
from wattslot.configuration import Automation, Behavior, Configuration, DeviceSettings
from wattslot.detection import Role
from wattslot.home_model import HomeDevice, HomeModel, HomeSensor
from wattslot.planning.assemble import configured, runtime_days_off
from wattslot.planning.engine import plan_day
from wattslot.planning.inputs import (
    V1_POOL,
    Need,
    PlanningInput,
    RecentHistory,
    from_v1,
)
from wattslot.planning.plan import POOL, Plan, Slot
from wattslot.planning.problem import from_input
from wattslot.storage.graph import GraphStore
from wattslot.time_constraints import ConstraintKind, TimeConstraint, problems

HEATER = "Chauffe-eau"  # tâche due de l'état capturé n° 0, calcul à partir de 6 h


def forbidden(start: int, end: int, hard: bool = True) -> TimeConstraint:
    return TimeConstraint(kind=ConstraintKind.FORBIDDEN, start_hour=start, end_hour=end, hard=hard)


def state() -> PlanningInput:
    data, _ = load(STATES[0])
    return from_v1(data)


def planned(data: PlanningInput) -> Plan:
    return plan_day(from_input(data)).day


def codes(day: Plan) -> list[str]:
    return [w["code"] for w in day.warnings if isinstance(w, dict)]


def slot(day: Plan, name: str) -> Slot:
    found = next(i for i in day.items if i.device == name)
    assert isinstance(found, Slot)
    return found


def test_blocked_periods_and_problems() -> None:
    night = forbidden(22, 7)
    assert night.blocked() == [(1320, 1440), (0, 420)]
    assert night.blocks(21 * 60, 22 * 60 + 1) and not night.blocks(7 * 60, 22 * 60)
    before = TimeConstraint(kind=ConstraintKind.FINISH_BEFORE, end_hour=18)
    after = TimeConstraint(kind=ConstraintKind.NOT_BEFORE, start_hour=9)
    assert before.blocks(17 * 60, 18 * 60 + 1) and not before.blocks(16 * 60, 18 * 60)
    assert after.blocks(8 * 60 + 59, 10 * 60) and not after.blocks(9 * 60, 10 * 60)
    assert [n.label() for n in (night, before, after)] == ["22h-7h", "≤18h", "≥9h"]
    assert problems([night, before]) == []
    assert problems([forbidden(5, 5)]) == [("constraint_range_empty", {"constraint": "5h-5h"})]
    assert [code for code, _ in problems([after, replace_hour(before, 9)])] == [
        "constraints_leave_no_time"
    ]
    assert problems([forbidden(0, 24, hard=False)]) == []  # souple : le calcul peut la violer


def replace_hour(constraint: TimeConstraint, end: int) -> TimeConstraint:
    return constraint.model_copy(update={"end_hour": end})


def test_saved_settings_and_validation(tmp_path: Path) -> None:
    graph = GraphStore(tmp_path)
    rules = [forbidden(22, 7), TimeConstraint(kind=ConstraintKind.FINISH_BEFORE, end_hour=18)]
    saved = Configuration(
        devices=[DeviceSettings(key="washer", behavior=Behavior.CYCLE, constraints=rules)]
    )
    configuration.save(graph, saved)
    assert configuration.load(graph) == saved
    observed = Configuration(
        devices=[
            DeviceSettings(
                key="washer",
                behavior=Behavior.UNCONTROLLED,
                automation=Automation.INFORM,
                constraints=rules,
            )
        ]
    )
    found = configuration.validate(MODEL, observed)
    assert [i.code for i in found] == ["constraints_not_used"]


def test_a_cycle_avoids_its_forbidden_range() -> None:
    data = replace(state(), constraints={HEATER: (forbidden(6, 14),)})

    found = slot(planned(data), HEATER)

    assert found.start_min is not None and found.start_min >= 14 * 60


def test_a_cycle_finished_before_an_hour() -> None:
    finish = TimeConstraint(kind=ConstraintKind.FINISH_BEFORE, end_hour=10)
    found = slot(planned(replace(state(), constraints={HEATER: (finish,)})), HEATER)

    assert found.end_min is not None and found.end_min <= 10 * 60


def test_a_hard_constraint_that_leaves_no_slot_is_reported() -> None:
    day = planned(replace(state(), constraints={HEATER: (forbidden(6, 24),)}))

    assert not [i for i in day.items if i.device == HEATER]
    warning = next(w for w in day.warnings if isinstance(w, dict))
    assert warning == {
        "code": "contrainte_impossible",
        "params": {"equipement": HEATER, "contraintes": "6h-24h"},
    }


def test_a_soft_constraint_is_broken_only_when_needed_and_reported() -> None:
    kept = planned(replace(state(), constraints={HEATER: (forbidden(6, 14, hard=False),)}))
    broken = planned(replace(state(), constraints={HEATER: (forbidden(0, 24, hard=False),)}))

    start = slot(kept, HEATER).start_min
    assert start is not None and start >= 14 * 60 and "contrainte_non_respectee" not in codes(kept)
    assert slot(broken, HEATER) and "contrainte_non_respectee" in codes(broken)


def test_a_runtime_stays_off_in_its_forbidden_hours() -> None:
    problem = from_input(state())
    pool = replace(problem.runtimes[0], min_hours=3)
    night = replace(problem, runtimes=[pool], constraints={POOL: (forbidden(8, 20),)})
    blocked = replace(problem, runtimes=[pool], constraints={POOL: (forbidden(0, 24),)})

    modes = plan_day(night).plan.runtimes[POOL]
    result = plan_day(blocked)

    assert all(modes[h] == "off" for h in range(8, 20))
    assert sum(mode != "off" for mode in modes.values()) >= 3
    assert all(mode == "off" for mode in result.plan.runtimes[POOL].values())
    assert "contrainte_impossible" in codes(result.day)


def test_a_need_is_not_delivered_in_its_forbidden_hours() -> None:
    car = Need(name="Voiture", energy_kwh=6, earliest_hour=0, deadline_hour=24, max_kw=2)
    data = replace(state(), needs=(car,), constraints={"Voiture": (forbidden(10, 16),)})

    found = slot(planned(data), "Voiture")

    assert found.hourly_kwh and not any(10 <= h < 16 for h in found.hourly_kwh)


def test_configured_constraints_by_plan_item() -> None:
    data = state()
    home = HomeModel(devices=[*MODEL.devices, DEHUMIDIFIER])
    rules = [forbidden(22, 7)]
    settings = Configuration(
        devices=[
            DeviceSettings(key="washer", behavior=Behavior.CYCLE, constraints=rules),
            DeviceSettings(key="dehumidifier", behavior=Behavior.RUNTIME, constraints=rules),
        ]
    )
    washing = replace(data, due_tasks=(*data.due_tasks, replace(data.due_tasks[0], name="Lessive")))

    found = configured(washing, home, settings).constraints

    assert set(found) == {"washer", "Lessive", "Déshumidificateur"}
    assert all(c == tuple(rules) for c in found.values())


def test_each_runtime_counts_its_own_days_off() -> None:
    # Charge complète due : la filtration peut sauter la journée, selon les jours sans.
    priority = replace(
        state(), history=RecentHistory(last_full_charge=TODAY - timedelta(days=30), days=14)
    )
    assert _skipped(priority, None) == _skipped(priority, 0)  # v1 : compteur à 0
    assert not _skipped(priority, 365)  # trop de jours sans : la filtration est due


def _skipped(data: PlanningInput, days_off: int | None) -> bool:
    found = from_input(replace(data, runtimes=(replace(V1_POOL, days_off=days_off),)))
    return found.runtimes[0].skipped


def test_days_off_measured_on_the_energy_counter() -> None:
    reader = Reader()
    entity = "sensor.dehum_energy"
    device = replace_sensor(entity)
    reader.add(entity, HOUR, local(TODAY - timedelta(days=3), 10), energy_kwh=0.4)
    home = HomeModel(devices=[device])
    settings = Configuration(devices=[DeviceSettings(key=device.key, behavior=Behavior.RUNTIME)])

    assert runtime_days_off(home, settings, reader, TODAY, PARIS) == {"dehumidifier": 2}
    no_counter = HomeModel(devices=[DEHUMIDIFIER])
    assert runtime_days_off(no_counter, settings, reader, TODAY, PARIS) == {}


def replace_sensor(entity: str) -> HomeDevice:
    return DEHUMIDIFIER.model_copy(
        update={"sensors": [HomeSensor(entity_id=entity, role=Role.ENERGY_CONSUMED)]}
    )
