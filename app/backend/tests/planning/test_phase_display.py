"""Maison en triphasé : ce que le plan calculé par phase donne aux écrans (échange de chaque
phase, courbe de charge, mesures par phase)."""

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from tests.planning.test_actual import DAY, MODEL, at, reading
from tests.planning.test_phase_battery import BASE, battery, home, on_phase_2
from wattslot.detection import DeviceKind, Role
from wattslot.home_model import HomeDevice, HomeModel, HomeSensor, Phase, Supply
from wattslot.planning.actual import actual_day
from wattslot.planning.engine import plan_day
from wattslot.planning.merge import merge_plans
from wattslot.storage.raw import RawStores
from wattslot.views.day import phase_days
from wattslot.views.display import grid_exchange

BY_PHASE = ("residu_reseau_par_phase", "compteur_par_phase", "batteries_par_phase")


def stored(found: Any) -> dict[str, Any]:
    """Plan tel qu'il est enregistré (format de la v1)."""
    return plan_day(found, explained=False).day.to_v1()


def test_a_plan_computed_on_the_whole_home_says_nothing_about_phases() -> None:
    plan = stored(home(BASE, sun_kwh=1.5))

    assert not any(key in plan for key in BY_PHASE)


def test_the_plan_keeps_the_exchange_of_each_phase() -> None:
    separate = stored(replace(home(BASE, sun_kwh=1.5), separate_phases=True))
    batteries = stored(on_phase_2(home(BASE, sun_kwh=1.5), battery(5.0, 0.0)))

    assert set(separate["residu_reseau_par_phase"]) == {"1", "2", "3"}
    assert separate["residu_reseau_par_phase"]["2"][10] == pytest.approx(1.3)
    assert separate["compteur_par_phase"] is True and "batteries_par_phase" not in separate
    # Batterie sur la phase 2 : elle prend le surplus de sa phase, qui n'injecte plus rien.
    assert batteries["residu_reseau_par_phase"]["2"][10] == pytest.approx(0.0)
    assert batteries["batteries_par_phase"] is True and "compteur_par_phase" not in batteries


def test_the_screens_count_each_phase_when_the_meter_does() -> None:
    summed = stored(home(BASE, sun_kwh=1.5))
    separate = stored(replace(home(BASE, sun_kwh=1.5), separate_phases=True))

    together, apart = grid_exchange(summed), grid_exchange(separate)

    # Compteur qui additionne : 0,5 kWh de surplus à 10 h, rien de soutiré.
    assert together[0][10] == 0.0 and together[1][10] == pytest.approx(0.5)
    # Chaque phase à part : la phase 2 injecte pendant que les phases 1 et 3 soutirent.
    assert apart[0][10] == pytest.approx(0.8) and apart[1][10] == pytest.approx(1.3)
    # Des batteries par phase ne changent pas ce que compte un compteur qui additionne.
    batteries = stored(on_phase_2(home(BASE, sun_kwh=1.5), battery(5.0, 0.0)))
    assert grid_exchange(batteries)[0][10] == pytest.approx(0.8)
    assert grid_exchange(batteries)[1][10] == pytest.approx(0.0)


def test_the_exchange_of_each_phase_is_merged_hour_by_hour() -> None:
    old = stored(replace(home(BASE, sun_kwh=1.5), separate_phases=True))
    new = stored(replace(home(BASE, sun_kwh=3.0), separate_phases=True))

    merged = merge_plans(new, old, 12)

    phase = merged["residu_reseau_par_phase"]["2"]
    assert phase[10] == pytest.approx(1.3)  # avant midi : l'ancien plan
    assert phase[12] == pytest.approx(2.8)  # ensuite : le nouveau


def test_the_day_view_lists_the_three_phases() -> None:
    plan = stored(replace(home(BASE, sun_kwh=1.5), separate_phases=True))
    actual = {
        "reseau_reel_soutire_par_phase": {"1": {0: 0.4, 1: 0.6}, "3": {0: 0.2}},
        "reseau_reel_injecte_par_phase": {"2": {10: 1.1}},
    }

    found = phase_days(plan, actual)

    assert [p.phase for p in found] == [1, 2, 3]
    # Phase 2 : 0,2 kWh soutirés vingt heures, 1,3 kWh injectés quatre heures.
    assert found[1].import_kwh == pytest.approx(4.0)
    assert found[1].export_kwh == pytest.approx(5.2)
    assert (found[0].import_actual_kwh, found[0].export_actual_kwh) == (1.0, None)
    assert (found[1].import_actual_kwh, found[1].export_actual_kwh) == (None, 1.1)
    assert phase_days(stored(home(BASE)), None) == []


def test_measures_of_the_day_by_phase(tmp_path: Path) -> None:
    grid = HomeDevice(
        key="grid",
        kind=DeviceKind.GRID,
        name="Réseau",
        sensors=[
            HomeSensor(entity_id="sensor.import_hp", role=Role.ENERGY_IMPORTED),
            HomeSensor(entity_id="sensor.import_l2", role=Role.ENERGY_IMPORTED, phase=Phase.L2),
            HomeSensor(entity_id="sensor.export_l2", role=Role.ENERGY_EXPORTED, phase=Phase.L2),
        ],
    )
    model = HomeModel(supply=Supply.THREE, devices=[grid])
    raw = RawStores(tmp_path, "Europe/Paris")
    raw.write(
        [
            reading("grid", "sensor.import_hp", 50.0, at(-1)),
            reading("grid", "sensor.import_hp", 51.0, at(9)),
            reading("grid", "sensor.import_l2", 10.0, at(-1)),
            reading("grid", "sensor.import_l2", 10.4, at(9)),
            reading("grid", "sensor.export_l2", 5.0, at(10)),
            reading("grid", "sensor.export_l2", 5.5, at(11)),
        ]
    )

    found = actual_day(model, raw, DAY, at(12))
    without = actual_day(MODEL, raw, DAY, at(12))

    assert sum(found["reseau_reel_soutire_par_phase"]["2"].values()) == pytest.approx(0.4)
    assert sum(found["reseau_reel_injecte_par_phase"]["2"].values()) == pytest.approx(0.5)
    # Le capteur de la phase n'entre pas dans le total, mesuré par un autre capteur.
    assert sum(found["reseau_reel_soutire_horaire"].values()) == pytest.approx(1.0)
    assert "reseau_reel_soutire_par_phase" not in without
