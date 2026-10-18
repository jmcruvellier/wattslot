"""Relevés bruts : ``flush`` espacés (volume ou temps écoulé), relevés lisibles avant."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from wattslot.storage import raw as raw_module
from wattslot.storage.raw import (
    FLUSH_INTERVAL,
    TRIPLES_PER_READING,
    RawStores,
    Reading,
)

START = datetime(2026, 10, 16, 8, tzinfo=UTC)


def readings(count: int, offset: int = 0) -> list[Reading]:
    return [
        Reading("sensor.p", "http://example.org/p", float(i), START + timedelta(seconds=offset + i))
        for i in range(count)
    ]


def test_flush_after_an_interval_and_readings_readable_before(tmp_path: Path) -> None:
    clock = [0.0]
    stores = RawStores(tmp_path, "Europe/Paris", clock=lambda: clock[0])
    day = stores.day_of(START)

    stores.write(readings(10))
    assert stores._unflushed[day] == 10 * TRIPLES_PER_READING  # pas encore vidé sur disque
    assert len(stores.readings(START, START + timedelta(hours=1))) == 10  # mais lisible

    clock[0] = FLUSH_INTERVAL.total_seconds()
    stores.write(readings(5, offset=100))
    assert stores._unflushed[day] == 0


def test_flush_after_a_volume(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(raw_module, "FLUSH_TRIPLES", 40)
    stores = RawStores(tmp_path, "Europe/Paris", clock=lambda: 0.0)
    day = stores.day_of(START)

    stores.write(readings(9))
    assert stores._unflushed[day] == 36
    stores.write(readings(1, offset=50))
    assert stores._unflushed[day] == 0


def test_explicit_flush_and_removal(tmp_path: Path) -> None:
    stores = RawStores(tmp_path, "Europe/Paris", clock=lambda: 0.0)
    day = stores.day_of(START)
    stores.write(readings(3))
    stores.flush()
    assert stores._unflushed[day] == 0
    stores.write(readings(3, offset=10))
    stores.remove_day(day)
    assert day not in stores._unflushed and stores.days() == []
