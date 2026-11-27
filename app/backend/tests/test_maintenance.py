"""Conservation et maintenance : brut par journée, agrégats échus, réglages."""

import asyncio
import logging
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

import pytest

from wattslot import memory
from wattslot.aggregation import (
    HOUR,
    QUARTER,
    AggregationStatus,
    Aggregator,
    Values,
    aggregate_nquads,
    graph_iri,
)
from wattslot.detection import Role
from wattslot.ingestion import Target
from wattslot.maintenance import (
    Maintenance,
    Retention,
    directory_size,
    load_retention,
    save_retention,
)
from wattslot.ontology import BASE
from wattslot.storage.database import open_database
from wattslot.storage.graph import GraphStore
from wattslot.storage.raw import RawStores, Reading

NOW = datetime(2026, 10, 15, 2, 0, tzinfo=UTC)  # 4h00 à Paris, le 15
POWER = Target("sensor.p", "urn:sensor:p", Role.POWER_CONSUMED)
PARIS = ZoneInfo("Europe/Paris")


class StubAggregator:
    def __init__(self, complete_until: datetime) -> None:
        self.complete_until = complete_until

    def status(self) -> AggregationStatus:
        until = self.complete_until
        return AggregationStatus(running=True, complete_until={QUARTER: until, HOUR: until})


def _maintenance(
    tmp_path: Path, complete_until: datetime
) -> tuple[Maintenance, RawStores, GraphStore]:
    raw = RawStores(tmp_path, "Europe/Paris")
    graph = GraphStore(tmp_path)
    aggregator = cast(Aggregator, StubAggregator(complete_until))
    return Maintenance(raw, graph, open_database(tmp_path), tmp_path, aggregator), raw, graph


def test_runs_every_night_at_half_past_three_local_time(tmp_path: Path) -> None:
    maintenance, _, _ = _maintenance(tmp_path, NOW)

    assert maintenance.next_run(NOW) == datetime(2026, 10, 16, 1, 30, tzinfo=UTC)
    assert maintenance.next_run(NOW - timedelta(hours=2)) == datetime(
        2026, 10, 15, 1, 30, tzinfo=UTC
    )


def test_retention_defaults_and_settings(tmp_path: Path) -> None:
    database = open_database(tmp_path)
    assert load_retention(database) == Retention(raw_days=3, quarter_days=35, hour_days=456)

    save_retention(database, Retention(raw_days=5, quarter_days=40, hour_days=400))

    assert load_retention(database) == Retention(raw_days=5, quarter_days=40, hour_days=400)


def _aggregate(graph: GraphStore, period: str, start: datetime) -> None:
    values = Values(mean=1.0, maximum=1.0)
    graph_name = graph_iri(period, start, PARIS)
    graph.add_nquads(aggregate_nquads(POWER.entity_id, POWER, period, start, values, graph_name))


def _starts(graph: GraphStore, period: str) -> list[str]:
    rows = graph.select(
        f'SELECT ?t WHERE {{ GRAPH ?g {{ ?a <{BASE}#start> ?t ; <{BASE}#period> "{period}" }} }}'
    )
    return sorted(row["t"] for row in rows)


def test_removes_expired_raw_days_and_aggregates(tmp_path: Path) -> None:
    # Agrégé jusqu'au 11 à 0h00 (heure de Paris) : la journée du 11 n'est pas encore complète.
    maintenance, raw, graph = _maintenance(tmp_path, datetime(2026, 10, 10, 22, tzinfo=UTC))
    for day in range(10, 16):
        raw.write(
            [
                Reading(
                    POWER.entity_id, POWER.sensor_iri, 1.0, datetime(2026, 10, day, 10, tzinfo=UTC)
                )
            ]
        )
    _aggregate(graph, QUARTER, datetime(2026, 9, 1, 10, tzinfo=UTC))  # échu (avant le 10/09)
    _aggregate(graph, QUARTER, datetime(2026, 9, 15, 10, tzinfo=UTC))
    _aggregate(graph, QUARTER, datetime(2026, 10, 1, 10, tzinfo=UTC))
    _aggregate(graph, HOUR, datetime(2025, 1, 1, 10, tzinfo=UTC))  # échu si limité à 366 jours
    save_retention(open_database(tmp_path), Retention(hour_days=366))

    run = asyncio.run(maintenance.run(NOW))

    assert run.removed_days == [date(2026, 10, 10)]
    assert run.kept_days == [date(2026, 10, 11)]  # échue mais pas entièrement agrégée
    assert raw.days() == [date(2026, 10, d) for d in range(11, 16)]
    assert run.removed_aggregates == {QUARTER: 1, HOUR: 1}
    assert run.compacted  # le graphe horaire de janvier 2025 est retiré
    assert _starts(graph, QUARTER) == ["2026-09-15T10:00:00Z", "2026-10-01T10:00:00Z"]
    assert _starts(graph, HOUR) == []
    assert f"{BASE}/graph/aggregates/{HOUR}/2025-01" not in graph.named_graphs()
    status = maintenance.status()
    assert status.last_run == run
    assert status.disk.raw_bytes > 0 and status.disk.graph_bytes > 0


