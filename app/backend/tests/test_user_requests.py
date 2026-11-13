"""Demandes déclarées dans l'application (lot 4.5)."""

import asyncio
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from tests.planning.test_assemble import MODEL, NOW, TODAY, Reader, client, local
from tests.test_health import _settings
from wattslot import user_requests
from wattslot.aggregation import HOUR, QUARTER
from wattslot.home_model import HomeModel
from wattslot.main import create_app
from wattslot.planning.assemble import build_input
from wattslot.planning.engine import Objective, plan_day
from wattslot.planning.inputs import PlanningInput, TaskRequest
from wattslot.planning.journal import Appliance, CycleJournal, appliances
from wattslot.planning.problem import from_input
from wattslot.planning.sources import PlanningSettings
from wattslot.storage.database import open_database
from wattslot.storage.raw import RawStores
from wattslot.user_requests import Status

CREATED = datetime(2026, 10, 15, 18, 0, tzinfo=UTC)
# Le lave-linge du modèle porte le nom que la liste de HA donne à la tâche.
HOME = HomeModel(
    devices=[
        d.model_copy(update={"name": "Lave-linge"}) if d.key == "washer" else d
        for d in MODEL.devices
    ]
)
WASHER = next(a for a in appliances(HOME) if a.key == "washer")


def test_one_open_request_per_device(tmp_path: Path) -> None:
    database = open_database(tmp_path)
    first = user_requests.ask(database, "washer", None, CREATED)
    again = user_requests.ask(database, "washer", date(2026, 10, 18), CREATED + timedelta(hours=1))

    assert again.id == first.id and again.latest == date(2026, 10, 18)
    assert [r.id for r in user_requests.open_requests(database)] == [first.id]

    cancelled = user_requests.close(
        database, first.id, Status.CANCELLED, CREATED + timedelta(hours=2)
    )
    assert cancelled is not None and cancelled.status is Status.CANCELLED
    assert user_requests.open_requests(database) == []
    assert [r.id for r in user_requests.recent(database, CREATED + timedelta(days=1))] == [first.id]
    assert user_requests.recent(database, CREATED + timedelta(days=9)) == []


def test_requests_become_on_demand_tasks(tmp_path: Path) -> None:
    database = open_database(tmp_path)
    dryer = Appliance("dryer", "Sèche-linge", WASHER.kind, (), ())
    user_requests.ask(database, "washer", date(2026, 10, 18), CREATED)
    user_requests.ask(database, "dryer", None, CREATED)
    user_requests.ask(database, "unknown", None, CREATED)

    due, waiting = user_requests.tasks(database, [WASHER, dryer], [], TODAY)
    assert due == [
        TaskRequest(
            name="Lave-linge",
            uid="app-1",
            due=date(2026, 10, 18),
            on_demand=True,
            needed_since=CREATED.date(),
            asked_at=CREATED,
        )
    ]
    assert [t.name for t in waiting] == ["Sèche-linge"]

    # Déjà demandé par la liste de HA : la demande de l'application est ignorée.
    due, waiting = user_requests.tasks(
        database, [WASHER, dryer], [TaskRequest(name="Lave linge")], TODAY
    )
    assert due == [] and [t.name for t in waiting] == ["Sèche-linge"]


def test_a_launched_request_closes_the_next_day(tmp_path: Path) -> None:
    database = open_database(tmp_path)
    request = user_requests.ask(database, "washer", None, CREATED)

    assert user_requests.mark_launched(database, {f"app-{request.id}"}, TODAY) == [request.id]
    assert user_requests.settle(database, TODAY, NOW) == []  # le plan du jour garde le cycle
    assert len(user_requests.tasks(database, [WASHER], [], TODAY)[1]) == 1

    assert user_requests.settle(database, TODAY + timedelta(days=1), NOW) == [request.id]
    found = user_requests.get(database, request.id)
    assert found is not None and found.status is Status.DONE


def test_a_new_request_after_a_launch_opens_another_one(tmp_path: Path) -> None:
    """Chauffe-eau lancé cette nuit, puis demandé pour demain : la demande lancée est faite et
    une nouvelle est ouverte ; clore la première ne touche plus à celle de demain."""
    database = open_database(tmp_path)
    tonight = user_requests.ask(database, "washer", None, CREATED)
    user_requests.mark_launched(database, {f"app-{tonight.id}"}, TODAY)

    tomorrow = user_requests.ask(database, "washer", TODAY + timedelta(days=1), NOW)
    assert tomorrow.id != tonight.id and tomorrow.latest == TODAY + timedelta(days=1)
    first = user_requests.get(database, tonight.id)
    assert first is not None and first.status is Status.DONE
    assert user_requests.close(database, tonight.id, Status.DONE, NOW) == first
    assert [r.id for r in user_requests.open_requests(database)] == [tomorrow.id]

    # Le lancement de cette nuit ne compte pas pour la nouvelle demande : un cycle réel n'est
    # attribué qu'à une tâche, et celle de la demande close n'est plus dans le calcul.
    assert user_requests.mark_launched(database, {f"app-{tonight.id}"}, TODAY) == []
    assert user_requests.settle(database, TODAY + timedelta(days=1), NOW) == []
    assert [r.id for r in user_requests.open_requests(database)] == [tomorrow.id]
    later = TODAY + timedelta(days=1)
    assert user_requests.mark_launched(database, {f"app-{tomorrow.id}"}, later) == [tomorrow.id]


