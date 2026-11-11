"""Départ au plus tôt d'un appareil : l'instant du calcul, pas le début de l'heure en cours.

Le calcul tourne à la minute 59. En partant du début de l'heure, celui de 11 h 59 pouvait placer
un départ à 11 h 00 : l'utilisateur ne l'avait jamais vu annoncé, et l'heure suivante ce créneau
était gelé comme commencé, sans que l'appareil soit replacé de la journée."""

from dataclasses import replace

from tests.v1_oracle import load, state_named
from wattslot.planning.engine import plan_day
from wattslot.planning.inputs import PlanningInput, from_v1
from wattslot.planning.plan import Slot
from wattslot.planning.problem import from_input


def _morning() -> PlanningInput:
    """Journée type calculée à 7 h 59, avec des appareils à placer."""
    state, _ = load(state_named("05_today_h07_morning"))
    data = from_v1(state)
    now = data.real_updated_at
    assert now is not None and (now.hour, now.minute) == (7, 59)
    return data


def test_no_start_is_placed_before_the_moment_of_the_run() -> None:
    data = _morning()

    problem = from_input(data)

    assert problem.tasks
    for task in problem.tasks:
        assert task.earliest_min >= 7 * 60 + 59
        assert task.candidates()[:2] == [479, 480]  # tout de suite, puis chaque heure pile
    launched = {cycle.name for cycle in problem.launched}
    starts = [
        i.start_min
        for i in plan_day(problem).day.items
        if isinstance(i, Slot) and i.start_min is not None and i.device not in launched
    ]
    assert starts and all(start >= 479 for start in starts)


def test_a_start_chosen_in_the_current_hour_is_kept() -> None:
    data = _morning()
    name = from_input(data).tasks[0].name

    problem = from_input(replace(data, chosen_starts={name: 7 * 60 + 30}))

    task = next(t for t in problem.tasks if t.name == name)
    assert task.candidates() == [7 * 60 + 30]


def test_another_day_starts_at_midnight() -> None:
    state, _ = load(state_named("05_today_h07_morning"))
    data = replace(from_v1(state), first_hour=0, real_updated_at=None)

    assert all(task.earliest_min == 0 for task in from_input(data).tasks)
