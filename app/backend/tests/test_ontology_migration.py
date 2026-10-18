"""Migration de l'espace de noms d'avant WattSlot (lot 7.1)."""

import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from wattslot.ontology import (
    BASE,
    GRAPH_CONFIGURATION,
    GRAPH_HOME,
    HOME,
    LEGACY_BASE,
    LEGACY_HOME,
    VOCAB,
)
from wattslot.ontology.migration import drop_legacy_aggregates, migrate, migrate_raw, renamed
from wattslot.storage.database import open_database
from wattslot.storage.graph import GraphStore
from wattslot.storage.raw import RawStores, Reading

RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
OLD = f"{LEGACY_BASE}#"


def _legacy_store(tmp_path: Path, aggregates: int = 3) -> GraphStore:
    graph = GraphStore(tmp_path)
    home = f"<{LEGACY_BASE}/graph/home>"
    configuration = f"<{LEGACY_BASE}/graph/configuration>"
    lines = [
        f"<{LEGACY_HOME}home> <{RDF_TYPE}> <{OLD}Home> {home} .",
        f"<{LEGACY_HOME}home> <{OLD}hasDevice> <{LEGACY_HOME}device/lave-linge> {home} .",
        f'<{LEGACY_HOME}device/lave-linge> <{OLD}key> "lave-linge" {home} .',
        f'_:settings <{OLD}behavior> "cycle" {configuration} .',
        f"<{LEGACY_BASE}/a> <{OLD}b> <{OLD}c> <{LEGACY_BASE}/graph/schema> .",
    ]
    month = f"<{LEGACY_BASE}/graph/aggregates/PT1H/2026-10>"
    for k in range(aggregates):
        lines.append(f"<{LEGACY_HOME}agg/PT1H/s/{k}> <{RDF_TYPE}> <{OLD}Aggregate> {month} .")
        lines.append(f'<{LEGACY_HOME}agg/PT1H/s/{k}> <{OLD}energyKwh> "{k}" {month} .')
    graph.add_nquads("\n".join(lines) + "\n")
    return graph


def test_iris_of_the_former_namespace_are_renamed() -> None:
    assert renamed(f"{LEGACY_BASE}#Home") == f"{BASE}#Home" == f"{VOCAB}Home"
    assert renamed(f"{LEGACY_HOME}device/x") == f"{HOME}device/x"
    assert renamed("https://www.w3.org/ns/sosa/Sensor") == "https://www.w3.org/ns/sosa/Sensor"


def test_home_and_configuration_are_rewritten_and_history_reimported(tmp_path: Path) -> None:
    graph = _legacy_store(tmp_path)
    database = open_database(tmp_path)
    with database:
        database.execute("INSERT INTO history_import VALUES ('sensor.x', 'now', 1, NULL, 1, NULL)")

    assert migrate(graph, database)

    home = {(str(q.subject), str(q.predicate), str(q.object)) for q in graph.quads(GRAPH_HOME)}
    assert (f"<{HOME}home>", f"<{VOCAB}hasDevice>", f"<{HOME}device/lave-linge>") in home
    assert (f"<{HOME}device/lave-linge>", f"<{VOCAB}key>", '"lave-linge"') in home
    assert [str(q.predicate) for q in graph.quads(GRAPH_CONFIGURATION)] == [f"<{VOCAB}behavior>"]
    # Bibliothèque et schéma retirés ; restent les anciens agrégats, vidés ensuite.
    assert graph.named_graphs(f"{LEGACY_BASE}/graph/") == [
        f"{LEGACY_BASE}/graph/aggregates/PT1H/2026-10"
    ]
    assert database.execute("SELECT COUNT(*) FROM history_import").fetchone() == (0,)
    # Redémarrage avant la fin du nettoyage : rien à refaire, la reprise n'est pas relancée.
    with database:
        database.execute("INSERT INTO history_import VALUES ('sensor.x', 'now', 1, NULL, 1, NULL)")
    assert not migrate(graph, database)
    assert database.execute("SELECT COUNT(*) FROM history_import").fetchone() == (1,)


def test_former_aggregates_are_dropped_in_batches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("wattslot.ontology.migration.DROP_BATCH", 2)
    graph = _legacy_store(tmp_path, aggregates=5)

    assert drop_legacy_aggregates(graph) == 5
    assert graph.named_graphs(LEGACY_BASE) == [
        f"{LEGACY_BASE}/graph/configuration",
        f"{LEGACY_BASE}/graph/home",
        f"{LEGACY_BASE}/graph/schema",
    ]
    assert drop_legacy_aggregates(graph) == 0


def test_dropping_stops_with_the_application(tmp_path: Path) -> None:
    graph = _legacy_store(tmp_path)
    stop = threading.Event()
    stop.set()

    assert drop_legacy_aggregates(graph, stop) == 0
    assert graph.named_graphs(f"{LEGACY_BASE}/graph/aggregates/")


def test_a_wattslot_store_has_nothing_to_migrate(tmp_path: Path) -> None:
    assert not migrate(GraphStore(tmp_path), open_database(tmp_path))


def test_raw_readings_follow_the_renamed_sensors(tmp_path: Path) -> None:
    """Relevés bruts d'avant la migration : sans réécriture, ils ne correspondent plus à la maison
    et les données réelles du jour restent vides (constaté le 18/10/2026)."""
    raw = RawStores(tmp_path)
    when = datetime(2026, 10, 18, 9, 0, tzinfo=UTC)
    raw.write(
        [
            Reading("sensor.pv", f"{LEGACY_HOME}sensor/pv", 1.5, when),
            Reading("sensor.pv", f"{LEGACY_HOME}sensor/pv", 1.7, when + timedelta(minutes=5)),
            Reading("sensor.grid", f"{HOME}sensor/grid", 0.2, when),
        ]
    )

    assert migrate_raw(raw) == 1
    sensors = {iri for iri, _, _ in raw.readings(when, when + timedelta(hours=1))}
    assert sensors == {f"{HOME}sensor/pv", f"{HOME}sensor/grid"}
    assert len(raw.readings(when, when + timedelta(hours=1))) == 3
    assert migrate_raw(raw) == 0  # déjà migrés : rien à refaire
