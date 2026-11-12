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
    GLITCH_MAX,
    HOUR,
    QUARTER,
    Aggregator,
    Carry,
    Drop,
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


def test_a_meter_dropping_to_zero_an_instant_is_not_a_reset() -> None:
    """Compteur coupé un instant (0 envoyé, puis l'index) : seule la hausse réelle compte."""
    points = [(at(1), 23147.10), (at(3), 0.0), (at(4), 23147.15), (at(9), 23147.20)]

    values, carry = compute(Role.ENERGY_IMPORTED, T0, QUARTER_END, Carry(at(-1), 23147.0), points)

    assert values is not None and values.energy_kwh is not None
    assert round(values.energy_kwh, 6) == 0.2
    assert carry == Carry(at(9), 23147.2)


def test_a_dropped_meter_back_in_the_next_period_is_not_counted_either() -> None:
    first, carry = compute(
        Role.ENERGY_IMPORTED, T0, QUARTER_END, Carry(at(-1), 23147.0), [(at(14), 0.0)]
    )
    assert carry is not None and carry.drop == Drop(at(14), 23147.0)

    second, carry = compute(Role.ENERGY_IMPORTED, QUARTER_END, at(30), carry, [(at(17), 23147.05)])

    assert first is not None and second is not None
    assert (first.energy_kwh, round(second.energy_kwh or 0, 6)) == (0.0, 0.05)
    assert carry == Carry(at(17), 23147.05)


def test_a_meter_spiking_high_an_instant_is_not_counted() -> None:
    """Relevé fantôme haut un instant (redémarrage de Home Assistant : index erroné, puis retour
    à l'index) : ni la hausse ni le retour ne comptent — comme une coupure à l'envers."""
    points = [(at(1), 23147.10), (at(3), 26000.0), (at(4), 23147.15), (at(9), 23147.20)]

    values, carry = compute(Role.ENERGY_IMPORTED, T0, QUARTER_END, Carry(at(-1), 23147.0), points)

    assert values is not None and values.energy_kwh is not None
    assert round(values.energy_kwh, 6) == 0.2
    assert carry == Carry(at(9), 23147.2)


def test_an_impossible_index_jump_is_ignored() -> None:
    """Saut d'index physiquement impossible (redémarrage de HA, quelle que soit la durée de
    l'excursion) : le relevé est ignoré et la base ne bouge pas — le retour à l'index réel
    compte normalement, aucune heure géante n'est produite."""
    points = [(at(1), 100.0), (at(2), 5000.0), (at(3), 100.2), (at(9), 100.3)]

    values, carry = compute(Role.ENERGY_IMPORTED, T0, QUARTER_END, Carry(at(-1), 100.0), points)

    assert values is not None and values.energy_kwh is not None
    assert round(values.energy_kwh, 6) == 0.3
    assert carry == Carry(at(9), 100.3)


def test_a_high_reading_that_stays_is_counted() -> None:
    """Une hausse qui ne revient pas dans le délai de glitch était réelle : elle reste comptée."""
    points = [(at(1), 100.0), (at(2), 106.0), (at(2) + GLITCH_MAX + timedelta(seconds=1), 106.5)]

    values, carry = compute(Role.ENERGY_IMPORTED, T0, at(30), Carry(at(-1), 100.0), points)

    assert values is not None and values.energy_kwh is not None
    assert round(values.energy_kwh, 6) == 6.5
    assert carry == Carry(at(2) + GLITCH_MAX + timedelta(seconds=1), 106.5)


def test_a_reset_stays_a_reset_after_the_glitch_delay_or_for_a_small_counter() -> None:
    late = [(at(1), 0.0), (at(1) + GLITCH_MAX + timedelta(seconds=1), 30.0)]
    values, carry = compute(Role.ENERGY_PRODUCED, T0, at(30), Carry(at(0), 30.0), late)
    assert values is not None and values.energy_kwh == 30.0  # remise à zéro, puis 30 kWh
    assert carry is not None and carry.drop is None

    # Petit compteur quotidien remis à zéro qui remonte vite : pas une coupure.
    small = [(at(1), 0.0), (at(2), 0.6), (at(3), 1.2)]
    values, _ = compute(Role.ENERGY_CONSUMED, T0, QUARTER_END, Carry(at(0), 1.3), small)
    assert values is not None and round(values.energy_kwh or 0, 6) == 1.2


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
    ready = True
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
    ready = True
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


def test_nothing_is_closed_until_the_raw_readings_are_complete(tmp_path: Path) -> None:
    """Avant la connexion à HA et la reprise du trou : aucune période close, sinon celles du
    trou le seraient à vide et les relevés repris ensuite jamais agrégés."""
    graph = GraphStore(tmp_path)
    raw = RawStores(tmp_path, "Europe/Paris")
    raw.write([Reading(ENERGY.entity_id, ENERGY.sensor_iri, 1.0, at(0))])
    waiting = StubIngestor()
    waiting.ready = False
    aggregator = Aggregator(cast(Ingestor, waiting), raw, graph, open_database(tmp_path))

    async def scenario() -> tuple[int, int]:
        before = await aggregator.step(at(31.5))
        raw.write([Reading(ENERGY.entity_id, ENERGY.sensor_iri, 1.5, at(20))])  # trou repris
        waiting.ready = True
        return before, await aggregator.step(at(31.5))

    before, after = asyncio.run(scenario())

    assert before == 0
    assert after > 0
    energy = aggregator.read(ENERGY.entity_id, QUARTER, T0, at(30))
    assert [a.energy_kwh for a in energy] == [0.0, 0.5]


