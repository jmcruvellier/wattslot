"""Serveur MCP de l'application (lots 6.1 et 6.2) : un vrai client MCP du SDK liste les outils
et les appelle sur des plans de référence ; ``/mcp`` répond en HTTP ; en mode extension, seul HA
Core l'appelle hors de l'ingress ; dépôt d'une demande ; budget de tokens ; prompts conseillés."""

import asyncio
import json
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from mcp.client.client import Client

from tests.test_health import _settings
from tests.test_views_day import actual_of, state_of
from tests.test_views_week import horizon_of
from tests.v1_oracle import STATES, state_named
from wattslot import home_model
from wattslot.assistant.prompts import prompt
from wattslot.assistant.tools import (
    WEATHER,
    _max_hour,
    clock,
    day_of,
    find_name,
    measured_energy,
)
from wattslot.detection import DeviceKind, Role
from wattslot.home_model import HomeDevice, HomeModel, HomeSensor
from wattslot.ingress import HOME_ASSISTANT_CORE_ADDRESS
from wattslot.languages import LANGUAGES
from wattslot.main import create_app
from wattslot.planning.store import PlanStore
from wattslot.runtime import RunMode, Settings
from wattslot.storage.database import open_database
from wattslot.storage.graph import GraphStore

READ_TOOLS = {
    "get_day_plan",
    "explain_device",
    "get_week",
    "get_current_status",
    "get_energy",
    "get_forecast",
    "get_home",
    "get_problems",
}
TOOLS = READ_TOOLS | {"request_device"}
# Budgets (point n° 6) : tokens estimés au plus large, un token pour 3 caractères.
TOOLS_BUDGET = 2000
PROMPT_BUDGET = 400
# Lave-linge prévu à 11 h, sèche-linge à 12 h 10.
LINGE = state_named("tomorrow_laundry")


@pytest.fixture
def api(tmp_path: Path) -> Iterator[TestClient]:
    today = state_of(LINGE)
    today["donnees_reelles_cache"] = actual_of(today, 14)
    tomorrow = {**state_of(STATES[0]), "date_cible": today["date_cible"] + timedelta(days=1)}
    horizon, days = horizon_of(2)
    with TestClient(create_app(_settings(tmp_path))) as client:
        store = PlanStore(open_database(tmp_path / "data"))
        store.save("today", today["date_cible"], today, 1.0, False)
        store.save("tomorrow", tomorrow["date_cible"], tomorrow, 1.0, False)
        store.save("horizon", days[0]["date_cible"], horizon, 1.0, False)
        yield client


def _call(api: TestClient, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    async def run() -> dict[str, Any]:
        async with Client(api.app.state.mcp) as client:  # type: ignore[attr-defined]
            result = await client.call_tool(name, arguments or {})
            assert not result.is_error, result
            found: dict[str, Any] = result.structured_content or {}
            return found

    return asyncio.run(run())


def test_the_client_lists_eight_read_only_tools_and_one_action(api: TestClient) -> None:
    async def run() -> Any:
        async with Client(api.app.state.mcp) as client:  # type: ignore[attr-defined]
            return (await client.list_tools()).tools

    tools = {t.name: t for t in asyncio.run(run())}
    assert set(tools) == TOOLS
    assert all(tools[n].annotations.read_only_hint for n in READ_TOOLS)
    action = tools["request_device"].annotations
    assert action is not None and not action.read_only_hint and not action.destructive_hint
    assert all(t.description and len(t.description) < 90 for t in tools.values())  # courtes


def test_day_plan_and_week(api: TestClient) -> None:
    plan = _call(api, "get_day_plan", {"day": "today"})
    assert plan["day"] == "2025-10-15"
    assert "Lave-linge : 11h" in plan["recommendation"]  # en français, la langue réglée
    assert plan["summary"]["production_kwh"] > 0 and "battery_end_percent" in plan["summary"]
    assert _call(api, "get_day_plan", {"day": "yesterday"})["error"] == "no_plan"

    week = _call(api, "get_week")
    assert len(week["days"]) >= 2 and all(d["production_kwh"] > 0 for d in week["days"])


def test_explain_device_finds_it_without_accents_or_dashes(api: TestClient) -> None:
    found = _call(api, "explain_device", {"device": "seche linge"})
    assert found["device"] == "Sèche-linge"
    assert found["planned"][0]["start"] == "12:10"
    assert found["status"] in {"planned", "no_cycle", "on_time", "shifted"}
    unknown = _call(api, "explain_device", {"device": "voiture"})
    assert unknown["error"] == "unknown_device" and "Lave-linge" in unknown["planned_devices"]


def test_energy_forecast_home_status_and_problems(api: TestClient) -> None:
    # Sans HA, pas d'agrégats : seulement ce que prévoyait le plan de ce jour.
    energy = _call(api, "get_energy", {"day": "2025-10-15"})
    assert energy["measured"] is None and energy["planned"]["production_kwh"] > 0
    assert {"Lave-linge", "Sèche-linge"} <= set(energy["planned"]["devices"])
    assert _call(api, "get_energy", {"day": "2026-10-01"})["error"] == "no_data"
    assert _call(api, "get_energy", {"day": "hier"})["error"] == "invalid_date"
    assert _call(api, "get_energy", {"day": "2099-01-01"})["error"] == "invalid_date"

    forecast = _call(api, "get_forecast", {"day": "tomorrow"})
    assert forecast["production_kwh"] > 0 and "12:00" in forecast["hourly_kwh"]

    home = _call(api, "get_home")
    assert home["objective"] == "cost" and "devices" in home and home["tariff"]

    assert _call(api, "get_current_status")["error"] == "not_connected"  # pas de HA en test
    problems = _call(api, "get_problems")["problems"]
    assert problems and problems[0]["code"] == "ha_not_configured"


def test_mcp_answers_over_http(api: TestClient) -> None:
    headers = {"Accept": "application/json, text/event-stream"}
    init = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        },
    }
    answer = api.post("/mcp", json=init, headers=headers)
    assert answer.status_code == 200
    assert answer.json()["result"]["serverInfo"]["name"] == "wattslot"
    listed = api.post(
        "/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers=headers
    )
    assert {t["name"] for t in json.loads(listed.text)["result"]["tools"]} == TOOLS


