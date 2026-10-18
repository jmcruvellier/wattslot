"""Entrées lues dans HA (prévision, tâches, batterie) et assemblage de l'entrée du calcul."""

import asyncio
import json
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from tests.test_health import _settings
from wattslot.aggregation import HOUR, QUARTER, Aggregate
from wattslot.detection import DeviceKind, Role
from wattslot.home_assistant import HomeAssistantClient
from wattslot.home_model import HomeDevice, HomeModel, HomeSensor
from wattslot.main import create_app
from wattslot.planning.assemble import battery_state, build_input, to_v1
from wattslot.planning.inputs import from_v1
from wattslot.planning.journal import CycleJournal
from wattslot.planning.sources import (
    ForecastUnavailable,
    PlanningSettings,
    energy_dashboard_forecast,
    entity_forecast,
    load_settings,
    read_tasks,
    solar_forecast,
)
from wattslot.storage.database import open_database
from wattslot.storage.raw import RawStores

PARIS = ZoneInfo("Europe/Paris")
TODAY = date(2026, 10, 16)
NOW = datetime(2026, 10, 16, 13, 20, tzinfo=PARIS)


def local(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), PARIS)


class StubClient:
    def __init__(self, answers: dict[str, Any]) -> None:
        self.answers = answers
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def command(self, command: str, **params: Any) -> Any:
        self.calls.append((command, params))
        answer = self.answers.get(command)
        if isinstance(answer, Exception):
            raise answer
        return answer


def client(answers: dict[str, Any]) -> HomeAssistantClient:
    return cast(HomeAssistantClient, StubClient(answers))


WH_HOURS = {
    "forecast_solar": {
        "wh_hours": {
            local(TODAY, 11).isoformat(): 1200,
            local(TODAY, 12).astimezone(UTC).isoformat(): 1500,  # en UTC : converti
            local(TODAY + timedelta(days=1), 12).isoformat(): 999,  # autre jour
        }
    },
    "solcast": {"wh_hours": {local(TODAY, 12).isoformat(): 500}},
}


def test_energy_dashboard_forecast_sums_every_source_by_local_hour() -> None:
    assert energy_dashboard_forecast(WH_HOURS, TODAY, PARIS) == pytest.approx({11: 1.2, 12: 2.0})


def test_entity_forecast_averages_the_quarter_hour_points() -> None:
    states = [
        {
            "entity_id": "sensor.panel_power_now",
            "attributes": {
                "forecast": [
                    {"datetime": local(TODAY, 10, m).astimezone(UTC).isoformat(), "watts": w}
                    for m, w in ((0, 800), (15, 1000), (30, 1200), (45, 1000))
                ]
            },
        },
        {"entity_id": "sensor.other", "attributes": {"forecast": [{"datetime": "x", "watts": 1}]}},
    ]

    assert entity_forecast(states, ["sensor.panel_power_now"], TODAY, PARIS) == {10: 1.0}


def test_solar_forecast_falls_back_on_entities_then_fails() -> None:
    settings = PlanningSettings(forecast_entities=["sensor.panel_power_now"])
    states = [
        {
            "entity_id": "sensor.panel_power_now",
            "attributes": {"forecast": [{"datetime": local(TODAY, 9).isoformat(), "watts": 500}]},
        }
    ]
    fallback = client(
        {"energy/solar_forecast": RuntimeError("non configuré"), "get_states": states}
    )

    hourly, warnings = asyncio.run(solar_forecast(fallback, TODAY, PARIS, settings))

    assert hourly == {9: 0.5} and warnings == []
    with pytest.raises(ForecastUnavailable):
        asyncio.run(
            solar_forecast(client({"energy/solar_forecast": {}}), TODAY, PARIS, PlanningSettings())
        )


