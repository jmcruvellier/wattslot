"""Serveur MCP de l'application (lots 6.1 et 6.2) : un vrai client MCP du SDK liste les outils
et les appelle sur des plans de référence ; ``/mcp`` répond en HTTP ; en mode extension, seul HA
Core l'appelle hors de l'ingress ; dépôt d'une demande ; budget de tokens ; prompts conseillés."""

import asyncio
import json
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
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
from wattslot import configuration, home_model
from wattslot.assistant.prompts import prompt
from wattslot.assistant.tools import (
    PENDING_FOR,
    WEATHER,
    _energy_texts,
    _max_hour,
    _next_action,
    _power_now,
    _price_ranges,
    _summary,
    _when,
    clock,
    day_of,
    find_name,
    get_current_status,
    get_tariff,
    measured_energy,
    plan_text,
    problem_text,
)
from wattslot.battery_settings import BatterySettings
from wattslot.configuration import Behavior, Configuration, DeviceSettings
from wattslot.detection import DeviceKind, Role
from wattslot.home_assistant import ConnectionState
from wattslot.home_model import HomeDevice, HomeModel, HomeSensor, Phase, Supply
from wattslot.ingress import HOME_ASSISTANT_CORE_ADDRESS
from wattslot.languages import LANGUAGES
from wattslot.main import create_app
from wattslot.planning.explain import catalog
from wattslot.planning.store import PlanStore
from wattslot.planning.warning_texts import long_date
from wattslot.runtime import RunMode, Settings
from wattslot.storage.database import open_database
from wattslot.storage.graph import GraphStore
from wattslot.tariff import V1, ColorPrices, PriceBand, Tariff, TariffKind
from wattslot.views.now import NextAction, OtherStart

