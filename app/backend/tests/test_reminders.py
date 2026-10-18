"""Rappels « Me le rappeler » (lot 6b.3)."""

import asyncio
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from tests.test_health import _settings
from tests.test_views_day import actual_of, state_of
from tests.v1_oracle import state_named
from wattslot import notifications, reminders
from wattslot.home_assistant import HomeAssistantClient
from wattslot.main import create_app
from wattslot.notifications import NotificationSettings
from wattslot.planning.store import PlanStore
from wattslot.storage.database import open_database, schema_version

PARIS = ZoneInfo("Europe/Paris")
LINGE = state_named("tomorrow_laundry")
DAY = date(2025, 10, 15)  # lave-linge prévu à 11 h, sèche-linge à 12 h 10


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2025, 10, 15, hour, minute, tzinfo=PARIS).astimezone(UTC)


class RecordingClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def command(self, kind: str, **payload: Any) -> Any:
        self.calls.append({"type": kind, **payload})
        return None


def test_migration_adds_the_reminders_table(tmp_path: Path) -> None:
    database = open_database(tmp_path)
    assert schema_version(database) >= 10
    reminders.ask(database, "Lave-linge", DAY, at(9))
    reminders.ask(database, "Lave-linge", DAY, at(9, 5))  # reposé : un seul rappel
    assert reminders.pending(database, DAY) == {"Lave-linge"}
    assert reminders.cancel(database, "Lave-linge", DAY)
    assert not reminders.cancel(database, "Lave-linge", DAY)
    assert reminders.pending(database, DAY) == set()


def test_due_at_the_start_planned_by_the_current_plan() -> None:
    plan = state_of(LINGE)
    waiting = {"Lave-linge", "Sèche-linge"}
    before, _ = reminders.due(plan, waiting, at(10, 59).astimezone(PARIS), PARIS, "fr")
    assert before == []
    found, launched = reminders.due(plan, waiting, at(11).astimezone(PARIS), PARIS, "fr")
    assert [(d.device, d.start_min) for d in found] == [("Lave-linge", 660)]
    assert found[0].message.startswith("Lancez Lave-linge maintenant : son cycle est prévu à 11h00")
    assert launched == []


def test_a_launched_appliance_closes_its_reminder_without_sending() -> None:
    plan = {**state_of(LINGE), "donnees_reelles_cache": actual_of(state_of(LINGE), hour=14)}
    found, launched = reminders.due(plan, {"Lave-linge"}, at(14, 20).astimezone(PARIS), PARIS, "fr")
    assert found == [] and launched == ["Lave-linge"]


def _scenario(
    tmp_path: Path, service: str | None, moments: list[datetime]
) -> tuple[Any, list[Any]]:
    database = open_database(tmp_path)
    PlanStore(database).save("today", DAY, state_of(LINGE), 1.0, False)
    notifications.save(database, NotificationSettings(service=service))
    reminders.ask(database, "Lave-linge", DAY, at(9))
    client = RecordingClient()
    sent = [
        asyncio.run(reminders.send_due(cast(HomeAssistantClient, client), database, moment, PARIS))
        for moment in moments
    ]
    return client, [sent, database]


def test_sent_once_at_its_time_even_with_the_notification_disabled(tmp_path: Path) -> None:
    client, (sent, database) = _scenario(
        tmp_path, "notify.mobile_app_phone", [at(10, 30), at(11, 1), at(11, 2)]
    )
    assert sent == [[], ["Lave-linge"], []]
    assert len(client.calls) == 1
    call = client.calls[0]
    assert (call["type"], call["domain"], call["service"]) == (
        "call_service",
        "notify",
        "mobile_app_phone",
    )
    assert "Lancez Lave-linge maintenant" in call["service_data"]["message"]
    assert reminders.pending(database, DAY) == set()
    # La notification « appareil à lancer » ne repartira pas en double.
    assert notifications.already_sent(database, "device_now", "Lave-linge@660", "2025-10-15")


def test_kept_until_a_notification_service_is_chosen(tmp_path: Path) -> None:
    client, (sent, database) = _scenario(tmp_path, None, [at(11, 1)])
    assert sent == [[]] and client.calls == []
    assert reminders.pending(database, DAY) == {"Lave-linge"}


def test_routes_ask_and_cancel_a_reminder(tmp_path: Path) -> None:
    today = datetime.now(UTC).date()  # l'application de test est à l'heure UTC
    with TestClient(create_app(_settings(tmp_path))) as client:
        assert client.post("/api/reminders", json={"device": "Lave-linge"}).status_code == 404
        PlanStore(open_database(tmp_path / "data")).save(
            "today", today, {**state_of(LINGE), "date_cible": today}, 1.0, False
        )
        created = client.post("/api/reminders", json={"device": "Lave-linge"})
        assert created.status_code == 201
        assert created.json() == {"device": "Lave-linge", "day": today.isoformat()}
        refused = client.post("/api/reminders", json={"device": "Piscine"})
        assert (refused.status_code, refused.json()["detail"]) == (422, "not_planned")
        view = client.get("/api/views/today").json()
        if view["next_action"] is not None and view["next_action"]["device"] == "Lave-linge":
            assert view["next_action"]["reminder"] is True
            assert view["next_action"]["can_remind"] is False  # aucun service réglé
        assert client.delete("/api/reminders/Lave-linge").status_code == 204
        assert client.delete("/api/reminders/Lave-linge").status_code == 404


def test_reminder_window_is_the_plan_day_only(tmp_path: Path) -> None:
    client, (sent, _) = _scenario(tmp_path, "notify.phone", [at(11) + timedelta(days=1)])
    assert sent == [[]] and client.calls == []