def test_compacts_only_when_a_monthly_graph_is_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Le compactage réécrit tout le magasin : pas pour une journée de quarts d'heure."""
    maintenance, _, graph = _maintenance(tmp_path, NOW)
    compactions: list[bool] = []
    monkeypatch.setattr(graph, "optimize", lambda: compactions.append(True))
    _aggregate(graph, QUARTER, datetime(2026, 9, 9, 10, tzinfo=UTC))  # échu, mois gardé
    _aggregate(graph, QUARTER, datetime(2026, 9, 15, 10, tzinfo=UTC))

    run = asyncio.run(maintenance.run(NOW))

    assert run.removed_aggregates == {QUARTER: 1, HOUR: 0}
    assert not run.compacted and compactions == []

    _aggregate(graph, QUARTER, datetime(2026, 8, 20, 10, tzinfo=UTC))  # mois entièrement échu

    run = asyncio.run(maintenance.run(NOW))

    assert run.removed_aggregates == {QUARTER: 1, HOUR: 0}
    assert run.compacted and compactions == [True]
    assert f"{BASE}/graph/aggregates/{QUARTER}/2026-08" not in graph.named_graphs()


def test_one_flush_per_graph_whatever_the_number_of_sensors(tmp_path: Path) -> None:
    """Un ``flush`` par capteur (82 capteurs) faisait recompacter RocksDB à chaque fois : 2,8 Go
    écrits pour une journée supprimée (rapport du 11/11/2026)."""

    class CountingStore:
        def __init__(self, store: object) -> None:
            self.store, self.flushes = store, 0

        def flush(self) -> None:
            self.flushes += 1

        def __getattr__(self, name: str) -> object:
            return getattr(self.store, name)

    maintenance, _, graph = _maintenance(tmp_path, NOW)
    expired, kept = datetime(2026, 9, 1, 10, tzinfo=UTC), datetime(2026, 9, 20, 10, tzinfo=UTC)
    values = Values(mean=1.0, maximum=1.0)
    name = graph_iri(QUARTER, expired, PARIS)
    for index in range(5):
        sensor = Target(f"sensor.p{index}", f"urn:sensor:p{index}", Role.POWER_CONSUMED)
        for start in (expired, kept):
            graph.add_nquads(
                aggregate_nquads(sensor.entity_id, sensor, QUARTER, start, values, name)
            )
    counting = CountingStore(graph._store)
    graph._store = counting  # type: ignore[assignment]

    run = asyncio.run(maintenance.run(NOW))

    assert run.removed_aggregates[QUARTER] == 5 and not run.compacted
    assert counting.flushes == 1
    assert _starts(graph, QUARTER) == ["2026-09-20T10:00:00Z"] * 5


