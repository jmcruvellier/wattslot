"""Diagnostic pour tous (lot 4.8) : ce qui ne va pas, en clair, et le rapport anonymisé."""

import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from tests.fake_home_assistant import default_responses, fake_home_assistant, running_client
from tests.test_health import _settings
from wattslot import home_model, profiles, report
from wattslot.aggregation import AggregationStatus, HistoryStatus
from wattslot.configuration import Configuration
from wattslot.detection import DeviceKind, Issue, Role
from wattslot.diagnostic import DeviceIssue, Diagnostic
from wattslot.home_assistant import ConnectionState
from wattslot.home_model import HomeDevice, HomeModel, HomeSensor
from wattslot.ingestion import EntityStatus, IngestionStatus
from wattslot.main import create_app
from wattslot.objective_settings import ObjectiveSettings, Preset
from wattslot.planning.runner import ImpossibleData, RunReport
from wattslot.planning.scheduler import SchedulerStatus
from wattslot.planning.sources import PlanningSettings
from wattslot.problems import Problem, Severity, collect
from wattslot.setup import Setup, setup_status
from wattslot.storage.database import open_database
from wattslot.storage.graph import GraphStore
from wattslot.tariff import Tariff, TariffKind

PARIS = ZoneInfo("Europe/Paris")
NOW = datetime(2026, 10, 17, 10, 0, tzinfo=UTC)
SOLAR = HomeDevice(
    key="solar",
    kind=DeviceKind.SOLAR,
    name="Toiture",
    sensors=[
        HomeSensor(entity_id="sensor.solar_energy", role=Role.ENERGY_PRODUCED),
        HomeSensor(entity_id="sensor.solar_gone", role=Role.ENERGY_PRODUCED),
    ],
)
HOME = HomeModel(devices=[SOLAR])


def codes(found: list[Problem]) -> list[str]:
    return [p.code for p in found]


async def _with_client(
    tmp_path: Path, responses: dict[str, Any], home: HomeModel = HOME
) -> list[Problem]:
    graph = GraphStore(tmp_path)
    home_model.save(graph, home)
    database = open_database(tmp_path)
    async with running_client(fake_home_assistant(responses)) as client:
        setup = await setup_status(client, graph, database, None, PARIS)
        return collect(setup, Diagnostic(generated_at=NOW), home, Configuration(), client)


def test_a_missing_meter_names_its_device(tmp_path: Path) -> None:
    responses = default_responses() | {"energy/solar_forecast": {}}
    found = asyncio.run(_with_client(tmp_path, responses))

    missing = next(p for p in found if p.code == "sensor_missing")
    assert missing.params["device"] == "Toiture" and missing.params["entity"] == "sensor.solar_gone"
    assert missing.severity is Severity.DEGRADED and missing.target == "home"


def test_a_cut_forecast_blocks_the_plan_and_says_where_to_act(tmp_path: Path) -> None:
    responses = default_responses() | {"energy/solar_forecast": {}}
    found = asyncio.run(_with_client(tmp_path, responses))

    assert found[0].code == "no_forecast" and found[0].severity is Severity.BLOCKING
    # Pas encore de premier plan : une étape de la mise en route (« Mise en route »).
    assert found[0].setup
    assert found[0].target == "home#solar" and found[0].doc is not None


def test_home_assistant_not_configured_or_disconnected(tmp_path: Path) -> None:
    graph, database = GraphStore(tmp_path), open_database(tmp_path)
    setup = asyncio.run(setup_status(None, graph, database, None, PARIS))
    found = collect(setup, Diagnostic(generated_at=NOW), HomeModel(), Configuration(), None)
    assert codes(found)[0] == "ha_not_configured" and found[0].doc is not None

    async def disconnected() -> list[Problem]:
        handler = fake_home_assistant()
        async with running_client(handler, token="mauvais", until=ConnectionState.ERROR) as client:
            setup = await setup_status(client, graph, database, None, PARIS)
            return collect(
                setup, Diagnostic(generated_at=NOW), HomeModel(), Configuration(), client
            )

    found = asyncio.run(disconnected())
    assert codes(found)[0] == "ha_disconnected" and "error" in found[0].params


