"""Physique de la maison simulée.

cd dev && python -m pytest tools/tests
"""

from pathlib import Path

import pytest

from tools.simulation import DAY_S, Cycle, Day, House

DONNEES = Path(__file__).resolve().parents[2] / "donnees"
DAYS = sorted(DONNEES.glob("*.json"))
STEP_S = 60


def simulate(day: Day) -> House:
    house = House(day)
    socs = []
    for t in range(0, DAY_S, STEP_S):
        house.step(t, STEP_S)
        if house.soc_pct is not None:
            socs.append(house.soc_pct)
    if day.battery:
        assert min(socs) >= day.battery.min_soc_pct - 1e-6
        assert max(socs) <= 100 + 1e-6
    return house


@pytest.mark.parametrize("path", DAYS, ids=lambda p: p.stem)
def test_energy_balance_over_the_day(path: Path) -> None:
    day = Day.load(path)
    house = simulate(day)

    consumed = sum(day.base_load_kwh) + sum(c.energy_kwh for c in day.cycles)
    supplied = house.solar_energy_kwh + house.grid_import_kwh + house.battery_discharge_kwh
    used = consumed + house.grid_export_kwh + house.battery_charge_kwh

    assert house.solar_energy_kwh == pytest.approx(sum(day.solar_kwh))
    assert supplied == pytest.approx(used)


@pytest.mark.parametrize("path", DAYS, ids=lambda p: p.stem)
def test_cycles_consume_their_energy(path: Path) -> None:
    day = Day.load(path)
    house = simulate(day)

    for cycle in day.cycles:
        assert house.device_energy_kwh[cycle.device] == pytest.approx(cycle.energy_kwh)


def test_cycle_power_follows_its_shape() -> None:
    cycle = Cycle(device="d", start_s=3600, energy_kwh=1.0, shape=(0.75, 0.25))

    assert cycle.power_w(3599) == 0
    assert cycle.power_w(3600) == pytest.approx(3000)  # 0,75 kWh en un quart d'heure
    assert cycle.power_w(3600 + 900) == pytest.approx(1000)
    assert cycle.power_w(3600 + 1800) == 0


def test_battery_absorbs_the_sunny_surplus() -> None:
    house = simulate(Day.load(DONNEES / "journee-ensoleillee.json"))

    assert house.battery_charge_kwh > 1
    assert house.battery_discharge_kwh > 0.5
