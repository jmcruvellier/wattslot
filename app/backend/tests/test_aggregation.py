"""Agrégats au quart d'heure et à l'heure, calculés sur les relevés bruts."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import ClassVar, cast
from zoneinfo import ZoneInfo

import pytest

from tests.fake_home_assistant import default_responses, fake_home_assistant, running_client
from wattslot import aggregation
from wattslot.aggregation import (
    HOUR,
    QUARTER,
    Aggregator,
    Carry,
    compute,
    period_start,
)
from wattslot.detection import Role
from wattslot.ingestion import Ingestor, Target
from wattslot.storage.database import open_database
from wattslot.storage.graph import GraphStore
from wattslot.storage.raw import RawStores, Reading

T0 = datetime(2026, 10, 15, 10, 0, tzinfo=UTC)
QUARTER_END = T0 + timedelta(minutes=15)


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


# --- Calcul d'une période --------------------------------------------------------------------


def test_counter_energy_is_the_difference_of_readings() -> None:
    values, carry = compute(
        Role.ENERGY_IMPORTED, T0, QUARTER_END, Carry(at(-3), 10.0), [(at(5), 10.2), (at(9), 10.5)]
    )

    assert values is not None and values.energy_kwh is not None
    assert round(values.energy_kwh, 6) == 0.5
    assert carry == Carry(at(9), 10.5)


def test_counter_reset_and_small_dips() -> None:
    points = [(at(1), 0.1), (at(2), 0.3), (at(3), 0.29), (at(4), 0.4)]  # remise à zéro, creux

    values, _ = compute(Role.ENERGY_PRODUCED, T0, QUARTER_END, Carry(at(-1), 5.0), points)

    assert values is not None and values.energy_kwh is not None
    assert round(values.energy_kwh, 6) == 0.4


def test_first_counter_reading_is_the_baseline() -> None:
    values, _ = compute(Role.ENERGY_PRODUCED, T0, QUARTER_END, None, [(at(1), 3.0), (at(4), 3.2)])

    assert values is not None and values.energy_kwh is not None
    assert round(values.energy_kwh, 6) == 0.2


def test_power_mean_is_weighted_by_duration() -> None:
    values, carry = compute(
        Role.POWER_CONSUMED, T0, QUARTER_END, Carry(at(-20), 100.0), [(at(5), 400.0)]
    )

    assert values is not None
    assert values.mean == 300.0  # 5 min à 100 W, 10 min à 400 W
    assert values.maximum == 400.0
    assert values.last == 400.0  # valeur en fin de quart d'heure
    assert carry == Carry(at(5), 400.0)


def test_constant_power_is_carried_over() -> None:
    values, _ = compute(Role.POWER_PRODUCED, T0, QUARTER_END, Carry(at(-60), 250.0), [])

    assert values is not None
    assert (values.mean, values.maximum) == (250.0, 250.0)


def test_nothing_known_gives_no_aggregate() -> None:
    assert compute(Role.POWER_PRODUCED, T0, QUARTER_END, None, []) == (None, None)
    assert compute(Role.ENERGY_PRODUCED, T0, QUARTER_END, None, []) == (None, None)


def test_periods_follow_the_local_time() -> None:
    kolkata = ZoneInfo("Asia/Kolkata")  # UTC+5:30
    moment = datetime(2026, 10, 15, 10, 47, tzinfo=UTC)  # 16h17 à Calcutta

    assert period_start(moment, timedelta(hours=1), kolkata) == datetime(
        2026, 10, 15, 10, 30, tzinfo=UTC
    )
    assert period_start(moment, timedelta(minutes=15), kolkata) == datetime(
        2026, 10, 15, 10, 45, tzinfo=UTC
    )


# --- Agrégation sur le brut ------------------------------------------------------------------

POWER = Target("sensor.p", "urn:sensor:p", Role.POWER_CONSUMED)
ENERGY = Target("sensor.e", "urn:sensor:e", Role.ENERGY_CONSUMED)


class StubIngestor:
    backfilling = False
    targets: ClassVar[dict[str, Target]] = {POWER.entity_id: POWER, ENERGY.entity_id: ENERGY}


def _aggregator(tmp_path: Path, raw: RawStores, graph: GraphStore) -> Aggregator:
    # Un seul magasin par dossier (verrou de RocksDB), comme dans l'application.
    return Aggregator(cast(Ingestor, StubIngestor()), raw, graph, open_database(tmp_path))


def test_aggregates_closed_periods_and_resumes_after_a_restart(tmp_path: Path) -> None:
    graph = GraphStore(tmp_path)
    raw = RawStores(tmp_path, "Europe/Paris")
    raw.write(
        [
            Reading(POWER.entity_id, POWER.sensor_iri, 1000.0, at(0)),
            Reading(POWER.entity_id, POWER.sensor_iri, 2000.0, at(7.5)),
            Reading(ENERGY.entity_id, ENERGY.sensor_iri, 1.0, at(0)),
            Reading(ENERGY.entity_id, ENERGY.sensor_iri, 1.25, at(10)),
            Reading(ENERGY.entity_id, ENERGY.sensor_iri, 1.5, at(20)),
        ]
    )

    async def scenario() -> tuple[int, int, int]:
        first = _aggregator(tmp_path, raw, graph)
        written = await first.step(at(31.5))  # quarts d'heure de 10h00 et 10h15 clos
        again = await first.step(at(31.5))
        restarted = _aggregator(tmp_path, raw, graph)  # redémarrage : reprend où il en était
        later = await restarted.step(at(61.5))
        return written, again, later

    written, again, later = asyncio.run(scenario())

    assert (written, again) == (4, 0)
    assert later == 4 + 2  # quarts d'heure de 10h30 et 10h45, heure de 10h00
    aggregator = _aggregator(tmp_path, raw, graph)
    quarters = aggregator.read(POWER.entity_id, QUARTER, T0, at(60))
    assert [(a.start, a.mean, a.max) for a in quarters] == [
        (at(0), 1500.0, 2000.0),
        (at(15), 2000.0, 2000.0),
        (at(30), 2000.0, 2000.0),  # valeur reportée, gardée en base au redémarrage
        (at(45), 2000.0, 2000.0),
    ]
    energy = aggregator.read(ENERGY.entity_id, QUARTER, T0, at(60))
    assert [a.energy_kwh for a in energy] == [0.25, 0.25, 0.0, 0.0]
    hours = aggregator.read(POWER.entity_id, HOUR, T0, at(60))
    assert [(a.mean, a.max) for a in hours] == [(1875.0, 2000.0)]
    assert [a.last for a in quarters] == [2000.0] * 4  # relue dans le magasin
    assert [a.energy_kwh for a in aggregator.read(ENERGY.entity_id, HOUR, T0, at(60))] == [0.5]


# --- Reprise de l'historique de HA -----------------------------------------------------------

SOC = Target("sensor.soc", "urn:sensor:soc", Role.STATE_OF_CHARGE)  # sans statistiques


class StubIngestorWithSoc:
    backfilling = False
    targets: ClassVar[dict[str, Target]] = {
        POWER.entity_id: POWER,
        ENERGY.entity_id: ENERGY,
        SOC.entity_id: SOC,
    }


def _stat(minutes: float, **values: float) -> dict[str, float]:
    return {"start": at(minutes).timestamp() * 1000, **values}


STATISTICS = {
    (POWER.entity_id, "5minute"): [
        _stat(-30, mean=100, max=150),
        _stat(-25, mean=200, max=250),
        _stat(-20, mean=300, max=350),
        _stat(0, mean=999, max=999),  # déjà calculé sur le brut
        _stat(30, mean=999, max=999),  # pas encore clos pour l'agrégation
    ],
    (POWER.entity_id, "hour"): [
        _stat(-120, mean=500, max=600),
        _stat(-60, mean=700, max=800),
        _stat(0, mean=999, max=999),
    ],
    (ENERGY.entity_id, "5minute"): [_stat(-15, change=0.1), _stat(-10, change=0.2)],
    (ENERGY.entity_id, "hour"): [_stat(-60, change=0.4)],
}


def test_imports_home_assistant_statistics_before_the_raw_readings(tmp_path: Path) -> None:
    graph = GraphStore(tmp_path)
    raw = RawStores(tmp_path, "Europe/Paris")
    raw.write(
        [
            Reading(POWER.entity_id, POWER.sensor_iri, 1000.0, at(0)),
            Reading(ENERGY.entity_id, ENERGY.sensor_iri, 1.0, at(0)),
            Reading(ENERGY.entity_id, ENERGY.sensor_iri, 1.25, at(10)),
        ]
    )
    requests: list[dict[str, object]] = []
    database = open_database(tmp_path)
    with database:  # journal des cycles calculé avant la reprise : sur les agrégats et le brut
        database.executemany(
            "INSERT INTO appliance_days VALUES (?, ?, ?, '[]')",
            [("lave-linge", "2026-09-01", "quarters"), ("lave-linge", "2026-09-02", "raw")],
        )

    def statistics(message: dict[str, object]) -> dict[str, object]:
        requests.append(message)
        (entity_id,) = cast(list[str], message["statistic_ids"])
        return {entity_id: STATISTICS.get((entity_id, cast(str, message["period"])), [])}

    responses = default_responses()
    responses["recorder/statistics_during_period"] = statistics

    async def scenario() -> tuple[int, int, int, int, Aggregator]:
        async with running_client(fake_home_assistant(responses)) as client:
            aggregator = Aggregator(
                cast(Ingestor, StubIngestorWithSoc()), raw, graph, open_database(tmp_path), client
            )
            before = await aggregator.import_history()  # rien tant que le brut n'est pas calculé
            await aggregator.step(at(31.5))
            first = await aggregator.import_history(limit=1)  # une entité par tour
            imported = first + await aggregator.import_history()
            again = await aggregator.import_history()
            return before, first, imported, again, aggregator

    before, first, imported, again, aggregator = asyncio.run(scenario())

    assert (before, first, imported, again) == (0, 1, 3, 0)
    # Journées calculées sur les agrégats d'avant la reprise : oubliées, recalculées à la demande.
    days = database.execute("SELECT day, source FROM appliance_days").fetchall()
    assert days == [("2026-09-02", "raw")]
    quarters = aggregator.read(POWER.entity_id, QUARTER, at(-60), at(30))
    assert [(a.start, a.mean, a.max) for a in quarters] == [
        (at(-30), 200.0, 350.0),  # trois statistiques à 5 minutes
        (at(0), 1000.0, 1000.0),  # calculé sur le brut, pas remplacé
        (at(15), 1000.0, 1000.0),
    ]
    hours = aggregator.read(POWER.entity_id, HOUR, at(-180), at(60))
    assert [(a.start, a.mean, a.max) for a in hours] == [
        (at(-120), 500.0, 600.0),
        (at(-60), 700.0, 800.0),
    ]
    energy = aggregator.read(ENERGY.entity_id, QUARTER, at(-60), at(0))
    assert [a.start for a in energy] == [at(-15)]
    assert energy[0].energy_kwh == 0.3  # arrondi : 0.1 + 0.2 = 0.30000000000000004
    assert [a.energy_kwh for a in aggregator.read(ENERGY.entity_id, HOUR, at(-60), at(0))] == [0.4]
    counter_request = next(r for r in requests if r["statistic_ids"] == [ENERGY.entity_id])
    assert counter_request["types"] == ["change"]
    assert counter_request["units"] == {"energy": "kWh", "power": "W"}
    history = aggregator.status().history
    assert (history.imported, history.pending) == (3, [])
    assert history.without_statistics == [SOC.entity_id]
    assert history.since == {QUARTER: at(-30), HOUR: at(-120)}


def _import_one_then_all(
    tmp_path: Path,
) -> tuple[tuple[int, list[datetime]], tuple[int, list[datetime]]]:
    """Reprise d'une entité puis des autres : (entités notées, heures lues) après chaque appel."""
    graph = GraphStore(tmp_path)
    raw = RawStores(tmp_path, "Europe/Paris")
    raw.write([Reading(POWER.entity_id, POWER.sensor_iri, 1000.0, at(0))])

    def statistics(message: dict[str, object]) -> dict[str, object]:
        (entity_id,) = cast(list[str], message["statistic_ids"])
        return {entity_id: STATISTICS.get((entity_id, cast(str, message["period"])), [])}

    responses = default_responses()
    responses["recorder/statistics_during_period"] = statistics

    async def scenario() -> tuple[tuple[int, list[datetime]], tuple[int, list[datetime]]]:
        async with running_client(fake_home_assistant(responses)) as client:
            aggregator = Aggregator(
                cast(Ingestor, StubIngestorWithSoc()), raw, graph, open_database(tmp_path), client
            )
            await aggregator.step(at(31.5))
            found = []
            for limit in (1, None):
                await aggregator.import_history(limit=limit)
                hours = aggregator.read(POWER.entity_id, HOUR, at(-180), at(0))
                found.append((aggregator.status().history.imported, [a.start for a in hours]))
            return found[0], found[1]

    return asyncio.run(scenario())


