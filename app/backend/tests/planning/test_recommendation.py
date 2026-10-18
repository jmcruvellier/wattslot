"""Texte de recommandation construit à partir des explications du plan (lot 3.7) ; envoi par un
service ``notify.*`` de HA."""

import asyncio
import copy
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from tests.v1_oracle import STATES, load
from wattslot.planning.engine import plan_day
from wattslot.planning.inputs import from_v1
from wattslot.planning.plan import Plan, Slot
from wattslot.planning.problem import from_input
from wattslot.planning.recommendation import recommendation, send, title
from wattslot.planning.sources import PlanningSettings

IDS = [p.stem for p in STATES]


def output(path: Path) -> dict[str, Any]:
    """Plan de la v2 (sortie au format de la v1, explications comprises) d'un état capturé."""
    state, _ = load(path)
    found: dict[str, Any] = plan_day(from_input(from_v1(state))).output
    return found


@pytest.mark.parametrize("path", STATES, ids=IDS)
def test_text_from_the_explanations_in_both_languages(path: Path) -> None:
    state = output(path)
    day = Plan.from_v1(state)

    texts = {lang: recommendation(state, lang) for lang in ("fr", "en")}

    assert texts["fr"].startswith("Objectif : le coût le plus bas.")
    assert texts["en"].startswith("Objective: the lowest cost.")
    for slot in day.items:
        if isinstance(slot, Slot):
            assert f"- {slot.device} :" in texts["fr"] and f"- {slot.device}:" in texts["en"]
    assert "Bilan prévu :" in texts["fr"] and "Expected balance:" in texts["en"]
    assert "Jamais sous" in texts["fr"]  # raisons de la batterie


def test_the_appliances_come_in_the_order_of_the_day() -> None:
    text = recommendation(output(STATES[11]))

    lines = [line for line in text.splitlines() if line.startswith("- ")]
    starts = [line.split(" : ")[1].split("-")[0] for line in lines]
    assert starts == sorted(starts, key=lambda s: int(s.split("h")[0]))
    assert any("aussi bon" in line or "Autre départ" in line for line in lines)


def test_a_plan_without_explanations_still_gives_its_text() -> None:
    """Plan gardé avant le lot 3.7 (sortie de la v1) : mêmes lignes, sans les raisons."""
    _, plan = load(STATES[11])

    text = recommendation(dict(plan))

    assert not text.startswith("Objectif") and "Équipements à lancer aujourd'hui :" in text
    assert "surplus solaire" not in text


def test_missing_parts_reports_and_warnings() -> None:
    state = copy.deepcopy(output(STATES[0]))
    state["planning"] = [i for i in state["planning"] if i["equipement"] != "Batterie"]
    for item in state["planning"]:
        for segment in item.get("segments", []):
            segment["mode"] = "off"
    state["reports"] = [
        {
            "code": "tache_reportee_sans_creneau",
            "params": {"equipement": "Lave-linge", "jour": "2026-10-18"},
        }
    ]
    state["avertissements"] = [{"code": "prevision_horaire_indisponible", "params": {"jours": 7}}]

    text = recommendation(state)

    assert "Batterie : aucune information disponible." in text
    assert "Piscine (filtration) : à l'arrêt toute la journée." in text
    assert "Reportés :" in text and "Avertissements :" in text


def test_titles() -> None:
    assert title("en") == "Today's energy plan" and title("fr") == "Planning énergétique du jour"


class Client:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def command(self, command: str, **params: Any) -> None:
        self.sent.append({"command": command, **params})


def test_send_calls_the_chosen_notify_service() -> None:
    client = Client()
    asyncio.run(send(client, "notify.mobile_app_phone", "Texte", "fr"))  # type: ignore[arg-type]
    assert client.sent == [
        {
            "command": "call_service",
            "domain": "notify",
            "service": "mobile_app_phone",
            "service_data": {"title": "Planning énergétique du jour", "message": "Texte"},
        }
    ]


def test_notifications_are_off_by_default_and_need_a_notify_service() -> None:
    assert PlanningSettings().notify_service is None
    assert PlanningSettings(notify_service="notify.mobile_app_x").notify_service
    with pytest.raises(ValidationError):
        PlanningSettings(notify_service="light.turn_on")


def test_notify_route_without_home_assistant(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from tests.test_health import _settings
    from wattslot.main import create_app

    with TestClient(create_app(_settings(tmp_path))) as api:
        assert api.post("/api/planning/notify").status_code == 503


def test_scheduled_run_sends_the_plan_text(tmp_path: Path) -> None:
    """Réglages d'avant le lot 5.6 (service choisi dans les réglages du calcul)."""
    from datetime import UTC, date, datetime
    from zoneinfo import ZoneInfo

    from wattslot.main import _notify
    from wattslot.planning.runner import RunReport
    from wattslot.planning.sources import save_settings
    from wattslot.planning.store import PlanStore
    from wattslot.storage.database import open_database

    database = open_database(tmp_path)
    now = datetime(2026, 10, 16, 12, 59, tzinfo=UTC)
    zone = ZoneInfo("Europe/Paris")
    report = RunReport(day=date(2026, 10, 16), started_at=now, manual=False, seconds_today=1)
    client = Client()
    on = PlanningSettings(notify_service="notify.mobile_app_phone", notify_language="en")

    save_settings(database, on)
    asyncio.run(_notify(client, database, now, zone, report))  # type: ignore[arg-type]
    assert client.sent == []  # pas encore de plan

    state = output(STATES[0])
    PlanStore(database).save("today", date(2026, 10, 16), state, 1.0, False)
    save_settings(database, PlanningSettings())
    asyncio.run(_notify(client, database, now, zone, report))  # type: ignore[arg-type]
    assert client.sent == []  # désactivé par défaut
    save_settings(database, on)
    asyncio.run(_notify(client, database, now, zone, report))  # type: ignore[arg-type]
    assert client.sent[0]["service_data"]["title"] == "Today's energy plan"
    assert client.sent[0]["service_data"]["message"].startswith("Objective: the lowest cost.")

    class Failing(Client):
        async def command(self, command: str, **params: Any) -> None:
            raise RuntimeError("service inconnu")

    asyncio.run(_notify(Failing(), database, now, zone, report))  # type: ignore[arg-type]
    assert report.errors == ["notification recommendation : RuntimeError: service inconnu"]
