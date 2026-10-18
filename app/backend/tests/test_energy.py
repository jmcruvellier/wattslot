from wattslot.energy import energy_sources

PREFERENCES = {
    "energy_sources": [
        {
            "type": "solar",
            "stat_energy_from": "sensor.solar_energy",
            "stat_rate": "sensor.solar_power",
        },
        {
            "type": "grid",
            "stat_energy_from": "sensor.grid_import_energy",
            "stat_energy_to": "sensor.grid_export_energy",
            "cost_adjustment_day": 0.0,
        },
        {
            "type": "battery",
            "stat_energy_from": "sensor.battery_discharge_energy",
            "stat_energy_to": "sensor.battery_charge_energy",
            "stat_soc": "sensor.battery_soc",
            "capacity": 5.12,
        },
        {"type": "gas", "stat_energy_from": "sensor.gas"},
    ],
    "device_consumption": [
        {
            "stat_consumption": "sensor.dryer_energy",
            "stat_rate": "sensor.dryer_power",
            "name": "Dryer",
        },
        {"stat_consumption": "sensor.fridge_energy"},
    ],
}


def test_not_configured() -> None:
    assert energy_sources(None).model_dump() == {
        "configured": False,
        "solar": [],
        "grid": {
            "imports": [],
            "exports": [],
            "import_price": None,
            "import_price_entity": None,
            "export_price": None,
            "export_price_entity": None,
        },
        "batteries": [],
        "devices": [],
    }


def test_reads_every_kind_of_source() -> None:
    sources = energy_sources(PREFERENCES)

    assert sources.configured
    assert [s.energy for s in sources.solar] == ["sensor.solar_energy"]
    assert sources.solar[0].power == "sensor.solar_power"
    assert sources.grid.imports == ["sensor.grid_import_energy"]
    assert sources.grid.exports == ["sensor.grid_export_energy"]
    battery = sources.batteries[0]
    assert battery.charge_energy == "sensor.battery_charge_energy"
    assert battery.discharge_energy == "sensor.battery_discharge_energy"
    assert battery.state_of_charge == "sensor.battery_soc"
    assert battery.capacity_kwh == 5.12
    assert [(d.energy, d.name) for d in sources.devices] == [
        ("sensor.dryer_energy", "Dryer"),
        ("sensor.fridge_energy", None),
    ]


def test_reads_the_legacy_grid_format() -> None:
    preferences = {
        "energy_sources": [
            {
                "type": "grid",
                "flow_from": [{"stat_energy_from": "sensor.hp"}, {"stat_energy_from": "sensor.hc"}],
                "flow_to": [{"stat_energy_to": "sensor.export"}],
                "cost_adjustment_day": 0.0,
            }
        ],
        "device_consumption": [],
    }

    sources = energy_sources(preferences)

    assert sources.grid.imports == ["sensor.hp", "sensor.hc"]
    assert sources.grid.exports == ["sensor.export"]
