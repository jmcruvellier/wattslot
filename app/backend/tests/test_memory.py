"""Détail de la mémoire du processus (``memory.py``)."""

import logging
import sys
from pathlib import Path

import pytest

from wattslot import memory
from wattslot.memory import MemoryDetail, detail, release, status_fields, trim
from wattslot.resources import ResourceMonitor
from wattslot.storage.database import open_database

STATUS = """Name:\tuvicorn
VmPeak:\t 1500000 kB
VmRSS:\t  520000 kB
RssAnon:\t  480000 kB
RssFile:\t   40000 kB
RssShmem:\t       0 kB
VmSwap:\t   90000 kB
Threads:\t37
"""


def test_status_fields_are_read_in_bytes() -> None:
    assert status_fields(STATUS) == {
        "resident_bytes": 520000 * 1024,
        "anonymous_bytes": 480000 * 1024,
        "file_bytes": 40000 * 1024,
        "swap_bytes": 90000 * 1024,
        "threads": 37,
    }
    assert status_fields("VmRSS:\nRssAnon: beaucoup kB\n") == {}


def test_detail_reads_the_process(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    status = tmp_path / "status"
    status.write_text(STATUS)
    descriptors = tmp_path / "fd"
    descriptors.mkdir()
    for name in ("0", "1", "2"):
        (descriptors / name).touch()
    monkeypatch.setattr(memory, "PROC_STATUS", status)
    monkeypatch.setattr(memory, "PROC_FD", descriptors)
    monkeypatch.setattr(memory, "_heap", lambda: {"heap_used_bytes": 300, "heap_free_bytes": 200})

    assert detail(database_connections=4) == MemoryDetail(
        resident_bytes=520000 * 1024,
        anonymous_bytes=480000 * 1024,
        file_bytes=40000 * 1024,
        swap_bytes=90000 * 1024,
        threads=37,
        open_files=3,
        database_connections=4,
        heap_used_bytes=300,
        heap_free_bytes=200,
    )


def test_detail_is_unknown_without_proc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(memory, "PROC_STATUS", tmp_path / "absent")
    monkeypatch.setattr(memory, "PROC_FD", tmp_path / "absent")
    monkeypatch.setattr(memory, "_libc", lambda: None)
    assert detail() == MemoryDetail()
    assert trim() is None
    assert release() is None  # rien à rendre, rien dans le journal


def test_release_logs_before_and_after(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    states = iter(
        [
            MemoryDetail(resident_bytes=520_000_000, heap_free_bytes=180_000_000),
            MemoryDetail(
                resident_bytes=350_000_000,
                heap_used_bytes=250_000_000,
                heap_free_bytes=10_000_000,
                swap_bytes=0,
                threads=30,
                open_files=120,
            ),
        ]
    )
    monkeypatch.setattr(memory, "detail", lambda connections=None: next(states))
    monkeypatch.setattr(memory, "trim", lambda: True)
    with caplog.at_level(logging.INFO, logger="wattslot.memory"):
        found = release(7)
    assert found is not None
    assert found[0].resident_bytes == 520_000_000 and found[1].resident_bytes == 350_000_000
    assert "520 Mo, puis 350 Mo" in caplog.text
    assert "gardée par l'allocateur 180 puis 10 Mo" in caplog.text
    assert "30 fils, 120 fichiers ouverts, 7 connexions" in caplog.text


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="glibc seulement")
def test_real_process_on_linux() -> None:
    """Sous Linux (CI) : les vraies valeurs se lisent et ``malloc_trim`` s'appelle."""
    found = detail()
    assert found.resident_bytes and found.anonymous_bytes and found.threads
    assert found.open_files and found.heap_used_bytes
    assert trim() is not None
    assert release() is not None


def test_snapshot_carries_the_memory_detail(tmp_path: Path) -> None:
    database = open_database(tmp_path)
    found = ResourceMonitor(tmp_path, database).snapshot()
    assert found.memory_detail is not None
    assert found.memory_detail.database_connections == 1
    database.close()
