"""Capteurs publiés dans Home Assistant : prévision de consommation de la maison."""

import asyncio
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from tests.test_health import _settings
from tests.test_views_day import state_of
from tests.v1_oracle import state_named
from wattslot import published_sensors as sensors
from wattslot.detection import sensor_choices
from wattslot.home_assistant import HomeSnapshot
from wattslot.main import _consumption_forecasts, create_app
from wattslot.planning.store import PlanStore
from wattslot.runtime import SUPERVISOR_CORE_WEBSOCKET_URL, HomeAssistantTarget
from wattslot.storage.database import open_database

PARIS = ZoneInfo("Europe/Paris")
DAY = date(2025, 10, 15)
HOURS = tuple(0.5 for _ in range(24))  # 12 kWh sur la journée
TARGET = HomeAssistantTarget("ws://192.0.2.10:8123/api/websocket", "jeton")


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2025, 10, 15, hour, minute, tzinfo=PARIS)


class Recorder:
    """Faux HA : note les requêtes et répond le code voulu."""

    def __init__(self, status: int = 200, fail: bool = False) -> None:
        self.status = status
        self.fail = fail
        self.calls: list[tuple[str, str, str, dict[str, Any] | None]] = []

    async def __call__(self, method: str, url: str, token: str, body: dict[str, Any] | None) -> int:
        if self.fail:
            raise sensors.Unreachable("injoignable")
        self.calls.append((method, url, token, body))
        return self.status


def publisher(
    tmp_path: Path,
    send: Recorder,
    today: sensors.Forecast | None = None,
    tomorrow: sensors.Forecast | None = None,
    enabled: bool = True,
    target: HomeAssistantTarget = TARGET,
) -> sensors.SensorPublisher:
    database = open_database(tmp_path)
    sensors.save(database, sensors.PublishedSensorsSettings(consumption_forecast=enabled))

    async def forecasts() -> tuple[sensors.Forecast | None, sensors.Forecast | None]:
        return today, tomorrow

    return sensors.SensorPublisher(target, database, forecasts, lambda: PARIS, send)


@pytest.mark.parametrize(
    ("websocket", "rest"),
    [
        ("ws://192.0.2.10:8123/api/websocket", "http://192.0.2.10:8123/api"),
        ("wss://ha.example.org/api/websocket", "https://ha.example.org/api"),
        ("ws://192.0.2.10:8123/prefix/api/websocket", "http://192.0.2.10:8123/prefix/api"),
        (SUPERVISOR_CORE_WEBSOCKET_URL, "http://supervisor/core/api"),
    ],
)
def test_rest_address_from_the_websocket_address(websocket: str, rest: str) -> None:
    assert sensors.rest_url(websocket) == rest


def test_remaining_counts_the_rest_of_the_hour_then_the_next_hours() -> None:
    assert sensors.remaining_kwh(HOURS, at(0)) == pytest.approx(12.0)
    assert sensors.remaining_kwh(HOURS, at(18, 30)) == pytest.approx(0.25 + 5 * 0.5)
    assert sensors.remaining_kwh(HOURS, at(23, 45)) == pytest.approx(0.125)


def test_states_of_the_three_sensors() -> None:
    computed = datetime(2025, 10, 15, 16, 59, tzinfo=UTC)
    today = sensors.Forecast(DAY, HOURS, computed)
    tomorrow = sensors.Forecast(DAY + timedelta(days=1), tuple(0.25 for _ in range(24)))

    found = sensors.consumption_states(today, tomorrow, at(18, 30))

    assert {entity: state.state for entity, state in found.items()} == {
        "sensor.wattslot_home_consumption_forecast_remaining_today": "2.75",
        "sensor.wattslot_home_consumption_forecast_today": "12.00",
        "sensor.wattslot_home_consumption_forecast_tomorrow": "6.00",
    }
    attributes = found[sensors.REMAINING_TODAY].attributes
    assert attributes["unit_of_measurement"] == "kWh"
    assert attributes["device_class"] == "energy"
    # Une prévision n'est pas une mesure : pas de statistiques à long terme dans HA.
    assert "state_class" not in attributes
    assert attributes["forecast_date"] == "2025-10-15"
    assert attributes["computed_at"] == computed.isoformat()
    assert "computed_at" not in found[sensors.TOMORROW].attributes


def test_a_plan_of_another_day_is_unavailable_rather_than_wrong() -> None:
    """Juste après minuit, avant le premier calcul : les plans gardés sont ceux de la veille."""
    yesterday = sensors.Forecast(DAY - timedelta(days=1), HOURS)
    today_kept_as_tomorrow = sensors.Forecast(DAY, HOURS)

    found = sensors.consumption_states(yesterday, today_kept_as_tomorrow, at(0, 5))

    assert {state.state for state in found.values()} == {"unavailable"}
    assert sensors.consumption_states(None, None, at(12))[sensors.TODAY].state == "unavailable"


def test_nothing_is_written_while_disabled(tmp_path: Path) -> None:
    send = Recorder()
    found = publisher(tmp_path, send, sensors.Forecast(DAY, HOURS), enabled=False)

    asyncio.run(found.publish(at(12)))

    assert send.calls == [] and found.published_at is None and found.error is None


