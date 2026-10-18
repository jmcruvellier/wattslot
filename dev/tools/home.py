"""Maison simulée du HA de test : entités et tableau Énergie.

Identifiants génériques, sans rien de propre à une maison réelle (décision 2).
Les compteurs d'énergie ont ``state_class: total_increasing`` pour que HA en tire des
statistiques, comme le ferait une vraie intégration.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Sensor:
    entity_id: str
    name: str
    unit: str
    device_class: str
    state_class: str

    def attributes(self) -> dict[str, str]:
        return {
            "friendly_name": self.name,
            "unit_of_measurement": self.unit,
            "device_class": self.device_class,
            "state_class": self.state_class,
        }


def power(entity_id: str, name: str) -> Sensor:
    return Sensor(entity_id, name, "W", "power", "measurement")


def energy(entity_id: str, name: str) -> Sensor:
    return Sensor(entity_id, name, "kWh", "energy", "total_increasing")


SOLAR_POWER = power("sensor.solar_power", "Solar power")
SOLAR_ENERGY = energy("sensor.solar_energy", "Solar energy")
HOME_POWER = power("sensor.home_power", "Home power")
GRID_POWER = power("sensor.grid_power", "Grid power")
GRID_IMPORT = energy("sensor.grid_import_energy", "Grid import energy")
GRID_EXPORT = energy("sensor.grid_export_energy", "Grid export energy")
BATTERY_POWER = power("sensor.battery_power", "Battery power")
BATTERY_SOC = Sensor("sensor.battery_soc", "Battery state of charge", "%", "battery", "measurement")
BATTERY_CHARGE = energy("sensor.battery_charge_energy", "Battery charge energy")
BATTERY_DISCHARGE = energy("sensor.battery_discharge_energy", "Battery discharge energy")


@dataclass(frozen=True)
class Device:
    key: str
    name: str

    @property
    def power(self) -> Sensor:
        return power(f"sensor.{self.key}_power", f"{self.name} power")

    @property
    def energy(self) -> Sensor:
        return energy(f"sensor.{self.key}_energy", f"{self.name} energy")


DEVICES = {
    device.key: device
    for device in (
        Device("water_heater", "Water heater"),
        Device("washing_machine", "Washing machine"),
        Device("dryer", "Dryer"),
        Device("dishwasher", "Dishwasher"),
    )
}

TODO_LIST_NAME = "Agent"
TODO_ENTITY_ID = "todo.agent"  # créée par HA à partir du nom de la liste


def energy_preferences(battery_capacity_kwh: float | None) -> dict[str, object]:
    """Préférences du tableau Énergie (commande WebSocket ``energy/save_prefs``)."""
    sources: list[dict[str, object]] = [
        {
            "type": "solar",
            "stat_energy_from": SOLAR_ENERGY.entity_id,
            "stat_rate": SOLAR_POWER.entity_id,
            "config_entry_solar_forecast": None,
        },
        {
            "type": "grid",
            "stat_energy_from": GRID_IMPORT.entity_id,
            "stat_energy_to": GRID_EXPORT.entity_id,
            "cost_adjustment_day": 0.0,
        },
    ]
    if battery_capacity_kwh is not None:
        sources.append(
            {
                "type": "battery",
                "stat_energy_from": BATTERY_DISCHARGE.entity_id,
                "stat_energy_to": BATTERY_CHARGE.entity_id,
                "stat_soc": BATTERY_SOC.entity_id,
                "capacity": battery_capacity_kwh,
            }
        )
    devices = [
        {
            "stat_consumption": device.energy.entity_id,
            "stat_rate": device.power.entity_id,
            "name": device.name,
        }
        for device in DEVICES.values()
    ]
    return {"energy_sources": sources, "device_consumption": devices}