# --- Statistiques externes du tableau Énergie (issue #224) ------------------------------------

LINKY = Target("linky:grid_import", "urn:sensor:linky", Role.ENERGY_IMPORTED)


class StubIngestorWithStatistic:
    ready = True
    targets: ClassVar[dict[str, Target]] = {ENERGY.entity_id: ENERGY, LINKY.entity_id: LINKY}


def test_external_statistics_are_followed_hour_after_hour(tmp_path: Path) -> None:
    """Pas de brut pour une statistique externe : ses agrégats viennent des statistiques de HA,
    relues régulièrement depuis la dernière heure reçue ; une heure publiée en retard (Linky,
    la veille) est reprise, une heure pas encore reçue reste sans agrégat."""
    graph = GraphStore(tmp_path)
    raw = RawStores(tmp_path, "Europe/Paris")
    raw.write([Reading(ENERGY.entity_id, ENERGY.sensor_iri, 1.0, at(0))])
    published = [_stat(-180, change=0.5), _stat(-120, change=0.7)]
    requests: list[dict[str, object]] = []

    def statistics(message: dict[str, object]) -> dict[str, object]:
        requests.append(message)
        (entity_id,) = cast(list[str], message["statistic_ids"])
        if entity_id != LINKY.entity_id or message["period"] != "hour":
            return {entity_id: []}
        start = datetime.fromisoformat(cast(str, message["start_time"]))
        rows = [r for r in published if r["start"] >= start.timestamp() * 1000]
        return {entity_id: rows}

    responses = default_responses()
    responses["recorder/statistics_during_period"] = statistics

    async def scenario() -> tuple[int, int, int, int, Aggregator]:
        async with running_client(fake_home_assistant(responses)) as client:
            aggregator = Aggregator(
                cast(Ingestor, StubIngestorWithStatistic()),
                raw,
                graph,
                open_database(tmp_path),
                client,
            )
            await aggregator.step(at(61.5))  # le brut ne fait pas avancer la statistique
            first = await aggregator.follow_statistics(at(61.5))
            soon = await aggregator.follow_statistics(at(65))  # moins d'un quart d'heure après
            published.append(_stat(-60, change=0.9))  # heure publiée en retard
            late = await aggregator.follow_statistics(at(80))
            again = await aggregator.follow_statistics(at(100))
            return first, soon, late, again, aggregator

    first, soon, late, again, aggregator = asyncio.run(scenario())

    assert (first, soon, late, again) == (2, 0, 1, 0)
    hours = aggregator.read(LINKY.entity_id, HOUR, at(-240), at(60))
    assert [(a.start, a.energy_kwh) for a in hours] == [
        (at(-180), 0.5),
        (at(-120), 0.7),
        (at(-60), 0.9),
    ]
    assert aggregator.read(LINKY.entity_id, HOUR, at(0), at(60)) == []  # pas encore reçue
    linky = [r for r in requests if r["statistic_ids"] == [LINKY.entity_id]]
    assert cast(str, linky[0]["start_time"]).startswith(
        "2000-"
    )  # première fois : tout l'historique
    lookback = datetime.fromisoformat(cast(str, linky[-1]["start_time"]))
    assert lookback == at(0) - aggregation.FOLLOW_LOOKBACK  # depuis la dernière heure reçue
    status = aggregator.status()
    assert status.statistics_until == {LINKY.entity_id: at(0)}
    assert LINKY.entity_id not in status.history.pending  # reprise notée à la première relecture
    state = aggregator._state()
    assert (LINKY.entity_id, HOUR) not in state and (ENERGY.entity_id, HOUR) in state


def test_a_quarter_of_an_external_statistic_waits_for_its_three_statistics(
    tmp_path: Path,
) -> None:
    """Statistiques à 5 minutes d'une statistique externe : un quart d'heure n'est repris qu'un
    quart d'heure après sa fin, quand ses trois statistiques sont publiées."""
    graph = GraphStore(tmp_path)
    raw = RawStores(tmp_path, "Europe/Paris")
    published = [_stat(0, change=0.1), _stat(5, change=0.1)]  # la troisième pas encore là

    def statistics(message: dict[str, object]) -> dict[str, object]:
        (entity_id,) = cast(list[str], message["statistic_ids"])
        if entity_id != LINKY.entity_id or message["period"] != "5minute":
            return {entity_id: []}
        return {entity_id: list(published)}

    responses = default_responses()
    responses["recorder/statistics_during_period"] = statistics

    async def scenario() -> Aggregator:
        async with running_client(fake_home_assistant(responses)) as client:
            aggregator = Aggregator(
                cast(Ingestor, StubIngestorWithStatistic()),
                raw,
                graph,
                open_database(tmp_path),
                client,
            )
            assert await aggregator.follow_statistics(at(16)) == 0  # quart d'heure tout juste clos
            published.append(_stat(10, change=0.1))
            assert await aggregator.follow_statistics(at(31)) == 1
            return aggregator

    aggregator = asyncio.run(scenario())

    quarters = aggregator.read(LINKY.entity_id, QUARTER, at(0), at(30))
    assert [(a.start, a.energy_kwh) for a in quarters] == [(at(0), 0.3)]
