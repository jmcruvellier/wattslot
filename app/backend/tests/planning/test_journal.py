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
from wattslot.planning.journal import CycleJournal, appliances, cycles_summary, real_cycles
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


def test_the_measured_cycles_say_which_ones_the_profile_keeps(
    setup: tuple[CycleJournal, RawStores, QuarterReader],
) -> None:
    """20/11/2026 : un appareil lancé plusieurs fois restait « insuffisant », et le diagnostic
    ne donnait que le nombre de cycles retenus. Un cycle hors norme écarte ici les autres."""
    journal, _, reader = setup
    for k in (9, 7, 5):
        reader.add_cycle(TODAY - timedelta(days=k), 10, 6, 0.3)
    reader.add_cycle(TODAY - timedelta(days=3), 10, 6, 3.0)
    washer = appliances(MODEL)[0]

    profile = journal.profile(washer, TODAY)
    found = cycles_summary(journal.measured(washer, TODAY), profile, PARIS)

    assert not profile.ok
    assert [(c["energy_kwh"], c["minutes"], c["kept"]) for c in found] == [
        (0.3, 90, False),
        (0.3, 90, False),
        (0.3, 90, False),
        (3.0, 90, True),
    ]
    assert found[0]["start"] == local(TODAY - timedelta(days=9), 10).isoformat(timespec="minutes")


def test_a_cycle_whose_start_is_the_first_reading_of_the_day_is_kept(
    setup: tuple[CycleJournal, RawStores, QuarterReader],
) -> None:
    """20/11/2026 : chauffe-eau lancé sept fois en 30 jours, deux cycles au journal. Une prise
    qui n'envoie rien tant que sa puissance ne change pas a pour premier relevé du jour le
    démarrage du cycle : pris pour un cycle déjà en marche à minuit, il était écarté."""
    journal, raw, reader = setup
    power_iri = sensor_iri("washer", POWER)
    raw.write([Reading(POWER, power_iri, 0.0, local(TODAY - timedelta(days=4), 12))])  # 1er jour
    for k in (3, 2, 1):
        day = TODAY - timedelta(days=k)
        raw.write(
            [
                Reading(POWER, power_iri, 900.0, local(day, 10)),
                Reading(POWER, power_iri, 0.0, local(day, 12)),
            ]
        )
        # Dernier quart d'heure de la veille : à l'arrêt.
        reader.data[POWER].append(
            Aggregate(
                entity_id=POWER,
                period=QUARTER,
                start=local(day, 0) - timedelta(minutes=15),
                mean=0.0,
                last=0.0,
            )
        )
    washer = appliances(MODEL)[0]

    found = journal.measured(washer, TODAY)

    assert [(c.start, round(c.minutes)) for c in found] == [
        (local(TODAY - timedelta(days=k), 10), 120) for k in (3, 2, 1)
    ]
    assert journal.profile(washer, TODAY).ok


def test_a_cycle_running_since_the_day_before_is_still_left_out(
    setup: tuple[CycleJournal, RawStores, QuarterReader],
) -> None:
    journal, raw, reader = setup
    power_iri = sensor_iri("washer", POWER)
    day = TODAY - timedelta(days=1)
    raw.write([Reading(POWER, power_iri, 0.0, local(day - timedelta(days=1), 12))])
    raw.write([Reading(POWER, power_iri, 0.0, local(day, 2))])  # fin d'un cycle parti la veille
    reader.data[POWER].append(
        Aggregate(
            entity_id=POWER,
            period=QUARTER,
            start=local(day, 0) - timedelta(minutes=15),
            mean=900.0,
            last=900.0,
        )
    )

    assert journal.measured(appliances(MODEL)[0], TODAY) == []


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


def test_real_cycle_paused_is_still_running(
    setup: tuple[CycleJournal, RawStores, QuarterReader],
) -> None:
    """Relevé tombé dans une pause du programme (sous le seuil, moins longue que la fenêtre de
    fusion) : le cycle n'est pas fini, sa fin prévue ne s'arrête pas à l'heure du calcul."""
    _, raw, _ = setup
    raw_cycle(raw, TODAY, local(TODAY, 9, 35), 23, 0.1, 50.0)  # puissance à 0 dès 9 h 58
    now = local(TODAY, 10).astimezone(UTC)

    (cycle,) = real_cycles(MODEL, raw, now)["Lave-linge"]

    assert cycle.end == local(TODAY, 9, 58) and cycle.running