def test_components_silent_sensors_and_statistics() -> None:
    old = NOW - timedelta(days=2)
    diagnostic = Diagnostic(
        generated_at=NOW,
        ingestion=IngestionStatus(
            running=True,
            entities=[
                EntityStatus(
                    entity_id="sensor.solar_energy", role=Role.ENERGY_PRODUCED, last_time=old
                )
            ],
            received=0,
            written=0,
            pending=5000,
            last_error="boom sur sensor.solar_energy",
        ),
        aggregation=AggregationStatus(
            running=True, history=HistoryStatus(without_statistics=["sensor.solar_energy"])
        ),
        planning=SchedulerStatus(
            running=True, enabled=True, last_success_at=NOW - timedelta(hours=3)
        ),
    )
    home = HomeModel(devices=[SOLAR.model_copy(update={"sensors": SOLAR.sensors[:1]})])
    found = collect(_ready(), diagnostic, home, Configuration(), None)

    assert set(codes(found)) >= {
        "internal_error",
        "writes_behind",
        "no_statistics",
        "plan_stale",
        "sensor_silent",
    }
    statistics = next(p for p in found if p.code == "no_statistics")
    assert statistics.params["devices"] == "Toiture"
    assert [p.severity for p in found] == sorted(
        (p.severity for p in found), key=lambda s: list(Severity).index(s)
    )


def _ready() -> Setup:
    return Setup(steps=[], ready=True)


def test_configuration_issues_name_the_device() -> None:
    profile = profiles.load("reference")
    wrong = profile.configuration.model_copy(
        update={
            "devices": [
                d.model_copy(update={"after": "nowhere"}) if d.key == "dryer" else d
                for d in profile.configuration.devices
            ]
        }
    )
    found = collect(_ready(), Diagnostic(generated_at=NOW), profile.home, wrong, None)

    issue = next(p for p in found if p.code == "configuration_issue")
    dryer = next(d for d in profile.home.devices if d.key == "dryer")
    assert issue.params["issue"] == "after_unknown" and issue.params["device"] == dryer.name


def test_the_report_has_no_identifier_of_the_home() -> None:
    profile = profiles.load("heat_pump")
    home = profile.home
    saved = profile.configuration.model_copy(
        update={
            "tariff": Tariff(
                kind=TariffKind.DYNAMIC,
                base_eur_kwh=0.25,
                price_entity="sensor.spot_price_maison",
                export_entity="sensor.spot_export_maison",
            ),
            "objective": ObjectiveSettings(preset=Preset.CO2, co2_entity="sensor.co2_maison"),
        }
    )
    first = home.devices[2]
    entity = first.sensors[0].entity_id
    diagnostic = Diagnostic(
        generated_at=NOW,
        planning=SchedulerStatus(
            running=True, enabled=True, last_error=f"{first.name} : {entity} illisible, light.salon"
        ),
    )
    problems = [
        Problem(
            code="sensor_missing",
            severity=Severity.DEGRADED,
            params={"device": first.name, "role": "EnergyConsumed", "entity": entity},
        )
    ]
    settings = PlanningSettings(todo_entity="todo.maison", notify_service="notify.mobile_app_jm")

    found = report.build(
        mode="standalone",
        ha_version="2026.10.1",
        ha_state="connected",
        diagnostic=diagnostic,
        problems=problems,
        home=home,
        saved=saved,
        settings=settings,
    )
    text = json.dumps(found, ensure_ascii=False)

    identifiers = [s.entity_id for d in home.devices for s in d.sensors]
    identifiers += [d.name for d in home.devices] + [t.name for t in home.types]
    identifiers += ["sensor.spot_price_maison", "sensor.co2_maison", "todo.maison", "light.salon"]
    identifiers += ["notify.mobile_app_jm", "mobile_app"]
    assert [i for i in identifiers if i in text] == []
    assert {d["key"] for d in found["home"]["devices"]} >= {"Battery_1", "OtherLoad_1"}
    alias = f"{first.kind.value}_1.{first.sensors[0].role.value}"
    assert found["problems"][0]["params"]["entity"] == alias
    assert "latitude" not in text and "longitude" not in text
    assert found["settings"]["notification"] is True