def test_memory_gained_by_each_step_is_recorded_and_logged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Mémoire utilisée relevée avant et après chaque étape (brut, périodes, compactage)."""
    maintenance, _, graph = _maintenance(tmp_path, NOW)
    monkeypatch.setattr(graph, "optimize", lambda: None)
    _aggregate(graph, QUARTER, datetime(2026, 8, 20, 10, tzinfo=UTC))  # mois retiré : compactage
    save_retention(open_database(tmp_path), Retention(hour_days=366))
    readings = iter([100_000_000, 101_000_000, 131_000_000, 131_000_000, 120_000_000])
    monkeypatch.setattr(memory, "heap_used", lambda: next(readings))

    with caplog.at_level(logging.INFO, logger="wattslot.maintenance"):
        run = asyncio.run(maintenance.run(NOW))

    assert run.heap_used_steps == {
        "raw": 1_000_000,
        QUARTER: 30_000_000,
        HOUR: 0,
        "optimize": -11_000_000,
    }
    assert (
        "mémoire utilisée : brut +1 Mo, quarts d'heure +30 Mo, heures +0 Mo, compactage -11 Mo"
        in caplog.text
    )


def test_memory_steps_are_empty_without_glibc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    maintenance, _, _ = _maintenance(tmp_path, NOW)
    monkeypatch.setattr(memory, "heap_used", lambda: None)
    with caplog.at_level(logging.INFO, logger="wattslot.maintenance"):
        run = asyncio.run(maintenance.run(NOW))
    assert run.heap_used_steps == {}
    assert "mémoire utilisée" not in caplog.text


def test_directory_size_ignores_files_removed_while_measuring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "a.sst").write_bytes(b"12345")
    (tmp_path / "b.sst").write_bytes(b"123")
    stat = Path.stat

    def flaky_stat(self: Path, *, follow_symlinks: bool = True) -> os.stat_result:
        if self.name == "b.sst":
            raise FileNotFoundError(self)
        return stat(self, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(Path, "stat", flaky_stat)

    assert directory_size(tmp_path) == 5
    assert directory_size(tmp_path / "absent") == 0


def test_whole_expired_months_are_removed_in_one_go(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Première maintenance après le passage des heures à 15 mois : des années à retirer. Les
    mois entièrement échus partent d'un bloc avec un seul ``flush`` pour tous (deux fois moins
    d'écritures au banc que capteur par capteur) ; seul le mois entamé est vidé capteur par
    capteur."""
    maintenance, _, graph = _maintenance(tmp_path, NOW)
    for month in (3, 4, 5):  # 2025, entièrement échus (limite : le 16/07/2025 à minuit)
        _aggregate(graph, HOUR, datetime(2025, month, 10, 10, tzinfo=UTC))
        _aggregate(graph, HOUR, datetime(2025, month, 20, 10, tzinfo=UTC))
    _aggregate(graph, HOUR, datetime(2025, 7, 10, 10, tzinfo=UTC))  # mois entamé, échu
    _aggregate(graph, HOUR, datetime(2025, 7, 20, 10, tzinfo=UTC))  # mois entamé, gardé
    _aggregate(graph, HOUR, datetime(2026, 10, 1, 10, tzinfo=UTC))
    flushes: list[bool] = []
    updates: list[str] = []
    real_flush, real_update = graph.flush, graph.update

    def update(sparql: str, flush: bool = True) -> None:
        updates.append(sparql)
        real_update(sparql, flush)

    def flush() -> None:
        flushes.append(True)
        real_flush()

    monkeypatch.setattr(graph, "flush", flush)
    monkeypatch.setattr(graph, "update", update)

    run = asyncio.run(maintenance.run(NOW))

    assert run.removed_aggregates == {QUARTER: 0, HOUR: 7}
    assert run.compacted
    assert _starts(graph, HOUR) == ["2025-07-20T10:00:00Z", "2026-10-01T10:00:00Z"]
    kept = [g.rsplit("/", 1)[1] for g in graph.named_graphs(f"{BASE}/graph/aggregates/{HOUR}/")]
    assert kept == ["2025-07", "2026-10"]
    # Un flush pour les trois mois entiers, un pour le mois entamé ; une suppression par requête
    # pour le seul capteur du mois entamé.
    assert len(flushes) == 2
    assert len(updates) == 1 and "2025-07" in updates[0]


def test_hours_without_limit_are_never_removed(tmp_path: Path) -> None:
    maintenance, _, graph = _maintenance(tmp_path, NOW)
    _aggregate(graph, HOUR, datetime(2020, 1, 1, 10, tzinfo=UTC))
    save_retention(open_database(tmp_path), Retention(hour_days=None))

    run = asyncio.run(maintenance.run(NOW))

    assert run.removed_aggregates == {QUARTER: 0}
    assert _starts(graph, HOUR) == ["2020-01-01T10:00:00Z"]
