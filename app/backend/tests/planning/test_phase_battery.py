"""Maison en triphasé : une batterie qui ne compense que sa phase charge sur le surplus de cette
phase et ne couvre que son déficit ; celle qui compense le total passe après."""

from dataclasses import replace

import pytest

from tests.planning.test_phase_limit import CHEAP_HOUR, NO_BATTERY, problem, starts, task
from wattslot.battery_settings import BatterySettings
from wattslot.configuration import Behavior, Configuration, DeviceSettings
from wattslot.detection import DeviceKind, Role
from wattslot.home_model import HomeDevice, HomeModel, HomeSensor, Phase, Supply
from wattslot.planning.assemble import battery_groups
from wattslot.planning.engine import Result, plan_day, simulate_plan, solve
from wattslot.planning.inputs import Battery, PlanningInput, with_battery
from wattslot.planning.problem import BatteryModel, Problem, from_input

HOURS = range(24)
SUNNY = range(10, 14)


def battery(capacity_kwh: float, stored_kwh: float, floor_kwh: float = 0.0) -> BatteryModel:
    return replace(
        NO_BATTERY,
        capacity_kwh=capacity_kwh,
        stored_kwh=stored_kwh,
        soc_percent=stored_kwh / capacity_kwh * 100,
        charge_max_kw=2.5,
        discharge_max_kw=2.5,
        floor_kwh=floor_kwh,
        full_kwh=capacity_kwh,
    )


def home(base: dict[Phase, float], sun_kwh: float = 0.0, **change: object) -> Problem:
    """Maison sans limite de phase : consommation de base constante sur chaque phase,
    production branchée sur la phase 2 aux heures ensoleillées."""
    production = {hour: sun_kwh if hour in SUNNY else 0.0 for hour in HOURS}
    total = sum(base.values())
    return problem(
        phase_limit_kwh=None,
        contract_kwh=None,
        production_kwh=production,
        net_kwh={hour: production[hour] - total for hour in HOURS},
        production_shares={Phase.L2: 1.0},
        base_by_phase={line: dict.fromkeys(HOURS, kwh) for line, kwh in base.items()},
        **change,
    )


def on_phase_2(found: Problem, group: BatteryModel) -> Problem:
    """La même batterie, qui ne compense que la phase 2 ; aucune ne compense le total."""
    return replace(
        found, battery=group, line_batteries={Phase.L2: group}, shared_battery=NO_BATTERY
    )


BASE = {Phase.L1: 0.5, Phase.L2: 0.2, Phase.L3: 0.3}


# --- Simulation -----------------------------------------------------------------------------------


def test_a_battery_on_one_phase_only_covers_the_deficit_of_that_phase() -> None:
    group = battery(5.0, 5.0)
    whole = replace(home(BASE), battery=group)
    alone = on_phase_2(home(BASE), group)

    everything = simulate_plan(whole, solve(whole))
    one_phase = simulate_plan(alone, solve(alone))

    # Sur le total : elle couvre le kWh de chaque heure, jusqu'à être vide.
    assert everything.residual_kwh[0] == pytest.approx(0.0)
    assert everything.end_kwh == pytest.approx(0.0)
    # Sur sa phase : 0,2 kWh par heure, le reste est soutiré.
    assert one_phase.residual_kwh[0] == pytest.approx(-0.8)
    assert one_phase.end_kwh == pytest.approx(5.0 - 24 * 0.2)
    assert one_phase.lines[Phase.L2].residual_kwh[0] == pytest.approx(0.0)


def test_a_battery_on_one_phase_only_charges_on_the_surplus_of_that_phase() -> None:
    alone = on_phase_2(home(BASE, sun_kwh=1.5), battery(5.0, 0.0))

    run = simulate_plan(alone, solve(alone))

    # 1,5 kWh produits sur la phase 2, 0,2 kWh consommés : 1,3 kWh chargés, alors que la maison
    # entière n'a que 0,5 kWh de surplus.
    assert run.soc_kwh[10] == pytest.approx(1.3)
    assert run.residual_kwh[10] == pytest.approx(0.5 - 1.3)
    assert [m.action for m in run.movements if m.hour == 10] == ["charge"]


def test_the_battery_that_offsets_the_total_comes_after_the_phase_batteries() -> None:
    group, shared = battery(5.0, 4.0), battery(5.0, 4.0)
    whole = battery(10.0, 8.0)
    found = replace(
        home(BASE), battery=whole, line_batteries={Phase.L2: group}, shared_battery=shared
    )

    run = simulate_plan(found, solve(found))

    # La batterie de la phase 2 couvre ses 0,2 kWh, l'autre les 0,8 kWh qui restent.
    assert run.residual_kwh[0] == pytest.approx(0.0)
    assert run.soc_kwh[0] == pytest.approx(8.0 - 1.0)
    assert run.lines[Phase.L2].soc_kwh[0] == pytest.approx(3.8)
    assert found.total_battery is shared


