"""Modèle de plan typé : aller-retour sans perte avec le format de la v1."""

import asyncio
from pathlib import Path
from typing import Any

import pytest

from tests.planning.test_assemble import TODAY, local
from tests.planning.test_runner import context, reader_with_history
from tests.v1_oracle import STATES, load
from wattslot.planning.plan import (
    BATTERY,
    POOL,
    BatteryPlan,
    Plan,
    RuntimePlan,
    RuntimeSegment,
    Slot,
)
from wattslot.planning.runner import run
from wattslot.planning.store import PlanStore

IDS = [p.stem for p in STATES]


@pytest.mark.parametrize("path", STATES, ids=IDS)
def test_round_trip_on_the_v1_outputs(path: Path) -> None:
    _, output = load(path)
    plan = Plan.from_v1(output)

    assert plan.to_v1() == output
    assert plan.battery is not None and plan.battery.device == BATTERY
    assert [r.device for r in plan.runtimes] == [POOL]
    assert len(plan.slots) == len(output["planning"]) - 2


def test_round_trip_on_the_plans_of_the_v2(tmp_path: Path) -> None:
    ctx = context(tmp_path, reader_with_history())
    asyncio.run(run(ctx, local(TODAY, 9, 20), manual=True))
    asyncio.run(run(ctx, local(TODAY, 13, 5)))  # plan fusionné avec le précédent
    store = PlanStore(ctx.database)

    contents: list[dict[str, Any]] = []
    for kind in ("today", "tomorrow"):
        stored = store.load(kind)
        assert stored is not None
        contents.append(stored.content)
    horizon = store.load("horizon")
    assert horizon is not None
    contents += horizon.content["jours"]

    for content in contents:
        assert Plan.from_v1(content).to_v1() == content


def test_absent_fields_stay_absent_and_unknown_keys_are_kept() -> None:
    content = {
        "planning": [
            {"equipement": "Lave-linge", "heure_debut": 10, "heure_fin": 12, "energie_kwh": 0.8},
            {"equipement": POOL, "segments": [], "note": "gardée"},
            {"equipement": BATTERY, "soc_horaire_kwh": {8: 1.5}},
        ],
        "autre": {"x": 1},
    }

    plan = Plan.from_v1(content)

    assert plan.to_v1() == content  # ordre des éléments conservé, rien d'ajouté
    assert plan.slots[0].start_min is None and plan.battery is not None
    assert plan.battery.soc_kwh == {8: 1.5}


def test_built_with_english_names() -> None:
    plan = Plan(
        day="2026-10-16",
        items=[
            Slot(device="Lave-linge", start_hour=10, end_hour=12, energy_kwh=0.8, start_min=600),
            BatteryPlan(start_kwh=1.0, end_kwh=2.0),
            RuntimePlan(segments=[RuntimeSegment(start_hour=0, end_hour=24, mode="off")]),
        ],
    )

    assert plan.to_v1() == {
        "date_cible": "2026-10-16",
        "planning": [
            {
                "equipement": "Lave-linge",
                "heure_debut": 10,
                "heure_fin": 12,
                "energie_kwh": 0.8,
                "debut_min": 600,
            },
            {"equipement": BATTERY, "soc_initial_kwh": 1.0, "soc_final_kwh": 2.0},
            {"equipement": POOL, "segments": [{"heure_debut": 0, "heure_fin": 24, "mode": "off"}]},
        ],
    }


def test_typed_merge_gives_the_v1_merge(tmp_path: Path) -> None:
    from wattslot.planning.merge import merge_day, merge_plans

    ctx = context(tmp_path, reader_with_history())
    asyncio.run(run(ctx, local(TODAY, 9, 20), manual=True))
    store = PlanStore(ctx.database)
    first = store.load("today")
    assert first is not None
    asyncio.run(run(ctx, local(TODAY, 13, 5)))
    second = store.load("tomorrow")  # un autre plan, pour avoir un passé et un futur différents
    assert second is not None
    new = {**second.content, "date_cible": first.content["date_cible"]}

    merged = merge_day(Plan.from_v1(new), first.plan, 13)

    assert merged.to_v1() == merge_plans(new, first.content, 13)
    assert merge_day(Plan.from_v1(new), None, 13).to_v1() == new
