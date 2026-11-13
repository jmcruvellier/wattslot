"""Délai maximal derrière le cycle suivi (« Démarre après la fin de », au plus tard N heures
après) : le sèche-linge ne laisse pas le linge mouillé attendre des heures."""

from dataclasses import replace

import pytest

from tests.v1_oracle import load, state_named
from wattslot.languages import LANGUAGES
from wattslot.planning.engine import plan_day
from wattslot.planning.inputs import PlanningInput, from_v1
from wattslot.planning.plan import Plan, Slot
from wattslot.planning.problem import from_input
from wattslot.planning.warning_texts import warning_text

WASHER = "Lave-linge"
DRYER = "Sèche-linge"


def wait(day: Plan) -> int:
    """Minutes entre la fin du lave-linge et le départ du sèche-linge."""
    slots = {s.device: s for s in day.items if isinstance(s, Slot)}
    start, end = slots[DRYER].start_min, slots[WASHER].end_min
    assert start is not None and end is not None
    return start - end


def late(day: Plan) -> list[dict[str, object]]:
    return [
        w for w in day.warnings if isinstance(w, dict) and w.get("code") == "delai_apres_depasse"
    ]


def sunny() -> PlanningInput:
    """Journée 12 à minuit : lave-linge et sèche-linge à placer, le second après le premier."""
    return from_v1(load(state_named("synthetic_sunny_h00"))[0])


def afternoon_sun() -> PlanningInput:
    """Lave-linge lancé à 6 h (départ choisi), soleil de 14 h à 18 h seulement, pas de batterie :
    le sèche-linge coûte nettement moins l'après-midi. Aucune égalité entre deux plans, donc le
    même résultat quel que soit le solveur."""
    data = sunny()
    return replace(
        data,
        net_kwh={h: 4.0 if 14 <= h < 18 else -0.2 for h in range(24)},
        production_kwh={h: 4.2 if 14 <= h < 18 else 0.0 for h in range(24)},
        battery=replace(data.battery, capacity_kwh=0.0, stored_kwh=0.0, soc_percent=0.0),
        chosen_starts={WASHER: 6 * 60},
        due_tasks=(),
    )


def test_without_a_limit_the_dryer_waits_for_the_sun() -> None:
    """Le plan d'avant : rien ne borne l'attente, le linge mouillé attend l'après-midi."""
    problem = from_input(afternoon_sun())
    assert all(task.within_min is None for task in problem.tasks)
    assert wait(plan_day(problem).day) >= 6 * 60


@pytest.mark.parametrize("limit", [0, 60, 120])
def test_with_a_limit_the_dryer_does_not_wait_for_the_sun(limit: int) -> None:
    """Le délai l'emporte sur le gain du soleil : le sèche-linge part dans le délai."""
    day = plan_day(from_input(replace(afternoon_sun(), after_max_min={DRYER: limit}))).day
    assert 0 <= wait(day) <= limit and late(day) == []


@pytest.mark.parametrize("limit", [0, 60])
def test_the_dryer_starts_within_the_limit(limit: int) -> None:
    """Les deux cycles sont à placer : le calcul rapproche le lave-linge du sèche-linge."""
    problem = from_input(replace(sunny(), after_max_min={DRYER: limit}))
    dryer = next(task for task in problem.tasks if task.name == DRYER)
    assert (dryer.within_min, dryer.after_label) == (limit, "lave-linge")

    day = plan_day(problem).day
    assert 0 <= wait(day) <= limit and late(day) == []


def test_the_limit_counts_from_the_end_of_a_cycle_already_launched() -> None:
    """Journée 13 à 13 h : le lave-linge tourne, sa fin réelle est le point de départ."""
    data = from_v1(load(state_named("synthetic_realignment_h13"))[0])
    limited = replace(data, after_max_min={DRYER: 60})

    dryer = next(task for task in from_input(limited).tasks if task.name == DRYER)
    assert dryer.depends_on is None and dryer.after_end_min == dryer.earliest_min

    day = plan_day(from_input(limited)).day
    assert 0 <= wait(day) <= 60 and late(day) == []


def test_a_limit_that_cannot_be_kept_gives_the_closest_start_and_a_warning() -> None:
    """Le délai ne peut pas être tenu (ici, un départ choisi plus tard) : le sèche-linge est
    placé quand même, et le plan le dit."""
    data = from_v1(load(state_named("synthetic_realignment_h13"))[0])
    base = plan_day(from_input(data)).day
    slots = {s.device: s for s in base.items if isinstance(s, Slot)}
    end = slots[WASHER].end_min
    assert end is not None
    chosen = (end // 60 + 3) * 60
    forced = replace(data, after_max_min={DRYER: 60}, chosen_starts={DRYER: chosen})

    day = plan_day(from_input(forced)).day
    assert wait(day) == chosen - end
    (warning,) = late(day)
    assert warning["params"] == {
        "equipement": DRYER,
        "apres": "lave-linge",
        "delai_min": 60,
        "attente_min": chosen - end,
    }
    assert warning_text(warning, "fr").startswith("Sèche-linge démarre ")
    for lang in LANGUAGES:
        text = warning_text(warning, lang)
        assert text != "delai_apres_depasse" and "{" not in text


def test_no_limit_without_a_cycle_to_follow() -> None:
    """Le lave-linge n'est pas demandé aujourd'hui : rien à suivre, le délai ne joue pas."""
    data = sunny()
    alone = replace(
        data,
        waiting_tasks=tuple(t for t in data.waiting_tasks if t.name != WASHER),
        after_max_min={DRYER: 0},
    )
    problem = from_input(alone)
    dryer = next(task for task in problem.tasks if task.name == DRYER)
    assert dryer.within_min is None
    assert late(plan_day(problem).day) == []
