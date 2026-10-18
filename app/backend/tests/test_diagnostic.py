"""Diagnostic : relevés du jour, mémoire, anomalies de configuration, réglages."""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from fastapi.testclient import TestClient

from tests.fake_home_assistant import ENERGY_PREFERENCES
from tests.test_health import _settings
from wattslot.diagnostic import configuration_issues, resident_bytes, written_from
from wattslot.home_assistant import (
    ConnectionState,
    HomeAssistantClient,
    HomeAssistantStatus,
    HomeSnapshot,
)
from wattslot.main import create_app
from wattslot.storage.raw import RawStores, Reading


def test_counts_today_readings_by_sensor(tmp_path: Path) -> None:
    raw = RawStores(tmp_path)
    moment = datetime(2026, 10, 15, 10, tzinfo=UTC)
    raw.write(
        [
            Reading("sensor.a", "urn:a", 1.0, moment),
            Reading("sensor.a", "urn:a", 2.0, moment.replace(minute=1)),
            Reading("sensor.b", "urn:b", 3.0, moment),
        ]
    )

    assert raw.counts_by_sensor(moment.date()) == {"urn:a": 2, "urn:b": 1}
    assert raw.counts_by_sensor(datetime(2026, 10, 16).date()) == {}
    assert raw.days() == [moment.date()]  # journée absente : pas de magasin créé


def test_reads_the_resident_memory() -> None:
    assert resident_bytes("Name:\tpython\nVmRSS:\t   86452 kB\nVmSwap: 0 kB\n") == 86452 * 1024
    assert resident_bytes("Name:\tpython\n") is None


def test_written_bytes_from_proc_io() -> None:
    proc_io = "rchar: 10\nwchar: 20\nwrite_bytes: 4096\ncancelled_write_bytes: 0\n"
    assert written_from(proc_io) == 4096
    assert written_from("rchar: 10\n") is None


def test_configuration_issues_come_from_the_energy_dashboard() -> None:
    client = SimpleNamespace(
        status=HomeAssistantStatus(ConnectionState.CONNECTED),
        snapshot=HomeSnapshot(energy_preferences=ENERGY_PREFERENCES),  # entité absente des états
    )

    issues = configuration_issues(cast(HomeAssistantClient, client))

    assert issues is not None
    assert [(i.device, i.entity_id, i.issue.code) for i in issues] == [
        ("sensor.solar_energy", None, "no_power_sensor"),  # nom repris de l'entité, absente
        ("sensor.solar_energy", "sensor.solar_energy", "entity_missing"),  # anomalie d'un capteur
    ]
    assert configuration_issues(None) is None


def test_diagnostic_and_retention_without_home_assistant(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        diagnostic = client.get("/api/diagnostic").json()
        default = client.get("/api/settings/retention").json()
        too_short = client.put("/api/settings/retention", json={"quarter_days": 10})
        saved = client.put("/api/settings/retention", json={"raw_days": 4}).json()
        maintenance = client.get("/api/maintenance")

    assert diagnostic["ingestion"] is None and diagnostic["issues"] is None
    assert diagnostic["today"] == {}
    assert default == {"raw_days": 3, "quarter_days": 35, "hour_days": None}
    assert too_short.status_code == 422  # profils de cycle : au moins 31 jours
    assert saved == {"raw_days": 4, "quarter_days": 35, "hour_days": None}
    assert maintenance.status_code == 503


def test_planning_history_needs_home_assistant(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        assert client.get("/api/planning/history").status_code == 503
