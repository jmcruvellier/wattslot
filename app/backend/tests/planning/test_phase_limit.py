"""Maison en triphasé : limite de puissance de chaque phase (un tiers de la puissance souscrite)
sur ce que les équipements placés y tirent ensemble."""

from dataclasses import replace
from datetime import date

from wattslot.configuration import Behavior, Configuration, DeviceSettings
from wattslot.detection import DeviceKind
from wattslot.energy_need import EnergyNeed
from wattslot.home_model import HomeDevice, HomeModel, Phase, Supply
from wattslot.planning.assemble import configured
from wattslot.planning.engine import phase_excess, plan_day
from wattslot.planning.inputs import Battery, PlanningInput, TaskRequest
from wattslot.planning.problem import (
    BatteryModel,
    NeedModel,
    Problem,
    Task,
    from_input,
    line_shares,
)
from wattslot.tariff import Tariff

NO_BATTERY = BatteryModel(
    capacity_kwh=0.0,
    stored_kwh=0.0,
    soc_percent=0.0,
    charge_max_kw=0.0,
    discharge_max_kw=0.0,
    active_from=0,
    active_to=24,
    charge_efficiency=1.0,
    discharge_efficiency=1.0,
    floor_kwh=0.0,
    full_kwh=0.0,
    full_priority=False,
)
CHEAP_HOUR = 3


def task(name: str, energy_kwh: float) -> Task:
    """Cycle d'une heure, de puissance constante."""
    return Task(
        name=name,
        key=name,
        energy_kwh=energy_kwh,
        cycle_min=60,
        slot_min=60,
        shape=None,
        priority=3,
        earliest_min=0,
    )


def problem(*tasks: Task, **change: object) -> Problem:
    """Journée sans soleil ni batterie, une seule heure bon marché : sans limite par phase,
    tous les cycles y démarrent. Contrat de 12 kVA, soit 4 kVA par phase."""
    hours = range(24)
    base = Problem(
        day=date(2026, 11, 10),
        first_hour=0,
        net_kwh=dict.fromkeys(hours, -0.3),
        production_kwh=dict.fromkeys(hours, 0.0),
        fixed_kwh=dict.fromkeys(hours, 0.0),
        tasks=list(tasks),
        launched=[],
        battery=NO_BATTERY,
        runtimes=[],
        prices_eur_kwh={hour: 0.10 if hour == CHEAP_HOUR else 0.25 for hour in hours},
        contract_kwh=12.0,
        phase_limit_kwh=4.0,
    )
    return replace(base, **change)  # type: ignore[arg-type]


def starts(found: Problem) -> dict[str, int]:
    return {
        name: start // 60 for name, start in plan_day(found, explained=False).plan.starts.items()
    }


def phase_warnings(found: Problem) -> list[dict[str, str]]:
    warnings = plan_day(found, explained=False).day.warnings
    return [w["params"] for w in warnings if isinstance(w, dict) and w["code"] == "phase_depassee"]


def test_shares_of_a_device_on_the_phases() -> None:
    assert line_shares(Phase.L2) == {Phase.L2: 1.0}
    assert line_shares(Phase.ALL) == {Phase.L1: 1 / 3, Phase.L2: 1 / 3, Phase.L3: 1 / 3}
    assert line_shares(None) == {}


def test_without_a_phase_limit_both_cycles_take_the_cheap_hour() -> None:
    both = {"heater": Phase.L1, "dishwasher": Phase.L1}
    single_phase = problem(
        task("heater", 3), task("dishwasher", 2), phases=both, phase_limit_kwh=None
    )

    assert starts(single_phase) == {"heater": CHEAP_HOUR, "dishwasher": CHEAP_HOUR}
    assert phase_warnings(single_phase) == []


def test_two_appliances_on_the_same_phase_are_kept_apart() -> None:
    both = {"heater": Phase.L1, "dishwasher": Phase.L1}
    found = problem(task("heater", 3), task("dishwasher", 2), phases=both)

    placed = starts(found)

    # 3 + 2 kWh dépasseraient les 4 kVA de la phase : le plus gros garde l'heure bon marché.
    assert placed["heater"] == CHEAP_HOUR and placed["dishwasher"] != CHEAP_HOUR
    assert phase_warnings(found) == []


def test_appliances_on_different_or_unknown_phases_are_not_limited() -> None:
    apart = {"heater": Phase.L1, "dishwasher": Phase.L2}
    unknown = {"heater": Phase.L1}
    for phases in (apart, unknown):
        found = problem(task("heater", 3), task("dishwasher", 2), phases=phases)

        assert starts(found) == {"heater": CHEAP_HOUR, "dishwasher": CHEAP_HOUR}


def test_a_three_phase_appliance_counts_for_a_third_on_each_phase() -> None:
    # 9 kWh en triphasé : 3 kWh par phase ; avec 2 kWh de plus sur la phase 2, elle dépasse.
    phases = {"charger": Phase.ALL, "dishwasher": Phase.L2}
    found = problem(task("charger", 9), task("dishwasher", 2), phases=phases)

    placed = starts(found)

    assert placed["charger"] == CHEAP_HOUR and placed["dishwasher"] != CHEAP_HOUR


