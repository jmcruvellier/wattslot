"""Entrées tirées de l'historique : ligne de base, meilleure production, historique récent."""

import random
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from tests.v1_oracle import v1
from wattslot.aggregation import HOUR, Aggregate
from wattslot.detection import DeviceKind, Role
from wattslot.home_model import HomeDevice, HomeModel, HomeSensor
from wattslot.planning.past import (
    BestProduction,
    RecentHistory,
    baseline,
    battery_efficiencies,
    best_production,
    efficiencies_from_hours,
    recent_history,
    spike,
)

PARIS = ZoneInfo("Europe/Paris")
TODAY = date(2026, 10, 16)  # vendredi


def device(key: str, kind: DeviceKind, *sensors: tuple[str, Role]) -> HomeDevice:
    return HomeDevice(
        key=key,
        kind=kind,
        name=key,
        sensors=[HomeSensor(entity_id=e, role=r) for e, r in sensors],
    )


MODEL = HomeModel(
    devices=[
        device("solar", DeviceKind.SOLAR, ("sensor.pv", Role.ENERGY_PRODUCED)),
        device(
            "grid",
            DeviceKind.GRID,
            ("sensor.imp_hc", Role.ENERGY_IMPORTED),
            ("sensor.imp_hp", Role.ENERGY_IMPORTED),
            ("sensor.exp", Role.ENERGY_EXPORTED),
        ),
        device(
            "battery",
            DeviceKind.BATTERY,
            ("sensor.chg", Role.ENERGY_CHARGED),
            ("sensor.dis", Role.ENERGY_DISCHARGED),
            ("sensor.soc", Role.STATE_OF_CHARGE),
        ),
        device("heater", DeviceKind.WATER_HEATER, ("sensor.wh", Role.ENERGY_CONSUMED)),
        device("pool", DeviceKind.POOL_PUMP, ("sensor.pool", Role.ENERGY_CONSUMED)),
        device("tv", DeviceKind.OTHER_LOAD, ("sensor.tv", Role.ENERGY_CONSUMED)),
    ]
)


class FakeReader:
    def __init__(self) -> None:
        self.data: dict[str, list[Aggregate]] = defaultdict(list)

    def add(self, entity_id: str, day: date, hour: int, **values: float) -> None:
        start = datetime.combine(day, time(hour), PARIS).astimezone(UTC)
        self.data[entity_id].append(
            Aggregate(entity_id=entity_id, period=HOUR, start=start, **values)
        )

    def read(self, entity_id: str, period: str, start: datetime, end: datetime) -> list[Aggregate]:
        assert period == HOUR
        return [a for a in self.data[entity_id] if start <= a.start < end]


def house(reader: FakeReader, day: date, hour: int, base: float, **overrides: float | None) -> None:
    """Une heure de la maison dont la ligne de base vaut ``base`` : production 0,5, soutirage
    réparti sur deux compteurs, chauffe-eau 0,3, téléviseur 0,1 (compté dans la base). Un
    capteur à None ne remonte rien cette heure-là (compté 0)."""
    values: dict[str, float | None] = {
        "pv": 0.5,
        "imp_hc": 0.1,
        "exp": 0.05,
        "chg": 0.2,
        "dis": 0.15,
        "wh": 0.3,
    }
    values |= overrides

    def v(name: str) -> float:
        return values[name] or 0.0

    # base = pv + imp_hc + imp_hp - exp + dis - chg - wh
    values["imp_hp"] = base - (v("pv") + v("imp_hc") - v("exp") + v("dis") - v("chg") - v("wh"))
    for name, kwh in values.items():
        if kwh is not None:
            reader.add(f"sensor.{name}", day, hour, energy_kwh=kwh)


def days_back(count: int) -> list[date]:
    return [TODAY - timedelta(days=k) for k in range(1, count + 1)]


def fill(reader: FakeReader, days: list[date], base: Callable[[date, int], float]) -> None:
    for day in days:
        for hour in range(24):
            house(reader, day, hour, base(day, hour))


def test_baseline_uses_the_last_six_same_weekdays() -> None:
    reader = FakeReader()
    # Vendredis à 1,0 kWh, autres jours à 0,2 ; les vendredis plus anciens que les 6 derniers à 5.
    fridays = [d for d in days_back(63) if d.weekday() == TODAY.weekday()]
    old = set(fridays[6:])
    fill(
        reader,
        days_back(63),
        lambda d, h: 5.0 if d in old else 1.0 if d.weekday() == TODAY.weekday() else 0.2,
    )

    result = baseline(MODEL, reader, TODAY, TODAY, PARIS)

    assert sorted(result) == list(range(24))
    assert all(v == pytest.approx(1.0) for v in result.values())