def test_read_tasks_from_the_home_assistant_list() -> None:
    items = [
        {
            "uid": "ce",
            "summary": "Chauffe-eau",
            "due": "2026-10-16T08:00:00+02:00",
            "description": json.dumps({"type": "recurrent", "regle": "FREQ=DAILY;INTERVAL=2"}),
        },
        {
            "uid": "sl",
            "summary": "Sèche-linge",
            "description": json.dumps({"type": "a_la_demande", "depend_de": "lave-linge"}),
        },
        {"uid": "x", "summary": "Lave-linge", "description": "pas du JSON"},
    ]
    ha = StubClient({"call_service": {"response": {"todo.maison": {"items": items}}}})

    due, waiting = asyncio.run(read_tasks(cast(HomeAssistantClient, ha), "todo.maison"))

    assert [(t.name, t.due, t.rule) for t in due] == [
        ("Chauffe-eau", date(2026, 10, 16), "FREQ=DAILY;INTERVAL=2")
    ]
    assert [(t.name, t.on_demand, t.depends_on) for t in waiting] == [
        ("Sèche-linge", True, "lave-linge"),
        ("Lave-linge", False, None),
    ]
    command, params = ha.calls[0]
    assert command == "call_service" and params["target"] == {"entity_id": "todo.maison"}
    assert params["return_response"] is True
    assert asyncio.run(read_tasks(cast(HomeAssistantClient, ha), None)) == ([], [])


def device(
    key: str, kind: DeviceKind, *sensors: tuple[str, Role], capacity: float | None = None
) -> HomeDevice:
    return HomeDevice(
        key=key,
        kind=kind,
        name=key,
        capacity_kwh=capacity,
        sensors=[HomeSensor(entity_id=e, role=r) for e, r in sensors],
    )


MODEL = HomeModel(
    devices=[
        device("solar", DeviceKind.SOLAR, ("sensor.pv", Role.ENERGY_PRODUCED)),
        device(
            "grid",
            DeviceKind.GRID,
            ("sensor.imp", Role.ENERGY_IMPORTED),
            ("sensor.exp", Role.ENERGY_EXPORTED),
        ),
        device(
            "battery",
            DeviceKind.BATTERY,
            ("sensor.chg", Role.ENERGY_CHARGED),
            ("sensor.dis", Role.ENERGY_DISCHARGED),
            ("sensor.soc", Role.STATE_OF_CHARGE),
            capacity=5.0,
        ),
        device(
            "washer",
            DeviceKind.WASHING_MACHINE,
            ("sensor.washer_power", Role.POWER_CONSUMED),
            ("sensor.washer_energy", Role.ENERGY_CONSUMED),
        ),
    ]
)


class Reader:
    """Agrégats horaires et au quart d'heure en mémoire."""

    def __init__(self) -> None:
        self.data: dict[tuple[str, str], list[Aggregate]] = defaultdict(list)

    def add(self, entity_id: str, period: str, start: datetime, **values: float) -> None:
        self.data[(entity_id, period)].append(
            Aggregate(entity_id=entity_id, period=period, start=start.astimezone(UTC), **values)
        )

    def read(self, entity_id: str, period: str, start: datetime, end: datetime) -> list[Aggregate]:
        return sorted(
            (a for a in self.data[(entity_id, period)] if start <= a.start < end),
            key=lambda a: a.start,
        )


def test_battery_state_from_home_assistant() -> None:
    states = [{"entity_id": "sensor.soc", "state": "40"}]
    assert battery_state(MODEL, states) == (5.0, 2.0, 40.0)
    assert battery_state(MODEL, [{"entity_id": "sensor.soc", "state": "unavailable"}]) == (
        0.0,
        0.0,
        0.0,
    )


