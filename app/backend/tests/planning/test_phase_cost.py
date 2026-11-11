"""Maison en triphasé dont le compteur compte chaque phase à part : le soutirage d'une phase
n'est pas compensé par l'injection d'une autre."""

from dataclasses import replace

import pytest

from tests.planning.test_phase_battery import BASE, SUNNY, battery, home, on_phase_2
from tests.planning.test_phase_limit import CHEAP_HOUR, NO_BATTERY, starts, task
from wattslot.home_model import LINES, HomeDevice, HomeModel, Phase, Supply
from wattslot.planning.assemble import configured
from wattslot.planning.engine import plan_day, simulate_plan, solve
from wattslot.planning.inputs import Battery, PlanningInput
from wattslot.planning.plan import Indicators
from wattslot.planning.problem import Problem, from_input


def indicators(found: Problem) -> Indicators:
    result = plan_day(found, explained=False).day.indicators
    assert result is not None
    return result


def test_surplus_on_one_phase_does_not_offset_the_import_of_another() -> None:
    # 1,5 kWh produits sur la phase 2 aux heures ensoleillées, 1 kWh consommé sur les trois.
    summed = home(BASE, sun_kwh=1.5)
    separate = replace(summed, separate_phases=True)

    together, apart = indicators(summed), indicators(separate)

    # Compteur qui additionne : 0,5 kWh de surplus par heure ensoleillée, rien de soutiré.
    assert together.import_kwh == pytest.approx(20.0)
    assert together.export_kwh == pytest.approx(2.0)
    # Chaque phase à part : la phase 2 injecte 1,3 kWh, les phases 1 et 3 soutirent 0,8 kWh.
    assert apart.import_kwh == pytest.approx(20.0 + len(SUNNY) * 0.8)
    assert apart.export_kwh == pytest.approx(len(SUNNY) * 1.3)
    assert apart.cost_eur == pytest.approx(together.cost_eur + len(SUNNY) * 0.8 * 0.25)


def test_the_exchange_of_each_phase_adds_up_to_the_exchange_of_the_home() -> None:
    separate = replace(home(BASE, sun_kwh=1.5), separate_phases=True)

    run = simulate_plan(separate, solve(separate))

    assert set(run.phase_residual_kwh) == set(LINES)
    assert run.phase_residual_kwh[Phase.L2][10] == pytest.approx(1.3)
    assert run.phase_residual_kwh[Phase.L1][10] == pytest.approx(-0.5)
    for hour in range(24):
        phases = sum(run.phase_residual_kwh[line][hour] for line in LINES)
        assert phases == pytest.approx(run.residual_kwh[hour])


def test_the_plan_puts_an_appliance_under_the_surplus_of_its_own_phase() -> None:
    def placed(phase: Phase, separate: bool) -> int:
        found = home(BASE, sun_kwh=1.5, tasks=[task("washer", 1)], phases={"washer": phase})
        return starts(replace(found, separate_phases=separate))["washer"]

    # Compteur qui additionne : 0,5 kWh de surplus ne valent pas l'heure bon marché.
    assert placed(Phase.L2, separate=False) == CHEAP_HOUR
    # Chaque phase à part : sur la phase du solaire, le cycle entier est gratuit au soleil.
    assert placed(Phase.L2, separate=True) in SUNNY
    # Sur une autre phase, le soleil ne lui sert à rien.
    assert placed(Phase.L1, separate=True) == CHEAP_HOUR


def test_what_is_on_no_phase_is_shared_between_the_three() -> None:
    # Un équipement sans phase : son kWh compte pour un tiers sur chacune.
    found = replace(home(BASE, tasks=[task("oven", 3)]), separate_phases=True)

    result = plan_day(found, explained=False)

    hour = result.plan.starts["oven"] // 60
    for line in LINES:
        assert result.battery.phase_residual_kwh[line][hour] == pytest.approx(-BASE[line] - 1.0)


def test_a_battery_on_one_phase_with_a_meter_that_counts_each_phase() -> None:
    alone = replace(on_phase_2(home(BASE), battery(5.0, 5.0)), separate_phases=True)

    run = simulate_plan(alone, solve(alone))

    # La batterie de la phase 2 couvre sa phase ; les deux autres soutirent toujours.
    assert run.phase_residual_kwh[Phase.L2][0] == pytest.approx(0.0)
    assert run.phase_residual_kwh[Phase.L1][0] == pytest.approx(-0.5)
    assert indicators(alone).import_kwh == pytest.approx(24 * 0.8)


def test_without_separate_phases_nothing_is_counted_by_phase() -> None:
    summed = home(BASE, sun_kwh=1.5)

    assert simulate_plan(summed, solve(summed)).phase_residual_kwh == {}


# --- De la maison au problème ---------------------------------------------------------------------

EVERY_HOUR = {line: dict.fromkeys(range(24), 0.3) for line in LINES}
INPUT = PlanningInput(
    day=home(BASE).day,
    first_hour=0,
    net_kwh=dict.fromkeys(range(24), -0.9),
    production_kwh=dict.fromkeys(range(24), 0.0),
    battery=Battery(0.0, 0.0, 0.0, charge_max_w=0.0, discharge_max_w=0.0),
    runtimes=(),
    base_by_phase=EVERY_HOUR,
)


def model(supply: Supply, sums: bool) -> HomeModel:
    return HomeModel(supply=supply, meter_sums_phases=sums, devices=list[HomeDevice]())


def test_each_phase_is_counted_apart_only_when_it_can_be() -> None:
    from wattslot.configuration import Configuration

    def separate(home_model: HomeModel, data: PlanningInput = INPUT) -> bool:
        return from_input(configured(data, home_model, Configuration())).separate_phases

    assert separate(model(Supply.THREE, sums=False)) is True
    assert separate(model(Supply.THREE, sums=True)) is False
    assert separate(model(Supply.SINGLE, sums=False)) is False
    # Consommation de base d'une phase inconnue à certaines heures : compté sur le total.
    partial = {**EVERY_HOUR, Phase.L3: {12: 0.3}}
    assert separate(model(Supply.THREE, sums=False), replace(INPUT, base_by_phase=partial)) is False
    assert NO_BATTERY.capacity_kwh == 0
