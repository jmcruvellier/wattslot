"""Ressources : moyenne du processeur, pics, limites du conteneur, disque."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from tests.test_health import _settings
from wattslot.main import create_app
from wattslot.resources import (
    ResourceMonitor,
    Resources,
    Sample,
    cpu_cores,
    cpu_limit_v1,
    cpu_limit_v2,
    cpu_percent,
    disk_alert,
    history,
    memory_alert,
    memory_limit,
    memory_limit_v1,
    memory_limit_v2,
    memory_total,
    summarize,
)
from wattslot.storage.database import DATABASE_FILENAME


def test_cpu_percent_is_relative_to_one_core() -> None:
    assert cpu_percent(Sample(0, 10, None), Sample(60, 40, None)) == 50
    assert cpu_percent(Sample(0, 10, None), Sample(60, 130, None)) == 200  # deux cœurs pleins
    assert cpu_percent(Sample(60, 10, None), Sample(60, 20, None)) is None


def test_summary_averages_the_last_fifteen_minutes() -> None:
    # Une minute très chargée il y a une heure, puis le repos : la moyenne n'en garde rien,
    # le pic si.
    samples = [Sample(0, 0, 100), Sample(60, 54, 300)]
    samples += [Sample(60 + 60 * i, 54 + 0.6 * (i - 1), 200) for i in range(2, 62)]
    now = Sample(samples[-1].at + 60, samples[-1].cpu_s + 0.6, 150)

    found = summarize(samples, now)

    assert found.cpu_percent is not None and round(found.cpu_percent, 3) == 1
    assert found.cpu_peak_percent == 90
    assert found.memory_bytes == 150
    assert found.memory_peak_bytes == 300
    assert found.memory_floor_bytes == 150  # plus bas des 15 dernières minutes, présent compris
    assert found.measured_s == now.at


def test_summary_right_after_start() -> None:
    found = summarize([Sample(0, 1, 50)], Sample(30, 4, 60))
    assert found.cpu_percent == 10
    assert found.measured_s == 30
    assert summarize([], Sample(0, 0, None)).cpu_percent is None


def test_memory_limits() -> None:
    assert memory_limit_v2("max\n") is None
    assert memory_limit_v2("536870912\n") == 536870912
    assert memory_limit_v1("9223372036854771712\n") is None
    assert memory_limit_v1("1073741824\n") == 1073741824
    assert memory_total("MemTotal:  4000000 kB\nMemFree: 1 kB\n") == 4000000 * 1024
    assert memory_total("MemFree: 1 kB\n") is None


def test_the_smallest_memory_limit_wins(tmp_path: Path) -> None:
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal: 4000000 kB\n")
    (tmp_path / "memory.max").write_text("max\n")
    assert memory_limit(tmp_path, meminfo) == (4000000 * 1024, "machine")
    (tmp_path / "memory.max").write_text("1048576\n")
    assert memory_limit(tmp_path, meminfo) == (1048576, "container")
    # Limite du conteneur au-delà de la machine : c'est la machine qui borne.
    (tmp_path / "memory.max").write_text(f"{8 * 10**9}\n")
    assert memory_limit(tmp_path, meminfo) == (4000000 * 1024, "machine")
    assert memory_limit(tmp_path / "absent", tmp_path / "absent") == (None, None)


def test_cpu_limits(tmp_path: Path) -> None:
    assert cpu_limit_v2("max 100000\n") is None
    assert cpu_limit_v2("150000 100000\n") == 1.5
    assert cpu_limit_v1("-1", "100000") is None
    assert cpu_limit_v1("50000", "100000") == 0.5
    (tmp_path / "cpu.max").write_text("50000 100000\n")
    assert cpu_cores(tmp_path) == 0.5


def test_snapshot_measures_the_data_folder(tmp_path: Path) -> None:
    (tmp_path / "base.sqlite").write_bytes(b"x" * 1000)
    monitor = ResourceMonitor(tmp_path)
    start = monitor._samples[0]  # relevé de départ, pris à la création

    found = monitor.snapshot(Sample(start.at + 60, start.cpu_s + 6, None))

    assert found.disk_used_bytes == 1000
    assert found.disk_free_bytes is not None and found.disk_total_bytes is not None
    assert found.disk_free_bytes <= found.disk_total_bytes
    assert found.cpu_percent is not None and round(found.cpu_percent) == 10


def test_resources_route(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        resources = client.get("/api/diagnostic/resources").json()
        diagnostic = client.get("/api/diagnostic").json()

    assert resources["disk_total_bytes"] > 0
    assert resources["cpu_cores"] > 0
    assert diagnostic["resources"]["disk_used_bytes"] >= 0


def test_history_gives_one_point_a_minute() -> None:
    start = datetime(2026, 11, 8, 8, 0, tzinfo=UTC)
    samples = [
        Sample(0, 0, 100, 5000, start),
        Sample(60, 6, 120, 4900, start + timedelta(minutes=1)),
        Sample(120, 6.6, 110, None, start + timedelta(minutes=2)),
    ]

    points = history(samples)

    assert [p.time for p in points] == [s.time for s in samples]
    assert points[0].cpu_percent is None  # pas de minute avant le premier relevé
    assert points[1].cpu_percent == 10
    assert points[2].cpu_percent is not None and round(points[2].cpu_percent) == 1
    assert [p.memory_bytes for p in points] == [100, 120, 110]
    assert [p.disk_free_bytes for p in points] == [5000, 4900, None]
    assert history([Sample(0, 0, None)]) == []  # relevé sans heure : pas de point


def test_history_route(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        points = client.get("/api/diagnostic/resources/history").json()

    assert len(points) == 1  # le relevé de départ
    assert points[0]["cpu_percent"] is None and points[0]["disk_free_bytes"] > 0


def test_alert_thresholds_for_the_red_line() -> None:
    gb, mb = 10**9, 10**6
    container = Resources(memory_limit_bytes=1000 * mb, memory_limit_source="container")
    assert memory_alert(container) == 750 * mb
    machine = Resources(memory_limit_bytes=2100 * mb, memory_limit_source="machine")
    assert memory_alert(machine) == 1 << 30
    # Disque : le plus haut de 2 Go, 10 % du disque et la place d'une sauvegarde.
    assert disk_alert(Resources()) is None
    small = Resources(disk_free_bytes=20 * gb, disk_total_bytes=16 * gb)
    assert disk_alert(small) == 2 * gb
    big = Resources(disk_free_bytes=20 * gb, disk_total_bytes=34 * gb)
    assert disk_alert(big) == round(3.4 * gb)
    backup = Resources(disk_free_bytes=20 * gb, disk_total_bytes=34 * gb, disk_backup_bytes=5 * gb)
    assert disk_alert(backup) == 5 * gb


def test_snapshot_gives_the_thresholds(tmp_path: Path) -> None:
    (tmp_path / DATABASE_FILENAME).write_bytes(b"x" * 1000)
    found = ResourceMonitor(tmp_path).snapshot()
    assert found.disk_backup_bytes == 2000  # deux fois la base, sans graphe
    assert found.memory_alert_bytes is not None
    assert found.disk_alert_free_bytes is not None and found.disk_alert_free_bytes >= 2 * 10**9
