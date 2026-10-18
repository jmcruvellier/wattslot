"""Conservation et maintenance : brut par journée, agrégats échus, réglages."""

import asyncio
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

import pytest

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
    assert load_retention(database) == Retention(raw_days=3, quarter_days=35, hour_days=None)

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
    assert _starts(graph, QUARTER) == ["2026-09-15T10:00:00Z", "2026-10-01T10:00:00Z"]
    assert _starts(graph, HOUR) == []
    assert f"{BASE}/graph/aggregates/{HOUR}/2025-01" not in graph.named_graphs()
    status = maintenance.status()
    assert status.last_run == run
    assert status.disk.raw_bytes > 0 and status.disk.graph_bytes > 0


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