def test_an_appliance_too_big_for_its_phase_is_still_placed_and_reported() -> None:
    found = problem(task("heater", 5), phases={"heater": Phase.L3})

    assert starts(found) == {"heater": CHEAP_HOUR}
    assert phase_warnings(found) == [{"phase": "3", "kva": "4", "heures": str(CHEAP_HOUR)}]


def test_cycles_already_decided_count_on_their_phase() -> None:
    fixed = {Phase.L1: {CHEAP_HOUR: 3.0}}
    found = problem(task("dishwasher", 2), phases={"dishwasher": Phase.L1}, fixed_by_phase=fixed)

    assert starts(found)["dishwasher"] != CHEAP_HOUR


def test_the_production_of_the_phase_is_deducted() -> None:
    both = {"heater": Phase.L1, "dishwasher": Phase.L1}
    sunny = {hour: 2.0 if hour == CHEAP_HOUR else 0.0 for hour in range(24)}
    net = {hour: sunny[hour] - 0.3 for hour in range(24)}
    here = problem(
        task("heater", 3),
        task("dishwasher", 2),
        phases=both,
        production_kwh=sunny,
        net_kwh=net,
        production_shares={Phase.L1: 1.0},
    )
    elsewhere = replace(here, production_shares={Phase.L2: 1.0})

    # 2 kWh produits sur la même phase : 3 + 2 - 2 tiennent dans les 4 kVA.
    assert starts(here) == {"heater": CHEAP_HOUR, "dishwasher": CHEAP_HOUR}
    assert starts(elsewhere)["dishwasher"] != CHEAP_HOUR


def test_an_energy_need_is_spread_under_the_limit_of_its_phase() -> None:
    need = NeedModel(name="car", energy_kwh=6.0, start_hour=0, deadline_hour=24, max_kw=7.4)
    found = replace(problem(phases={"car": Phase.L1}), needs=[need])

    result = plan_day(found, explained=False)

    delivered = result.plan.needs["car"]
    assert sum(delivered.values()) == 6.0
    assert max(delivered.values()) <= 4.0 + 1e-6  # jamais plus que la phase en une heure
    assert phase_excess(found, result.plan) == {}


# --- De la maison au problème --------------------------------------------------------------------

HOME = HomeModel(
    supply=Supply.THREE,
    devices=[
        HomeDevice(key="roof", kind=DeviceKind.SOLAR, name="Toit", sensors=[], phase=Phase.L2),
        HomeDevice(key="shed", kind=DeviceKind.SOLAR, name="Abri", sensors=[], phase=Phase.ALL),
        HomeDevice(key="south", kind=DeviceKind.SOLAR, name="Sud", sensors=[]),
        HomeDevice(
            key="washer",
            kind=DeviceKind.WASHING_MACHINE,
            name="Lave-linge",
            sensors=[],
            phase=Phase.L1,
        ),
        HomeDevice(
            key="car", kind=DeviceKind.OTHER_LOAD, name="Voiture", sensors=[], phase=Phase.L3
        ),
        HomeDevice(key="dryer", kind=DeviceKind.DRYER, name="Sèche-linge", sensors=[]),
    ],
)
SETTINGS = Configuration(
    tariff=Tariff(base_eur_kwh=0.2, contract_kva=12.0),
    devices=[
        DeviceSettings(
            key="car",
            behavior=Behavior.ENERGY_BY_DEADLINE,
            energy=EnergyNeed(energy_kwh=6, earliest_hour=0, deadline_hour=7, max_kw=7.4),
        )
    ],
)
INPUT = PlanningInput(
    day=date(2026, 11, 10),
    first_hour=0,
    net_kwh=dict.fromkeys(range(24), -0.3),
    production_kwh=dict.fromkeys(range(24), 0.0),
    battery=Battery(0.0, 0.0, 0.0, charge_max_w=0.0, discharge_max_w=0.0),
    waiting_tasks=(TaskRequest(name="Lave-linge", due=None),),
    runtimes=(),
)


def test_the_home_gives_the_phases_to_the_calculation() -> None:
    data = configured(INPUT, HOME, SETTINGS)

    assert data.three_phase is True
    assert data.phases == {
        "Lave-linge": Phase.L1,
        "Voiture": Phase.L3,
        "Toit": Phase.L2,
        "Abri": Phase.ALL,
    }
    # Trois installations à parts égales : le toit sur la phase 2, l'abri réparti sur les trois,
    # celle dont la phase n'est pas connue sur aucune.
    third = 1 / 3
    assert data.production_shares == {
        Phase.L1: third / 3,
        Phase.L2: third + third / 3,
        Phase.L3: third / 3,
    }
    found = from_input(data)
    assert found.phase_limit_kwh == 4.0
    assert found.phases["Voiture"] is Phase.L3


def test_no_phase_limit_in_a_single_phase_home_or_without_a_contract() -> None:
    single = HOME.model_copy(update={"supply": Supply.SINGLE})
    no_contract = SETTINGS.model_copy(update={"tariff": Tariff(base_eur_kwh=0.2)})

    assert from_input(configured(INPUT, single, SETTINGS)).phase_limit_kwh is None
    assert from_input(configured(INPUT, HOME, no_contract)).phase_limit_kwh is None
