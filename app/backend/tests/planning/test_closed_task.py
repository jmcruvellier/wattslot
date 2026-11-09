"""Cycle lancé dont la tâche est close (« Fait », tâche de HA cochée, nouvelle demande du même
équipement) : il reste dans le plan du jour, recalé sur le réel, avec sa consommation."""

from dataclasses import replace

from tests.v1_oracle import load, state_named
from wattslot.planning.engine import plan_day
from wattslot.planning.inputs import FrozenCycle, PlanningInput, from_v1
from wattslot.planning.plan import Plan, Slot
from wattslot.planning.problem import from_input

HEATER = "Chauffe-eau"


def launched_heater() -> tuple[PlanningInput, Slot]:
    """Journée 02 à midi, chauffe-eau lancé ; son bloc dans le plan, comme un bloc gelé."""
    data = from_v1(load(state_named("today_h12_water_heater"))[0])
    day = plan_day(from_input(data)).day
    slot = next(i for i in day.items if isinstance(i, Slot) and i.device == HEATER)
    return data, slot


def frozen(slot: Slot) -> FrozenCycle:
    assert slot.start_hour is not None and slot.end_hour is not None
    return FrozenCycle(
        name=slot.device,
        start_hour=slot.start_hour,
        end_hour=slot.end_hour,
        energy_kwh=slot.energy_kwh or 0.0,
        start_min=slot.start_min,
        end_min=slot.end_min,
        cycle_min=slot.cycle_min,
        shape=tuple(slot.shape) if slot.shape else None,
    )


def heater(day: Plan) -> Slot | None:
    return next((i for i in day.items if isinstance(i, Slot) and i.device == HEATER), None)


def test_a_launched_cycle_stays_in_the_plan_once_its_task_is_closed() -> None:
    data, slot = launched_heater()
    assert slot.justification is not None and slot.justification.startswith("Lancé à ")
    closed = replace(
        data,
        due_tasks=tuple(t for t in data.due_tasks if t.name != HEATER),
        waiting_tasks=tuple(t for t in data.waiting_tasks if t.name != HEATER),
        frozen=(*data.frozen, frozen(slot)),
    )

    problem = from_input(closed)
    kept = heater(plan_day(problem).day)

    assert [c.name for c in problem.launched] == [HEATER]
    assert HEATER not in {t.name for t in problem.tasks}  # pas replacé
    assert kept is not None and (kept.start_min, kept.end_min) == (slot.start_min, slot.end_min)
    # Sa consommation restante compte toujours, comme avant la clôture.
    assert problem.fixed_kwh == from_input(data).fixed_kwh


def test_a_cycle_never_launched_leaves_the_plan_when_its_task_is_closed() -> None:
    """Demande annulée avant le lancement : le bloc gelé disparaît, comme avant."""
    data, slot = launched_heater()
    closed = replace(
        data,
        due_tasks=tuple(t for t in data.due_tasks if t.name != HEATER),
        real_segments={},
        real_updated_at=None,
        frozen=(*data.frozen, frozen(slot)),
    )
    problem = from_input(closed)
    assert problem.launched == [] and heater(plan_day(problem).day) is None
