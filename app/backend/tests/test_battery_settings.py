"""Batterie générique (lot 3.3) : réglages, enregistrement, effet sur le calcul, maison sans."""

from dataclasses import replace
from pathlib import Path

import pytest

from tests.planning.test_assemble import MODEL
from tests.planning.test_configured_run import plans
from tests.v1_oracle import STATES, load
from wattslot import configuration
from wattslot.battery_settings import (
    DEFAULT,
    BatterySettings,
    FloorRange,
    combine,
    problems,
    share_of,
)
from wattslot.configuration import Behavior, Configuration, DeviceSettings
from wattslot.detection import DeviceKind
from wattslot.home_model import HomeDevice, HomeModel
from wattslot.planning.assemble import configured
from wattslot.planning.inputs import RecentHistory, from_v1
from wattslot.planning.problem import from_input
from wattslot.storage.graph import GraphStore

CUSTOM = BatterySettings(
    charge_max_w=3000,
    discharge_max_w=1500,
    floor_percent=20,
    active_from_hour=8,
    active_to_hour=22,
    full_charge_every_days=None,
)


def test_powers_default_to_half_the_capacity_per_hour() -> None:
    assert DEFAULT.powers_w(5.12) == (2560.0, 2560.0)
    assert DEFAULT.powers_w(0.0) == (0.0, 0.0)
    assert CUSTOM.powers_w(5.12) == (3000, 1500)
    assert BatterySettings(charge_max_w=1000).powers_w(4.0) == (1000, 2000.0)


def test_problems() -> None:
    assert problems(DEFAULT) == [] and problems(CUSTOM) == []
    empty = BatterySettings(active_from_hour=10, active_to_hour=10)
    assert problems(empty) == [("battery_active_range_empty", {})]


def test_saved_and_read_back(tmp_path: Path) -> None:
    graph = GraphStore(tmp_path)
    for settings in (DEFAULT, CUSTOM):
        configuration.save(graph, Configuration(battery=settings))
        assert configuration.load(graph).battery == settings
    configuration.save(graph, Configuration())
    assert configuration.battery_of(configuration.load(graph)) == DEFAULT


def test_the_problem_follows_the_battery_settings() -> None:
    state, _ = load(STATES[0])
    data = from_v1(state)
    # Sans les plannings de la batterie Marstek (entrée de la v1) : la plage active réglée.
    data = replace(data, battery=replace(data.battery, schedules=()))
    capacity = data.battery.capacity_kwh

    battery = from_input(configured(data, MODEL, Configuration(battery=CUSTOM))).battery

    assert (battery.charge_max_kw, battery.discharge_max_kw) == (3.0, 1.5)
    assert battery.floor_kwh == pytest.approx(capacity * 0.20)
    assert (battery.active_from, battery.active_to) == (8, 22)
    assert battery.full_priority is False  # pas de charge complète périodique

    weekly = CUSTOM.model_copy(update={"full_charge_every_days": 1})
    # Aucune charge complète sur 30 jours d'historique : la journée la vise en priorité.
    with_history = replace(data, history=RecentHistory(last_full_charge=None, days=30))
    due = from_input(configured(with_history, MODEL, Configuration(battery=weekly))).battery
    assert due.full_priority is True


def test_a_home_without_battery(tmp_path: Path) -> None:
    without = HomeModel(devices=[d for d in MODEL.devices if d.kind is not DeviceKind.BATTERY])

    found = plans(tmp_path, without, Configuration())

    for plan in found:
        assert plan.battery is not None and plan.battery.movements == []
        assert plan.battery.start_kwh == 0 and plan.battery.end_kwh == 0


# --- Réglages par batterie ---------------------------------------------------------------------

EVENING = BatterySettings(
    charge_max_w=800,
    discharge_max_w=800,
    floor_percent=30,
    active_from_hour=6,
    active_to_hour=20,
    full_charge_every_days=14,
    floor_ranges=[FloorRange(start_hour=18, end_hour=22, percent=50)],
    all_phases=True,
)
TWO = HomeModel(
    devices=[
        HomeDevice(
            key="small", kind=DeviceKind.BATTERY, name="Petite", sensors=[], capacity_kwh=2.0
        ),
        HomeDevice(
            key="large", kind=DeviceKind.BATTERY, name="Grande", sensors=[], capacity_kwh=6.0
        ),
    ]
)


def storage(key: str, battery: BatterySettings | None = None) -> DeviceSettings:
    return DeviceSettings(key=key, behavior=Behavior.STORAGE, battery=battery)