def test_publishes_the_three_states_with_the_token(tmp_path: Path) -> None:
    send = Recorder(status=201)
    found = publisher(tmp_path, send, sensors.Forecast(DAY, HOURS))

    asyncio.run(found.publish(at(12)))

    assert [(method, url, token) for method, url, token, _ in send.calls] == [
        ("POST", f"http://192.0.2.10:8123/api/states/{entity}", "jeton")
        for entity in sensors.CONSUMPTION_FORECAST
    ]
    assert [body["state"] for *_, body in send.calls if body] == ["6.00", "12.00", "unavailable"]
    assert found.error is None and found.published_at == at(12).astimezone(UTC)


def test_the_supervisor_address_and_a_refreshed_token(tmp_path: Path) -> None:
    async def token() -> str:
        return "rafraîchi"

    send = Recorder()
    target = HomeAssistantTarget(SUPERVISOR_CORE_WEBSOCKET_URL, "ancien", token)
    found = publisher(tmp_path, send, sensors.Forecast(DAY, HOURS), target=target)

    asyncio.run(found.publish(at(12)))

    assert send.calls[0][1] == f"http://supervisor/core/api/states/{sensors.REMAINING_TODAY}"
    assert {call[2] for call in send.calls} == {"rafraîchi"}


@pytest.mark.parametrize(
    ("send", "error"),
    [
        (Recorder(status=401), "refused"),
        (Recorder(status=403), "refused"),
        (Recorder(status=500), "unknown"),
        (Recorder(fail=True), "unreachable"),
    ],
)
def test_a_failure_is_kept_for_the_interface_without_raising(
    tmp_path: Path, send: Recorder, error: str
) -> None:
    found = publisher(tmp_path, send, sensors.Forecast(DAY, HOURS))

    asyncio.run(found.publish(at(12)))

    assert found.error == error and found.published_at is None
    assert len(send.calls) <= 1  # arrêt au premier refus

    send.status, send.fail = 200, False
    asyncio.run(found.publish(at(12, 15)))
    assert found.error is None and found.published_at is not None


def test_remove_deletes_the_states(tmp_path: Path) -> None:
    send = Recorder(status=404)  # déjà oubliés par HA : sans importance
    found = publisher(tmp_path, send, sensors.Forecast(DAY, HOURS))

    asyncio.run(found.remove())

    assert [(method, url.rsplit("/", 1)[1]) for method, url, *_ in send.calls] == [
        ("DELETE", entity) for entity in sensors.CONSUMPTION_FORECAST
    ]


def test_published_sensors_are_never_offered_as_house_sensors() -> None:
    def energy() -> dict[str, Any]:
        return {"attributes": {"unit_of_measurement": "kWh", "device_class": "energy"}}

    snapshot = HomeSnapshot(states={sensors.TODAY: energy(), "sensor.meter_energy": energy()})

    assert [choice.entity_id for choice in sensor_choices(snapshot)] == ["sensor.meter_energy"]


def test_forecasts_are_the_consumption_of_the_views(tmp_path: Path) -> None:
    today = datetime.now(UTC).date()  # l'application de test est à l'heure UTC
    with TestClient(create_app(_settings(tmp_path))) as client:
        assert asyncio.run(_consumption_forecasts(client.app.state)) == (None, None)  # type: ignore[attr-defined]
        PlanStore(open_database(tmp_path / "data")).save(
            "today",
            today,
            {**state_of(state_named("tomorrow_laundry")), "date_cible": today},
            1.0,
            False,
        )
        view = client.get("/api/views/today").json()
        found, tomorrow = asyncio.run(_consumption_forecasts(client.app.state))  # type: ignore[attr-defined]

    assert tomorrow is None and found is not None
    assert found.day == today
    assert list(found.hours) == [hour["consumption_kwh"] for hour in view["hours"]]
    assert sum(found.hours) > 0


def test_routes_read_and_save_the_setting(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        initial = client.get("/api/settings/sensors").json()
        assert initial == {
            "consumption_forecast": False,
            "entities": list(sensors.CONSUMPTION_FORECAST),
            "available": False,  # pas de connexion à HA dans ce test
            "published_at": None,
            "error": None,
        }
        saved = client.put("/api/settings/sensors", json={"consumption_forecast": True})
        assert saved.status_code == 200 and saved.json()["consumption_forecast"] is True
        assert client.get("/api/settings/sensors").json()["consumption_forecast"] is True


def test_the_request_really_sent_to_home_assistant() -> None:
    """Vraie requête HTTP vers un faux HA local : méthode, jeton, corps JSON, code renvoyé."""
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    seen: list[tuple[str, str, str | None, Any]] = []

    class Handler(BaseHTTPRequestHandler):
        def _answer(self, status: int) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length)) if length else None
            seen.append((self.command, self.path, self.headers.get("Authorization"), body))
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_POST(self) -> None:
            self._answer(201)

        def do_DELETE(self) -> None:
            self._answer(404)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/api/states/{sensors.TODAY}"
    try:
        body = {"state": "12.00", "attributes": {"unit_of_measurement": "kWh"}}
        assert asyncio.run(sensors.send_request("POST", url, "jeton", body)) == 201
        assert asyncio.run(sensors.send_request("DELETE", url, "jeton", None)) == 404
    finally:
        server.shutdown()
        server.server_close()
    path = f"/api/states/{sensors.TODAY}"
    assert seen == [("POST", path, "Bearer jeton", body), ("DELETE", path, "Bearer jeton", None)]
    with pytest.raises(sensors.Unreachable):
        asyncio.run(sensors.send_request("POST", url, "jeton", body))  # serveur arrêté
