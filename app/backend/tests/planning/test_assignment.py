"""Affectation des tâches à un jour : la réécriture donne les mêmes résultats que la v1."""

import random
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from tests.v1_oracle import STATES, load, v1
from wattslot.planning.assignment import Previous, decide, launched_keys
from wattslot.planning.inputs import TaskRequest, from_v1
from wattslot.time_constraints import ConstraintKind, TimeConstraint

TODAY = date(2026, 10, 12)
TASKS: list[dict[str, Any]] = [
    {"summary": "Lave-linge", "uid": "ll", "description": {"type": "a_la_demande"}},
    {
        "summary": "Sèche-linge",
        "uid": "sl",
        "description": {"type": "a_la_demande", "depend_de": "lave-linge"},
    },
    {"summary": "Lave-vaisselle", "uid": "lv", "description": {"type": "a_la_demande"}},
    {"summary": "Lave-vaisselle", "description": {"type": "a_la_demande"}},  # sans uid
]


def _iso(rng: random.Random, low: int, high: int) -> str:
    return (TODAY + timedelta(days=rng.randint(low, high))).isoformat()


def scenario(rng: random.Random) -> dict[str, Any]:
    tasks: list[dict[str, Any]] = []
    for raw in rng.sample(TASKS, rng.randint(1, len(TASKS))):
        task = {**raw, "description": dict(raw["description"])}
        if rng.random() < 0.3:
            task["description"]["besoin_detecte"] = rng.choice([_iso(rng, -4, 0), "illisible"])
        tasks.append(task)
    cycles = {
        name: {
            "status": "ok",
            "energie_kwh": rng.uniform(0.1, 2),
            "duree_min": rng.randint(40, 300),
        }
        for name in ("Lave-linge", "Sèche-linge", "Lave-vaisselle")
        if rng.random() < 0.85
    }
    surplus = {
        TODAY + timedelta(days=k): {
            h: rng.uniform(0, 2.5) for h in range(6, 21) if rng.random() < 0.8
        }
        for k in range(4)
        if k == 0 or rng.random() < 0.8
    }
    memory = {
        uid: {
            "jour": rng.choice([_iso(rng, 0, 3), "illisible", None]),
            "reference": rng.choice([_iso(rng, -4, 0), "illisible", None]),
        }
        for uid in ("ll", "sl", "lv")
        if rng.random() < 0.5
    }
    locked = {k for k in ("lavelinge", "sechelinge", "lavevaisselle") if rng.random() < 0.15}
    return {
        "tasks": tasks,
        "cycles": cycles,
        "surplus": surplus,
        "hour": rng.randint(0, 23),
        "memory": memory,
        "locked": locked,
    }


def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


@pytest.mark.parametrize("seed", range(400))
def test_same_as_v1(seed: int) -> None:
    case = scenario(random.Random(seed))
    expected, expected_reports = v1(
        "affectation.decider",
        case["tasks"],
        case["surplus"],
        TODAY,
        case["hour"],
        {},
        case["cycles"],
        case["memory"],
        set(case["locked"]),
    )
    requests = from_v1(
        {
            "date_cible": TODAY,
            "taches_en_attente": case["tasks"],
            "capacite_batterie_kwh": 0,
            "stored_energy_kwh": 0,
            "soc_percent": 0,
            "puissance_charge_max_w": 0,
            "puissance_decharge_max_w": 0,
        }
    ).waiting_tasks
    cycles = {name: (c["energie_kwh"], c["duree_min"]) for name, c in case["cycles"].items()}
    memory = {
        uid: Previous(day=_date(m["jour"]), reference=_date(m["reference"]))
        for uid, m in case["memory"].items()
    }

    assignments, reports = decide(
        list(requests), case["surplus"], TODAY, case["hour"], cycles, memory, case["locked"]
    )

    assert {
        uid: {
            "jour": a.day.isoformat(),
            "reference": a.reference.isoformat(),
            "equipement": a.task,
            "couverture": a.coverage,
            "couverture_aujourdhui": a.coverage_today,
        }
        for uid, a in assignments.items()
    } == expected  # même arithmétique : égalité exacte
    assert reports == expected_reports


def test_a_chosen_start_keeps_the_task_on_its_day() -> None:
    """Départ choisi par l'utilisateur pour après-demain : la tâche y reste, quel que soit le
    score des autres jours."""
    washer = TaskRequest(name="Lave-linge", uid="ll", on_demand=True, needed_since=TODAY)
    sunny = {h: 2.0 for h in range(10, 16)}
    surplus = {TODAY + timedelta(days=k): sunny for k in range(3)}
    cycles = {"Lave-linge": (1.0, 90.0)}
    later = TODAY + timedelta(days=2)

    free, _ = decide([washer], surplus, TODAY, 8, cycles, {}, set())
    pinned, reports = decide(
        [washer], surplus, TODAY, 8, cycles, {}, set(), pinned={"Lave-linge": later}
    )

    assert free["ll"].day == TODAY and pinned["ll"].day == later
    assert reports[0]["params"]["equipement"] == "Lave-linge"
    # Lancé aujourd'hui : le choix d'un autre jour ne compte plus.
    locked, _ = decide(
        [washer], surplus, TODAY, 8, cycles, {}, {"lavelinge"}, pinned={"Lave-linge": later}
    )
    assert locked["ll"].day == TODAY