READ_TOOLS = {
    "get_day_plan",
    "explain_device",
    "get_week",
    "get_current_status",
    "get_energy",
    "get_forecast",
    "get_home",
    "get_problems",
    "get_tariff",
    "get_requests",
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
    tomorrow["indicateurs"] = {
        "cout_eur": 1.23,
        "soutirage_kwh": 4.5,
        "injection_kwh": 0.7,
        "autoconsommation_pct": 82.4,
    }
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


def test_the_client_lists_ten_read_only_tools_and_one_action(api: TestClient) -> None:
    async def run() -> Any:
        async with Client(api.app.state.mcp) as client:  # type: ignore[attr-defined]
            return (await client.list_tools()).tools

    tools = {t.name: t for t in asyncio.run(run())}
    assert set(tools) == TOOLS
    assert all(tools[n].annotations.read_only_hint for n in READ_TOOLS)
    action = tools["request_device"].annotations
    assert action is not None and not action.read_only_hint and not action.destructive_hint
    assert all(t.description and len(t.description) < 240 for t in tools.values())  # courtes


def test_day_plan_and_week(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _call(api, "get_day_plan", {"day": "today"})
    assert plan["day"] == long_date(date(2025, 10, 15), "fr")  # en toutes lettres
    assert "Lave-linge : 11h" in plan["recommendation"]  # en français, la langue réglée
    assert plan["summary"]["production_kwh"] > 0
    # La batterie en phrase : « battery_end_of_day_percent » était lu « se charge à 12 % ».
    assert plan["summary"]["battery"].startswith(
        ("La batterie monte au plus à ", "La batterie part de ")
    )
    assert not any(k.startswith("battery_") for k in plan["summary"])
    assert "next_appliance" in plan  # selon l'heure : le prochain appareil, ou aucun
    # « Combien va me coûter la journée ? » : le coût, écrit dans la devise de la maison.
    tomorrow = _call(api, "get_day_plan", {"day": "tomorrow"})["summary"]
    assert tomorrow["cost"] == "1,23\u00a0€" and tomorrow["self_consumption_percent"] == 82
    assert "co2_kg" not in tomorrow
    assert _call(api, "get_day_plan", {"day": "yesterday"})["error"] == "no_plan"

    # À partir de demain : avec aujourd'hui en tête, « le reste de la semaine » le comptait.
    _, days = horizon_of(2)
    first = days[0]["date_cible"]
    monkeypatch.setattr("wattslot.assistant.tools.today_of", lambda _: first)
    week = _call(api, "get_week")
    assert week["today"] == long_date(first, "fr")
    # Demain avec sa date : « demain » seul faisait deviner un faux jour de la semaine.
    assert [d["when"] for d in week["days"]] == [
        f"demain, {long_date(days[1]['date_cible'], 'fr')}"
    ]
    assert week["days"][0]["production_kwh"] > 0
    assert (
        week["forecast_end"]
        == f"Pas de prévision au-delà du {long_date(days[1]['date_cible'], 'fr')}."
    )
    assert all(d.get("weather", "journée").startswith("journée") for d in week["days"])
    # La batterie en phrase : « battery_end_of_day_percent » était lu « se charge à 12 % ».
    battery = [d["battery"] for d in week["days"] if "battery" in d]
    assert battery and all(b.startswith("La batterie finit la journée à ") for b in battery)
    assert all(not k.startswith("battery_") for d in week["days"] for k in d)

    # Prévision d'une date : la journée après demain, la fin des prévisions au-delà.
    monkeypatch.setattr("wattslot.assistant.tools.today_of", lambda _: first - timedelta(days=2))
    third = _call(api, "get_forecast", {"day": days[1]["date_cible"].isoformat()})
    assert third["day"] == long_date(days[1]["date_cible"], "fr") and "hourly_kwh" not in third
    assert third["production_kwh"] > 0
    far = _call(api, "get_forecast", {"day": (first + timedelta(days=10)).isoformat()})
    assert "production_kwh" not in far and far["forecast_end"] == week["forecast_end"]
    # Une date passée : la date du jour et la fin de la prévision (« dans 10 jours » demandé
    # avec une année fausse).
    past = _call(api, "get_forecast", {"day": "2001-01-01"})
    assert past["error"] == "invalid_date"
    assert f"today is {(first - timedelta(days=2)).isoformat()}" in past["hint"]
    assert past["forecast_end"] == week["forecast_end"]
    assert _call(api, "get_forecast", {"day": "lundi"})["error"] == "invalid_date"
    # Un nombre de jours à partir d'aujourd'hui : « dans 10 jours » sans connaître la date.
    ahead = (days[1]["date_cible"] - (first - timedelta(days=2))).days
    assert _call(api, "get_forecast", {"day": str(ahead)})["day"] == third["day"]
    assert _call(api, "get_forecast", {"day": "+12"})["forecast_end"] == week["forecast_end"]
    assert (
        _call(api, "get_forecast", {"day": "0"})["day"]
        == _call(api, "get_forecast", {"day": "today"})["day"]
    )


def test_days_of_the_week_in_words() -> None:
    today = date(2026, 11, 4)
    assert _when(today, today, "fr") == "aujourd'hui"
    assert _when(date(2026, 11, 5), today, "en") == "tomorrow"
    assert _when(date(2026, 11, 6), today, "fr") == "Vendredi 6 Novembre 2026"


def test_the_battery_of_the_home_in_words(api: TestClient) -> None:
    """« 5.12 », « floor_percent: 12.0 » se lisaient « 12.0 % d'espace »."""
    battery = HomeModel(
        devices=[
            HomeDevice(
                key="battery",
                kind=DeviceKind.BATTERY,
                name="Batterie",
                capacity_kwh=5.12,
                sensors=[HomeSensor(entity_id="sensor.soc", role=Role.STATE_OF_CHARGE)],
            )
        ]
    )
    home_model.save(api.app.state.graph, battery)  # type: ignore[attr-defined]
    home = _call(api, "get_home")
    assert "planned" not in home and "not_planned" not in home  # lus « prévus aujourd'hui »
    assert home["about"].startswith("Équipements de la maison, pas le plan du jour")
    (found,) = home["batteries"]
    assert found["capacity"] == "5,12\u00a0kWh" and found["never_below"].endswith("\u00a0%")
    assert "other_loads" not in home  # aucune autre charge mesurée


def test_the_other_loads_of_the_home_are_counted() -> None:
    """Liste souvent longue, recopiée en entier : un nombre seulement."""
    assert catalog("fr")["assistant.other_loads"].format(count=12) == (
        "Autres appareils mesurés : 12"
    )


def test_the_plan_text_leaves_the_figures_to_the_summary() -> None:
    """« Bilan prévu : 0,99 € » (le plan au moment du calcul) à côté du coût de la journée
    entière : les modèles prenaient l'un pour l'autre ; la batterie en kWh, de même."""
    text = "\n".join(
        [
            "Objectif : le coût le plus bas.",
            "",
            "Équipements à lancer aujourd'hui :",
            "- Lave-linge : 11h-12h10 (0,90 kWh).",
            "",
            "Batterie : 0,63 kWh au départ, maximum prévu 2,19 kWh vers 11 h, 0,61 kWh en fin de "
            "journée. Recharge au soleil.",
            "Filtration : à l'arrêt toute la journée.",
            "",
            "Bilan prévu : 0,99 € et 2,1 kWh soutirés. Autoconsommation : 99 %.",
        ]
    )
    found = plan_text(text, "fr")
    assert found is not None and "Lave-linge : 11h-12h10" in found
    assert "Filtration" in found and "Bilan" not in found and "Batterie :" not in found
    assert "\n\n\n" not in found and plan_text(None, "fr") is None


def test_no_appliance_left_today_is_a_sentence(api: TestClient) -> None:
    """Plus rien aujourd'hui : une phrase plutôt que « null », et le prochain jour prévu."""
    plan = _call(api, "get_day_plan", {"day": "today"})
    if isinstance(plan["next_appliance"], str):
        assert plan["next_appliance"] == "Plus aucun appareil à lancer aujourd'hui."


def test_explain_device_finds_it_without_accents_or_dashes(api: TestClient) -> None:
    found = _call(api, "explain_device", {"device": "seche linge"})
    assert found["device"] == "Sèche-linge"
    assert found["planned"][0]["start"] == "12:10"
    assert found["status"].endswith(".") and "_" not in found["status"]  # une phrase, pas un code
    # « Et l'autre appareil ? » : les autres appareils du jour, ici le lave-linge.
    others = [o["device"] for o in found["other_appliances_this_day"]]
    assert "Lave-linge" in others and "Sèche-linge" not in others
    unknown = _call(api, "explain_device", {"device": "voiture"})
    assert unknown["error"] == "unknown_device" and "ask the user" in unknown["hint"]
    assert "Lave-linge" in [o["device"] for o in unknown["appliances_this_day"]]


def test_energy_forecast_home_status_and_problems(api: TestClient) -> None:
    # Sans HA, pas d'agrégats : seulement ce que prévoyait le plan de ce jour.
    # Rien de mesuré : dit en toutes lettres, et le plan en phrase, « prévu » collé aux chiffres.
    energy = _call(api, "get_energy", {"day": "2025-10-15"})
    assert energy["measured"] == "Aucune mesure pour ce jour."
    assert energy["planned"].startswith("Prévu sur la journée, rien de mesuré : consommation ")
    assert {"Lave-linge", "Sèche-linge"} <= set(energy["planned_appliances_kwh"])
    assert all(v.endswith("\u00a0kWh") for v in energy["planned_appliances_kwh"].values())
    assert _call(api, "get_energy", {"day": "2026-10-01"})["error"] == "no_data"
    assert _call(api, "get_energy", {"day": "hier"})["error"] == "invalid_date"
    assert _call(api, "get_energy", {"day": "2099-01-01"})["error"] == "invalid_date"

    forecast = _call(api, "get_forecast", {"day": "tomorrow"})
    assert forecast["production_kwh"] > 0 and "12:00" in forecast["hourly_kwh"]
    # Le résumé en phrase avant le détail : total, heures de production, heure du maximum.
    first = min(forecast["hourly_kwh"])
    peak = max(forecast["hourly_kwh"], key=forecast["hourly_kwh"].get)
    total = f"{forecast['production_kwh']:.1f}".replace(".", ",")
    assert forecast["summary"].startswith(f"Production prévue : {total} kWh, de {first} à ")
    assert f"pic entre {peak} et " in forecast["summary"]
    assert list(forecast)[:2] == ["day", "summary"]

    home = _call(api, "get_home")
    assert home["objective"] == "le coût le plus bas" and home["tariff"] == "prix unique"

    assert _call(api, "get_current_status")["error"] == "not_connected"  # pas de HA en test
    # En phrases, avec la gravité et le geste à faire : plus de codes à recopier.
    problems = _call(api, "get_problems")["problems"]
    assert problems[0] == {
        "severity": "Bloque le plan",
        "problem": "L'application ne connaît pas l'adresse de Home Assistant.",
        "what_to_do": "Extension : redémarrez-la. Docker : renseignez l'adresse de Home "
        "Assistant et un jeton d'accès longue durée.",
    }


def test_problems_read_as_on_the_diagnostic_screen() -> None:
    assert problem_text(
        "sensor_silent",
        {"device": "Lave-linge", "role": "PowerConsumed", "entity": "sensor.washer"},
        "fr",
    ) == (
        "Lave-linge : le capteur « Puissance consommée » (sensor.washer) n'a rien envoyé "
        "depuis un jour."
    )
    assert problem_text("ha_disconnected", {"error_code": "token_refused"}, "en").startswith(
        "Home Assistant does not respond. Home Assistant refuses"
    )
    assert problem_text("internal_error", {"component": "planning", "error": "x"}, "fr") == (
        "Erreur dans le calcul du plan : x"
    )
    assert problem_text(
        "configuration_issue", {"issue": "duplicate_device", "device": "Lave-linge"}, "fr"
    ) == ("Lave-linge : réglé deux fois.")
    assert problem_text("backup_space", {"free": "5.0", "needed": "6.0"}, "fr") == (
        "Plus que 5,0 Go libres sur le disque des données : une sauvegarde de WattSlot demande "
        "environ 6,0 Go et risque d'échouer."
    )
    assert problem_text("memory_heavy", {"used": "1100"}, "en").startswith(
        "WattSlot has been using 1100 MB of memory"
    )
    assert "18 Octobre 2026" in problem_text(
        "impossible_data_unknown",
        {"day": "2026-10-18", "hour": "19", "kwh": "12.4", "limit": "9.0"},
        "fr",
    )


def test_the_problem_texts_are_those_of_the_interface() -> None:
    """Copiés des catalogues de l'interface (écran Diagnostic) : ils doivent rester les mêmes."""
    sections = {
        ("problems", "code"): "problem.code",
        ("problems", "action"): "problem.action",
        ("problems", "severity"): "problem.severity",
        ("problems", "component"): "problem.component",
        ("problems", "hour"): "problem.hour",
        ("problems", "none"): "problem.none",
        ("role",): "problem.role",
        ("issue",): "problem.issue",
        ("configuration", "issue"): "problem.configuration_issue",
        ("connection_error",): "problem.connection_error",
    }
    interface = Path(__file__).parents[2] / "frontend/src/i18n/catalogs"
    for lang in LANGUAGES:
        ui = json.loads((interface / f"{lang}.json").read_text(encoding="utf-8"))
        server = catalog(lang)
        expected: dict[str, str] = {}
        for source, prefix in sections.items():
            value: Any = ui
            for part in source:
                value = value[part]
            if isinstance(value, str):
                expected[prefix] = value
            else:
                expected.update({f"{prefix}.{k}": v for k, v in value.items()})
        copied = {k: v for k, v in server.items() if k.startswith("problem.")}
        assert copied == expected, lang


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


def _request(api: TestClient, arguments: dict[str, Any]) -> dict[str, Any]:
    """Demande confirmée : la question d'abord, puis le même appel confirmé."""
    _call(api, "request_device", arguments)
    return _call(api, "request_device", {**arguments, "confirm": True})


def test_request_device_asks_first_then_files_once_confirmed(api: TestClient) -> None:
    """« Fais tourner le lave-linge avant demain soir » : rien n'est déposé sans la question
    d'abord ; les modèles essayés déposaient la demande sans rien demander, puis montraient le
    code rendu avec la question."""
    home_model.save(api.app.state.graph, HOME)  # type: ignore[attr-defined]
    refused = _call(api, "request_device", {"device": "Lave-linge", "confirm": True})
    assert refused["error"] == "not_asked"  # confirmé sans question
    asked = _call(api, "request_device", {"device": "lave linge", "latest_date": "2099-01-31"})
    assert asked["filed"] is False and asked["device"] == "Lave-linge"
    assert asked["question"].startswith("Faire tourner « Lave-linge »")  # langue réglée
    assert "2099" in asked["question"] and "confirm_code" not in asked
    # La question vaut pour cette date limite seulement.
    other = _call(api, "request_device", {"device": "Lave-linge", "confirm": True})
    assert other["error"] == "not_asked"
    assert api.get("/api/requests").json() == []

    confirmed = {"device": "Lave-linge", "latest_date": "2099-01-31", "confirm": True}
    filed = _call(api, "request_device", confirmed)
    assert filed["filed"] is True and filed["status"] == "open"
    assert filed["latest_date"] == "2099-01-31"
    # Une question, une demande : la confirmer de nouveau demande une nouvelle question.
    assert _call(api, "request_device", confirmed)["error"] == "not_asked"


def test_a_question_is_worth_confirmation_for_ten_minutes(api: TestClient) -> None:
    home_model.save(api.app.state.graph, HOME)  # type: ignore[attr-defined]
    _call(api, "request_device", {"device": "Lave-linge"})
    pending = api.app.state.assistant_pending  # type: ignore[attr-defined]
    for key in pending:
        pending[key] -= PENDING_FOR + timedelta(seconds=1)
    late = _call(api, "request_device", {"device": "Lave-linge", "confirm": True})
    assert late["error"] == "not_asked" and api.get("/api/requests").json() == []


def test_request_device_files_a_request_like_my_requests(api: TestClient) -> None:
    home_model.save(api.app.state.graph, HOME)  # type: ignore[attr-defined]
    asked = _request(api, {"device": "lave linge"})
    assert asked["device"] == "Lave-linge" and asked["latest_date"] is None
    later = _request(api, {"device": "Lave-linge", "latest_date": "2099-01-31"})
    assert later["latest_date"] == "2099-01-31"
    opened = [r for r in api.get("/api/requests").json() if r["status"] == "open"]
    assert len(opened) == 1 and opened[0]["latest"] == "2099-01-31"  # une seule, redatée

    unknown = _call(api, "request_device", {"device": "voiture"})
    assert unknown["error"] == "unknown_device" and "Lave-linge" in unknown["devices"]
    for wrong in ("demain", "2001-01-01"):
        found = _call(api, "request_device", {"device": "Lave-linge", "latest_date": wrong})
        assert found["error"] == "invalid_date" and "today is 20" in found["hint"]


def test_request_device_understands_today_and_tomorrow(api: TestClient) -> None:
    """« Avant demain soir » : les modèles passent « tomorrow » sans connaître la date."""
    home_model.save(api.app.state.graph, HOME)  # type: ignore[attr-defined]
    today = date.fromisoformat(
        _call(api, "request_device", {"device": "Lave-linge", "latest_date": "today"})[
            "latest_date"
        ]
    )
    found = _call(api, "request_device", {"device": "Lave-linge", "latest_date": "Tomorrow"})
    assert found["latest_date"] == (today + timedelta(days=1)).isoformat()
    assert "Ask the user this question" in found["next"]


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
        "bought_from_grid_kwh": 2.0,
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

    assert washer["device"] == "Lave-linge" and "scheduled" not in washer
    assert {o["device"] for o in washer["other_appliances_this_day"]} == {
        "Chauffe-eau",
        "Piscine (filtration)",
    }
    assert washer["next_planned"] == {
        "day": "Jeudi 15 Octobre 2026",
        "start": "11:00",
        "end": "12:10",
    }
    # Dans la langue réglée et sans nom d'outil : les modèles recopiaient « request_device ».
    assert washer["reason"].startswith("Pas prévu ce jour-là")
    assert washer["hint"].startswith("Il peut être demandé") and "_" not in washer["hint"]
    assert "scheduled" not in dishwasher and "next_planned" not in dishwasher
    # Appareil inconnu (« l'autre appareil ») : ceux qui tournent ce jour-là, sans la batterie.
    assert unknown["error"] == "unknown_device"
    assert {o["device"] for o in unknown["appliances_this_day"]} == {
        "Chauffe-eau",
        "Piscine (filtration)",
    }


def test_other_days_say_what_today_means_and_the_maximum_is_an_hour_range(api: TestClient) -> None:
    today = _call(api, "get_day_plan", {"day": "today"})
    tomorrow = _call(api, "get_day_plan", {"day": "tomorrow"})
    assert "note" not in today and "note" not in tomorrow
    battery = today["summary"]["battery"]
    assert "(" not in battery if battery.startswith("La batterie part de ") else "-" in battery
    assert _max_hour(15) == "14:00-15:00" and _max_hour(0) == "00:00"


def test_weather_labels_in_every_language() -> None:
    assert set(WEATHER) == set(LANGUAGES)
    assert all(set(labels) == {"sunny", "mixed", "cloudy"} for labels in WEATHER.values())
    assert WEATHER["fr"]["mixed"] == "journée mitigée"


def test_the_next_appliance_and_its_other_starts() -> None:
    """« Quel est le prochain appareil à lancer ? » : heure, explication, autres départs avec
    leur écart de coût."""
    action = NextAction(
        device="Lave-linge",
        start_min=660,
        end_min=730,
        explanation="Au soleil.",
        alternatives=[
            OtherStart(start_min=780, end_min=850, cost_eur_delta=0.12, import_kwh_delta=0.5)
        ],
    )
    found = _next_action(SimpleNamespace(next_action=action), "fr")  # type: ignore[arg-type]
    assert found == {
        "device": "Lave-linge",
        "start": "11:00",
        "end": "12:10",
        "why": "Au soleil.",
        "other_starts": [{"start": "13:00", "extra_cost": "+0,12\u00a0€"}],
    }
    assert _next_action(SimpleNamespace(next_action=None), "fr") is None  # type: ignore[arg-type]


def test_requests_list_like_my_requests(api: TestClient) -> None:
    """« Quelles sont mes demandes en cours ? »"""
    # Aucune ouverte : une phrase, et non une liste où les closes passaient pour « en cours ».
    assert _call(api, "get_requests") == {"open": "Aucune demande en cours."}
    home_model.save(api.app.state.graph, HOME)  # type: ignore[attr-defined]
    _request(api, {"device": "lave vaisselle", "latest_date": "2099-01-31"})
    (found,) = _call(api, "get_requests")["open"]
    assert found["device"] == "Lave-vaisselle" and "status" not in found
    assert found["latest_date"] == "Samedi 31 Janvier 2099" and "launched_on" not in found
    assert found["asked_on"] == "aujourd'hui"  # en mots

    (opened,) = api.get("/api/requests").json()
    assert api.delete(f"/api/requests/{opened['id']}").status_code < 300
    listed = _call(api, "get_requests")
    assert listed["open"] == "Aucune demande en cours."
    (closed,) = listed["closed_this_week"]
    assert closed["device"] == "Lave-vaisselle" and closed["status"] == "annulée"


def test_tariff_of_the_home_without_home_assistant(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """« Quand sont les heures creuses aujourd'hui ? » : plages de prix réunies, heures
    creuses ; sans tarif configuré, un prix unique et aucune heure creuse."""
    single = _call(api, "get_tariff")
    assert single["tariff"] == "prix unique" and single["off_peak"] == []
    assert single["prices"] == [{"start": "00:00", "end": "00:00", "price": "0,250\u00a0€/kWh"}]

    monkeypatch.setattr("wattslot.configuration.tariff_of", lambda _: V1)
    found = _call(api, "get_tariff", {"day": "tomorrow"})
    assert found["tariff"] == "heures pleines et heures creuses"
    assert found["off_peak"] == [
        {"start": "00:00", "end": "06:00"},
        {"start": "22:00", "end": "00:00"},
    ]
    assert [(p["price"], p["period"]) for p in found["prices"]] == [
        ("0,210\u00a0€/kWh", "heures creuses"),
        ("0,270\u00a0€/kWh", "heures pleines"),
        ("0,210\u00a0€/kWh", "heures creuses"),
    ]
    assert "export_prices" not in found


def test_assistant_tariff_uses_weighted_minute_bands(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    tariff = Tariff(
        kind=TariffKind.TIME_OF_USE,
        base_eur_kwh=0.30,
        bands=[PriceBand(start_hour=1, start_minute=30, end_hour=5, end_minute=38, eur_kwh=0.12)],
    )
    monkeypatch.setattr("wattslot.configuration.tariff_of", lambda _: tariff)
    found = _call(api, "get_tariff")
    assert [(p["start"], p["end"], p["price"], p["period"]) for p in found["prices"]] == [
        ("00:00", "01:00", "0,300\u00a0€/kWh", "heures pleines"),
        ("01:00", "02:00", "0,210\u00a0€/kWh", "heures creuses"),
        ("02:00", "05:00", "0,120\u00a0€/kWh", "heures creuses"),
        ("05:00", "06:00", "0,186\u00a0€/kWh", "heures creuses"),
        ("06:00", "00:00", "0,300\u00a0€/kWh", "heures pleines"),
    ]
    assert found["off_peak"] == [{"start": "01:00", "end": "06:00"}]


class FakeHomeAssistant:
    """Client de HA connecté qui rend la couleur Tempo du jour et du lendemain."""

    status = SimpleNamespace(state=ConnectionState.CONNECTED)

    async def command(self, command: str, **params: Any) -> Any:
        assert command == "get_states"
        return [
            {"entity_id": "sensor.color_today", "state": "Rouge"},
            {"entity_id": "sensor.color_tomorrow", "state": "unknown"},
        ]


def test_the_color_of_the_day_comes_from_home_assistant(tmp_path: Path) -> None:
    """« Quelle est la couleur Tempo demain ? » : couleur lue dans HA comme pour le calcul ;
    pas encore annoncée, les prix par défaut et une note."""
    tempo = Tariff(
        kind=TariffKind.DAY_COLOR,
        base_eur_kwh=0.2,
        colors=[
            ColorPrices(color="Bleu", base_eur_kwh=0.16),
            ColorPrices(
                color="Rouge",
                base_eur_kwh=0.75,
                bands=[PriceBand(start_hour=0, end_hour=6, eur_kwh=0.15)],
            ),
        ],
        color_entity="sensor.color_today",
        color_tomorrow_entity="sensor.color_tomorrow",
    )
    graph = GraphStore(tmp_path)
    home_model.load_vocabulary(graph)
    state = SimpleNamespace(
        graph=graph,
        database=open_database(tmp_path),
        raw=SimpleNamespace(zone=ZoneInfo("Europe/Paris")),
        home_assistant=FakeHomeAssistant(),
    )
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("wattslot.configuration.tariff_of", lambda _: tempo)
        today = asyncio.run(get_tariff(state, "today"))
        tomorrow = asyncio.run(get_tariff(state, "tomorrow"))
    assert today["color"] == "Rouge" and "note" not in today
    assert today["prices"][0] == {
        "start": "00:00",
        "end": "06:00",
        "price": "0,150\u00a0€/kWh",
        "period": "heures creuses",
    }
    assert today["off_peak"] == [{"start": "00:00", "end": "06:00"}]
    assert tomorrow["color"] is None and "not announced" in tomorrow["note"]
    graph.flush()


def test_current_status_says_what_powers_the_home(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """« Qu'est-ce qui alimente la maison en ce moment ? » : la phrase « En ce moment »."""
    now = SimpleNamespace(sentence="La batterie alimente la maison", off_peak=False)

    async def today(*args: Any) -> Any:
        return SimpleNamespace(now=now)

    monkeypatch.setattr("wattslot.assistant.tools.day_view_of", today)
    app = api.app.state  # type: ignore[attr-defined]
    moment = datetime.now(UTC)

    def entity(name: str, role: Role, value: float, age_h: float = 0.1) -> Any:
        return SimpleNamespace(
            entity_id=f"sensor.{name}",
            role=role,
            last_value=value,
            last_time=moment - timedelta(hours=age_h),
        )

    entities = [
        entity("soc", Role.STATE_OF_CHARGE, 41.6, age_h=9),  # stable : toujours valable
        entity("pv1", Role.POWER_PRODUCED, 800.4),
        entity("pv2", Role.POWER_PRODUCED, 200),
        entity("pv_night", Role.POWER_PRODUCED, 999, age_h=5),  # figé : écarté
        entity("oven", Role.POWER_CONSUMED, 2100),
        entity("tv", Role.POWER_CONSUMED, 4),  # veille
    ]
    ingestor = SimpleNamespace(status=lambda: SimpleNamespace(entities=entities))
    state = SimpleNamespace(
        graph=app.graph,
        database=app.database,
        ingestor=ingestor,
        raw=SimpleNamespace(zone=ZoneInfo("Europe/Paris")),
    )
    found = asyncio.run(get_current_status(state))
    assert found["now"] == "La batterie alimente la maison" and found["off_peak"] is False
    assert found["battery_percent"] == 42 and found["solar_power_w"] == 1000
    assert found["appliances_on"] == [{"device": "sensor.oven", "power_w": 2100}]
    local = (moment - timedelta(hours=0.1)).astimezone(ZoneInfo("Europe/Paris"))
    assert found["measured_at"] == local.strftime("%H:%M")  # heure locale


def test_power_now_says_whether_the_appliance_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    """« Pourquoi le chauffe-eau tourne ? » : en marche ou à l'arrêt, d'après sa puissance."""
    home = HomeModel(
        devices=[
            HomeDevice(
                key=key,
                kind=DeviceKind.WATER_HEATER,
                name=name,
                sensors=[HomeSensor(entity_id=f"sensor.{key}", role=Role.POWER_CONSUMED)],
            )
            for key, name in (("heater", "Chauffe-eau"), ("idle", "Ballon"), ("old", "Cumulus"))
        ]
        + [HomeDevice(key="pool", kind=DeviceKind.POOL_PUMP, name="Piscine", sensors=[])]
    )
    monkeypatch.setattr("wattslot.assistant.tools.home_model.load", lambda _: home)
    monkeypatch.setattr("wattslot.assistant.tools.language", lambda _: "fr")
    moment = datetime.now(UTC)

    def entity(name: str, value: float, age_h: float = 0.1) -> Any:
        return SimpleNamespace(
            entity_id=f"sensor.{name}",
            role=Role.POWER_CONSUMED,
            last_value=value,
            last_time=moment - timedelta(hours=age_h),
        )

    entities = [entity("heater", 1800.4), entity("idle", 3), entity("old", 2000, age_h=5)]
    ingestor = SimpleNamespace(status=lambda: SimpleNamespace(entities=entities))
    state = SimpleNamespace(graph=None, ingestor=ingestor)
    assert _power_now(state, "chauffe eau") == "En ce moment : en marche (1800 W)."
    assert _power_now(state, "Ballon") == "En ce moment : à l'arrêt."  # veille
    assert _power_now(state, "Cumulus") == "En ce moment : à l'arrêt."  # relevé figé
    assert _power_now(state, "Piscine") is None  # sans capteur de puissance
    assert _power_now(SimpleNamespace(graph=None, ingestor=None), "Chauffe-eau") is None


def test_dynamic_prices_have_no_peak_hours() -> None:
    """Prix dynamiques : des heures moins chères, pas des heures creuses ; aucune étiquette."""
    prices = {hour: 0.10 + hour / 100 for hour in range(24)}
    assert all("period" not in p for p in _price_ranges(prices, "fr"))
    assert _price_ranges(prices, "fr", periods=True)[-1]["period"] == "heures pleines"


def test_energy_texts_follow_the_language() -> None:
    """« 0,89 kWh » en français : avec le nombre brut, les modèles recopiaient « 0.89 kWh »."""
    values = {"production_kwh": 0.89, "devices": {"Lave-linge": 1.5}}
    assert _energy_texts(values, "fr") == {
        "production_kwh": "0,89\u00a0kWh",
        "devices": {"Lave-linge": "1,50\u00a0kWh"},
    }
    assert _energy_texts(values, "en")["production_kwh"] == "0.89\u00a0kWh"


@pytest.mark.parametrize(
    ("hour", "expected"),
    [
        (
            12,
            "La batterie monte au plus à 90\u00a0% (11:00-12:00) et finit la journée à 20\u00a0%.",
        ),
        # Au plus haut dès minuit : elle ne monte pas, elle part de ce niveau.
        (0, "La batterie part de 90\u00a0% et finit la journée à 20\u00a0%."),
    ],
)
def test_battery_of_the_day_in_a_sentence(hour: int, expected: str) -> None:
    summary = SimpleNamespace(
        production_kwh=1.0,
        grid_import_kwh=2.0,
        grid_export_kwh=0.0,
        soc_max_percent=90.0,
        soc_max_hour=hour,
        soc_end_percent=20.0,
    )
    view = SimpleNamespace(summary=summary, battery_capacity_kwh=5.0, indicators=None)
    assert _summary(view, "fr")["battery"] == expected  # type: ignore[arg-type]


# --- Plusieurs batteries, maison en triphasé -------------------------------------------------


def _three_phase_home() -> HomeModel:
    def battery(key: str, name: str, capacity: float, phase: Phase) -> HomeDevice:
        return HomeDevice(
            key=key,
            kind=DeviceKind.BATTERY,
            name=name,
            capacity_kwh=capacity,
            phase=phase,
            sensors=[HomeSensor(entity_id=f"sensor.{key}_soc", role=Role.STATE_OF_CHARGE)],
        )

    return HomeModel(
        supply=Supply.THREE,
        meter_sums_phases=False,
        devices=[
            battery("small", "Petite batterie", 2.0, Phase.L2),
            battery("large", "Grande batterie", 6.0, Phase.L3),
            HomeDevice(
                key="heater",
                kind=DeviceKind.WATER_HEATER,
                name="Chauffe-eau",
                phase=Phase.ALL,
                sensors=[],
            ),
            HomeDevice(
                key="washer", kind=DeviceKind.WASHING_MACHINE, name="Lave-linge", sensors=[]
            ),
            HomeDevice(
                key="tv", kind=DeviceKind.OTHER_LOAD, name="Télé", phase=Phase.L1, sensors=[]
            ),
        ],
    )


def test_the_home_says_its_phases_and_each_battery(api: TestClient) -> None:
    graph = api.app.state.graph  # type: ignore[attr-defined]
    home_model.save(graph, _three_phase_home())
    configuration.save(
        graph,
        Configuration(
            tariff=Tariff(base_eur_kwh=0.2, contract_kva=12.0),
            battery=BatterySettings(floor_percent=10),
            devices=[
                DeviceSettings(
                    key="small",
                    behavior=Behavior.STORAGE,
                    battery=BatterySettings(floor_percent=30),
                )
            ],
        ),
    )

    home = _call(api, "get_home")

    # Chaque batterie avec son propre plancher : les réglages de la petite, ceux de la maison
    # pour la grande.
    by_name = {battery["name"]: battery for battery in home["batteries"]}
    assert by_name["Petite batterie"]["never_below"] == "30\u00a0%"
    assert by_name["Grande batterie"]["never_below"] == "10\u00a0%"
    assert home["grid_connection"] == {
        "supply": "triphasé",
        "meter": "le compteur compte chaque phase à part",
        "limit": "4,0 kVA par phase",
    }
    # La phase de ce que le calcul place ou simule ; pas celle d'une charge seulement mesurée,
    # ni d'un équipement dont la phase n'est pas renseignée.
    assert home["connected_to"] == {
        "Petite batterie": "phase 2",
        "Grande batterie": "phase 3",
        "Chauffe-eau": "les trois phases",
    }


def test_a_single_phase_home_says_nothing_about_phases(api: TestClient) -> None:
    single = _three_phase_home().model_copy(update={"supply": Supply.SINGLE})
    home_model.save(api.app.state.graph, single)  # type: ignore[attr-defined]

    home = _call(api, "get_home")

    assert "grid_connection" not in home and "connected_to" not in home


def test_the_charge_now_weighs_each_battery(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """2 kWh à 40 % et 6 kWh à 80 % : 70 %, pas la moyenne simple de 60 %."""

    async def today(*_: Any, **__: Any) -> None:
        return None

    monkeypatch.setattr("wattslot.assistant.tools.day_view_of", today)
    app = api.app.state  # type: ignore[attr-defined]
    home_model.save(app.graph, _three_phase_home())
    moment = datetime.now(UTC)
    entities = [
        SimpleNamespace(
            entity_id=f"sensor.{key}_soc",
            role=Role.STATE_OF_CHARGE,
            last_value=value,
            last_time=moment,
        )
        for key, value in (("small", 40.0), ("large", 80.0), ("unknown", 10.0))
    ]
    state = SimpleNamespace(
        graph=app.graph,
        database=app.database,
        ingestor=SimpleNamespace(status=lambda: SimpleNamespace(entities=entities)),
        raw=SimpleNamespace(zone=ZoneInfo("Europe/Paris")),
    )

    found = asyncio.run(get_current_status(state))

    assert found["battery_percent"] == 70
    assert found["batteries"] == [
        {"name": "Grande batterie", "charge": "80\u00a0%"},
        {"name": "Petite batterie", "charge": "40\u00a0%"},
    ]
