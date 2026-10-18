"""Ingestion en temps réel : filtre, unités, magasins par jour, abonnement auprès d'un faux HA."""

import asyncio
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from tests.fake_home_assistant import (
    Subscriptions,
    default_responses,
    fake_home_assistant,
    running_client,
)
from wattslot.detection import DeviceKind, Role
from wattslot.home_model import HomeDevice, HomeModel, HomeSensor
from wattslot.ingestion import Ingestor, ReadingFilter, normalize, targets
from wattslot.storage.database import open_database
from wattslot.storage.raw import RawStores, Reading

T0 = datetime(2026, 10, 15, 10, 0, tzinfo=UTC)

MODEL = HomeModel(
    devices=[
        HomeDevice(
            key="solar",
            kind=DeviceKind.SOLAR,
            name="PV",
            sensors=[
                HomeSensor(entity_id="sensor.pv_energy", role=Role.ENERGY_PRODUCED),
                HomeSensor(entity_id="sensor.pv_power", role=Role.POWER_PRODUCED),
            ],
        )
    ]
)


# --- Filtre et unités ----------------------------------------------------------------------


def test_power_is_kept_on_a_clear_change_or_once_a_minute() -> None:
    f = ReadingFilter()
    keep = [
        f.keep(Role.POWER_PRODUCED, "p", 1000.0, T0),  # premier relevé
        f.keep(Role.POWER_PRODUCED, "p", 1020.0, T0 + timedelta(seconds=10)),  # < 5 %
        f.keep(Role.POWER_PRODUCED, "p", 1200.0, T0 + timedelta(seconds=20)),  # variation nette
        f.keep(Role.POWER_PRODUCED, "p", 1201.0, T0 + timedelta(seconds=30)),
        f.keep(Role.POWER_PRODUCED, "p", 1202.0, T0 + timedelta(seconds=81)),  # une minute
    ]
    assert keep == [True, False, True, False, True]


def test_small_powers_use_an_absolute_deadband() -> None:
    f = ReadingFilter()
    f.keep(Role.POWER_CONSUMED, "p", 2.0, T0)

    assert not f.keep(Role.POWER_CONSUMED, "p", 9.0, T0 + timedelta(seconds=5))
    assert f.keep(Role.POWER_CONSUMED, "p", 13.0, T0 + timedelta(seconds=10))


def test_counters_at_most_once_a_minute_except_on_reset() -> None:
    f = ReadingFilter()
    keep = [
        f.keep(Role.ENERGY_PRODUCED, "e", 10.0, T0),
        f.keep(Role.ENERGY_PRODUCED, "e", 10.1, T0 + timedelta(seconds=30)),
        f.keep(Role.ENERGY_PRODUCED, "e", 10.2, T0 + timedelta(seconds=61)),
        f.keep(Role.ENERGY_PRODUCED, "e", 10.2, T0 + timedelta(seconds=200)),  # inchangé
        f.keep(Role.ENERGY_PRODUCED, "e", 0.0, T0 + timedelta(seconds=210)),  # remise à zéro
    ]
    assert keep == [True, False, True, False, True]


@pytest.mark.parametrize(
    ("role", "raw", "unit", "expected"),
    [
        (Role.ENERGY_PRODUCED, "1500", "Wh", 1.5),
        (Role.ENERGY_IMPORTED, "2.5", "kWh", 2.5),
        (Role.POWER_CONSUMED, "1.2", "kW", 1200.0),
        (Role.STATE_OF_CHARGE, "55", "%", 55.0),
        (Role.POWER_PRODUCED, "unavailable", "W", None),
        (Role.ENERGY_PRODUCED, "12", "GJ", None),
        (Role.POWER_PRODUCED, "nan", "W", None),
    ],
)
def test_normalize(role: Role, raw: str, unit: str, expected: float | None) -> None:
    assert normalize(role, raw, unit) == expected