DISHWASHER = TaskRequest(name="Lave-vaisselle", uid="lv", on_demand=True, needed_since=TODAY)
DISHWASHER_CYCLES = {"Lave-vaisselle": (1.2, 120.0)}
TOMORROW = TODAY + timedelta(days=1)
BEFORE_NOON = TimeConstraint(kind=ConstraintKind.FINISH_BEFORE, end_hour=12)


def test_an_evening_request_finished_before_noon_goes_to_tomorrow() -> None:
    """Demande faite à 20 h, équipement « terminé avant 12 h », pas de soleil : aujourd'hui
    ne laisse aucun départ, la tâche va à demain. Elle restait sur aujourd'hui, où le calcul
    la disait impossible à placer jusqu'après minuit (issue 273)."""
    dull: dict[date, dict[int, float]] = {TODAY: {}, TOMORROW: {}}

    free, _ = decide([DISHWASHER], dull, TODAY, 20, DISHWASHER_CYCLES, {}, set())
    strict, reports = decide(
        [DISHWASHER],
        dull,
        TODAY,
        20,
        DISHWASHER_CYCLES,
        {},
        set(),
        constraints={"Lave-vaisselle": (BEFORE_NOON,)},
    )
    # Souple : le calcul peut la violer, aujourd'hui reste candidat.
    soft, _ = decide(
        [DISHWASHER],
        dull,
        TODAY,
        20,
        DISHWASHER_CYCLES,
        {},
        set(),
        constraints={"Lave-vaisselle": (BEFORE_NOON.model_copy(update={"hard": False}),)},
    )

    assert free["lv"].day == TODAY and soft["lv"].day == TODAY
    assert strict["lv"].day == TOMORROW and strict["lv"].coverage_today is None
    assert [r["params"]["equipement"] for r in reports] == ["Lave-vaisselle"]


def test_coverage_counts_only_the_allowed_starts() -> None:
    """Soleil l'après-midi aujourd'hui, le matin demain : « terminé avant 12 h » ne peut pas
    profiter de l'après-midi, demain l'emporte."""
    surplus = {TODAY: {h: 2.0 for h in range(13, 17)}, TOMORROW: {h: 2.0 for h in range(9, 12)}}

    free, _ = decide([DISHWASHER], surplus, TODAY, 8, DISHWASHER_CYCLES, {}, set())
    strict, _ = decide(
        [DISHWASHER],
        surplus,
        TODAY,
        8,
        DISHWASHER_CYCLES,
        {},
        set(),
        constraints={"Lave-vaisselle": (BEFORE_NOON,)},
    )

    assert free["lv"].day == TODAY
    assert strict["lv"].day == TOMORROW
    assert strict["lv"].coverage_today == 0 and strict["lv"].coverage == 1


def test_no_allowed_day_keeps_the_task_today() -> None:
    """Aucun report toléré et aucun départ permis aujourd'hui : la tâche reste aujourd'hui,
    où le calcul signale la contrainte impossible."""
    found, reports = decide(
        [DISHWASHER],
        {TODAY: {}, TOMORROW: {}},
        TODAY,
        20,
        DISHWASHER_CYCLES,
        {},
        set(),
        delays={"Lave-vaisselle": 0},
        constraints={"Lave-vaisselle": (BEFORE_NOON,)},
    )

    assert found["lv"].day == TODAY and reports == []


def test_a_couple_follows_the_constraints_of_each_appliance() -> None:
    """Lave-linge à 17 h, sèche-linge interdit de 18 h à minuit : le couple ne tient plus
    aujourd'hui, il va à demain."""
    washer = TaskRequest(name="Lave-linge", uid="ll", on_demand=True, needed_since=TODAY)
    dryer = TaskRequest(
        name="Sèche-linge", uid="sl", on_demand=True, needed_since=TODAY, depends_on="Lave-linge"
    )
    cycles = {"Lave-linge": (1.0, 90.0), "Sèche-linge": (2.0, 60.0)}
    dull: dict[date, dict[int, float]] = {TODAY: {}, TOMORROW: {}}
    evening = TimeConstraint(kind=ConstraintKind.FORBIDDEN, start_hour=18, end_hour=24)

    free, _ = decide([washer, dryer], dull, TODAY, 17, cycles, {}, set())
    strict, _ = decide(
        [washer, dryer], dull, TODAY, 17, cycles, {}, set(), constraints={"Sèche-linge": (evening,)}
    )

    assert {a.day for a in free.values()} == {TODAY}
    assert {uid: a.day for uid, a in strict.items()} == {"ll": TOMORROW, "sl": TOMORROW}


def test_task_request_reads_the_detected_need() -> None:
    task = TaskRequest("Lave-linge", needed_since=date(2026, 10, 10))
    assert task.needed_since == date(2026, 10, 10)


@pytest.mark.parametrize("path", STATES, ids=[p.stem for p in STATES])
def test_launched_equipment_as_v1(path: Path) -> None:
    state, _ = load(path)

    assert launched_keys(from_v1(state)) == v1("noeud_affectation.equipements_lances", state)