def test_identical_settings_combine_to_themselves() -> None:
    assert combine([(2.0, CUSTOM), (6.0, CUSTOM)]) == CUSTOM
    assert combine([(5.12, DEFAULT)]) == DEFAULT
    assert combine([]) == DEFAULT


def test_combined_powers_add_up_and_floors_follow_the_capacities() -> None:
    combined = combine([(2.0, EVENING), (6.0, DEFAULT)])

    # 800 W réglés pour la petite, 0,5 C (3 kW) pour la grande.
    assert (combined.charge_max_w, combined.discharge_max_w) == (3800, 3800)
    # Plancher en énergie : 30 % de 2 kWh + 10 % de 6 kWh = 1,2 kWh, soit 15 % de 8 kWh.
    assert combined.floor_percent == pytest.approx(15)
    # De 18 h à 22 h, la petite garde 50 % : 1 kWh + 0,6 kWh = 1,6 kWh, soit 20 %.
    assert [(r.start_hour, r.end_hour) for r in combined.floor_ranges] == [(18, 22)]
    assert combined.floor_ranges[0].percent == pytest.approx(20)
    # Plage où une batterie au moins fonctionne ; charge complète la plus fréquente.
    assert (combined.active_from_hour, combined.active_to_hour) == (0, 24)
    assert combined.full_charge_every_days == 7


def test_own_settings_are_saved_and_read_back_per_battery(tmp_path: Path) -> None:
    graph = GraphStore(tmp_path)
    ranges = BatterySettings(floor_ranges=[FloorRange(start_hour=0, end_hour=6, percent=25)])
    saved = Configuration(
        battery=ranges, devices=[storage("large", CUSTOM), storage("small", EVENING)]
    )

    configuration.save(graph, saved)

    assert configuration.load(graph) == saved


def test_the_calculation_sees_the_batteries_combined() -> None:
    house = Configuration(battery=CUSTOM)
    own = Configuration(battery=CUSTOM, devices=[storage("small", EVENING), storage("large")])

    assert configuration.battery_of(house, TWO) == CUSTOM
    assert configuration.battery_of(own) == CUSTOM  # sans la maison : ses réglages
    assert configuration.battery_of(own, TWO) == combine(
        [(2.0, EVENING), (6.0, share_of(CUSTOM, 0.75))]
    )
    # Une batterie sans capacité ne compte pas, comme au calcul.
    unknown = TWO.model_copy(
        update={
            "devices": [TWO.devices[0].model_copy(update={"capacity_kwh": None}), TWO.devices[1]]
        }
    )
    assert configuration.battery_of(own, unknown) == CUSTOM


def test_own_settings_are_checked_like_the_home_ones() -> None:
    empty = BatterySettings(active_from_hour=10, active_to_hour=10)
    washer = HomeDevice(
        key="washer", kind=DeviceKind.WASHING_MACHINE, name="Lave-linge", sensors=[]
    )
    home = HomeModel(devices=[*TWO.devices, washer])
    saved = Configuration(
        devices=[
            storage("small", empty),
            DeviceSettings(key="washer", behavior=Behavior.CYCLE, battery=CUSTOM),
        ]
    )

    found = {(i.code, i.device) for i in configuration.validate(home, saved)}

    assert found == {("battery_active_range_empty", "small"), ("battery_not_used", "washer")}


def test_the_problem_follows_the_combined_settings() -> None:
    state, _ = load(STATES[0])
    data = from_v1(state)
    data = replace(data, battery=replace(data.battery, schedules=()))
    battery = next(d for d in MODEL.devices if d.kind is DeviceKind.BATTERY)
    saved = Configuration(devices=[storage(battery.key, CUSTOM)])

    found = from_input(configured(data, MODEL, saved)).battery

    assert (found.charge_max_kw, found.discharge_max_kw) == (3.0, 1.5)
    assert (found.active_from, found.active_to) == (8, 22)


def test_a_battery_without_own_settings_takes_its_share_of_the_home_powers() -> None:
    """Les puissances de la maison valent pour toutes les batteries ensemble (défaut trouvé avec
    la maison de test en triphasé : chaque groupe recevait la puissance entière)."""
    house = Configuration(battery=CUSTOM)  # 3 kW de charge, 1,5 kW de décharge
    own = Configuration(battery=CUSTOM, devices=[storage("small", EVENING), storage("large")])

    # Sans réglages propres : exactement ceux de la maison.
    assert configuration.battery_of(house, TWO) == CUSTOM
    # La grande batterie (6 kWh sur 8) prend les trois quarts des puissances de la maison.
    combined = configuration.battery_of(own, TWO)
    assert combined.charge_max_w == pytest.approx(800 + 3000 * 0.75)
    assert combined.discharge_max_w == pytest.approx(800 + 1500 * 0.75)
