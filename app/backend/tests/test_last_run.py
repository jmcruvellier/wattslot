"""Boutons de la barre de titre : ``/api/planning/last-run`` donne l'heure du dernier calcul
(à la main ou automatique) et du dernier relevé des données réelles, sans lire la vue du jour."""

from datetime import UTC, date, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from wattslot.main import create_app
from wattslot.planning.store import PlanStore
from wattslot.runtime import RunMode, Settings


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        mode=RunMode.STANDALONE,
        data_dir=tmp_path / "data",
        static_dir=None,
        home_assistant=None,
    )


def test_last_run_without_plan(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        response = client.get("/api/planning/last-run")

    assert response.status_code == 200
    assert response.json() == {"computed_at": None, "manual": False, "actual_updated_at": None}


def test_last_run_of_a_manual_plan_with_real_readings(tmp_path: Path) -> None:
    day = date(2025, 10, 24)
    read_at = datetime(2025, 10, 24, 15, 15, tzinfo=UTC)
    with TestClient(create_app(_settings(tmp_path))) as client:
        PlanStore(client.app.state.database).save(  # type: ignore[attr-defined]
            "today",
            day,
            {"donnees_reelles_cache": {"heure_maj_iso": read_at.isoformat()}},
            seconds=1.2,
            manual=True,
        )
        response = client.get("/api/planning/last-run")

    assert response.status_code == 200
    found = response.json()
    assert found["manual"] is True
    assert found["actual_updated_at"] == read_at.isoformat().replace("+00:00", "Z")
    computed = datetime.fromisoformat(found["computed_at"])
    assert computed.date() == date.today() and computed.tzinfo is not None