def test_young_history_uses_every_day() -> None:
    reader = FakeReader()
    fill(reader, days_back(14), lambda d, h: 1.4 if d.weekday() == TODAY.weekday() else 0.4)

    result = baseline(MODEL, reader, TODAY, TODAY, PARIS)

    assert result[12] == pytest.approx((2 * 1.4 + 12 * 0.4) / 14)


def test_hours_need_grid_and_battery_on_three_days() -> None:
    reader = FakeReader()
    days = days_back(4)
    fill(reader, days[:2], lambda d, h: 0.5)
    for day in days[2:]:  # 2 jours sans batterie à 13 h : 13 h n'a que 2 jours valables
        for hour in range(24):
            if hour == 13:
                house(reader, day, hour, 0.5, chg=None, dis=None)
            else:
                house(reader, day, hour, 0.5)

    result = baseline(MODEL, reader, TODAY, TODAY, PARIS)

    assert 13 not in result and result[12] == pytest.approx(0.5)


def test_missing_production_counts_as_zero_and_baseline_is_never_negative() -> None:
    reader = FakeReader()
    for day in days_back(3):
        house(reader, day, 2, 0.3, pv=None)  # la nuit, pas de production remontée
        house(reader, day, 3, -0.4)  # bilan négatif (mesure imprécise)

    result = baseline(MODEL, reader, TODAY, TODAY, PARIS)

    assert result[2] == pytest.approx(0.3)  # production absente : comptée 0, heure gardée
    assert result[3] == 0.0


def test_today_is_never_used() -> None:
    reader = FakeReader()
    fill(reader, [TODAY], lambda d, h: 9.0)
    fill(reader, days_back(3), lambda d, h: 0.5)

    assert baseline(MODEL, reader, TODAY, TODAY, PARIS)[10] == pytest.approx(0.5)


def test_best_production_over_thirty_complete_days() -> None:
    reader = FakeReader()
    for k, day in enumerate(days_back(40)):
        for hour in range(8, 18):
            reader.add("sensor.pv", day, hour, energy_kwh=1.0 + k / 100)
    reader.add("sensor.pv", TODAY, 12, energy_kwh=50.0)  # journée en cours : ignorée

    result = best_production(MODEL, reader, TODAY, PARIS)

    assert result == BestProduction(
        max_kwh=round(10 * 1.29, 2), day=TODAY - timedelta(days=30), days=30
    )
    assert best_production(MODEL, FakeReader(), TODAY, PARIS) is None


def test_recent_history() -> None:
    reader = FakeReader()
    for k, day in enumerate(days_back(14)):
        reader.add("sensor.soc", day, 14, max=99.6 if k in (4, 9) else 80.0, mean=50.0)
        reader.add("sensor.pool", day, 12, energy_kwh=0.0 if k < 3 else 0.4)

    result = recent_history(MODEL, reader, TODAY, PARIS)

    assert result == RecentHistory(
        last_full_charge=TODAY - timedelta(days=5), days_without_filtration=3, days=14
    )
    assert recent_history(MODEL, FakeReader(), TODAY, PARIS) is None


# --- Rendements de la batterie par sens -------------------------------------------------


def hourly_battery(
    rng: random.Random, hours: int
) -> tuple[dict[datetime, float], dict[datetime, float], dict[datetime, float]]:
    start = datetime(2026, 9, 16, 22, tzinfo=UTC)
    stored, charged, discharged = {}, {}, {}
    level = rng.uniform(1, 4)
    eta_c, eta_d = rng.uniform(0.4, 1.05), rng.uniform(0.4, 1.05)
    for k in range(hours):
        hour = start + timedelta(hours=k)
        kind = rng.choice(["charge", "decharge", "mixte", "repos"])
        c = rng.uniform(0.1, 2) if kind in ("charge", "mixte") else rng.choice([0.0, 0.003])
        d = rng.uniform(0.1, 0.8) if kind in ("decharge", "mixte") else rng.choice([0.0, 0.004])
        level += c * eta_c - d / eta_d + rng.uniform(-0.02, 0.02)
        stored[hour], charged[hour], discharged[hour] = level, c, d
    return stored, charged, discharged