def test_another_request_for_the_same_device_is_one_more_cycle(tmp_path: Path) -> None:
    """Deux lessives le même jour : la seconde demande s'ajoute à la première, chacune devient
    une tâche du calcul, et le lancement de l'une ne marque pas l'autre."""
    database = open_database(tmp_path)
    first = user_requests.ask(database, "washer", None, CREATED)
    second = user_requests.ask(database, "washer", None, NOW, another=True)
    assert second.id != first.id
    assert [r.id for r in user_requests.open_requests(database)] == [first.id, second.id]

    waiting = user_requests.tasks(database, [WASHER], [], TODAY)[1]
    assert [t.uid for t in waiting] == [f"app-{first.id}", f"app-{second.id}"]
    assert [t.asked_at for t in waiting] == [first.created_at, second.created_at]

    # Sans « un cycle de plus », redemander change la date de la plus récente pas encore lancée.
    assert user_requests.ask(database, "washer", TODAY, NOW).id == second.id
    assert user_requests.mark_launched(database, {f"app-{first.id}"}, TODAY) == [first.id]
    assert user_requests.mark_launched(database, {f"app-{first.id}"}, TODAY) == []
    found = user_requests.get(database, second.id)
    assert found is not None and found.launched_on is None


def _input(tmp_path: Path, items: list[dict[str, Any]], with_requests: bool) -> PlanningInput:
    reader = Reader()
    for k in range(1, 15):
        day = TODAY - timedelta(days=k)
        for hour in range(24):
            start = local(day, hour)
            for entity in ("sensor.imp", "sensor.exp", "sensor.chg", "sensor.dis"):
                reader.add(entity, HOUR, start, energy_kwh=0.4 if entity == "sensor.imp" else 0)
        for q in range(-1, 7):
            start = local(day, 10) + timedelta(minutes=15 * q)
            on = 0 <= q < 6
            reader.add("sensor.washer_power", QUARTER, start, mean=800.0 if on else 1.0)
            reader.add("sensor.washer_energy", QUARTER, start, energy_kwh=0.05 if on else 0.0)
    raw = RawStores(tmp_path, "Europe/Paris")
    database = open_database(tmp_path)
    if with_requests:
        user_requests.ask(database, "washer", date(2026, 10, 18), CREATED)
    ha = client(
        {
            "energy/solar_forecast": {"x": {"wh_hours": {local(TODAY, 12).isoformat(): 2000}}},
            "call_service": {"response": {"todo.maison": {"items": items}}},
            "get_states": [{"entity_id": "sensor.soc", "state": "60"}],
        }
    )
    journal = CycleJournal(database, raw, reader)
    settings = PlanningSettings(todo_entity="todo.maison")
    return asyncio.run(
        build_input(TODAY, NOW, ha, HOME, reader, raw, journal, settings, database=database)
    )


def test_requests_give_the_same_plan_as_the_home_assistant_list(tmp_path: Path) -> None:
    """Fin du lot 4.5 : la demande saisie dans l'application à la place de la tâche « à la
    demande » de la liste de HA donne la même entrée et le même plan."""
    task = {
        "uid": "ll",
        "summary": "Lave-linge",
        "due": "2026-10-18",
        "description": json.dumps({"type": "a_la_demande", "besoin_detecte": "2026-10-15"}),
    }
    (tmp_path / "ha").mkdir()
    (tmp_path / "app").mkdir()
    from_ha = _input(tmp_path / "ha", [task], with_requests=False)
    from_app = _input(tmp_path / "app", [], with_requests=True)

    def without_uid(data: PlanningInput) -> PlanningInput:
        # Sans ce qui désigne la demande : son uid et le moment où elle a été faite.
        return replace(
            data,
            due_tasks=tuple(replace(t, uid=None, asked_at=None) for t in data.due_tasks),
            waiting_tasks=tuple(replace(t, uid=None, asked_at=None) for t in data.waiting_tasks),
        )

    assert [t.name for t in from_app.due_tasks] == ["Lave-linge"]
    assert without_uid(from_app) == without_uid(from_ha)
    plan_ha = plan_day(from_input(without_uid(from_ha)), Objective.COST)
    plan_app = plan_day(from_input(without_uid(from_app)), Objective.COST)
    assert plan_app.output == plan_ha.output


def test_routes(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as api:
        assert api.get("/api/requests/devices").json() == []
        assert api.post("/api/requests", json={"device": "washer"}).status_code == 422
        assert api.get("/api/requests").json() == []
        assert api.delete("/api/requests/42").status_code == 404
