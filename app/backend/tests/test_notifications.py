"""Notifications personnalisables (lot 5.6, PR 1) : réglages, reprise de ceux d'avant, rythme
de la recommandation, heures de silence, appareil propre, envoi d'essai ; contre un faux HA."""

import asyncio
import sqlite3
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from tests.planning.test_recommendation import output
from tests.test_health import _settings
from tests.v1_oracle import STATES
from wattslot import notifications
from wattslot.main import create_app
from wattslot.notifications import (
    NotificationSettings,
    QuietHours,
    RecommendationRule,
    dispatch,
    load,
    save,
)
from wattslot.planning.sources import PlanningSettings, save_settings
from wattslot.planning.store import PlanStore
from wattslot.storage.database import open_database

PARIS = ZoneInfo("Europe/Paris")
PHONE = "notify.mobile_app_phone"


class FakeHA:
    """Faux HA : garde les services appelés."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def command(self, command: str, **params: Any) -> None:
        self.sent.append({"command": command, **params})

    def services(self) -> list[str]:
        return [f"{c['domain']}.{c['service']}" for c in self.sent]

    def messages(self) -> list[str]:
        return [c["service_data"]["message"] for c in self.sent]


def _plan(changed: bool = False) -> dict[str, Any]:
    state = output(STATES[0])
    if changed:
        state["avertissements"] = [{"code": "prevision_incomplete", "params": {}}]
    return state


@pytest.fixture
def database(tmp_path: Path) -> sqlite3.Connection:
    found = open_database(tmp_path)
    PlanStore(found).save("today", date(2026, 10, 16), _plan(), 1.0, False)
    return found


def _at(hour: int, minute: int = 59, day: int = 16) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=PARIS).astimezone(UTC)


def _run(client: FakeHA, database: sqlite3.Connection, moment: datetime) -> list[Any]:
    return asyncio.run(dispatch(client, database, moment, PARIS))  # type: ignore[arg-type]


def _with(**rule: Any) -> NotificationSettings:
    return NotificationSettings(
        service=PHONE, recommendation=RecommendationRule(enabled=True, **rule)
    )


def test_nothing_is_sent_by_default(database: sqlite3.Connection) -> None:
    client = FakeHA()
    assert load(database) == NotificationSettings()  # ni appareil ni notification activée
    assert _run(client, database, _at(12)) == [] and client.sent == []


def test_settings_before_lot_5_6_still_apply(database: sqlite3.Connection) -> None:
    save_settings(database, PlanningSettings(notify_service=PHONE, notify_language="en"))
    found = load(database)
    assert found.service == PHONE and found.language == "en" and found.recommendation.enabled
    client = FakeHA()
    assert [sent.kind for sent in _run(client, database, _at(12))] == ["recommendation"]
    assert client.sent[0]["service_data"]["title"] == "Today's energy plan"
    # Une fois les nouveaux réglages enregistrés, les anciens ne comptent plus.
    save(database, NotificationSettings(service=PHONE))
    assert not load(database).recommendation.enabled


def test_every_run_sends_each_time_like_the_v1(database: sqlite3.Connection) -> None:
    save(database, _with(cadence="every_run"))
    client = FakeHA()
    _run(client, database, _at(10))
    _run(client, database, _at(11))
    assert client.services() == [PHONE, PHONE]
    assert client.sent[0]["service_data"]["title"] == "Planning énergétique du jour"
    assert client.messages()[0].startswith("Objectif")


def test_when_changed_sends_only_a_new_plan(database: sqlite3.Connection) -> None:
    save(database, _with(cadence="when_changed"))
    client = FakeHA()
    _run(client, database, _at(10))
    _run(client, database, _at(11))
    assert len(client.sent) == 1
    PlanStore(database).save("today", date(2026, 10, 16), _plan(changed=True), 2.0, False)
    _run(client, database, _at(12))
    assert len(client.sent) == 2 and client.messages()[0] != client.messages()[1]


def test_daily_sends_once_from_its_hour(database: sqlite3.Connection) -> None:
    save(database, _with(cadence="daily", daily_at=time(7, 30)))
    client = FakeHA()
    _run(client, database, _at(6))  # trop tôt
    _run(client, database, _at(7))  # 7 h 59
    _run(client, database, _at(8))
    assert len(client.sent) == 1
    _run(client, database, _at(7, day=17))  # le lendemain
    assert len(client.sent) == 2


def test_quiet_hours_skip_and_daily_waits_for_their_end(database: sqlite3.Connection) -> None:
    quiet = QuietHours(start=time(22, 0), end=time(8, 0))
    assert quiet.contains(time(23, 0)) and quiet.contains(time(7, 59))
    assert not quiet.contains(time(8, 0)) and not quiet.contains(time(21, 59))
    assert QuietHours(start=time(12, 0), end=time(14, 0)).contains(time(13, 0))

    save(database, _with(cadence="every_run", quiet_hours=quiet))
    client = FakeHA()
    _run(client, database, _at(23))
    _run(client, database, _at(7))
    assert client.sent == []
    _run(client, database, _at(8))
    assert len(client.sent) == 1

    save(database, _with(cadence="daily", daily_at=time(6, 0), quiet_hours=quiet))
    daily = FakeHA()
    _run(daily, database, _at(7, day=17))  # heure passée, mais silence
    assert daily.sent == []
    _run(daily, database, _at(8, day=17))  # premier calcul après le silence
    assert len(daily.sent) == 1


def test_a_notification_can_use_its_own_device(database: sqlite3.Connection) -> None:
    tablet = "notify.mobile_app_tablet"
    save(
        database,
        NotificationSettings(
            service=PHONE, recommendation=RecommendationRule(enabled=True, service=tablet)
        ),
    )
    client = FakeHA()
    _run(client, database, _at(12))
    assert client.services() == [tablet]


def test_no_device_no_notification(database: sqlite3.Connection) -> None:
    save(database, NotificationSettings(recommendation=RecommendationRule(enabled=True)))
    client = FakeHA()
    assert _run(client, database, _at(12)) == [] and client.sent == []


def test_only_notify_services_are_accepted() -> None:
    with pytest.raises(ValidationError):
        NotificationSettings(service="light.turn_on")
    with pytest.raises(ValidationError):
        RecommendationRule(service="script.alarm")


def test_test_send_ignores_quiet_hours_and_is_not_recorded(database: sqlite3.Connection) -> None:
    always = QuietHours(start=time(0, 0), end=time(23, 59))
    save(database, _with(cadence="when_changed", quiet_hours=always))
    client = FakeHA()
    sent = asyncio.run(notifications.send_test(client, database, "recommendation"))  # type: ignore[arg-type]
    assert sent.service == PHONE and len(client.sent) == 1
    assert notifications.last_sent(database, "recommendation", "plan") is None


def test_test_send_errors(tmp_path: Path) -> None:
    database = open_database(tmp_path)
    with pytest.raises(LookupError, match="no_notify_service"):
        asyncio.run(notifications.send_test(FakeHA(), database, "recommendation"))  # type: ignore[arg-type]
    save(database, NotificationSettings(service=PHONE))
    with pytest.raises(LookupError, match="no_plan"):
        asyncio.run(notifications.send_test(FakeHA(), database, "recommendation"))  # type: ignore[arg-type]


def test_settings_routes(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as api:
        assert api.get("/api/settings/notifications").json()["recommendation"]["enabled"] is False
        body = {
            "service": PHONE,
            "language": "en",
            "recommendation": {
                "enabled": True,
                "cadence": "when_changed",
                "quiet_hours": {"start": "22:00:00", "end": "07:00:00"},
            },
        }
        saved = api.put("/api/settings/notifications", json=body).json()
        assert saved["recommendation"]["cadence"] == "when_changed"
        assert api.get("/api/settings/notifications").json()["language"] == "en"
        bad = {**body, "recommendation": {"cadence": "hourly"}}
        assert api.put("/api/settings/notifications", json=bad).status_code == 422
        # Sans HA connecté : 503, comme l'essai d'avant le lot 5.6.
        assert api.post("/api/notifications/recommendation/test").status_code == 503
        assert api.post("/api/notifications/unknown/test").status_code == 422
