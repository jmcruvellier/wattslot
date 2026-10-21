"""Propositions de rôles sur une maison fictive qui reproduit les situations rencontrées sur une
vraie installation le 15/10/2026 : coût déclaré comme
compteur, compteur quotidien, batterie sans capacité, appareils sans puissance."""

from typing import Any

import pytest

from wattslot.detection import (
    DeviceKind,
    DeviceProposal,
    Issue,
    Role,
    classify_appliance,
    propose,
)
from wattslot.home_assistant import HomeSnapshot


def _state(entity_id: str, unit: str | None, device_class: str | None, **extra: Any) -> dict:  # type: ignore[type-arg]
    attributes = {"unit_of_measurement": unit, "device_class": device_class} | extra
    return {"entity_id": entity_id, "state": "1", "attributes": attributes}


STATES = [
    _state("sensor.pv_1_total", "kWh", "energy", friendly_name="PV 1"),
    _state("sensor.pv_1_power", "W", "power"),
    _state("sensor.shed_daily_energy", "kWh", "energy", state_class="total", last_reset="x"),
    _state("sensor.shed_power", "W", "power"),
    _state("sensor.grid_offpeak", "kWh", "energy"),
    _state("sensor.grid_peak", "kWh", "energy"),
    _state("sensor.subscription_cost", "EUR", "monetary"),
    _state("sensor.grid_export", "kWh", "energy"),
    _state("sensor.battery_in", "kWh", "energy"),
    _state("sensor.battery_out", "kWh", "energy"),
    _state("sensor.battery_soc", "%", "battery"),
    _state("sensor.plug_washer_energy", "kWh", "energy"),
    _state("sensor.plug_washer_power", "W", "power"),
    _state("sensor.plug_dryer_energy", "kWh", "energy"),
    _state("sensor.plug_dishwasher_energy", "kWh", "energy"),
    _state("sensor.heater_energy", "kWh", "energy"),
    _state("sensor.pool_energy", "kWh", "energy"),
    _state("sensor.tv_energy", "kWh", "energy"),
]

ENTITIES = {
    "sensor.shed_daily_energy": {"entity_id": "sensor.shed_daily_energy", "device_id": "shed"},
    "sensor.shed_power": {"entity_id": "sensor.shed_power", "device_id": "shed"},
    "sensor.plug_washer_energy": {"entity_id": "sensor.plug_washer_energy", "device_id": "wm"},
    "sensor.plug_washer_power": {"entity_id": "sensor.plug_washer_power", "device_id": "wm"},
}

PREFERENCES = {
    "energy_sources": [
        {
            "type": "solar",
            "stat_energy_from": "sensor.pv_1_total",
            "stat_rate": "sensor.pv_1_power",
        },
        {"type": "solar", "stat_energy_from": "sensor.shed_daily_energy"},
        {
            "type": "grid",
            "flow_from": [
                {"stat_energy_from": "sensor.subscription_cost"},
                {"stat_energy_from": "sensor.grid_offpeak"},
                {"stat_energy_from": "sensor.grid_peak"},
            ],
            "flow_to": [{"stat_energy_to": "sensor.grid_export"}],
            "cost_adjustment_day": 0,
        },
        {
            "type": "battery",
            "stat_energy_to": "sensor.battery_in",
            "stat_energy_from": "sensor.battery_out",
            "stat_soc": "sensor.battery_soc",
        },
    ],
    "device_consumption": [
        {"stat_consumption": "sensor.plug_washer_energy", "name": "Lave Linge"},
        {"stat_consumption": "sensor.plug_dryer_energy", "name": "Sèche Linge"},
        {"stat_consumption": "sensor.plug_dishwasher_energy", "name": "Lave Vaisselle"},
        {"stat_consumption": "sensor.heater_energy", "name": "Chauffe-Eau"},
        {"stat_consumption": "sensor.pool_energy", "name": "Filtration Piscine"},
        {"stat_consumption": "sensor.tv_energy", "name": "Salon TV"},
    ],
}


def _proposal() -> dict[str, DeviceProposal]:
    snapshot = HomeSnapshot(
        energy_preferences=PREFERENCES,
        states={s["entity_id"]: s for s in STATES},
        entities=ENTITIES,
    )
    return {d.key: d for d in propose(snapshot).devices}


def _codes(issues: list[Issue]) -> list[str]:
    return [issue.code for issue in issues]


