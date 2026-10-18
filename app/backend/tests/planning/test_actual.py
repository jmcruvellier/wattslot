"""Données réelles du jour : la réécriture donne les mêmes résultats que la v1."""

import random
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from tests.v1_oracle import v1
from wattslot.aggregation import Carry, compute
from wattslot.detection import DeviceKind, Role
from wattslot.home_model import HomeDevice, HomeModel, HomeSensor, sensor_iri
from wattslot.planning.actual import (
    BATTERY_THRESHOLD_W,
    actual_day,
    counter_hourly,
    counter_power,
    hourly_mean,
    labelled_segments,
    pool_segments,
    soc_at_midnight,
    soc_end_of_hour,
    soc_max,
)
from wattslot.planning.plan import POOL
from wattslot.storage.raw import RawStores, Reading

V1 = "forme_horaire_solaire."
PARIS = ZoneInfo("Europe/Paris")
DAY = date(2026, 10, 16)
MIDNIGHT = datetime.combine(DAY, time(), PARIS)


def utc(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def v1_obs(points: list[tuple[datetime, float]]) -> list[tuple[str, float]]:
    return [(utc(t), v) for t, v in points]


def series(
    rng: random.Random, start: datetime, hours: float, levels: list[float]
) -> list[tuple[datetime, float]]:
    points, moment = [], start + timedelta(seconds=rng.randint(0, 900))
    end = start + timedelta(hours=hours)
    while moment < end:
        points.append(
            (moment, rng.choice(levels) if rng.random() < 0.3 else rng.uniform(*levels[:2]))
        )
        moment += timedelta(seconds=rng.choice([30, 60, 120, 300, 900, 1800, 3600]))
    rng.shuffle(points)  # la v1 trie elle-même ses relevés
    return points


def counter(
    rng: random.Random,
    start: datetime,
    hours: float,
    total: float | None = None,
    noise: bool = True,
) -> list[tuple[datetime, float]]:
    total = rng.uniform(0, 500) if total is None else total
    points, moment = [], start + timedelta(seconds=rng.randint(0, 900))
    end = start + timedelta(hours=hours)
    while moment < end:
        points.append((moment, round(total, 3)))
        moment += timedelta(seconds=rng.choice([30, 60, 300, 900, 3600, 7200]))
        roll = rng.random()
        if roll < 0.02:
            total = 0.0  # remise à zéro
        elif noise and roll < 0.05:
            total = max(0.0, total - rng.uniform(0, 0.01))  # bruit
        else:
            total += rng.uniform(0, 0.8)
    return points


@pytest.mark.parametrize("seed", range(200))
def test_soc_same_as_v1(seed: int) -> None:
    rng = random.Random(seed)
    points = series(rng, MIDNIGHT, rng.uniform(0.5, 24), [10.0, 100.0, 12.0])
    before = series(rng, MIDNIGHT - timedelta(days=1), 24, [10.0, 100.0])
    if rng.random() < 0.2:
        before = []
    until = rng.choice([None, MIDNIGHT + timedelta(hours=rng.uniform(0, 23.9))])
    if until is not None:
        points = [p for p in points if p[0] < until]
    until_utc = utc(until) if until else None

    assert hourly_mean(points, until, PARIS) == pytest.approx(
        v1(V1 + "_moyenne_horaire_simple", v1_obs(points), until_utc)
    )
    assert soc_end_of_hour(points, until, PARIS) == v1(
        V1 + "_soc_fin_heure", v1_obs(points), until_utc
    )
    expected_max = v1(V1 + "_soc_max_instantane", v1_obs(points))
    assert soc_max(points, PARIS) == expected_max
    assert soc_at_midnight(before, points) == v1(V1 + "_soc_minuit", v1_obs(before), v1_obs(points))


@pytest.mark.parametrize("seed", range(300))
def test_counter_hourly_same_as_v1(seed: int) -> None:
    """Sans bruit, même résultat que la v1 (compteur total, ou quotidien remis à zéro)."""
    rng = random.Random(seed)
    before = counter(rng, MIDNIGHT - timedelta(hours=rng.uniform(1, 24)), 24, noise=False)
    before = [p for p in before if p[0] < MIDNIGHT]
    total = before[-1][1] if before and rng.random() < 0.7 else 0.0
    today = counter(rng, MIDNIGHT, 24, total, noise=False)
    today = [p for p in today if p[0] < MIDNIGHT + timedelta(days=1)]
    if rng.random() < 0.15:
        before = []
    if rng.random() < 0.1:
        today = []

    expected = v1(V1 + "_energie_horaire_compteur", v1_obs(before), v1_obs(today), utc(MIDNIGHT))
    found = counter_hourly(before, today, MIDNIGHT, PARIS)

    if expected is None:
        assert found is None
    else:
        assert found == pytest.approx(expected)


@pytest.mark.parametrize("seed", range(300))
def test_counter_hourly_same_total_as_aggregates(seed: int) -> None:
    """Avec du bruit, le total du jour est celui des agrégats horaires des compteurs."""
    rng = random.Random(seed)
    before = counter(rng, MIDNIGHT - timedelta(hours=rng.uniform(1, 24)), 24)
    before = [p for p in before if p[0] < MIDNIGHT]
    total = max(0.0, before[-1][1] - rng.uniform(0, 0.01)) if before else None
    today = [p for p in counter(rng, MIDNIGHT, 24, total) if p[0] < MIDNIGHT + timedelta(days=1)]

    carry = Carry(*before[-1]) if before else None
    values, _ = compute(Role.ENERGY_PRODUCED, MIDNIGHT, at(24), carry, sorted(today))
    found = counter_hourly(before, today, MIDNIGHT, PARIS)

    assert sum((found or {}).values()) == pytest.approx(values.energy_kwh if values else 0.0)


def test_counter_hourly_ignores_a_small_drop_at_midnight() -> None:
    """Compteur total relu un peu plus bas au matin : rien sur la nuit, pas le cumul entier."""
    before = [(at(-5), 2048.9)]
    today = [(at(7.8), 2048.875), (at(8.5), 2048.92), (at(9), 2049.1)]

    found = counter_hourly(before, today, MIDNIGHT, PARIS) or {}

    assert min(found) == 7  # la hausse de 7 h 48 à 8 h 30
    assert sum(found.values()) == pytest.approx(0.2)


def test_counter_hourly_does_not_count_noise_twice() -> None:
    found = counter_hourly([(at(-1), 10.0)], [(at(9), 9.99), (at(10.5), 10.01)], MIDNIGHT, PARIS)

    assert sum((found or {}).values()) == pytest.approx(0.01)


def test_counter_hourly_daily_counter_reset_at_midnight() -> None:
    found = counter_hourly([(at(-4), 5.2)], [(at(8), 0.1), (at(9), 0.4)], MIDNIGHT, PARIS)

    assert sum((found or {}).values()) == pytest.approx(0.4)


def as_v1_segments(
    found: list[tuple[datetime, datetime, str, float]], key: str
) -> list[dict[str, Any]]:
    return [
        {
            "debut_iso": b.astimezone(PARIS).isoformat(),
            "fin_iso": e.astimezone(PARIS).isoformat(),
            key: name,
            "energie_kwh": round(abs(energy), 3),
        }
        for b, e, name, energy in found
    ]


@pytest.mark.parametrize("seed", range(300))
def test_battery_segments_same_as_v1(seed: int) -> None:
    rng = random.Random(seed)
    power = series(rng, MIDNIGHT, 24, [-2500.0, 2500.0, 0.0, 29.9, -30.0, 30.0])
    until = rng.choice([None, max(t for t, _ in power) + timedelta(minutes=rng.randint(0, 90))])

    def action(watts: float) -> str | None:
        if watts >= BATTERY_THRESHOLD_W:
            return "decharge"
        return "charge" if watts <= -BATTERY_THRESHOLD_W else None

    expected = v1(V1 + "_segments_batterie_reelle", v1_obs(power), utc(until) if until else None)
    assert as_v1_segments(labelled_segments(power, until, action), "action") == expected


@pytest.mark.parametrize("seed", range(300))
def test_pool_segments_same_as_v1(seed: int) -> None:
    rng = random.Random(seed)
    power = series(rng, MIDNIGHT, 24, [0.0, 600.0, 130.0, 415.0, 19.9, 20.0, 272.5])
    until = rng.choice([None, max(t for t, _ in power) + timedelta(minutes=rng.randint(0, 90))])

    expected = v1(V1 + "_segments_piscine_reelle", v1_obs(power), utc(until) if until else None)
    assert pool_segments(power, until, PARIS) == expected


def test_counter_power_holds_the_rise_between_readings() -> None:
    t0 = MIDNIGHT + timedelta(hours=10)
    points = [(t0, 10.0), (t0 + timedelta(minutes=30), 10.5), (t0 + timedelta(hours=2), 10.5)]
    assert counter_power(points) == [
        (t0, 1000.0),
        (t0 + timedelta(minutes=30), 0.0),
        (t0 + timedelta(hours=2), 0.0),
    ]


# --- Bout en bout sur le brut ------------------------------------------------------------------

SENSORS = {
    "solar": (DeviceKind.SOLAR, [("sensor.pv_energy", Role.ENERGY_PRODUCED)]),
    "grid": (
        DeviceKind.GRID,
        [
            ("sensor.import_hp", Role.ENERGY_IMPORTED),
            ("sensor.import_hc", Role.ENERGY_IMPORTED),
            ("sensor.export", Role.ENERGY_EXPORTED),
        ],
    ),
    "battery": (
        DeviceKind.BATTERY,
        [
            ("sensor.bat_in", Role.ENERGY_CHARGED),
            ("sensor.bat_out", Role.ENERGY_DISCHARGED),
            ("sensor.soc", Role.STATE_OF_CHARGE),
        ],
    ),
    "pool": (DeviceKind.POOL_PUMP, [("sensor.pool_power", Role.POWER_CONSUMED)]),
}
MODEL = HomeModel(
    devices=[
        HomeDevice(
            key=key,
            kind=kind,
            name=key,
            sensors=[HomeSensor(entity_id=e, role=r) for e, r in sensors],
        )
        for key, (kind, sensors) in SENSORS.items()
    ]
)


def at(hour: float) -> datetime:
    return MIDNIGHT + timedelta(hours=hour)


def reading(device: str, entity_id: str, value: float, moment: datetime) -> Reading:
    return Reading(entity_id, sensor_iri(device, entity_id), value, moment.astimezone(UTC))


def test_actual_day_from_raw_readings(tmp_path: Path) -> None:
    raw = RawStores(tmp_path, "Europe/Paris")
    readings = [
        reading("solar", "sensor.pv_energy", 100.0, at(-3)),
        reading("solar", "sensor.pv_energy", 101.0, at(10)),
        reading("solar", "sensor.pv_energy", 103.0, at(12)),
        reading("grid", "sensor.import_hp", 50.0, at(-1)),
        reading("grid", "sensor.import_hp", 50.4, at(8)),
        reading("grid", "sensor.import_hc", 20.0, at(-1)),
        reading("grid", "sensor.import_hc", 20.2, at(2)),
        reading("grid", "sensor.export", 5.0, at(-1)),
        reading("grid", "sensor.export", 5.5, at(12)),
        reading("battery", "sensor.bat_in", 7.0, at(-5)),
        reading("battery", "sensor.bat_in", 7.0, at(11)),
        reading("battery", "sensor.bat_in", 8.0, at(12)),
        reading("battery", "sensor.bat_out", 3.0, at(-5)),
        reading("battery", "sensor.bat_out", 3.6, at(20)),
        reading("battery", "sensor.soc", 40.0, at(-0.5)),
        reading("battery", "sensor.soc", 60.0, at(11.5)),
        reading("battery", "sensor.soc", 90.0, at(12)),
        reading("pool", "sensor.pool_power", 0.0, at(9)),
        reading("pool", "sensor.pool_power", 420.0, at(10)),
        reading("pool", "sensor.pool_power", 140.0, at(11)),
        reading("pool", "sensor.pool_power", 0.0, at(12)),
    ]
    raw.write(readings)

    found: dict[str, Any] = actual_day(MODEL, raw, DAY, at(12.5))

    assert found["soc_pct_minuit"] == 40.0
    assert found["soc_pct_fin_heure"][11] == 60.0 and found["soc_pct_fin_heure"][12] == 90.0
    assert found["soc_max_reel"]["pct"] == 90.0
    assert sum(found["production_reelle_horaire"].values()) == pytest.approx(3.0)
    assert sum(found["reseau_reel_soutire_horaire"].values()) == pytest.approx(0.6)
    assert found["reseau_reel_injecte_horaire"][11] == pytest.approx(0.5 / 12)
    battery = found["batterie_reelle_segments"]
    assert [(s["action"], s["energie_kwh"]) for s in battery] == [("charge", 1.0)]
    assert battery[0]["debut_iso"] == at(11).isoformat()
    pool = found["equipements_reels_horaire"][POOL]
    assert [(s["mode"], s["energie_kwh"]) for s in pool] == [("eco", 0.42), ("silence", 0.14)]
    consumption = found["consommation_reelle_horaire"]
    assert sum(consumption.values()) == pytest.approx(3.0 + 0.6 - 0.5 - 1.0)
    assert found["heure_maj_iso"] == at(12.5).isoformat() and found["manuel"] is False

    # Journée passée : bornée à minuit le lendemain ; la décharge de 20 h y figure.
    whole = actual_day(MODEL, raw, DAY, at(30))
    assert whole["heure_maj_iso"] == at(24).isoformat()
    assert [s["action"] for s in whole["batterie_reelle_segments"]] == ["charge"]


def test_actual_day_two_solar_installations(tmp_path: Path) -> None:
    """Deux installations : un compteur total relu un peu plus bas au matin (micro-onduleur qui
    se réveille) et un compteur quotidien remis à zéro. Seule la production du jour compte."""
    model = HomeModel(
        devices=[
            HomeDevice(
                key=key,
                kind=DeviceKind.SOLAR,
                name=key,
                sensors=[HomeSensor(entity_id=entity_id, role=Role.ENERGY_PRODUCED)],
            )
            for key, entity_id in (("terrasse", "sensor.yieldtotal"), ("cabanon", "sensor.daily"))
        ]
    )
    raw = RawStores(tmp_path, "Europe/Paris")
    raw.write(
        [
            reading("terrasse", "sensor.yieldtotal", 2048.4, at(-7)),
            reading("terrasse", "sensor.yieldtotal", 2048.9, at(-6)),
            reading("terrasse", "sensor.yieldtotal", 2048.875, at(7.8)),
            reading("terrasse", "sensor.yieldtotal", 2049.0, at(9)),
            reading("terrasse", "sensor.yieldtotal", 2050.0, at(12)),
            reading("cabanon", "sensor.daily", 1.8, at(-6)),
            reading("cabanon", "sensor.daily", 0.0, at(7.8)),
            reading("cabanon", "sensor.daily", 0.5, at(12)),
        ]
    )

    found: dict[str, Any] = actual_day(model, raw, DAY, at(12.5))

    production = found["production_reelle_horaire"]
    assert all(production.get(h, 0.0) == 0.0 for h in range(7))
    assert sum(production.values()) == pytest.approx(1.1 + 0.5)