def test_build_input_assembles_every_source(tmp_path: Path) -> None:
    reader = Reader()
    for k in range(1, 15):  # 14 jours : ligne de base de 0,4 kWh, lessive chaque jour
        day = TODAY - timedelta(days=k)
        for hour in range(24):
            start = local(day, hour)
            reader.add("sensor.imp", HOUR, start, energy_kwh=0.4)
            reader.add("sensor.exp", HOUR, start, energy_kwh=0.0)
            reader.add("sensor.chg", HOUR, start, energy_kwh=0.0)
            reader.add("sensor.dis", HOUR, start, energy_kwh=0.0)
        for q in range(-1, 7):
            start = local(day, 10) + timedelta(minutes=15 * q)
            on = 0 <= q < 6
            reader.add("sensor.washer_power", QUARTER, start, mean=800.0 if on else 1.0)
            reader.add("sensor.washer_energy", QUARTER, start, energy_kwh=0.05 if on else 0.0)
    for q in range(4 * 13):  # production mesurée ce matin : 0,1 kWh par quart d'heure
        reader.add(
            "sensor.pv", QUARTER, local(TODAY, 0) + timedelta(minutes=15 * q), energy_kwh=0.1
        )
    raw = RawStores(tmp_path, "Europe/Paris")
    journal = CycleJournal(open_database(tmp_path), raw, reader)
    ha = client(
        {
            "energy/solar_forecast": {"x": {"wh_hours": {local(TODAY, 12).isoformat(): 2000}}},
            "call_service": {
                "response": {
                    "todo.maison": {
                        "items": [
                            {
                                "uid": "ll",
                                "summary": "Lave-linge",
                                "description": json.dumps({"type": "a_la_demande"}),
                            }
                        ]
                    }
                }
            },
            "get_states": [{"entity_id": "sensor.soc", "state": "60"}],
        }
    )
    settings = PlanningSettings(todo_entity="todo.maison")

    data = asyncio.run(build_input(TODAY, NOW, ha, MODEL, reader, raw, journal, settings))

    assert data.first_hour == 13
    assert data.production_kwh[12] == 2.0
    assert data.net_kwh[12] == pytest.approx(2.0 - 0.4)
    assert data.net_kwh[3] == pytest.approx(-0.4)
    assert [t.name for t in data.waiting_tasks] == ["Lave-linge"]
    profile = data.cycle_profiles["Lave-linge"]  # rattaché au lave-linge du modèle
    assert profile.energy_kwh == pytest.approx(0.3) and profile.duration_min == 90
    assert (data.battery.capacity_kwh, data.battery.stored_kwh, data.battery.soc_percent) == (
        5.0,
        3.0,
        60.0,
    )
    assert data.measured_production_kwh == pytest.approx(5.2)
    assert data.measured_at_hour == 13.0

    v1 = to_v1(data)
    back = from_v1({**v1, "date_cible": TODAY})
    assert back.net_kwh == data.net_kwh and back.waiting_tasks == data.waiting_tasks
    assert {
        n: (p.energy_kwh, p.duration_min, tuple(p.shape or ()))
        for n, p in back.cycle_profiles.items()
    } == {
        n: (p.energy_kwh, p.duration_min, tuple(p.shape or ()))
        for n, p in data.cycle_profiles.items()
    }
    assert back.battery.stored_kwh == data.battery.stored_kwh


def test_settings_saved_with_the_removed_legacy_dashboard_still_load(tmp_path: Path) -> None:
    database = open_database(tmp_path)
    with database:
        database.execute(
            "INSERT INTO app_settings VALUES ('planning', ?)",
            (json.dumps({"objective": "import", "legacy_dashboard": False}),),
        )

    assert load_settings(database).objective == "import"  # ancien dashboard supprimé (lot 7.1)


def test_planning_routes_without_home_assistant(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as api:
        assert api.get("/api/planning/input").status_code == 503
        assert api.get("/api/settings/planning").json()["objective"] == "cost"
        saved = api.put(
            "/api/settings/planning", json={"objective": "import", "todo_entity": "todo.maison"}
        ).json()
    assert saved["objective"] == "import" and saved["todo_entity"] == "todo.maison"
