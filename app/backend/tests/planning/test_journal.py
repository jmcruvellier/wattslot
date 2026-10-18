"""Journal des cycles : brut quand la journée y est entière, sinon quarts d'heure ; profil sur
30 jours ; cycles réels du jour."""

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from wattslot.aggregation import QUARTER, Aggregate
from wattslot.detection import DeviceKind, Role
from wattslot.home_model import HomeDevice, HomeModel, HomeSensor, sensor_iri
from wattslot.planning.journal import CycleJournal, appliances, real_cycles
from wattslot.storage.database import open_database
from wattslot.storage.raw import RawStores, Reading

PARIS = ZoneInfo("Europe/Paris")
TODAY = date(2026, 10, 16)
POWER, ENERGY = "sensor.washer_power", "sensor.washer_energy"
MODEL = HomeModel(
    devices=[
        HomeDevice(
            key="washer",
            kind=DeviceKind.WASHING_MACHINE,
            name="Lave-linge",
            sensors=[
                HomeSensor(entity_id=POWER, role=Role.POWER_CONSUMED),
                HomeSensor(entity_id=ENERGY, role=Role.ENERGY_CONSUMED),
            ],
        ),
        HomeDevice(key="grid", kind=DeviceKind.GRID, name="Réseau", sensors=[]),
    ]
)


def local(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), PARIS)


class QuarterReader:
    def __init__(self) -> None:
        self.data: dict[str, list[Aggregate]] = defaultdict(list)

    def add_cycle(self, day: date, start_hour: int, quarters: int, kwh: float) -> None:
        """Un cycle de ``quarters`` quarts d'heure à puissance constante."""
        for k in range(quarters):
            start = local(day, start_hour) + timedelta(minutes=15 * k)
            per_quarter = kwh / quarters
            self.data[POWER].append(
                Aggregate(entity_id=POWER, period=QUARTER, start=start, mean=per_quarter * 4000)
            )
            self.data[ENERGY].append(
                Aggregate(entity_id=ENERGY, period=QUARTER, start=start, energy_kwh=per_quarter)
            )
        for k in (-1, quarters):  # veille autour du cycle
            start = local(day, start_hour) + timedelta(minutes=15 * k)
            self.data[POWER].append(
                Aggregate(entity_id=POWER, period=QUARTER, start=start, mean=1.0)
            )
            self.data[ENERGY].append(
                Aggregate(entity_id=ENERGY, period=QUARTER, start=start, energy_kwh=0.0)
            )

    def read(self, entity_id: str, period: str, start: datetime, end: datetime) -> list[Aggregate]:
        assert period == QUARTER
        return sorted(
            (a for a in self.data[entity_id] if start <= a.start < end), key=lambda a: a.start
        )


def raw_cycle(
    raw: RawStores, day: date, start: datetime, minutes: int, kwh: float, counter: float
) -> float:
    """Relevés bruts d'un cycle : puissance à la minute, compteur toutes les 10 minutes."""
    power_iri, energy_iri = sensor_iri("washer", POWER), sensor_iri("washer", ENERGY)
    watts = kwh * 60_000 / minutes
    readings = [Reading(POWER, power_iri, 0.0, local(day, 0, 5))]
    readings += [
        Reading(POWER, power_iri, watts, start + timedelta(minutes=m)) for m in range(minutes)
    ]
    readings.append(Reading(POWER, power_iri, 0.0, start + timedelta(minutes=minutes)))
    readings.append(Reading(ENERGY, energy_iri, counter, local(day, 0, 5)))
    for m in range(10, minutes + 1, 10):
        readings.append(
            Reading(ENERGY, energy_iri, counter + kwh * m / minutes, start + timedelta(minutes=m))
        )
    readings.append(
        Reading(ENERGY, energy_iri, counter + kwh, start + timedelta(minutes=minutes + 2))
    )
    raw.write(readings)
    return counter + kwh


@pytest.fixture
def setup(tmp_path: Path) -> tuple[CycleJournal, RawStores, QuarterReader]:
    raw = RawStores(tmp_path, "Europe/Paris")
    reader = QuarterReader()
    return CycleJournal(open_database(tmp_path), raw, reader), raw, reader


def test_profile_uses_raw_days_then_quarters(
    setup: tuple[CycleJournal, RawStores, QuarterReader],
) -> None:
    journal, raw, reader = setup
    for k in range(4, 15):  # cycles anciens, connus au quart d'heure : 6 quarts d'heure, 0,3 kWh
        reader.add_cycle(TODAY - timedelta(days=k), 10, 6, 0.3)
    counter = 100.0
    for k in (3, 2, 1):  # brut : la première journée (J-3) est partielle, donc au quart d'heure
        day = TODAY - timedelta(days=k)
        counter = raw_cycle(raw, day, local(day, 10), 80, 0.24, counter)
        reader.add_cycle(day, 10, 6, 0.3)
    washer = appliances(MODEL)[0]

    profile = journal.profile(washer, TODAY)

    assert journal.sources(washer, TODAY) == {"quarters": 28, "raw": 2}
    by_day = {c.start.astimezone(PARIS).date(): c for c in profile.cycles}
    assert by_day[TODAY - timedelta(days=1)].minutes == 80  # précision du brut
    assert by_day[TODAY - timedelta(days=1)].energy_kwh == pytest.approx(0.24)
    assert by_day[TODAY - timedelta(days=5)].minutes == 90  # au quart d'heure
    assert profile.ok and profile.energy_kwh == pytest.approx(0.3)
    assert profile.duration_min == 90


def test_quarter_days_are_redone_once_raw_is_complete(
    setup: tuple[CycleJournal, RawStores, QuarterReader],
) -> None:
    journal, raw, reader = setup
    yesterday = TODAY - timedelta(days=1)
    reader.add_cycle(yesterday, 10, 6, 0.3)
    washer = appliances(MODEL)[0]
    journal.record(washer, [yesterday])
    assert journal.sources(washer, TODAY) == {"quarters": 1}

    counter = raw_cycle(
        raw, yesterday - timedelta(days=1), local(yesterday - timedelta(days=1), 8), 60, 0.2, 10.0
    )
    raw_cycle(raw, yesterday, local(yesterday, 10), 80, 0.24, counter)
    journal.record(washer, [yesterday])

    assert journal.sources(washer, TODAY) == {"raw": 1}
    (cycle,) = journal.cycles(washer, yesterday, yesterday)
    assert cycle.minutes == 80 and cycle.from_counter


def test_real_cycles_of_the_day(setup: tuple[CycleJournal, RawStores, QuarterReader]) -> None:
    _, raw, _ = setup
    raw_cycle(raw, TODAY, local(TODAY, 9), 40, 0.2, 50.0)
    now = local(TODAY, 9, 31).astimezone(UTC)  # relevé du compteur de 9 h 30 compris

    cycles = real_cycles(MODEL, raw, now)

    (cycle,) = cycles["Lave-linge"]
    assert cycle.start == local(TODAY, 9) and cycle.running
    # Heure locale de la maison (le brut est en UTC) : le calcul lit l'heure du démarrage.
    assert (cycle.start.hour, cycle.start.utcoffset()) == (9, timedelta(hours=2))
    assert cycle.energy_kwh == pytest.approx(0.15)  # au compteur, relevé de 9 h 30