def test_in_addon_mode_only_home_assistant_core_reaches_mcp(tmp_path: Path) -> None:
    def addon(name: str) -> Settings:
        return Settings(
            mode=RunMode.ADDON, data_dir=tmp_path / name, static_dir=None, home_assistant=None
        )

    core = TestClient(create_app(addon("core")), client=(HOME_ASSISTANT_CORE_ADDRESS, 50000))
    other = TestClient(create_app(addon("other")), client=("172.30.33.5", 50000))
    with core, other:
        assert core.post("/mcp", json={}).status_code != 403
        assert core.get("/api/health").status_code == 403  # l'interface reste à l'ingress
        assert other.post("/mcp", json={}).status_code == 403


def test_helpers() -> None:
    assert clock(13.5) == "13:30" and clock(24) == "00:00"
    names = ["Lave-linge", "Sèche-linge", "Piscine (filtration)"]
    assert find_name("LAVE LINGE", names) == "Lave-linge"
    assert find_name("piscine", names) == "Piscine (filtration)"
    assert find_name("four", names) is None


# Maison où l'on peut demander deux équipements à cycle.
HOME = HomeModel(
    devices=[
        HomeDevice(
            key=key,
            kind=kind,
            name=name,
            sensors=[HomeSensor(entity_id=f"sensor.{key}", role=Role.ENERGY_CONSUMED)],
        )
        for key, kind, name in (
            ("washer", DeviceKind.WASHING_MACHINE, "Lave-linge"),
            ("dishwasher", DeviceKind.DISHWASHER, "Lave-vaisselle"),
        )
    ]
)


def test_request_device_files_a_request_like_my_requests(api: TestClient) -> None:
    home_model.save(api.app.state.graph, HOME)  # type: ignore[attr-defined]
    asked = _call(api, "request_device", {"device": "lave linge"})
    assert asked["device"] == "Lave-linge" and asked["latest_date"] is None
    later = _call(api, "request_device", {"device": "Lave-linge", "latest_date": "2099-01-31"})
    assert later["latest_date"] == "2099-01-31"
    opened = [r for r in api.get("/api/requests").json() if r["status"] == "open"]
    assert len(opened) == 1 and opened[0]["latest"] == "2099-01-31"  # une seule, redatée

    unknown = _call(api, "request_device", {"device": "voiture"})
    assert unknown["error"] == "unknown_device" and "Lave-linge" in unknown["devices"]
    for wrong in ("demain", "2001-01-01"):
        found = _call(api, "request_device", {"device": "Lave-linge", "latest_date": wrong})
        assert found["error"] == "invalid_date"


def test_the_tool_schemas_stay_under_the_token_budget(api: TestClient) -> None:
    headers = {"Accept": "application/json, text/event-stream"}
    listed = api.post(
        "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers=headers
    )
    schemas = json.dumps(listed.json()["result"]["tools"], ensure_ascii=False)
    assert len(schemas) / 3 < TOOLS_BUDGET, len(schemas) / 3


def test_the_advised_prompt_in_every_language(api: TestClient) -> None:
    for lang in LANGUAGES:
        text = prompt(lang)
        assert len(text) / 3 < PROMPT_BUDGET, (lang, len(text) / 3)
        missing = {name for name in TOOLS if name not in text}
        assert not missing, (lang, missing)  # un outil renommé se voit ici
    found = api.get("/api/assistant/prompt?lang=de").json()
    assert found["language"] == "de" and found["prompt"].startswith("Du bist")
    assert api.get("/api/assistant/prompt?lang=xx").json()["language"] == "fr"


