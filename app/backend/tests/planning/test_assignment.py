"""Affectation des tâches à un jour : la réécriture donne les mêmes résultats que la v1."""

import random
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from tests.v1_oracle import STATES, load, v1
from wattslot.planning.assignment import Previous, decide, launched_keys
from wattslot.planning.inputs import TaskRequest, from_v1

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


def test_task_request_reads_the_detected_need() -> None:
    task = TaskRequest("Lave-linge", needed_since=date(2026, 10, 10))
    assert task.needed_since == date(2026, 10, 10)


@pytest.mark.parametrize("path", STATES, ids=[p.stem for p in STATES])
def test_launched_equipment_as_v1(path: Path) -> None:
    state, _ = load(path)

    assert launched_keys(from_v1(state)) == v1("noeud_affectation.equipements_lances", state)
