"""Boutons de la barre de titre : ``/api/planning/last-run`` donne l'heure du dernier calcul
(à la main ou automatique) et du dernier relevé des données réelles, sans lire la vue du jour.
Le calcul vient de la trace gardée dans le plan, pas de l'heure de la base (avancée par le
bouton « Rafraîchir », qui réenregistre le plan sans recalculer)."""

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


def test_last_run_reads_the_execution_trace_of_the_plan(tmp_path: Path) -> None:
    day = date(2025, 10, 24)
    computed = datetime(2025, 10, 24, 14, 59, tzinfo=UTC)
    read_at = datetime(2025, 10, 24, 15, 15, tzinfo=UTC)
    content = {
        "derniere_execution": {"heure_iso": computed.isoformat(), "manuel": True},
        "donnees_reelles_cache": {"heure_maj_iso": read_at.isoformat()},
    }
    with TestClient(create_app(_settings(tmp_path))) as client:
        PlanStore(client.app.state.database).save("today", day, content, seconds=1.2, manual=True)  # type: ignore[attr-defined]
        response = client.get("/api/planning/last-run")

    assert response.status_code == 200
    found = response.json()
    assert found["manual"] is True
    assert found["computed_at"] == computed.isoformat().replace("+00:00", "Z")
    assert found["actual_updated_at"] == read_at.isoformat().replace("+00:00", "Z")


def test_a_refresh_does_not_rejuvenate_the_last_compute(tmp_path: Path) -> None:
    """Bouton « Rafraîchir » : le plan est réenregistré (heure de la base avancée) sans
    recalculer ; l'heure du dernier calcul affichée ne doit pas bouger."""
    day = date(2025, 10, 24)
    computed = datetime(2025, 10, 24, 14, 59, tzinfo=UTC)
    content = {"derniere_execution": {"heure_iso": computed.isoformat(), "manuel": False}}
    with TestClient(create_app(_settings(tmp_path))) as client:
        database = client.app.state.database  # type: ignore[attr-defined]
        store = PlanStore(database)
        store.save("today", day, content, seconds=1.2, manual=False)
        # Relevé relu une heure plus tard : contenu réenregistré, trace du calcul inchangée.
        store.save(
            "today",
            day,
            {
                **content,
                "donnees_reelles_cache": {
                    "heure_maj_iso": datetime(2025, 10, 24, 16, 0, tzinfo=UTC).isoformat()
                },
            },
            seconds=1.2,
            manual=False,
        )
        response = client.get("/api/planning/last-run")

    assert response.status_code == 200
    found = response.json()
    assert found["computed_at"] == computed.isoformat().replace("+00:00", "Z")
    assert found["manual"] is False
    assert found["actual_updated_at"] == "2025-10-24T16:00:00Z"
