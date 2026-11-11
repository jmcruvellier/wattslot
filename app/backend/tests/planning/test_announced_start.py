"""Heure annoncée gardée : le calcul ne quitte le départ du plan précédent que pour un gain net.

Sans cela, le départ d'un appareil changeait d'un calcul horaire à l'autre pour quelques
centimes (12 h, puis 14 h, puis 12 h dans la maison de démonstration) : l'utilisateur qui lit son
plan le matin ne retrouvait pas la même heure une heure plus tard."""

from dataclasses import replace

from tests.v1_oracle import load, state_named
from wattslot.planning.engine import KEEP_MARGIN, Objective, Result, plan_day
from wattslot.planning.explain import render
from wattslot.planning.inputs import PlanningInput, from_v1
from wattslot.planning.plan import Slot
from wattslot.planning.problem import from_input
from wattslot.planning.runner import announced_starts

DEVICE = "Lave-vaisselle"


def _morning() -> PlanningInput:
    """Journée type calculée à 7 h 59 : un lave-vaisselle à placer, au mieux à 13 h."""
    state, _ = load(state_named("05_today_h07_morning"))
    return from_v1(state)


def _plan(data: PlanningInput) -> Result:
    return plan_day(from_input(data), Objective.COST)


def _slot(result: Result) -> Slot:
    return next(i for i in result.day.items if isinstance(i, Slot) and i.device == DEVICE)


def test_an_announced_start_is_kept_when_another_saves_little() -> None:
    data = _morning()
    best = _slot(_plan(data))
    assert best.explanation is not None
    # Un autre départ presque aussi bon : quelques millièmes d'euro de plus, sous la marge.
    close = best.explanation.alternatives[-1]
    task = next(t for t in from_input(data).tasks if t.name == DEVICE)
    margin = KEEP_MARGIN * task.energy_kwh * min(from_input(data).prices_eur_kwh.values())
    assert 0 < close.cost_eur_delta < margin

    kept = _slot(_plan(replace(data, announced_starts={DEVICE: close.start_min})))

    assert kept.start_min == close.start_min
    assert kept.explanation is not None
    assert kept.explanation.reasons[0].code == "announced_kept"
    assert "objective" not in [r.code for r in kept.explanation.reasons]
    assert render(kept.explanation, "fr").startswith("Heure déjà annoncée, gardée")
    # Le meilleur départ reste proposé : on voit ce que l'on y gagnerait.
    assert best.start_min in {a.start_min for a in kept.explanation.alternatives}


def test_an_announced_start_is_left_for_a_clear_gain() -> None:
    data = _morning()
    best = _slot(_plan(data))
    late = from_input(data).tasks[0].candidates()[-1]  # 22 h : plus de soleil

    moved = _slot(_plan(replace(data, announced_starts={DEVICE: late})))

    assert moved.start_min == best.start_min
    assert moved.explanation is not None
    assert moved.explanation.reasons[0].code == "objective"


def test_the_best_start_announced_changes_nothing() -> None:
    data = _morning()
    best = _slot(_plan(data))
    assert best.start_min is not None

    again = _slot(_plan(replace(data, announced_starts={DEVICE: best.start_min})))

    assert again.start_min == best.start_min
    assert again.explanation is not None
    assert again.explanation.reasons[0].code == "objective"


def test_a_start_chosen_by_the_user_comes_first() -> None:
    data = replace(_morning(), chosen_starts={DEVICE: 900}, announced_starts={DEVICE: 840})

    problem = from_input(data)

    task = next(t for t in problem.tasks if t.name == DEVICE)
    assert task.announced_min is None
    assert plan_day(problem, Objective.COST).plan.starts[DEVICE] == 900


def test_an_announced_start_that_is_no_longer_possible_is_ignored() -> None:
    data = _morning()
    best = _slot(_plan(data))

    passed = _slot(_plan(replace(data, announced_starts={DEVICE: 5 * 60})))  # 5 h, il est 7 h 59

    assert passed.start_min == best.start_min


def test_the_starts_of_the_previous_plan_are_the_announced_ones() -> None:
    result = _plan(_morning())

    assert announced_starts(result.output) == {DEVICE: _slot(result).start_min}
    assert announced_starts(None) == {}
