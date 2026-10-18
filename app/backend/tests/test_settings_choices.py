"""Choix proposés par le formulaire des réglages de fonctionnement (lot 4.2)."""

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from tests.fake_home_assistant import default_responses, fake_home_assistant, running_client
from tests.test_health import _settings
from wattslot.main import create_app
from wattslot.settings_choices import SettingsChoices, settings_choices

STATES = [
    {
        "entity_id": "sensor.solar_energy",
        "state": "1",
        "attributes": {"unit_of_measurement": "kWh"},
    },
    {"entity_id": "todo.courses", "state": "2", "attributes": {"friendly_name": "Courses"}},
    {"entity_id": "todo.maison", "state": "0", "attributes": {}},
    {
        "entity_id": "sensor.helios_forecast",
        "state": "3.2",
        "attributes": {
            "friendly_name": "Prévision",
            "forecast": [{"datetime": "2026-10-16T12:00:00+02:00", "watts": 1500}],
        },
    },
    # Une prévision météo n'est pas une prévision solaire : pas de « watts ».
    {
        "entity_id": "weather.home",
        "state": "sunny",
        "attributes": {"forecast": [{"datetime": "2026-10-16T12:00:00+02:00", "temp": 18}]},
    },
]

SERVICES = {
    "light": {"turn_on": {}},
    "notify": {
        "mobile_app_phone": {"name": "Send a notification via mobile_app_phone"},
        "notify": {"name": "Send a notification with notify"},
        "send_message": {"name": "Send a notification message"},
    },
}


async def _choices(services: object) -> SettingsChoices:
    responses = default_responses() | {"get_states": STATES, "get_services": services}
    async with running_client(fake_home_assistant(responses)) as client:
        return await settings_choices(client)


def test_choices_are_read_from_home_assistant() -> None:
    found = asyncio.run(_choices(SERVICES))

    assert found.connected
    assert [(c.id, c.name) for c in found.todo_lists] == [
        ("todo.courses", "Courses"),
        ("todo.maison", None),
    ]
    assert [c.id for c in found.notify_services] == ["notify.mobile_app_phone", "notify.notify"]
    assert [c.id for c in found.forecast_entities] == ["sensor.helios_forecast"]


def test_without_services_the_other_choices_remain() -> None:
    found = asyncio.run(_choices(None))  # get_services en erreur

    assert found.notify_services == []
    assert len(found.todo_lists) == 2


def test_without_home_assistant_the_lists_are_empty(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as api:
        found = api.get("/api/settings/choices").json()

    assert found == {
        "connected": False,
        "todo_lists": [],
        "notify_services": [],
        "forecast_entities": [],
    }