def test_without_energy_dashboard() -> None:
    proposal = propose(HomeSnapshot())

    assert not proposal.energy_dashboard
    assert proposal.devices == []


def test_solar_power_comes_from_the_dashboard_or_the_same_device() -> None:
    devices = _proposal()

    pv = devices["solar-sensor-pv-1-total"]
    assert [(s.entity_id, s.role) for s in pv.sensors] == [
        ("sensor.pv_1_total", Role.ENERGY_PRODUCED),
        ("sensor.pv_1_power", Role.POWER_PRODUCED),
    ]
    shed = devices["solar-sensor-shed-daily-energy"]
    assert [s.entity_id for s in shed.sensors] == ["sensor.shed_daily_energy", "sensor.shed_power"]
    assert shed.sensors[0].resets_daily


def test_a_power_setting_of_the_same_device_is_not_a_measure() -> None:
    # Essai du 21/10/2026 : la limite de puissance d'un micro-onduleur (``number.``, en W) était
    # prise pour la puissance produite.
    states = {s["entity_id"]: s for s in STATES}
    states["number.shed_limit"] = _state("number.shed_limit", "W", None)
    entities = {
        "number.shed_limit": {"entity_id": "number.shed_limit", "device_id": "shed"},
        **{k: v for k, v in ENTITIES.items() if k != "sensor.shed_power"},
    }
    snapshot = HomeSnapshot(energy_preferences=PREFERENCES, states=states, entities=entities)

    shed = next(d for d in propose(snapshot).devices if d.key == "solar-sensor-shed-daily-energy")
    assert [s.entity_id for s in shed.sensors] == ["sensor.shed_daily_energy"]
    assert _codes(shed.issues) == ["no_power_sensor"]


@pytest.mark.parametrize(
    ("language", "grid", "battery"),
    [
        ("fr", "Réseau", "Batterie"),
        ("en", "Grid", "Battery"),
        ("de-DE", "Netz", "Batterie"),
        (None, "Grid", "Battery"),
    ],
)
def test_grid_and_unnamed_battery_are_named_in_the_language_of_ha(
    language: str | None, grid: str, battery: str
) -> None:
    snapshot = HomeSnapshot(
        energy_preferences=PREFERENCES,
        states={s["entity_id"]: s for s in STATES},
        entities=ENTITIES,
        config={"language": language} if language else {},
    )
    devices = {d.kind: d for d in propose(snapshot).devices}

    assert devices[DeviceKind.GRID].name == grid
    assert devices[DeviceKind.BATTERY].name == battery


def test_a_cost_declared_as_a_grid_meter_is_flagged() -> None:
    grid = _proposal()["grid"]

    imports = {s.entity_id: s for s in grid.sensors if s.role is Role.ENERGY_IMPORTED}
    assert set(imports) == {"sensor.subscription_cost", "sensor.grid_offpeak", "sensor.grid_peak"}
    cost = imports["sensor.subscription_cost"]
    assert _codes(cost.issues) == ["not_energy_unit", "name_suggests_cost"]
    assert cost.excluded
    assert _codes(imports["sensor.grid_peak"].issues) == []
    assert not imports["sensor.grid_peak"].excluded
    assert [s.entity_id for s in grid.sensors if s.role is Role.ENERGY_EXPORTED] == [
        "sensor.grid_export"
    ]


def test_an_artificial_cost_meter_in_energy_units_is_proposed_excluded() -> None:
    # Cas réel : compteur artificiel en Wh, créé pour faire apparaître l'abonnement dans le
    # tableau Énergie ; son unité seule ne le trahit pas, son nom si.
    snapshot = HomeSnapshot(
        energy_preferences={
            "energy_sources": [
                {
                    "type": "grid",
                    "stat_energy_from": "sensor.cout_abonnement_fournisseur",
                    "cost_adjustment_day": 0,
                }
            ],
            "device_consumption": [],
        },
        states={
            "sensor.cout_abonnement_fournisseur": _state(
                "sensor.cout_abonnement_fournisseur", "Wh", "energy"
            )
        },
    )

    sensor = propose(snapshot).devices[0].sensors[0]

    assert sensor.excluded
    assert _codes(sensor.issues) == ["name_suggests_cost"]


