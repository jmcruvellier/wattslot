"""Lancements déclarés par l'utilisateur (« C'est lancé ») : gardés en base pour la journée,
puis oubliés ; routes de l'écran Aujourd'hui."""

from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient

from wattslot.planning import declared
from wattslot.planning.store import PlanStore
from wattslot.storage.database import open_database


def test_declared_launches_are_kept_for_the_day_only(tmp_path: Path) -> None:
    database = open_database(tmp_path)
    now = datetime(2026, 10, 21, 8, 0, tzinfo=UTC)
    declared.declare(database, date(2026, 10, 20), "Chauffe-eau", now)
    declared.declare(database, date(2026, 10, 21), "Lave-linge", now)
    declared.declare(database, date(2026, 10, 21), "Lave-linge", now)  # deux clics : une ligne

    assert declared.load(database, date(2026, 10, 21)) == {"Lave-linge"}
    assert declared.load(database, date(2026, 10, 20)) == set()  # jour passé : oublié
    assert declared.withdraw(database, date(2026, 10, 21), "Lave-linge")  # retour en arrière
    assert not declared.withdraw(database, date(2026, 10, 21), "Lave-linge")
    assert declared.load(database, date(2026, 10, 21)) == set()


def test_a_declaration_is_forgotten_with_its_request(tmp_path: Path) -> None:
    """21/11/2026 : sèche-linge déclaré lancé par erreur, sa demande annulée puis refaite. La
    déclaration, attachée au seul nom de l'appareil, valait pour la nouvelle demande : elle
    était aussitôt dite « marquée comme lancée »."""
    database = open_database(tmp_path)
    day, now = date(2026, 11, 21), datetime(2026, 11, 21, 9, 0, tzinfo=UTC)
    declared.declare(database, day, "Sèche-linge", now, request="app-1")
    declared.declare(database, day, "Lave-linge", now, request="app-2")
    declared.declare(database, day, "Chauffe-eau", now)  # sans demande connue

    assert declared.forget_request(database, "app-1") == 1  # demande annulée
    assert declared.load(database, day) == {"Lave-linge", "Chauffe-eau"}
    # Au calcul : les déclarations des demandes closes entre-temps ; sans demande, gardée.
    assert declared.forget_closed(database, day, {"app-3"}) == 1
    assert declared.load(database, day) == {"Chauffe-eau"}
    # Redéclaré pour la demande suivante : l'instant d'avant est gardé, la demande suivie.
    declared.declare(database, day, "Chauffe-eau", now, request="app-3")
    assert declared.forget_closed(database, day, {"app-3"}) == 0
    assert declared.forget_request(database, "app-3") == 1


def test_the_route_ties_the_declaration_to_the_request_of_the_cycle(tmp_path: Path) -> None:
    app = FastAPI()
    app.include_router(declared.router)
    app.state.database = database = open_database(tmp_path)
    app.state.raw = SimpleNamespace(zone=ZoneInfo("Europe/Paris"))
    today = datetime.now(UTC).astimezone(ZoneInfo("Europe/Paris")).date()
    planning = [
        {"equipement": "Sèche-linge", "demande": "app-1"},
        {"equipement": "Sèche-linge", "rang": 2, "demande": "app-7"},
    ]
    PlanStore(database).save("today", today, {"planning": planning}, 0.1, False)
    with TestClient(app) as api:
        for device in ("Sèche-linge #2", "Lave-linge"):
            assert api.post("/api/planning/launched", json={"device": device}).status_code == 201

    assert declared.forget_request(database, "app-7") == 1
    assert declared.load(database, today) == {"Lave-linge"}  # hors du plan : sans demande


def test_routes(tmp_path: Path) -> None:
    app = FastAPI()
    app.include_router(declared.router)
    app.state.database = open_database(tmp_path)
    app.state.raw = SimpleNamespace(zone=ZoneInfo("Europe/Paris"))
    with TestClient(app) as api:
        assert api.get("/api/planning/launched").json() == []
        assert api.post("/api/planning/launched", json={"device": "Lave-linge"}).status_code == 201
        assert api.get("/api/planning/launched").json() == [{"device": "Lave-linge"}]
        assert api.delete("/api/planning/launched/Lave-linge").status_code == 204
        assert api.delete("/api/planning/launched/Lave-linge").status_code == 404
        assert api.get("/api/planning/launched").json() == []
