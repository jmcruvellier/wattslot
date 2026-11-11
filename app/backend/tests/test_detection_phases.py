"""Détection des phases d'après les noms de Home Assistant : compteurs par phase d'un compteur
triphasé, phase d'un équipement, maison proposée en triphasé."""

from typing import Any

import pytest

from tests.test_detection import PREFERENCES, STATES, _state
from wattslot.detection import DeviceKind, Phase, Role, Supply, phase_of, propose
from wattslot.home_assistant import HomeSnapshot


@pytest.mark.parametrize(
    ("texts", "expected"),
    [
        (("sensor.meter_phase_a_total_active_energy",), Phase.L1),
        (("sensor.meter_channel_b_energy", "Meter channel B energy"), Phase.L2),
        (("sensor.grid_import_l3_energy",), Phase.L3),
        (("sensor.compteur_energie", "Compteur phase 2"), Phase.L2),
        (("sensor.plug_washer_energy", "Lave-linge", "Prise L1"), Phase.L1),
        # Rien ne nomme une phase : un numéro seul, un mot qui en contient la marque.
        (("sensor.pv_1_total", "PV 1"), None),
        (("sensor.shelly_channel_1_energy",), None),
        (("sensor.hall1_energy", "Hall 1"), None),
        (("sensor.multiphase_energy", "Three-phase meter"), None),
        # Deux phases nommées : on ne tranche pas.
        (("sensor.meter_l1_l2_energy",), None),
        ((None, ""), None),
    ],
)
def test_the_phase_a_name_gives(texts: tuple[str | None, ...], expected: Phase | None) -> None:
    assert phase_of(*texts) is expected


METER = "three-phase-meter"


def _counter(entity_id: str, name: str) -> dict[str, Any]:
    return _state(entity_id, "kWh", "energy", friendly_name=name, state_class="total_increasing")


def _three_phase_snapshot(**change: Any) -> HomeSnapshot:
    """Compteur triphasé : le total est au tableau Énergie, les compteurs par phase non."""
    meter = [
        _counter("sensor.meter_total_active_energy", "Meter total active energy"),
        _counter("sensor.meter_total_active_returned_energy", "Meter total active returned energy"),
        *(
            _counter(
                f"sensor.meter_phase_{letter}_total_active{suffix}_energy", f"Meter phase {letter}"
            )
            for letter in "abc"
            for suffix in ("", "_returned")
        ),
        # Du même appareil, mais ni compteur d'énergie ni capteur d'une phase.
        _state("sensor.meter_phase_a_active_power", "W", "power"),
        _state("sensor.meter_phase_a_voltage", "V", "voltage"),
        _counter("sensor.meter_daily_energy", "Meter daily energy"),
    ]
    others = [
        _counter("sensor.battery_l2_charged", "Battery L2 charged"),
        _counter("sensor.battery_l2_discharged", "Battery L2 discharged"),
        _state("sensor.battery_l2_soc", "%", "battery"),
        _counter("sensor.roof_energy", "Roof energy"),
        _counter("sensor.heater_energy", "Chauffe-eau"),
    ]
    states = {s["entity_id"]: s for s in [*meter, *others]}
    preferences = {
        "energy_sources": [
            {
                "type": "grid",
                "stat_energy_from": "sensor.meter_total_active_energy",
                "stat_energy_to": "sensor.meter_total_active_returned_energy",
            },
            {
                "type": "battery",
                "stat_energy_to": "sensor.battery_l2_charged",
                "stat_energy_from": "sensor.battery_l2_discharged",
                "stat_soc": "sensor.battery_l2_soc",
                "capacity": 5,
            },
            {"type": "solar", "stat_energy_from": "sensor.roof_energy"},
        ],
        "device_consumption": [{"stat_consumption": "sensor.heater_energy", "name": "Chauffe-eau"}],
    }
    entities = {s["entity_id"]: {"entity_id": s["entity_id"], "device_id": METER} for s in meter}
    entities["sensor.roof_energy"] = {"entity_id": "sensor.roof_energy", "device_id": "roof"}
    devices = {
        METER: {"id": METER, "name": "Meter"},
        "roof": {"id": "roof", "name": "Toit phase 3"},
    }
    values: dict[str, Any] = {
        "energy_preferences": preferences,
        "states": states,
        "entities": entities,
        "devices": devices,
    }
    return HomeSnapshot(**(values | change))


def test_phase_meters_of_the_grid_meter_are_proposed() -> None:
    proposal = propose(_three_phase_snapshot())

    grid = next(d for d in proposal.devices if d.kind is DeviceKind.GRID)
    by_phase = {(s.role, s.phase): s.entity_id for s in grid.sensors}
    # Le total du tableau Énergie, puis un compteur de soutirage et un d'injection par phase.
    assert by_phase[Role.ENERGY_IMPORTED, None] == "sensor.meter_total_active_energy"
    assert by_phase[Role.ENERGY_EXPORTED, None] == "sensor.meter_total_active_returned_energy"
    assert by_phase[Role.ENERGY_IMPORTED, Phase.L1] == "sensor.meter_phase_a_total_active_energy"
    assert (
        by_phase[Role.ENERGY_EXPORTED, Phase.L3]
        == "sensor.meter_phase_c_total_active_returned_energy"
    )
    assert len(grid.sensors) == 8
    assert all(not sensor.issues for sensor in grid.sensors)
    assert proposal.supply is Supply.THREE


def test_devices_take_the_phase_their_names_give() -> None:
    by_kind = {d.kind: d for d in propose(_three_phase_snapshot()).devices}

    assert by_kind[DeviceKind.BATTERY].phase is Phase.L2  # nom de ses capteurs
    assert by_kind[DeviceKind.SOLAR].phase is Phase.L3  # nom de son appareil HA
    assert by_kind[DeviceKind.WATER_HEATER].phase is None  # rien ne la nomme
    assert by_kind[DeviceKind.GRID].phase is None


def test_phase_meters_declared_in_the_energy_dashboard_are_recognised() -> None:
    """Trois compteurs par phase déclarés comme sources du réseau : ils font le total à eux
    trois, et chacun garde sa phase."""
    snapshot = _three_phase_snapshot()
    preferences = dict(snapshot.energy_preferences or {})
    preferences["energy_sources"] = [
        {
            "type": "grid",
            "flow_from": [
                {"stat_energy_from": f"sensor.meter_phase_{letter}_total_active_energy"}
                for letter in "abc"
            ],
            "flow_to": [],
        }
    ]

    grid = propose(_three_phase_snapshot(energy_preferences=preferences)).devices[0]

    imports = [s for s in grid.sensors if s.role is Role.ENERGY_IMPORTED]
    assert [s.phase for s in imports] == [Phase.L1, Phase.L2, Phase.L3]
    # Les compteurs d'injection par phase du même appareil s'y ajoutent.
    assert {s.phase for s in grid.sensors if s.role is Role.ENERGY_EXPORTED} == {
        Phase.L1,
        Phase.L2,
        Phase.L3,
    }


def test_a_home_whose_names_say_nothing_stays_as_it_was() -> None:
    snapshot = HomeSnapshot(
        energy_preferences=PREFERENCES, states={s["entity_id"]: s for s in STATES}, entities={}
    )

    proposal = propose(snapshot)

    assert proposal.supply is None
    assert all(device.phase is None for device in proposal.devices)
    assert all(sensor.phase is None for device in proposal.devices for sensor in device.sensors)