@pytest.mark.parametrize(
    "entity_id", ["sensor.linky_consommation_hp", "sensor.prise_courant_cuisine_energy"]
)
def test_ordinary_meters_are_not_mistaken_for_costs(entity_id: str) -> None:
    snapshot = HomeSnapshot(
        energy_preferences={
            "energy_sources": [
                {"type": "grid", "stat_energy_from": entity_id, "cost_adjustment_day": 0}
            ],
            "device_consumption": [],
        },
        states={entity_id: _state(entity_id, "kWh", "energy")},
    )

    sensor = propose(snapshot).devices[0].sensors[0]

    assert not sensor.excluded
    assert sensor.issues == []


def test_battery_without_capacity_is_flagged() -> None:
    battery = next(d for d in _proposal().values() if d.kind is DeviceKind.BATTERY)

    assert _codes(battery.issues) == ["battery_capacity_missing"]
    assert {s.role for s in battery.sensors} == {
        Role.ENERGY_CHARGED,
        Role.ENERGY_DISCHARGED,
        Role.STATE_OF_CHARGE,
    }


def _battery_snapshot(capacity_state: dict[str, Any]) -> HomeSnapshot:
    """Batterie sans capacité dans le tableau Énergie, une entité candidate sur son appareil."""
    states = [
        _state("sensor.bat_in", "kWh", "energy"),
        _state("sensor.bat_out", "kWh", "energy"),
        _state("sensor.bat_soc", "%", "battery"),
        capacity_state,
    ]
    return HomeSnapshot(
        energy_preferences={
            "energy_sources": [
                {
                    "type": "battery",
                    "stat_energy_to": "sensor.bat_in",
                    "stat_energy_from": "sensor.bat_out",
                    "stat_soc": "sensor.bat_soc",
                }
            ],
            "device_consumption": [],
        },
        states={s["entity_id"]: s for s in states},
        entities={
            s["entity_id"]: {"entity_id": s["entity_id"], "device_id": "bat"} for s in states
        },
    )


def test_battery_capacity_is_read_on_the_battery_device() -> None:
    # Comme une Marstek Venus : capacité en « state_class: total », sans last_reset.
    capacity = _state("sensor.bat_total_energy", "kWh", "energy", state_class="total")
    capacity["state"] = "5.12"

    battery = propose(_battery_snapshot(capacity)).devices[0]

    assert battery.capacity_kwh == 5.12
    assert battery.capacity_source == "sensor.bat_total_energy"
    assert battery.issues == []


def test_battery_capacity_in_wh_is_converted() -> None:
    capacity = _state("sensor.bat_capacity", "Wh", "energy")
    capacity["state"] = "5120"

    assert propose(_battery_snapshot(capacity)).devices[0].capacity_kwh == 5.12


def test_a_battery_energy_counter_is_not_taken_for_its_capacity() -> None:
    counter = _state("sensor.bat_total_energy", "kWh", "energy", state_class="total_increasing")
    counter["state"] = "812.4"

    battery = propose(_battery_snapshot(counter)).devices[0]

    assert battery.capacity_kwh is None
    assert _codes(battery.issues) == ["battery_capacity_missing"]


def test_appliances_are_classified_and_missing_power_is_flagged() -> None:
    by_kind = {d.kind: d for d in _proposal().values()}

    washer = by_kind[DeviceKind.WASHING_MACHINE]
    assert [s.entity_id for s in washer.sensors] == [
        "sensor.plug_washer_energy",
        "sensor.plug_washer_power",
    ]
    assert washer.issues == []
    assert _codes(by_kind[DeviceKind.DRYER].issues) == ["no_power_sensor"]
    assert DeviceKind.DISHWASHER in by_kind
    assert DeviceKind.WATER_HEATER in by_kind
    assert DeviceKind.POOL_PUMP in by_kind
    other = by_kind[DeviceKind.OTHER_LOAD]
    assert other.name == "Salon TV"
    assert other.issues == []  # Pas de puissance attendue pour une consommation non pilotable.


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("Lave-linge séchant", DeviceKind.WASHING_MACHINE),
        ("Washing machine", DeviceKind.WASHING_MACHINE),
        ("Sèche-linge", DeviceKind.DRYER),
        ("Ballon d'eau chaude", DeviceKind.WATER_HEATER),
        ("Pool pump", DeviceKind.POOL_PUMP),
        ("Congélateur", DeviceKind.OTHER_LOAD),
    ],
)
def test_classify_appliance(name: str, kind: DeviceKind) -> None:
    assert classify_appliance(name) is kind