def test_history_waits_for_a_full_batch_before_writing(tmp_path: Path) -> None:
    """Agrégats de plusieurs entités écrits ensemble ; une entité n'est notée reprise qu'une fois
    ses agrégats écrits (un arrêt avant l'écriture la fait reprendre au démarrage suivant)."""
    first, last = _import_one_then_all(tmp_path)

    assert first == (0, [])  # en attente : rien d'écrit, rien de noté
    assert last == (3, [at(-120), at(-60)])


def test_history_batches_split_across_entities(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(aggregation, "IMPORT_BATCH", 2)

    first, last = _import_one_then_all(tmp_path)

    # Trois agrégats (un quart d'heure, deux heures) : un lot de deux écrit, le dernier en
    # attente des entités suivantes ; l'entité n'est pas encore notée.
    assert first == (0, [at(-120)])
    assert last == (3, [at(-120), at(-60)])


def test_imports_history_before_the_first_period_closes(tmp_path: Path) -> None:
    """Installation démarrée juste après minuit : le brut commence à minuit, aucune heure n'est
    close, mais la reprise de l'historique n'attend pas la fin de la première heure."""
    midnight = datetime(2026, 10, 15, 22, 0, tzinfo=UTC)  # 16/10 à 0 h à Paris
    graph = GraphStore(tmp_path)
    raw = RawStores(tmp_path, "Europe/Paris")
    raw.write([Reading(POWER.entity_id, POWER.sensor_iri, 1000.0, midnight + timedelta(minutes=2))])

    def statistics(message: dict[str, object]) -> dict[str, object]:
        (entity_id,) = cast(list[str], message["statistic_ids"])
        return {entity_id: STATISTICS.get((entity_id, cast(str, message["period"])), [])}

    responses = default_responses()
    responses["recorder/statistics_during_period"] = statistics

    async def scenario() -> tuple[int, Aggregator]:
        async with running_client(fake_home_assistant(responses)) as client:
            aggregator = Aggregator(
                cast(Ingestor, StubIngestorWithSoc()), raw, graph, open_database(tmp_path), client
            )
            written = await aggregator.step(midnight + timedelta(minutes=10))
            assert written == 0  # ni quart d'heure ni heure clos
            return await aggregator.import_history(), aggregator

    imported, aggregator = asyncio.run(scenario())

    assert imported == 3
    assert aggregator.status().history.pending == []
    hours = aggregator.read(POWER.entity_id, HOUR, at(-180), midnight)
    assert [a.start for a in hours] == [at(-120), at(-60), at(0)]