def test_movements_of_the_same_hour_on_two_phases_are_netted() -> None:
    # Phase 2 : surplus de 1,3 kWh, sa batterie charge. Phase 3 : déficit, sa batterie décharge.
    lines = {Phase.L2: battery(5.0, 0.0), Phase.L3: battery(5.0, 5.0)}
    found = replace(
        home(BASE, sun_kwh=1.5),
        battery=battery(10.0, 5.0),
        line_batteries=lines,
        shared_battery=NO_BATTERY,
    )

    run = simulate_plan(found, solve(found))

    assert [(m.action, m.energy_kwh) for m in run.movements if m.hour == 10] == [("charge", 1.0)]
    assert run.soc_kwh[10] == pytest.approx(5.0 + 1.3 - 11 * 0.3)


# --- Moteur ---------------------------------------------------------------------------------------


def imported_kwh(result: Result) -> float:
    assert result.day.indicators is not None
    return result.day.indicators.import_kwh


def test_the_plan_does_not_count_on_the_battery_of_another_phase() -> None:
    # Batterie pleine sur la phase 2, qui n'a rien à couvrir ; chauffe-eau sur la phase 1.
    base = {Phase.L1: 0.5, Phase.L2: 0.0, Phase.L3: 0.0}
    heater = home(base, tasks=[task("heater", 2)], phases={"heater": Phase.L1})
    alone = on_phase_2(heater, battery(5.0, 4.0))

    result = plan_day(alone, explained=False)

    # La batterie ne peut rien pour lui : il prend l'heure bon marché, et tout est soutiré.
    assert result.plan.starts == {"heater": CHEAP_HOUR * 60}
    assert imported_kwh(result) == pytest.approx(24 * 0.5 + 2)
    assert result.battery.end_kwh == pytest.approx(4.0)


def test_an_appliance_on_the_phase_of_the_battery_is_covered_by_it() -> None:
    base = {Phase.L1: 0.5, Phase.L2: 0.0, Phase.L3: 0.0}
    heater = home(base, tasks=[task("heater", 2)], phases={"heater": Phase.L2})
    alone = on_phase_2(heater, battery(5.0, 4.0))

    result = plan_day(alone, explained=False)

    assert "heater" in result.plan.starts
    assert imported_kwh(result) == pytest.approx(24 * 0.5)
    assert result.battery.end_kwh == pytest.approx(2.0)


def test_without_phase_batteries_the_calculation_is_unchanged() -> None:
    heater = replace(
        home(BASE, tasks=[task("heater", 2)], phases={"heater": Phase.L1}),
        battery=battery(5.0, 4.0),
    )
    # Mêmes données, sans phase ni consommation par phase : le calcul d'avant.
    plain = replace(heater, phases={}, base_by_phase={}, production_shares={})

    assert starts(heater) == starts(plain)
    assert simulate_plan(heater, solve(heater)) == simulate_plan(plain, solve(plain))


# --- De la maison au problème ---------------------------------------------------------------------


def storage(key: str, phase: Phase | None, capacity_kwh: float) -> HomeDevice:
    return HomeDevice(
        key=key,
        kind=DeviceKind.BATTERY,
        name=key,
        phase=phase,
        capacity_kwh=capacity_kwh,
        sensors=[HomeSensor(entity_id=f"sensor.{key}_soc", role=Role.STATE_OF_CHARGE)],
    )


MODEL = HomeModel(
    supply=Supply.THREE,
    devices=[
        storage("garage", Phase.L2, 5.0),
        storage("cellar", Phase.L2, 3.0),
        storage("attic", Phase.L3, 2.0),
        storage("hybrid", Phase.ALL, 10.0),
        storage("shed", None, 4.0),
        storage("meter", Phase.L1, 6.0),
        storage("silent", Phase.L1, 6.0),
    ],
)
STATES = [
    {"entity_id": f"sensor.{key}_soc", "state": state}
    for key, state in (
        ("garage", "50"),
        ("cellar", "100"),
        ("attic", "10"),
        ("hybrid", "20"),
        ("shed", "50"),
        ("meter", "100"),
        ("silent", "unavailable"),
    )
]
SETTINGS = Configuration(
    devices=[
        DeviceSettings(
            key="cellar",
            behavior=Behavior.STORAGE,
            battery=BatterySettings(floor_percent=30, charge_max_w=600, discharge_max_w=600),
        ),
        # Elle suit un compteur triphasé : elle compense le total, pas sa phase.
        DeviceSettings(
            key="meter", behavior=Behavior.STORAGE, battery=BatterySettings(all_phases=True)
        ),
    ]
)
WHOLE = Battery(30.0, 16.0, 53.3, charge_max_w=15000, discharge_max_w=15000)


