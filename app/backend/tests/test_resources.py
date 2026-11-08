"""Ressources : moyenne du processeur, pics, limites du conteneur, disque."""

from pathlib import Path

from fastapi.testclient import TestClient

from tests.test_health import _settings
from wattslot.main import create_app
from wattslot.resources import (
    ResourceMonitor,
    Sample,
    cpu_cores,
    cpu_limit_v1,
    cpu_limit_v2,
    cpu_percent,
    memory_limit,
    memory_limit_v1,
    memory_limit_v2,
    memory_total,
    summarize,
)


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
    assert memory_limit(tmp_path, meminfo) == 4000000 * 1024
    (tmp_path / "memory.max").write_text("1048576\n")
    assert memory_limit(tmp_path, meminfo) == 1048576
    assert memory_limit(tmp_path / "absent", tmp_path / "absent") is None


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
