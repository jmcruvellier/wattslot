"""Lancements déclarés par l'utilisateur (« C'est lancé ») : gardés en base pour la journée,
puis oubliés ; routes de l'écran Aujourd'hui."""

from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient

from wattslot.planning import declared
from wattslot.storage.database import open_database


def test_declared_launches_are_kept_for_the_day_only(tmp_path: Path) -> None:
    database = open_database(tmp_path)
    now = datetime(2026, 10, 21, 8, 0, tzinfo=UTC)
    declared.declare(database, date(2026, 10, 20), "Chauffe-eau", now)
    declared.declare(database, date(2026, 10, 21), "Lave-linge", now)
    declared.declare(database, date(2026, 10, 21), "Lave-linge", now)  # deux clics : une ligne

    assert declared.load(database, date(2026, 10, 21)) == {"Lave-linge"}
    assert declared.load(database, date(2026, 10, 20)) == set()  # jour passé : oublié


def test_routes(tmp_path: Path) -> None:
    app = FastAPI()
    app.include_router(declared.router)
    app.state.database = open_database(tmp_path)
    app.state.raw = SimpleNamespace(zone=ZoneInfo("Europe/Paris"))
    with TestClient(app) as api:
        assert api.get("/api/planning/launched").json() == []
        assert api.post("/api/planning/launched", json={"device": "Lave-linge"}).status_code == 201
        assert api.get("/api/planning/launched").json() == [{"device": "Lave-linge"}]
