"""Planification annulée par l'utilisateur pour le jour : l'équipement n'est plus placé par le
calcul (ni sa tâche, ni son besoin, ni sa durée à placer), gardé en base pour la journée, puis
rétabli ; le calcul de demain reprend la tâche."""

import asyncio
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.planning.test_assemble import TODAY, local
from tests.planning.test_runner import context, reader_with_history
from tests.v1_oracle import STATES, load
from wattslot.planning import cancelled
from wattslot.planning.engine import Objective, plan_day
from wattslot.planning.inputs import Battery, Need, PlanningInput, Runtime, TaskRequest, from_v1
from wattslot.planning.problem import from_input
from wattslot.planning.runner import run
from wattslot.planning.store import PlanStore
from wattslot.storage.database import open_database


def test_a_cancelled_equipment_is_not_planned_anymore() -> None:
    state, _ = load(STATES[11])  # lave-linge et sèche-linge à placer, journée ensoleillée
    data = from_v1(state)
    before = plan_day(from_input(data), Objective.COST).day
    placed = {item.device for item in before.items}
    assert "Lave-linge" in placed and "Sèche-linge" in placed

    after = plan_day(
        from_input(cancelled.without_cancelled(data, {"Lave-linge"})), Objective.COST
    ).day
    kept = {item.device for item in after.items}
    assert "Lave-linge" not in kept
    assert "Sèche-linge" in kept  # seul l'équipement annulé disparaît


def test_a_cancelled_need_or_runtime_is_not_placed_either() -> None:
    data = PlanningInput(
        day=date(2026, 10, 21),
        first_hour=0,
        net_kwh={},
        production_kwh={},
        battery=Battery(
            capacity_kwh=5.0,
            stored_kwh=2.0,
            soc_percent=40.0,
            charge_max_w=1000.0,
            discharge_max_w=1000.0,
        ),
        due_tasks=(TaskRequest(name="Lave-linge"),),
        needs=(
            Need(name="Véhicule", energy_kwh=10.0, earliest_hour=0, deadline_hour=23, max_kw=3.0),
        ),
        runtimes=(Runtime(name="Piscine", speeds=(("eco", 0.5),), minimum_hours={}, skip_days={}),),
    )
    out = cancelled.without_cancelled(data, {"Lave-linge", "Véhicule", "Piscine"})
    assert out.due_tasks == () and out.needs == () and out.runtimes == ()
    assert cancelled.without_cancelled(data, set()) is data


def test_cancellations_are_kept_for_the_day_only(tmp_path: Path) -> None:
    database = open_database(tmp_path)
    now = datetime(2026, 10, 21, 8, 0, tzinfo=UTC)
    cancelled.cancel(database, date(2026, 10, 20), "Chauffe-eau", now)
    cancelled.cancel(database, date(2026, 10, 21), "Chauffe-eau", now)
    cancelled.cancel(database, date(2026, 10, 21), "Lave-linge", now)

    assert cancelled.load(database, date(2026, 10, 21)) == {"Chauffe-eau", "Lave-linge"}
    assert cancelled.load(database, date(2026, 10, 20)) == set()  # jour passé : oublié
    assert cancelled.restore(database, date(2026, 10, 21), "Chauffe-eau")
    assert not cancelled.restore(database, date(2026, 10, 21), "Chauffe-eau")


def test_a_cancelled_equipment_leaves_the_plan_and_comes_back(tmp_path: Path) -> None:
    reader = reader_with_history()
    ctx = context(tmp_path, reader)
    store = PlanStore(ctx.database)

    first = asyncio.run(run(ctx, local(TODAY, 9, 20), manual=True))
    assert first.errors == []
    before = store.load("today")
    assert before is not None
    assert "Lave-linge" in {item["equipement"] for item in before.content["planning"]}

    # « Annuler » : le calcul suivant ne place plus le lave-linge, même fusionné au précédent.
    cancelled.cancel(ctx.database, before.day, "Lave-linge", datetime.now(UTC))
    asyncio.run(run(ctx, local(TODAY, 9, 25)))
    after = store.load("today")
    assert after is not None
    assert "Lave-linge" not in {item["equipement"] for item in after.content["planning"]}

    # « Rétablir » : le calcul suivant le place de nouveau.
    assert cancelled.restore(ctx.database, before.day, "Lave-linge")
    asyncio.run(run(ctx, local(TODAY, 9, 30)))
    back = store.load("today")
    assert back is not None
    assert "Lave-linge" in {item["equipement"] for item in back.content["planning"]}


def test_routes(tmp_path: Path) -> None:
    app = FastAPI()
    app.include_router(cancelled.router)
    app.state.database = open_database(tmp_path)
    app.state.raw = SimpleNamespace(zone=ZoneInfo("Europe/Paris"))
    with TestClient(app) as api:
        assert (
            api.post("/api/planning/cancelled", json={"device": "Chauffe-eau"}).status_code == 201
        )
        assert api.get("/api/planning/cancelled").json() == [{"device": "Chauffe-eau"}]
        assert api.delete("/api/planning/cancelled/Chauffe-eau").status_code == 204
        assert api.delete("/api/planning/cancelled/Chauffe-eau").status_code == 404