def test_real_cycle_ended_after_long_pause(
    setup: tuple[CycleJournal, RawStores, QuarterReader],
) -> None:
    """Pause plus longue que la fenêtre de fusion du lave-linge (30 min) : le cycle est fini."""
    _, raw, _ = setup
    raw_cycle(raw, TODAY, local(TODAY, 9, 35), 23, 0.1, 50.0)
    now = local(TODAY, 10, 29).astimezone(UTC)

    (cycle,) = real_cycles(MODEL, raw, now)["Lave-linge"]

    assert cycle.end == local(TODAY, 9, 58) and not cycle.running


def test_a_declared_second_load_splits_the_activity(
    setup: tuple[CycleJournal, RawStores, QuarterReader],
) -> None:
    """20/11/2026 : une seconde charge lancée juste derrière la première, mesurée avec elle
    comme une seule activité (pause de 10 minutes, fenêtre de fusion de 30). Le second cycle
    demandé restait à lancer ; son « C'est lancé » dit qu'il y a deux charges, et l'activité
    est coupée à la pause mesurée, pas à l'instant de la déclaration."""
    _, raw, _ = setup
    counter = raw_cycle(raw, TODAY, local(TODAY, 10), 150, 1.0, 50.0)
    again = local(TODAY, 12, 40)  # seconde charge : 400 W, compteur toutes les 10 minutes
    power_iri, energy_iri = sensor_iri("washer", POWER), sensor_iri("washer", ENERGY)
    raw.write(
        [Reading(POWER, power_iri, 400.0, again + timedelta(minutes=m)) for m in range(150)]
        + [
            Reading(ENERGY, energy_iri, counter + m / 150, again + timedelta(minutes=m))
            for m in range(10, 151, 10)
        ]
    )
    now = local(TODAY, 13, 45).astimezone(UTC)
    said = local(TODAY, 12, 55).astimezone(UTC)

    (whole,) = real_cycles(MODEL, raw, now)["Lave-linge"]
    first, second = real_cycles(MODEL, raw, now, declared={"Lave-linge #2": said})["Lave-linge"]

    assert whole.start == local(TODAY, 10) and whole.running
    assert (first.start, first.end, first.running) == (whole.start, local(TODAY, 12, 30), False)
    assert (second.start, second.end, second.running) == (local(TODAY, 12, 40), whole.end, True)
    assert first.energy_kwh == pytest.approx(1.0)
    assert second.energy_kwh == pytest.approx(0.4, abs=0.05)
    # Pendant la pause (avant de relancer) : la même coupure.
    during = {"Lave-linge #2": local(TODAY, 12, 35).astimezone(UTC)}
    assert real_cycles(MODEL, raw, now, declared=during)["Lave-linge"] == (first, second)
    # Le premier cycle de la journée, un autre équipement, un instant hors de l'activité :
    # rien n'est coupé.
    for declared in (
        {"Lave-linge": said},
        {"Sèche-linge #2": said},
        {"Lave-linge #2": local(TODAY, 9).astimezone(UTC)},
    ):
        assert real_cycles(MODEL, raw, now, declared=declared)["Lave-linge"] == (whole,)
    # Déclaré sans aucune pause mesurée avant : coupé à l'instant déclaré.
    early = local(TODAY, 11).astimezone(UTC)
    first, second = real_cycles(MODEL, raw, now, declared={"Lave-linge #2": early})["Lave-linge"]
    assert first.end == second.start == early


def test_real_cycles_of_a_closed_day(setup: tuple[CycleJournal, RawStores, QuarterReader]) -> None:
    """À l'archivage de la veille, les cycles sont lus jusqu'à minuit du lendemain : ceux de la
    journée demandée, pas ceux (aucun) de la journée qui commence."""
    _, raw, _ = setup
    raw_cycle(raw, TODAY, local(TODAY, 9), 40, 0.2, 50.0)
    end = local(TODAY + timedelta(days=1), 0).astimezone(UTC)

    (cycle,) = real_cycles(MODEL, raw, end, day=TODAY)["Lave-linge"]

    assert cycle.start == local(TODAY, 9) and not cycle.running
    assert real_cycles(MODEL, raw, end)["Lave-linge"] == ()  # lu sur le lendemain : rien
