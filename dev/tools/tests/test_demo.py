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


# --- Maison en triphasé -------------------------------------------------------------------------


def three_phase_day(separate_meter: bool = False) -> tuple[dict[str, float], dict[str, float]]:
    """(premier, dernier) relevé d'une journée de la maison en triphasé, chauffe-eau à midi."""
    house = h.ThreePhaseHouse(separate_meter=separate_meter)
    house.start(h.WATER_HEATER, datetime.combine(h.DAY, time(12), h.ZONE))
    midnight = datetime.combine(h.DAY, time(), h.ZONE)
    values = [house.step(midnight + timedelta(minutes=m)) for m in range(1441)]
    return values[0], values[-1]


def test_the_three_phase_home_balances_phase_by_phase() -> None:
    first, last = three_phase_day()

    def delta(entity_id: str) -> float:
        return last[entity_id] - first[entity_id]

    exchanged = {n: delta(h.phase_import(n)) - delta(h.phase_export(n)) for n in h.PHASES}
    # Le compteur du total additionne les phases.
    total = delta(h.GRID_IMPORT) - delta(h.GRID_EXPORT)
    assert sum(exchanged.values()) == pytest.approx(total, abs=0.01)
    # Phase 1 : ni solaire ni batterie, elle ne fait que soutirer (dont un tiers du chauffe-eau,
    # triphasé).
    heater = delta(h.energy_entity(h.WATER_HEATER))
    assert delta(h.phase_export(1)) == 0 and delta(h.phase_import(1)) > heater / 3
    # Phases 2 et 3 : la moitié du toit chacune, et une batterie qui ne compense que sa phase.
    assert delta(h.SOLAR_ENERGY) == pytest.approx(delta(h.SOLAR_2_ENERGY))
    assert delta(h.phase_export(2)) > 0 and delta(h.phase_export(3)) > 0
    consumed_2 = delta(h.SOLAR_ENERGY) + exchanged[2] + delta(h.BATTERY_DISCHARGE)
    consumed_2 -= delta(h.BATTERY_CHARGE)
    # Un cinquième de la consommation de base et un tiers du chauffe-eau, en kWh.
    assert 1.5 + heater / 3 < consumed_2 < 4 + heater / 3


def test_the_three_phase_home_is_read_by_the_detection() -> None:
    from tools.demo import energy_preferences, home_from_proposal
    from wattslot.home_model import Phase, Supply

    first, _ = three_phase_day()
    entities, devices = registries("fr", three_phase=True)
    snapshot = HomeSnapshot(
        config={"time_zone": "Europe/Paris"},
        energy_preferences=energy_preferences(True),
        states={s["entity_id"]: s for s in ha_states(first, "fr")},
        entities={e["entity_id"]: e for e in entities},
        devices={d["id"]: d for d in devices},
    )

    home = home_from_proposal(propose(snapshot), "fr", three_phase=True)

    assert home.supply is Supply.THREE
    by_name = {device.name: device for device in home.devices}
    assert by_name["Batterie maison"].phase is Phase.L2
    assert by_name["Batterie du garage"].phase is Phase.L3
    assert by_name["Batterie du garage"].capacity_kwh == h.CAPACITY_KWH
    assert by_name["Panneaux solaires du garage"].phase is Phase.L3
    assert by_name["Chauffe-eau"].phase is Phase.ALL  # triphasé
    assert by_name["Lave-linge"].phase is Phase.L1
    assert home.meter_sums_phases is True
    grid = by_name["Réseau"]
    assert grid.phase is None
    assert sorted(s.phase.value for s in grid.sensors if s.phase) == [
        "PhaseL1", "PhaseL1", "PhaseL2", "PhaseL2", "PhaseL3", "PhaseL3"
    ]  # fmt: skip
    assert len([s for s in grid.sensors if s.phase is None]) == 2


def test_a_meter_that_counts_each_phase_apart_does_not_net_them() -> None:
    summed_first, summed_last = three_phase_day()
    first, last = three_phase_day(separate_meter=True)

    def delta(entity_id: str) -> float:
        return last[entity_id] - first[entity_id]

    # Le total est la somme de chaque phase, sans compensation entre elles.
    imported = sum(delta(h.phase_import(n)) for n in h.PHASES)
    exported = sum(delta(h.phase_export(n)) for n in h.PHASES)
    assert delta(h.GRID_IMPORT) == pytest.approx(imported, abs=0.01)
    assert delta(h.GRID_EXPORT) == pytest.approx(exported, abs=0.01)
    # La même journée coûte plus de soutirage qu'avec un compteur qui additionne.
    summed = summed_last[h.GRID_IMPORT] - summed_first[h.GRID_IMPORT]
    assert delta(h.GRID_IMPORT) > summed + 1
