"""Relevés bruts : ``flush`` espacés (volume ou temps écoulé), relevés lisibles avant."""

import threading
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


def test_a_store_in_use_is_not_closed_by_another_thread(tmp_path: Path) -> None:
    """Conservation de 30 jours : un fil ouvre plus de journées que ``OPEN_STORES`` pendant
    qu'un autre se sert encore d'un magasin. Fermé puis rouvert, ce magasin était refusé par le
    verrou de RocksDB ; il reste ouvert jusqu'à ce qu'il soit rendu."""
    stores = RawStores(tmp_path)
    days = [START + timedelta(days=d) for d in range(raw_module.OPEN_STORES + 3)]
    for moment in days:
        stores.write([Reading("sensor.p", "http://example.org/p", 1.0, moment)])
    first = stores.day_of(days[0])

    with stores._using(first) as held:
        for moment in days[1:]:
            assert stores.count(stores.day_of(moment)) == 1  # ouvre les autres journées
        assert first in stores._open  # pas fermé : un fil s'en sert
        held.flush()

    # Rendu : la limite est de nouveau tenue, et la journée se relit (rouverte sans verrou).
    assert len(stores._open) <= raw_module.OPEN_STORES
    assert stores.count(first) == 1


def test_removal_waits_for_a_reader(tmp_path: Path) -> None:
    """La conservation supprime une journée qu'un autre fil lit encore : elle attend qu'il l'ait
    rendue, au lieu d'effacer le dossier d'un magasin ouvert."""
    stores = RawStores(tmp_path)
    stores.write(readings(3))
    day = stores.day_of(START)

    with stores._using(day):
        remover = threading.Thread(target=stores.remove_day, args=(day,))
        remover.start()
        remover.join(0.3)
        assert remover.is_alive()  # attend le lecteur
        assert stores.days() == [day]
    remover.join(5)

    assert not remover.is_alive()
    assert stores.days() == [] and day not in stores._open


def test_a_read_during_removal_waits_and_does_not_recreate_the_day(tmp_path: Path) -> None:
    """Une lecture demandée pendant la suppression attend qu'elle soit finie, puis ne trouve
    rien : elle ne recrée pas un dossier vide pour la journée supprimée."""
    stores = RawStores(tmp_path)
    stores.write(readings(3))
    day = stores.day_of(START)
    found: list[object] = []

    with stores._using(day):
        remover = threading.Thread(target=stores.remove_day, args=(day,))
        remover.start()
        remover.join(0.3)  # la suppression a commencé : elle attend le premier lecteur
        reader = threading.Thread(
            target=lambda: found.append(stores.readings(START, START + timedelta(hours=1)))
        )
        reader.start()
        reader.join(0.3)
        assert reader.is_alive()  # attend la fin de la suppression
    remover.join(5)
    reader.join(5)

    assert found == [[]]
    assert stores.days() == [] and stores.count(day) == 0 and stores.days() == []
    assert not stores._users