def test_batteries_are_grouped_by_the_phase_they_offset() -> None:
    lines, shared = battery_groups(WHOLE, MODEL, STATES, SETTINGS)

    assert set(lines) == {Phase.L2, Phase.L3}
    # Phase 2 : 5 kWh à 50 % et 3 kWh à 100 % ; puissances additionnées, plancher pondéré.
    two = lines[Phase.L2]
    assert (two.capacity_kwh, two.stored_kwh) == (8.0, 5.5)
    assert (two.charge_max_w, two.discharge_max_w) == (3100, 3100)
    assert two.floor_percent == pytest.approx((5 * 10 + 3 * 30) / 8)
    assert (lines[Phase.L3].capacity_kwh, lines[Phase.L3].stored_kwh) == (2.0, 0.2)
    # Le total : la batterie triphasée, celle sans phase et celle qui suit le compteur ; celle
    # dont l'état de charge est illisible n'est comptée nulle part.
    assert (shared.capacity_kwh, shared.stored_kwh) == (20.0, 10.0)
    assert sum(g.capacity_kwh for g in [*lines.values(), shared]) == WHOLE.capacity_kwh


def test_each_group_takes_its_share_of_the_home_powers() -> None:
    house = Configuration(battery=BatterySettings(charge_max_w=6000, discharge_max_w=3000))

    lines, shared = battery_groups(WHOLE, MODEL, STATES, house)

    # 36 kWh de batteries dans la maison, dont une illisible : 8 kWh sur la phase 2, 2 kWh sur
    # la phase 3, 6 kWh sur la phase 1, 14 kWh sur le total ; chacune prend sa part des 6 kW.
    assert lines[Phase.L2].charge_max_w == pytest.approx(6000 * 8 / 36)
    assert lines[Phase.L3].discharge_max_w == pytest.approx(3000 * 2 / 36)
    assert lines[Phase.L1].charge_max_w == pytest.approx(6000 * 6 / 36)
    assert shared.charge_max_w == pytest.approx(6000 * 14 / 36)


def test_no_groups_without_a_battery_on_one_phase() -> None:
    single = MODEL.model_copy(update={"supply": Supply.SINGLE})
    all_shared = Configuration(battery=BatterySettings(all_phases=True))

    assert battery_groups(WHOLE, single, STATES, SETTINGS) == ({}, WHOLE)
    assert battery_groups(WHOLE, MODEL, STATES, all_shared) == ({}, WHOLE)


def test_the_groups_follow_the_whole_battery() -> None:
    lines, shared = battery_groups(WHOLE, MODEL, STATES, SETTINGS)
    data = PlanningInput(
        day=problem().day,
        first_hour=0,
        net_kwh={},
        production_kwh={},
        battery=WHOLE,
        runtimes=(),
        three_phase=True,
        line_batteries=lines,
        shared_battery=shared,
    )

    # Heure en cours : même part écoulée, variation mesurée répartie selon la capacité.
    now = with_battery(data, replace(WHOLE, hour_elapsed=0.5, hour_change_kwh=-3.0))
    assert now.line_batteries[Phase.L2].stored_kwh == 5.5
    assert now.line_batteries[Phase.L2].hour_elapsed == 0.5
    assert now.line_batteries[Phase.L2].hour_change_kwh == pytest.approx(-3.0 * 8 / 30)
    # Jour suivant : on ne connaît que le total, réparti selon la capacité.
    later = with_battery(data, replace(WHOLE, stored_kwh=15.0), spread=True)
    assert later.line_batteries[Phase.L2].stored_kwh == pytest.approx(4.0)
    assert later.shared_battery is not None and later.shared_battery.stored_kwh == pytest.approx(
        10.0
    )

    found = from_input(now)
    assert set(found.line_batteries) == {Phase.L2, Phase.L3}
    assert found.total_battery.capacity_kwh == 20.0 and found.battery.capacity_kwh == 30.0
    # Sans triphasé, les groupes ne servent pas : toutes les batteries compensent le total.
    assert from_input(replace(now, three_phase=False)).line_batteries == {}