def test_targets_come_from_the_home_model() -> None:
    found = targets(MODEL)

    assert set(found) == {"sensor.pv_energy", "sensor.pv_power"}
    assert found["sensor.pv_power"].role is Role.POWER_PRODUCED
    assert found["sensor.pv_power"].sensor_iri.endswith("/sensor/solar/sensor-pv-power")


# --- Magasins par jour -----------------------------------------------------------------------


def test_readings_go_to_the_local_day(tmp_path: Path) -> None:
    stores = RawStores(tmp_path, "Europe/Paris")
    late = datetime(2026, 10, 15, 21, 59, tzinfo=UTC)  # 23h59 à Paris
    early = datetime(2026, 10, 15, 22, 1, tzinfo=UTC)  # 0h01 à Paris, le 16

    written = stores.write(
        [Reading("sensor.x", "urn:s", 1.0, late), Reading("sensor.x", "urn:s", 2.0, early)]
    )

    assert written == 2
    assert stores.days() == [date(2026, 10, 15), date(2026, 10, 16)]
    assert stores.count(date(2026, 10, 15)) == 1
    assert stores.count(date(2026, 10, 16)) == 1


def test_removing_a_day_removes_its_folder(tmp_path: Path) -> None:
    stores = RawStores(tmp_path)
    stores.write([Reading("sensor.x", "urn:s", 1.0, T0)])

    stores.remove_day(T0.date())

    assert stores.days() == []


# --- Abonnement auprès d'un faux HA ------------------------------------------------------------


def _responses() -> dict[str, object]:
    responses = default_responses()
    responses["get_states"] = [
        {
            "entity_id": "sensor.pv_energy",
            "state": "1500",
            "attributes": {"unit_of_measurement": "Wh"},
            "lc": T0.timestamp(),
        },
        {
            "entity_id": "sensor.pv_power",
            "state": "800",
            "attributes": {"unit_of_measurement": "W"},
            "lc": T0.timestamp(),
        },
        {"entity_id": "sensor.not_followed", "state": "1", "attributes": {}},
    ]
    return responses


def test_ingests_followed_entities_into_the_day_store(tmp_path: Path) -> None:
    subscriptions = Subscriptions()

    async def scenario() -> tuple[object, int]:
        handler = fake_home_assistant(_responses(), subscriptions)
        async with running_client(handler) as client:
            stores = RawStores(tmp_path)
            ingestor = Ingestor(client, stores)
            await ingestor.start(MODEL)
            async with asyncio.timeout(5):
                while ingestor.status().received < 2:
                    await asyncio.sleep(0.01)
            later = (T0 + timedelta(seconds=30)).timestamp()
            await subscriptions.push({"c": {"sensor.pv_power": {"+": {"s": "1500", "lu": later}}}})
            async with asyncio.timeout(5):
                while ingestor.status().received < 3:
                    await asyncio.sleep(0.01)
            await ingestor.stop()
            return ingestor.status(), stores.count(T0.date())

    status, stored = asyncio.run(scenario())

    by_entity = {e.entity_id: e for e in status.entities}  # type: ignore[attr-defined]
    assert set(by_entity) == {"sensor.pv_energy", "sensor.pv_power"}
    assert by_entity["sensor.pv_energy"].last_value == 1.5  # Wh → kWh
    assert by_entity["sensor.pv_power"].last_value == 1500.0
    assert status.written == 3  # type: ignore[attr-defined]
    assert stored == 3


# --- Reprise après coupure -------------------------------------------------------------------


def _backfill_responses(last: datetime) -> dict[str, object]:
    responses = _responses()
    before = (last - timedelta(hours=1)).timestamp()  # états actuels plus anciens que la reprise
    for state in responses["get_states"]:  # type: ignore[attr-defined]
        state["lc"] = before
    responses["history/history_during_period"] = {
        "sensor.pv_power": [
            {"s": "800", "lu": last.timestamp()},  # déjà écrit avant la coupure
            {"s": "900", "lu": (last + timedelta(minutes=1)).timestamp()},
            {"s": "2000", "lu": (last + timedelta(minutes=2)).timestamp()},
        ],
        # Pas encore suivie avant la coupure : relève de la reprise de l'historique (lot 1.3).
        "sensor.pv_energy": [{"s": "1600", "lu": last.timestamp()}],
    }
    return responses


