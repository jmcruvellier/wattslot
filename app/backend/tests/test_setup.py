"""Mise en route (lot 4.1) : étapes vers un premier plan, calculées par l'application."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from tests.planning.test_open_meteo import response
from tests.test_detection_phases import _three_phase_snapshot
from tests.test_health import _settings
from wattslot import configuration, home_model, notifications, profiles
from wattslot.aggregation import Aggregator
from wattslot.configuration import Automation, Behavior, Configuration, DeviceSettings
from wattslot.detection import DeviceKind, Role
from wattslot.home_assistant import ConnectionState, HomeAssistantClient, HomeSnapshot
from wattslot.main import create_app
from wattslot.notifications import NotificationSettings, Rule
from wattslot.planning import open_meteo
from wattslot.planning.sources import PlanningSettings, save_settings
from wattslot.planning.store import PlanStore
from wattslot.setup import Setup, StepState, setup_status
from wattslot.solar_panels import PanelArray, SolarPanels
from wattslot.storage.database import open_database
from wattslot.storage.graph import GraphStore

PARIS = ZoneInfo("Europe/Paris")
REFERENCE = profiles.load("reference")


def states(found: Setup) -> dict[str, str]:
    return {step.key: step.state.value for step in found.steps}


class Client:
    """Client de HA connecté, avec ou sans tableau Énergie et prévision."""

    def __init__(self, dashboard: bool = True, forecast: bool = True) -> None:
        sources = [{"type": "solar", "stat_energy_from": "sensor.pv"}] if dashboard else []
        self.status = SimpleNamespace(state=ConnectionState.CONNECTED, error=None, error_code=None)
        self.snapshot = HomeSnapshot(energy_preferences={"energy_sources": sources})
        self.forecast = forecast

    async def command(self, command: str, **_: Any) -> Any:
        if command == "energy/solar_forecast" and self.forecast:
            today = (
                datetime.now(UTC).astimezone(PARIS).date()
            )  # midi local, quelle que soit l'heure
            noon = datetime(today.year, today.month, today.day, 12, tzinfo=PARIS)
            return {"1": {"wh_hours": {noon.isoformat(): 500}}}
        return {} if command == "energy/solar_forecast" else []


def aggregator(pending: list[str]) -> Aggregator:
    history = SimpleNamespace(pending=pending)
    return cast(Aggregator, SimpleNamespace(status=lambda: SimpleNamespace(history=history)))


def run(client: Any, graph: GraphStore, tmp_path: Path, pending: list[str] | None = None) -> Setup:
    database = open_database(tmp_path)
    found = setup_status(
        cast(HomeAssistantClient, client) if client else None,
        graph,
        database,
        aggregator(pending or []) if client else None,
        PARIS,
    )
    return asyncio.run(found)


def test_a_fresh_install_says_what_is_missing(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as api:
        found = Setup.model_validate(api.get("/api/setup").json())

    assert states(found) == {
        "connection": "todo",
        "energy_dashboard": "blocked",
        "home": "todo",
        "forecast": "blocked",
        "first_plan": "blocked",
        "history": "blocked",
        "template": "blocked",
        "tariff": "todo",
        "battery": "not_applicable",
        "phases": "not_applicable",
        "notification": "todo",
    }
    assert [s.key for s in found.steps if s.required][:2] == ["connection", "energy_dashboard"]
    assert found.steps[0].reason == "ha_not_configured" and not found.ready


def test_the_steps_follow_the_home(tmp_path: Path) -> None:
    graph = GraphStore(tmp_path)

    without_dashboard = run(Client(dashboard=False, forecast=False), graph, tmp_path)
    assert states(without_dashboard)["energy_dashboard"] == "todo"
    assert states(without_dashboard)["forecast"] == "todo"
    assert states(without_dashboard)["first_plan"] == "blocked"

    home_model.save(graph, REFERENCE.home)
    importing = run(Client(), graph, tmp_path, pending=["sensor.pv"])
    assert states(importing)["history"] == "waiting"
    assert states(importing)["first_plan"] == "todo"
    assert states(importing)["battery"] == "todo"
    assert states(importing)["template"] == "todo"
    plan_step = next(s for s in importing.steps if s.key == "first_plan")
    assert plan_step.reason == "no_plan_yet"

    configuration.save(graph, REFERENCE.configuration)
    database = open_database(tmp_path)
    today = datetime.now(UTC).astimezone(PARIS).date()
    PlanStore(database).save("today", today, {"planning": []}, 1.0, True)
    save_settings(database, PlanningSettings(notify_service="notify.mobile_app_phone"))
    ready = run(Client(), graph, tmp_path)

    # Tout est fait, sauf l'étape du triphasé, sans objet pour cette maison en monophasé.
    assert states(ready).pop("phases") == "not_applicable"
    assert all(s.state is StepState.DONE for s in ready.steps if s.key != "phases")
    assert ready.ready
    tariff = next(s for s in ready.steps if s.key == "tariff")
    assert tariff.target == "home#tariff"
    notification = next(s for s in ready.steps if s.key == "notification")
    assert notification.target == "settings#notification"


def test_a_home_without_panels_needs_no_forecast(tmp_path: Path) -> None:
    graph = GraphStore(tmp_path)
    home = REFERENCE.home
    home_model.save(
        graph,
        home.model_copy(
            update={"devices": [d for d in home.devices if d.kind is not DeviceKind.SOLAR]}
        ),
    )

    found = run(Client(forecast=False), graph, tmp_path)
    assert states(found)["forecast"] == "not_applicable"
    assert states(found)["first_plan"] == "todo"

    database = open_database(tmp_path)
    today = datetime.now(UTC).astimezone(PARIS).date()
    PlanStore(database).save("today", today, {"planning": []}, 1.0, True)
    assert run(Client(forecast=False), graph, tmp_path).ready


def test_the_notification_step_follows_the_notification_settings(tmp_path: Path) -> None:
    """Réglages des notifications du lot 5.6 : l'étape est faite dès qu'une notification est
    activée avec un appareil, quel que soit l'ancien réglage du calcul."""
    database = open_database(tmp_path)
    graph = GraphStore(tmp_path)

    notifications.save(database, NotificationSettings(service="notify.mobile_app_phone"))
    assert states(run(Client(), graph, tmp_path))["notification"] == "todo"  # rien d'activé

    notifications.save(
        database,
        NotificationSettings(
            device_now=Rule(enabled=True, service="notify.mobile_app_tablet"),
        ),
    )
    assert states(run(Client(), graph, tmp_path))["notification"] == "done"


