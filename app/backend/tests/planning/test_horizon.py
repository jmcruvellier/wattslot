"""Horizon et tâches récurrentes : la réécriture donne les mêmes entrées que la v1."""

import asyncio
import random
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from tests.v1_oracle import STATES, V1Raised, load, state_named, v1
from wattslot.planning.engine import plan_day
from wattslot.planning.horizon import (
    DayForecast,
    compute_horizon,
    end_soc_kwh,
    next_day_input,
)
from wattslot.planning.inputs import from_v1
from wattslot.planning.problem import from_input
from wattslot.planning.recurrence import UnsupportedRule, occurrences, tasks_of_day

DAY = date(2026, 10, 12)
RULES = [
    "FREQ=DAILY",
    "FREQ=DAILY;INTERVAL=2",
    "FREQ=DAILY;INTERVAL=3;UNTIL=20261020",
    "FREQ=WEEKLY",
    "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,TH",
    "RRULE:FREQ=WEEKLY;BYDAY=SA,SU",
    "FREQ=WEEKLY;BYDAY=XX",
    "FREQ=DAILY;BYDAY=MO",
    "FREQ=MONTHLY",
    "FREQ=DAILY;COUNT=3",
    "FREQ=DAILY;INTERVAL=0",
    "FREQ=DAILY;INTERVAL=deux",
    "FREQ=DAILY;UNTIL=2026",
    "freq=daily;interval=4",
]


@pytest.mark.parametrize("seed", range(300))
def test_occurrences_same_as_v1(seed: int) -> None:
    rng = random.Random(seed)
    due = DAY + timedelta(days=rng.randint(-10, 10))
    rule = rng.choice(RULES)
    first = DAY + timedelta(days=rng.randint(-3, 5))
    last = first + timedelta(days=rng.randint(0, 20))
    try:
        expected = v1("recurrences.occurrences", due, rule, first, last)
    except V1Raised:  # RegleNonGeree
        with pytest.raises(UnsupportedRule):
            occurrences(due, rule, first, last)
        return
    assert occurrences(due, rule, first, last) == expected


def tasks(rng: random.Random) -> list[dict[str, Any]]:
    found = []
    for name in ("Chauffe-eau", "Lave-vaisselle", "Lave-linge"):
        if rng.random() < 0.8:
            description: dict[str, Any] = rng.choice(
                [{"type": "recurrent", "regle": rng.choice(RULES)}, {"type": "a_la_demande"}, {}]
            )
            due = rng.choice(
                [(DAY + timedelta(days=rng.randint(-5, 5))).isoformat(), "", "illisible", None]
            )
            found.append({"summary": name, "uid": name, "due": due, "description": description})
    return found


def _state(raw_tasks: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {
        "date_cible": DAY,
        "taches_placees": raw_tasks,
        "capacite_batterie_kwh": 5.0,
        "stored_energy_kwh": 1.0,
        "soc_percent": 20.0,
        "puissance_charge_max_w": 2500,
        "puissance_decharge_max_w": 800,
        **extra,
    }


@pytest.mark.parametrize("seed", range(300))
def test_tasks_of_day_same_as_v1(seed: int) -> None:
    rng = random.Random(seed)
    raw = tasks(rng)
    day = DAY + timedelta(days=rng.randint(0, 6))
    expected, expected_unsupported = v1("recurrences.taches_du_jour", raw, day)

    kept, unsupported = tasks_of_day(list(from_v1(_state(raw)).due_tasks), day)

    assert kept == list(from_v1(_state(expected)).due_tasks)
    assert unsupported == expected_unsupported


def forecast(rng: random.Random) -> dict[str, Any]:
    net = {h: rng.uniform(-1, 2) for h in range(24)}
    return {
        "surplus_horaire": {h: max(0.0, v) for h, v in net.items()},
        "net_horaire_signe": net,
        "production_solaire_horaire": {h: max(0.0, v + 0.3) for h, v in net.items()},
        "consommation_baseline_horaire": {h: 0.3 for h in range(24)},
        "avertissements": [{"code": "prevision_repli", "params": {}}] if rng.random() < 0.3 else [],
    }


@pytest.mark.parametrize("path", STATES, ids=[p.stem for p in STATES])
def test_next_day_input_same_as_v1(path: Path) -> None:
    first, _ = load(path)
    rng = random.Random(path.stem)
    for offset in range(1, 6):
        day = first["date_cible"] + timedelta(days=offset)
        surplus, soc = forecast(rng), rng.uniform(0, first["capacite_batterie_kwh"])
        expected = v1("horizon.etat_jour_suivant", first, day, surplus, soc)

        actual = next_day_input(
            from_v1(first),
            day,
            DayForecast(
                surplus["net_horaire_signe"],
                surplus["production_solaire_horaire"],
                tuple(surplus["avertissements"]),
            ),
            soc,
        )

        assert actual == from_v1(expected)


def test_horizon_chains_the_battery_and_stops_without_forecast() -> None:
    first_state, _ = load(state_named("tomorrow_laundry"))
    first = from_v1(first_state)
    rng = random.Random(0)
    available = {first.day + timedelta(days=k): forecast(rng) for k in range(1, 4)}

    async def forecast_of(day: date) -> DayForecast:
        surplus = available[day]  # KeyError au-delà : prévision indisponible
        return DayForecast(surplus["net_horaire_signe"], surplus["production_solaire_horaire"])

    result = asyncio.run(compute_horizon(first, plan_day(from_input(first)), forecast_of, days=6))

    assert [data.day for data, _ in result.days] == [
        first.day + timedelta(days=k) for k in range(4)
    ]
    for (_, previous), (data, _) in zip(result.days, result.days[1:], strict=False):
        assert data.battery.stored_kwh == end_soc_kwh(previous)
        assert data.first_hour == 0
    assert result.warnings == [
        {
            "code": "horizon_interrompu",
            "params": {
                "jour": (first.day + timedelta(days=4)).isoformat(),
                "raison": f"KeyError : {first.day + timedelta(days=4)!r}",
            },
        }
    ]
    assert len(result.seconds) == 3
