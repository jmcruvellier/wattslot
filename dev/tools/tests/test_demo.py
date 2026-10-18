"""Démonstration des captures (lot 7.2) : maison synthétique déterministe, physique cohérente,
capteurs que la détection et le journal des cycles de l'application savent lire."""

from datetime import UTC, datetime, time, timedelta

import pytest

from tools import demo_home as h
from tools.demo import (
    ENERGY_PREFERENCES,
    Clock,
    FrozenDatetime,
    ha_states,
    planned_starts,
    registries,
    solar_forecast,
)
from wattslot.detection import DeviceKind, Role, propose
from wattslot.home_assistant import HomeSnapshot
from wattslot.planning.appliances import measure_cycles


def simulate(day: h.date, starts: dict[str, datetime]) -> list[tuple[datetime, dict[str, float]]]:
    house = h.House()
    for appliance, start in starts.items():
        house.start(appliance, start)
    midnight = datetime.combine(day, time(), h.ZONE)
    return [
        (midnight + timedelta(minutes=m), house.step(midnight + timedelta(minutes=m)))
        for m in range(1440)
    ]


def test_the_synthetic_home_is_deterministic() -> None:
    day = h.DAY - timedelta(days=5)

    assert h.weather(day) == h.weather(day)
    assert h.past_starts(day) == h.past_starts(day)
    assert simulate(day, h.past_starts(day))[-1] == simulate(day, h.past_starts(day))[-1]


def test_energy_balances_every_minute() -> None:
    values = simulate(h.DAY, {h.WATER_HEATER: datetime.combine(h.DAY, time(12), h.ZONE)})
    first, last = values[0][1], values[-1][1]

    def delta(entity_id: str) -> float:
        return last[entity_id] - first[entity_id]

    supplied = delta(h.SOLAR_ENERGY) + delta(h.GRID_IMPORT) + delta(h.BATTERY_DISCHARGE)
    used = delta(h.GRID_EXPORT) + delta(h.BATTERY_CHARGE)
    appliances = sum(delta(h.energy_entity(a)) for a in h.APPLIANCES)
    assert supplied - used > appliances > 0  # le reste : la consommation de base
    assert 8 < supplied - used - appliances < 16  # kWh de base par jour
    assert all(h.FLOOR_PERCENT - 1 <= v[h.BATTERY_LEVEL] <= 100 for _, v in values)


def test_a_sunny_june_day_and_its_forecast() -> None:
    produced = sum(h.solar_w(h.DAY, m) for m in range(1440)) / 60_000
    forecast = sum(h.forecast_wh(h.DAY).values()) / 1000

    assert 20 < produced < 27
    assert forecast == pytest.approx(produced, rel=0.1)
    assert sum(h.forecast_wh(h.DAY + timedelta(days=3)).values()) < forecast * 1000 / 2  # pluie


@pytest.mark.parametrize("appliance", h.APPLIANCES)
def test_each_program_is_measured_as_one_cycle(appliance: str) -> None:
    start = datetime.combine(h.DAY, time(10), h.ZONE)
    values = simulate(h.DAY, {appliance: start})
    power = [(t, v[h.power_entity(appliance)]) for t, v in values]
    counter = [(t, v[h.energy_entity(appliance)]) for t, v in values]
    kind = {
        h.WATER_HEATER: DeviceKind.WATER_HEATER,
        h.WASHING_MACHINE: DeviceKind.WASHING_MACHINE,
        h.DRYER: DeviceKind.DRYER,
        h.DISHWASHER: DeviceKind.DISHWASHER,
    }[appliance]
    end = values[-1][0] + timedelta(minutes=1)

    (cycle,) = measure_cycles(kind, power, counter, end, window_start=values[0][0])

    assert cycle.start == start
    assert cycle.minutes == pytest.approx(h.program_minutes(appliance), abs=1)
    assert cycle.energy_kwh == pytest.approx(h.program_kwh(appliance), abs=0.02)


@pytest.mark.parametrize("language", ["en", "fr"])
def test_detection_proposes_the_whole_home_without_issue(language: str) -> None:
    values = simulate(h.DAY, {})[-1][1]
    entities, devices = registries(language)
    snapshot = HomeSnapshot(
        config={"time_zone": "Europe/Paris"},
        energy_preferences=ENERGY_PREFERENCES,
        states={s["entity_id"]: s for s in ha_states(values, language)},
        entities={e["entity_id"]: e for e in entities},
        devices={d["id"]: d for d in devices},
    )

    proposal = propose(snapshot)

    assert sorted(d.kind for d in proposal.devices) == sorted(
        [
            DeviceKind.SOLAR,
            DeviceKind.GRID,
            DeviceKind.BATTERY,
            DeviceKind.WATER_HEATER,
            DeviceKind.WASHING_MACHINE,
            DeviceKind.DRYER,
            DeviceKind.DISHWASHER,
        ]
    )
    assert [i for d in proposal.devices for i in d.issues] == []
    assert [i for d in proposal.devices for s in d.sensors for i in s.issues] == []
    battery = next(d for d in proposal.devices if d.kind is DeviceKind.BATTERY)
    assert battery.capacity_kwh == h.CAPACITY_KWH
    assert Role.STATE_OF_CHARGE in {s.role for s in battery.sensors}


def test_the_forecast_covers_the_horizon() -> None:
    hours = solar_forecast()["demo-forecast"]["wh_hours"]
    days = {datetime.fromisoformat(m).astimezone(h.ZONE).date() for m in hours}

    assert min(days) == h.DAY - timedelta(days=1)
    assert max(days) == h.DAY + timedelta(days=h.FORECAST_DAYS)


def test_the_frozen_clock() -> None:
    Clock.moment = h.NOW

    assert FrozenDatetime.now(UTC) == h.NOW
    assert FrozenDatetime.now(h.ZONE).hour == 14
    assert FrozenDatetime.now().replace(tzinfo=h.ZONE) == h.NOW


def test_planned_starts_are_read_in_local_time() -> None:
    content = {
        "date_cible": h.DAY.isoformat(),
        "planning": [
            {"equipement": "Dishwasher", "heure_debut": 15, "heure_fin": 17, "debut_min": 900},
            {"equipement": "Batterie", "mouvements": []},
        ],
    }

    starts = planned_starts(content, {"Dishwasher": h.DISHWASHER})

    assert starts == {h.DISHWASHER: datetime.combine(h.DAY, time(15), h.ZONE)}