class FakeAggregator:
    """Agrégats horaires d'une journée : 1 kWh par heure de 10 h à 14 h pour chaque compteur,
    0,5 kWh pour l'achat."""

    def read(self, entity_id: str, period: str, start: Any, end: Any) -> list[Any]:
        kwh = 0.5 if entity_id == "sensor.import" else 1.0
        return [
            SimpleNamespace(energy_kwh=kwh, start=start + timedelta(hours=h)) for h in range(10, 14)
        ]


def test_measured_energy_comes_from_the_aggregates_of_any_day(tmp_path: Path) -> None:
    graph = GraphStore(tmp_path)
    home_model.load_vocabulary(graph)
    sensors = {
        "solar": ("sensor.pv", Role.ENERGY_PRODUCED, DeviceKind.SOLAR, "Panneaux"),
        "grid": ("sensor.import", Role.ENERGY_IMPORTED, DeviceKind.GRID, "Réseau"),
        "washer": ("sensor.washer", Role.ENERGY_CONSUMED, DeviceKind.WASHING_MACHINE, "Lave-linge"),
    }
    home_model.save(
        graph,
        HomeModel(
            devices=[
                HomeDevice(
                    key=key,
                    kind=kind,
                    name=name,
                    sensors=[HomeSensor(entity_id=entity, role=role)],
                )
                for key, (entity, role, kind, name) in sensors.items()
            ]
        ),
    )
    state = SimpleNamespace(
        aggregator=FakeAggregator(), graph=graph, raw=SimpleNamespace(zone=ZoneInfo("Europe/Paris"))
    )
    found = measured_energy(state, date(2026, 10, 1))
    assert found == {
        "production_kwh": 4.0,
        "grid_import_kwh": 2.0,
        "consumption_kwh": 6.0,  # produit + acheté
        "devices": {"Lave-linge": 4.0},
    }
    assert measured_energy(SimpleNamespace(aggregator=None), date(2026, 10, 1)) is None
    assert day_of(state, "2026-10-01") == date(2026, 10, 1) and day_of(state, "x") is None
    graph.flush()


def test_an_appliance_of_the_home_not_planned_this_day(tmp_path: Path) -> None:
    """Le lave-linge est dans la maison mais pas dans le plan du jour : « pas prévu », avec le
    prochain jour où l'horizon le place, et non « équipement inconnu »."""
    today = {**state_of(STATES[0]), "date_cible": date(2026, 10, 14)}  # chauffe-eau, piscine
    next_day = {**state_of(LINGE), "date_cible": date(2026, 10, 15)}  # lave-linge à 11 h
    horizon = {"jours": [next_day], "avertissements": [], "duree_s": 1.0}
    with TestClient(create_app(_settings(tmp_path))) as client:
        store = PlanStore(open_database(tmp_path / "data"))
        store.save("today", today["date_cible"], today, 1.0, False)
        store.save("horizon", next_day["date_cible"], horizon, 1.0, False)
        home_model.save(client.app.state.graph, HOME)  # type: ignore[attr-defined]

        washer = _call(client, "explain_device", {"device": "lave linge"})
        dishwasher = _call(client, "explain_device", {"device": "Lave-vaisselle"})
        unknown = _call(client, "explain_device", {"device": "voiture"})

    assert washer["device"] == "Lave-linge" and washer["scheduled"] is False
    assert washer["next_planned"] == {"day": "2026-10-15", "start": "11:00", "end": "12:10"}
    assert "request_device" in washer["hint"]
    assert dishwasher["scheduled"] is False and "next_planned" not in dishwasher
    assert unknown["error"] == "unknown_device" and "Chauffe-eau" in unknown["planned_devices"]


def test_other_days_say_what_today_means_and_the_maximum_is_an_hour_range(api: TestClient) -> None:
    today = _call(api, "get_day_plan", {"day": "today"})
    tomorrow = _call(api, "get_day_plan", {"day": "tomorrow"})
    assert "note" not in today
    assert tomorrow["note"] == f'In the recommendation text, "today" means {tomorrow["day"]}.'
    assert (
        "-" in today["summary"]["battery_max_at"] or today["summary"]["battery_max_at"] == "00:00"
    )
    assert _max_hour(15) == "14:00-15:00" and _max_hour(0) == "00:00"


def test_weather_labels_in_every_language() -> None:
    assert set(WEATHER) == set(LANGUAGES)
    assert all(set(labels) == {"sunny", "mixed", "cloudy"} for labels in WEATHER.values())
    assert WEATHER["fr"]["mixed"] == "journée mitigée"