def as_v1_observations(
    stored: dict[datetime, float], charged: dict[datetime, float], discharged: dict[datetime, float]
) -> tuple[list[tuple[str, float]], ...]:
    """Relevés de la v1 aux fins d'heures : stock, compteurs cumulés."""
    stock, charge, discharge = [], [], []
    total_c = total_d = 0.0
    for hour in sorted(stored):
        total_c += charged[hour]
        total_d += discharged[hour]
        at = (hour + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        stock.append((at, stored[hour]))
        charge.append((at, total_c))
        discharge.append((at, total_d))
    return stock, charge, discharge


@pytest.mark.parametrize("seed", range(300))
def test_efficiencies_same_as_v1(seed: int) -> None:
    rng = random.Random(seed)
    stored, charged, discharged = hourly_battery(rng, rng.randint(2, 30 * 24))
    expected = v1(
        "forme_horaire_solaire.rendements_depuis_releves",
        *as_v1_observations(stored, charged, discharged),
    )

    actual = efficiencies_from_hours(stored, charged, discharged)

    assert actual.ok == (expected["status"] == "ok")
    assert actual.message == expected.get("message")
    assert actual.charged_kwh == expected["energie_chargee_kwh"]
    assert actual.discharged_kwh == expected["energie_dechargee_kwh"]
    assert (actual.charge_hours, actual.discharge_hours) == (
        expected["nb_heures_charge"],
        expected["nb_heures_decharge"],
    )
    assert actual.days == expected["nb_jours"]
    assert actual.raw_charge_percent == expected.get("rendement_charge_brut_percent")
    assert actual.raw_discharge_percent == expected.get("rendement_decharge_brut_percent")
    assert actual.charge_percent == expected.get("rendement_charge_percent")
    assert actual.discharge_percent == expected.get("rendement_decharge_percent")


def test_battery_efficiencies_read_the_soc_at_the_end_of_each_hour() -> None:
    reader = FakeReader()
    model = MODEL.model_copy(deep=True)
    for d in model.devices:
        if d.kind is DeviceKind.BATTERY:
            d.capacity_kwh = 5.0
    soc = 20.0
    for day in reversed(days_back(10)):
        for hour in range(24):
            charging = 10 <= hour < 14
            charge, discharge = (1.0, 0.0) if charging else (0.0, 0.2 if hour >= 18 else 0.0)
            soc += (charge * 0.9 - discharge / 0.95) / 5.0 * 100
            reader.add("sensor.soc", day, hour, last=soc, mean=soc, max=soc)
            reader.add("sensor.chg", day, hour, energy_kwh=charge)
            reader.add("sensor.dis", day, hour, energy_kwh=discharge)

    result = battery_efficiencies(model, reader, TODAY, PARIS)

    assert result.ok
    assert result.charge_percent == pytest.approx(90.0, abs=0.1)
    assert result.discharge_percent == pytest.approx(95.0, abs=0.1)
    assert not battery_efficiencies(MODEL, reader, TODAY, PARIS).ok  # capacité inconnue


def test_the_meter_jump_behind_an_impossible_baseline_is_found() -> None:
    """Un compteur coupé un instant puis revenu à son index : tout l'index compté en une heure
    un vendredi à 20 h fausse la base des vendredis suivants (lot 7.3)."""
    reader = FakeReader()
    fill(reader, days_back(63), lambda d, h: 0.4)
    jump_day = TODAY - timedelta(days=7)
    reader.add("sensor.imp_hp", jump_day, 20, energy_kwh=64045.0)
    reader.add("sensor.tv", TODAY - timedelta(days=3), 20, energy_kwh=-90.0)  # autre jour
    friday = TODAY + timedelta(days=7)

    found = spike(MODEL, reader, friday, 20, TODAY, PARIS, limit_kwh=11.5)

    assert found is not None
    assert (found.entity_id, found.device, found.energy_kwh) == ("sensor.imp_hp", "grid", 64045.0)
    assert found.start == datetime.combine(jump_day, time(20), PARIS)
    assert baseline(MODEL, reader, friday, TODAY, PARIS)[20] > 10000  # la base en dépend
    assert spike(MODEL, reader, friday, 20, TODAY, PARIS, limit_kwh=1e6) is None
