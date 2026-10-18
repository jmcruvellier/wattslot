"""Banc des écritures disque de la reprise de l'historique de HA (lot 7.1).

    python dev/tools/bench_import.py [--sensors 12] [--since 2023-09-01] [--quarter-days 30]
                                     [--legacy 0] [--batch N]

Rejoue la reprise de l'historique (``Aggregator.import_history``, statistiques de HA simulées)
pour ``--sensors`` capteurs, moitié compteurs, moitié puissances : heures depuis ``--since``,
quarts d'heure sur ``--quarter-days`` jours (la maison de référence : 83 capteurs, 1,27 million
d'agrégats). Avec ``--legacy N``, le magasin contient d'abord ``N`` agrégats de l'ancien espace
de noms, vidés ensuite comme au démarrage (``drop_legacy_aggregates``) : coût mesuré à part.

Compte les octets écrits par le processus (compactages de RocksDB compris, attendus jusqu'au
calme) et les rapporte au volume du magasin sur disque et au nombre d'agrégats. À lancer avec
l'environnement du backend (``app/backend/.venv``).
"""

import argparse
import asyncio
import json
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from zoneinfo import ZoneInfo

from bench_writes import peak_memory_mb, written_bytes

from wattslot import aggregation, history
from wattslot.aggregation import (
    HOUR,
    PERIODS,
    QUARTER,
    Aggregator,
    Values,
    aggregate_nquads,
    graph_iri,
)
from wattslot.detection import Role
from wattslot.home_assistant import ConnectionState, HomeAssistantClient
from wattslot.ingestion import Ingestor, Target
from wattslot.ontology import BASE, HOME, LEGACY_BASE, LEGACY_HOME
from wattslot.ontology.migration import drop_legacy_aggregates
from wattslot.storage.database import open_database
from wattslot.storage.graph import GRAPH_DIRNAME, GraphStore
from wattslot.storage.raw import RawStores

NOW = datetime(2026, 10, 18, 16, tzinfo=UTC)


def settle() -> int:
    """Octets écrits une fois les compactages de fond terminés (aucune écriture pendant 3 s)."""
    last, quiet = written_bytes(), 0
    while quiet < 3:
        time.sleep(1)
        current = written_bytes()
        quiet = quiet + 1 if current == last else 0
        last = current
    return last


def size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def statistics_of(since: datetime, quarter_days: int) -> Any:
    async def statistics(
        _client: object, entity_id: str, period: str, end: datetime, counter: bool
    ) -> list[dict[str, Any]]:
        step = timedelta(minutes=5) if period == QUARTER else timedelta(hours=1)
        moment = end - timedelta(days=quarter_days) if period == QUARTER else since
        rows = []
        k = 0
        while moment < end:
            value = (k % 97) / 10
            row = {"change": value} if counter else {"mean": value * 100, "max": value * 120}
            rows.append({"start": moment.timestamp() * 1000, **row})
            moment += step
            k += 1
        return rows

    return statistics


def fill_legacy(graph: GraphStore, count: int, sensors: int) -> None:
    """Agrégats horaires de l'ancien espace de noms (même forme), écrits en masse hors mesure."""
    zone = ZoneInfo("Europe/Paris")
    lines = []
    for k in range(count):
        start = NOW - timedelta(hours=k // sensors + 1)
        target = Target(
            f"sensor.s{k % sensors}",
            f"{HOME}sensor/s{k % sensors}",
            Role.POWER_CONSUMED,
        )
        values = Values(mean=k / 7, maximum=k / 3)
        nquads = aggregate_nquads(
            target.entity_id, target, HOUR, start, values, graph_iri(HOUR, start, zone)
        )
        lines.append(nquads.replace(BASE, LEGACY_BASE).replace(HOME, LEGACY_HOME))
    graph.bulk_add_nquads(lines)


def run(sensors: int, since: datetime, quarter_days: int, legacy: int) -> dict[str, float]:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = Path(tmp)
        graph = GraphStore(root)
        raw = RawStores(root, "Europe/Paris")
        database = open_database(root)
        roles = (Role.ENERGY_IMPORTED, Role.POWER_CONSUMED)
        targets = {
            f"sensor.s{i}": Target(f"sensor.s{i}", f"{HOME}sensor/s{i}", roles[i % 2])
            for i in range(sensors)
        }
        with database:
            database.executemany(
                "INSERT INTO aggregation_state VALUES (?, ?, ?, NULL, NULL)",
                [(e, p, NOW.isoformat()) for e in targets for p in PERIODS],
            )
        ingestor = SimpleNamespace(backfilling=False, targets=targets)
        client = SimpleNamespace(status=SimpleNamespace(state=ConnectionState.CONNECTED))
        aggregator = Aggregator(
            cast(Ingestor, ingestor),
            raw,
            graph,
            database,
            cast(HomeAssistantClient, client),
        )
        history.statistics = statistics_of(since, quarter_days)  # type: ignore[assignment]
        result: dict[str, float] = {"sensors": sensors}
        if legacy:
            fill_legacy(graph, legacy, sensors)
            before, began = settle(), time.perf_counter()
            drop_legacy_aggregates(graph)
            written = settle() - before
            result |= {
                "legacy_aggregates": legacy,
                "drop_written_mb": round(written / 1e6, 1),
                "drop_kb_per_aggregate": round(written / legacy / 1e3, 2),
                "drop_seconds": round(time.perf_counter() - began, 1),
            }
        store = root / GRAPH_DIRNAME
        size_before = size(store)
        before, began = settle(), time.perf_counter()
        asyncio.run(aggregator.import_history())
        seconds = time.perf_counter() - began
        written = settle() - before
        stored = size(store) - size_before
        aggregates = aggregator.status().written
        assert aggregates == len(targets) * (
            len(aggregator.read("sensor.s0", HOUR, since, NOW))
            + len(aggregator.read("sensor.s0", QUARTER, since, NOW))
        )
        database.close()
        del aggregator, graph
    return result | {
        "aggregates": aggregates,
        "written_mb": round(written / 1e6, 1),
        "store_mb": round(stored / 1e6, 1),
        "bytes_per_aggregate": round(written / aggregates),
        "amplification": round(written / stored, 1) if stored > 0 else 0.0,
        "seconds": round(seconds, 1),
        "peak_memory_mb": round(peak_memory_mb()),
        "import_batch": aggregation.IMPORT_BATCH,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sensors", type=int, default=12)
    parser.add_argument(
        "--since", type=datetime.fromisoformat, default=datetime(2023, 9, 1, tzinfo=UTC)
    )
    parser.add_argument("--quarter-days", type=int, default=30)
    parser.add_argument("--legacy", type=int, default=0)
    parser.add_argument("--batch", type=int, help="agrégats par écriture (défaut : l'application)")
    args = parser.parse_args()
    if args.batch is not None:
        aggregation.IMPORT_BATCH = args.batch
    since = args.since if args.since.tzinfo else args.since.replace(tzinfo=UTC)
    print(json.dumps(run(args.sensors, since, args.quarter_days, args.legacy), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