def test_routes_without_home_assistant(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as api:
        problems = api.get("/api/diagnostic/problems").json()
        found = api.get("/api/diagnostic/report").json()

    assert problems[0]["code"] == "ha_not_configured"
    assert found["format"] == "wattslot/report"
    assert found["home_assistant"] == {"version": None, "state": "not_configured"}
    assert found["problems"][0]["code"] == "ha_not_configured"


def test_energy_dashboard_issues_of_a_sensor() -> None:
    """Une anomalie d'un capteur du tableau Énergie porte déjà son entité : elle ne doit pas
    faire échouer la liste des problèmes (erreur 500 constatée sur une vraie installation)."""
    issue = Issue(code="not_energy_unit", params={"entity": "sensor.pv_power", "unit": "W"})
    diagnostic = Diagnostic(
        generated_at=NOW,
        issues=[
            DeviceIssue(device="Toiture", entity_id="sensor.pv_power", issue=issue),
            DeviceIssue(device="Batterie", issue=Issue(code="battery_soc_missing")),
        ],
    )

    found = collect(_ready(), diagnostic, HomeModel(), Configuration(), None)

    assert [p.params for p in found] == [
        {"entity": "sensor.pv_power", "unit": "W", "issue": "not_energy_unit", "device": "Toiture"},
        {"issue": "battery_soc_missing", "device": "Batterie", "entity": ""},
    ]
    built = report.build(
        mode="addon",
        ha_version=None,
        ha_state="connected",
        diagnostic=diagnostic,
        problems=found,
        home=HOME,
        saved=Configuration(),
        settings=PlanningSettings(),
    )
    assert "sensor.pv_power" not in json.dumps(built) and "Toiture" not in json.dumps(built)


def test_dashboard_issues_follow_the_saved_home() -> None:
    """Maison enregistrée : les anomalies d'un équipement ou d'un capteur écarté ne sont plus
    signalées, et l'équipement prend son nom dans la maison (« Grid » constaté au lieu du nom
    donné par l'utilisateur)."""
    cost = Issue(code="name_suggests_cost", params={"entity": "sensor.cout_abonnement"})
    unit = Issue(code="not_energy_unit", params={"entity": "sensor.solar_energy", "unit": "W"})
    unused = Issue(code="not_energy_unit", params={"entity": "sensor.pv_unused", "unit": "W"})
    diagnostic = Diagnostic(
        generated_at=NOW,
        issues=[
            DeviceIssue(device="Grid", key="grid", entity_id="sensor.cout_abonnement", issue=cost),
            DeviceIssue(device="Solar", key="solar", entity_id="sensor.pv_unused", issue=unused),
            DeviceIssue(device="Solar", key="solar", entity_id="sensor.solar_energy", issue=unit),
        ],
    )

    found = [
        p
        for p in collect(_ready(), diagnostic, HOME, Configuration(), None)
        if p.code == "energy_dashboard_issue"
    ]

    assert [(p.params["device"], p.params["entity"]) for p in found] == [
        ("Toiture", "sensor.solar_energy")
    ]


def test_a_missing_forecast_is_not_an_internal_error() -> None:
    """Calcul planifié sans prévision : déjà signalé par « no_forecast » (constaté au banc
    d'intégration, calcul de hh:59 pendant le contrôle)."""
    planning = SchedulerStatus(
        running=True,
        enabled=True,
        last_error="ForecastUnavailable: 2026-10-17",
        last_error_code="no_forecast",
    )
    found = collect(
        _ready(),
        Diagnostic(generated_at=NOW, planning=planning),
        HomeModel(),
        Configuration(),
        None,
    )
    assert "internal_error" not in codes(found)


def test_an_impossible_day_names_the_meter_jump() -> None:
    """Jour non calculé, consommation de base impossible (lot 7.3) : le saut de compteur à
    l'origine, ou seulement l'heure s'il n'est pas retrouvé."""
    paris = ZoneInfo("Europe/Paris")
    found_jump = ImpossibleData(
        day=date(2026, 10, 23),
        hour=20,
        consumption_kwh=10674.1,
        limit_kwh=11.5,
        device="Réseau",
        entity_id="sensor.grid_import",
        source_start=datetime(2026, 10, 16, 20, tzinfo=paris),
        source_kwh=64045.0,
        until=date(2026, 11, 27),
    )
    unknown = ImpossibleData(day=date(2026, 10, 24), hour=7, consumption_kwh=80.0, limit_kwh=11.5)
    last = RunReport(
        day=date(2026, 10, 19),
        started_at=NOW,
        manual=False,
        seconds_today=1.0,
        impossible=[found_jump, unknown],
    )
    planning = SchedulerStatus(running=True, enabled=True, last_report=last)

    found = collect(
        _ready(),
        Diagnostic(generated_at=NOW, planning=planning),
        HomeModel(),
        Configuration(),
        None,
    )

    jump, bare = (p for p in found if p.code.startswith("impossible_data"))
    assert (jump.code, jump.severity) == ("impossible_data", Severity.DEGRADED)
    assert jump.params == {
        "day": "2026-10-23",
        "hour": "20",
        "kwh": "10674.1",
        "limit": "11.5",
        "device": "Réseau",
        "entity": "sensor.grid_import",
        "when": "2026-10-16",
        "when_hour": "20",
        "source_kwh": "64045",
        "until": "2026-11-27",
    }
    assert bare.code == "impossible_data_unknown"
    assert bare.params == {"day": "2026-10-24", "hour": "7", "kwh": "80", "limit": "11.5"}
    assert "internal_error" not in codes(found)