def test_described_panels_give_a_forecast_without_integration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    graph = GraphStore(tmp_path)
    home_model.save(graph, REFERENCE.home)
    no_forecast = Client(forecast=False)
    no_forecast.snapshot = replace(
        no_forecast.snapshot, config={"latitude": 45.76, "longitude": 4.84}
    )
    assert states(run(no_forecast, graph, tmp_path))["forecast"] == "todo"
    forecast_step = next(s for s in run(no_forecast, graph, tmp_path).steps if s.key == "forecast")
    assert forecast_step.target == "home#solar"

    solar = next(d for d in REFERENCE.home.devices if d.kind.value == "SolarInstallation")
    panels = SolarPanels(arrays=[PanelArray(kwp=3)])
    settings = DeviceSettings(
        key=solar.key, behavior=Behavior.PRODUCTION, automation=Automation.INFORM, panels=panels
    )
    configuration.save(graph, Configuration(devices=[settings]))

    async def fetch(url: str) -> dict[str, Any]:
        return response(around=datetime.now(UTC).astimezone(PARIS).date())

    monkeypatch.setattr(open_meteo, "fetch", fetch)
    assert states(run(no_forecast, graph, tmp_path))["forecast"] == "done"


# --- Triphasé -----------------------------------------------------------------------------------


def phases_step(found: Setup) -> tuple[str, str | None, str | None]:
    step = next(s for s in found.steps if s.key == "phases")
    return step.state.value, step.reason, step.target


def three_phase(change: Any = None) -> home_model.HomeModel:
    """La maison de référence en triphasé, chaque équipement sur la phase 1."""
    devices = [
        d if d.kind is DeviceKind.GRID else d.model_copy(update={"phase": home_model.Phase.L1})
        for d in REFERENCE.home.devices
    ]
    home = REFERENCE.home.model_copy(update={"devices": devices, "supply": home_model.Supply.THREE})
    return change(home) if change else home


def test_a_single_phase_home_has_no_phase_step(tmp_path: Path) -> None:
    graph = GraphStore(tmp_path)
    home_model.save(graph, REFERENCE.home)

    assert phases_step(run(Client(), graph, tmp_path)) == ("not_applicable", None, None)


def test_a_home_whose_names_give_phases_is_told_to_check_its_supply(tmp_path: Path) -> None:
    graph = GraphStore(tmp_path)
    home_model.save(graph, REFERENCE.home)
    client = Client()
    client.snapshot = HomeSnapshot(
        energy_preferences={
            "energy_sources": [{"type": "solar", "stat_energy_from": "sensor.roof_l2_energy"}]
        }
    )

    assert phases_step(run(client, graph, tmp_path)) == (
        "todo",
        "three_phase_detected",
        "home#supply",
    )


def test_a_three_phase_home_is_led_to_its_phases_then_its_phase_meters(tmp_path: Path) -> None:
    graph = GraphStore(tmp_path)

    # 1. Des équipements placés ou simulés sans phase : on y mène, en nommant les premiers.
    home_model.save(graph, REFERENCE.home.model_copy(update={"supply": home_model.Supply.THREE}))
    found = run(Client(), graph, tmp_path)
    step = next(s for s in found.steps if s.key == "phases")
    assert (step.state.value, step.reason) == ("todo", "phases_missing")
    assert step.target is not None and step.target.startswith("home#device-")
    assert int(step.params["count"]) >= 3 and step.params["devices"].count(",") == 2

    # 2. Toutes les phases renseignées, et Home Assistant sans compteur par phase : rien de plus
    # à faire.
    home_model.save(graph, three_phase())
    assert phases_step(run(Client(), graph, tmp_path)) == ("done", None, "home#supply")

    # 3. Home Assistant a des compteurs par phase que la maison ne suit pas : la fiche du réseau.
    with_meter = Client()
    with_meter.snapshot = _three_phase_snapshot()
    grid = next(d for d in REFERENCE.home.devices if d.kind is DeviceKind.GRID)
    assert phases_step(run(with_meter, graph, tmp_path)) == (
        "todo",
        "phase_sensors_missing",
        f"home#device-{grid.key}",
    )

    # 4. Un compteur de soutirage par phase dans la maison : l'étape est faite.
    def with_meters(home: home_model.HomeModel) -> home_model.HomeModel:
        meters = [
            home_model.HomeSensor(
                entity_id=f"sensor.meter_l{number}", role=Role.ENERGY_IMPORTED, phase=line
            )
            for number, line in enumerate(home_model.LINES, start=1)
        ]
        devices = [
            d.model_copy(update={"sensors": [*d.sensors, *meters]})
            if d.kind is DeviceKind.GRID
            else d
            for d in home.devices
        ]
        return home.model_copy(update={"devices": devices})

    home_model.save(graph, three_phase(with_meters))
    assert phases_step(run(with_meter, graph, tmp_path)) == ("done", None, "home#supply")