def test_backfills_the_gap_left_by_an_outage(tmp_path: Path) -> None:
    last = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=2)
    database = open_database(tmp_path)
    with database:
        database.execute(
            "INSERT INTO ingestion_state VALUES (?, ?, ?)",
            ("sensor.pv_power", last.isoformat(), 800.0),
        )

    async def scenario() -> tuple[object, int]:
        handler = fake_home_assistant(_backfill_responses(last))
        async with running_client(handler) as client:
            stores = RawStores(tmp_path)
            ingestor = Ingestor(client, stores, database)
            await ingestor.start(MODEL)
            async with asyncio.timeout(5):
                while ingestor.status().last_backfill_at is None:
                    await asyncio.sleep(0.01)
            await ingestor.stop()
            return ingestor.status(), sum(stores.count(day) for day in stores.days())

    status, stored = asyncio.run(scenario())

    assert status.backfilled == 2  # type: ignore[attr-defined]
    assert stored == 2 + 2  # deux relevés repris, plus les deux états reçus à l'abonnement
    row = database.execute(
        "SELECT last_time, last_value FROM ingestion_state WHERE entity_id = 'sensor.pv_power'"
    ).fetchone()
    assert datetime.fromisoformat(row[0]) == last + timedelta(minutes=2)
    assert row[1] == 2000.0


def test_first_start_records_the_last_written_reading(tmp_path: Path) -> None:
    database = open_database(tmp_path)

    async def scenario() -> object:
        handler = fake_home_assistant(_responses())
        async with running_client(handler) as client:
            ingestor = Ingestor(client, RawStores(tmp_path), database)
            await ingestor.start(MODEL)
            async with asyncio.timeout(5):
                while ingestor.status().received < 2:
                    await asyncio.sleep(0.01)
            await ingestor.stop()  # écrit la file
            return ingestor.status()

    status = asyncio.run(scenario())

    assert status.backfilled == 0  # type: ignore[attr-defined]
    assert status.last_backfill_at is None  # type: ignore[attr-defined]
    rows = dict(database.execute("SELECT entity_id, last_value FROM ingestion_state"))
    assert rows == {"sensor.pv_energy": 1.5, "sensor.pv_power": 800.0}


def test_restart_state_is_saved_every_few_minutes_and_on_close(tmp_path: Path) -> None:
    from datetime import timedelta

    from wattslot.ingestion import STATE_INTERVAL, Ingestor
    from wattslot.storage.raw import RawStores, Reading

    database = open_database(tmp_path)
    ingestor = Ingestor(None, RawStores(tmp_path), database)  # type: ignore[arg-type]
    start = datetime(2026, 10, 16, 8, tzinfo=UTC)

    def reading(minutes: int) -> Reading:
        return Reading("sensor.p", "http://example.org/p", 1.0, start + timedelta(minutes=minutes))

    def saved() -> str | None:
        row = database.execute("SELECT last_time FROM ingestion_state").fetchone()
        return row[0] if row else None

    ingestor.write_batch([reading(0)], start)  # premier lot : en base aussitôt
    assert saved() == start.isoformat()
    ingestor.write_batch([reading(1)], start + timedelta(minutes=1))
    assert saved() == start.isoformat()  # pas avant STATE_INTERVAL
    ingestor.write_batch([reading(6)], start + STATE_INTERVAL + timedelta(minutes=1))
    assert saved() == (start + timedelta(minutes=6)).isoformat()
    ingestor.write_batch([reading(7)], start + STATE_INTERVAL + timedelta(minutes=2))
    ingestor.close()
    assert saved() == (start + timedelta(minutes=7)).isoformat()
