"""Sources d'énergie déclarées dans le tableau Énergie de Home Assistant.

Point de départ de la détection automatique (ce que l'application peut
détecter seule) : l'utilisateur qui a configuré son tableau Énergie n'a
presque rien à mapper. Les deux formats du réseau sont lus : actuel (``stat_energy_from`` /
``stat_energy_to`` sur la source) et ancien (listes ``flow_from`` / ``flow_to``).
"""

from typing import Any

from pydantic import BaseModel


class SolarSource(BaseModel):
    energy: str
    power: str | None = None


class GridSource(BaseModel):
    imports: list[str] = []
    exports: list[str] = []
    # Prix déclarés (lot 3.2) : fixes (€/kWh) ou entité de prix, au soutirage et à la revente.
    import_price: float | None = None
    import_price_entity: str | None = None
    export_price: float | None = None
    export_price_entity: str | None = None


class BatterySource(BaseModel):
    charge_energy: str
    discharge_energy: str
    state_of_charge: str | None = None
    capacity_kwh: float | None = None


class DeviceSource(BaseModel):
    energy: str
    power: str | None = None
    name: str | None = None


class EnergySources(BaseModel):
    configured: bool
    solar: list[SolarSource] = []
    grid: GridSource = GridSource()
    batteries: list[BatterySource] = []
    devices: list[DeviceSource] = []


def _read_prices(grid: GridSource, source: dict[str, Any]) -> None:
    """Prix du réseau : sur la source (format actuel) ou dans ses flux (ancien format) ; le
    premier trouvé l'emporte."""
    imports = [source, *source.get("flow_from", [])]
    exports = [
        {
            "number_energy_price": source.get("number_energy_price_export"),
            "entity_energy_price": source.get("entity_energy_price_export"),
        },
        *source.get("flow_to", []),
    ]
    for flows, number, entity in (
        (imports, "import_price", "import_price_entity"),
        (exports, "export_price", "export_price_entity"),
    ):
        for flow in flows:
            if getattr(grid, number) is None and flow.get("number_energy_price") is not None:
                setattr(grid, number, float(flow["number_energy_price"]))
            if getattr(grid, entity) is None and flow.get("entity_energy_price"):
                setattr(grid, entity, flow["entity_energy_price"])


def energy_sources(preferences: dict[str, Any] | None) -> EnergySources:
    if preferences is None:
        return EnergySources(configured=False)

    sources = EnergySources(configured=True)
    for source in preferences.get("energy_sources", []):
        kind = source.get("type")
        if kind == "solar":
            sources.solar.append(
                SolarSource(energy=source["stat_energy_from"], power=source.get("stat_rate"))
            )
        elif kind == "grid":
            if source.get("stat_energy_from"):
                sources.grid.imports.append(source["stat_energy_from"])
            if source.get("stat_energy_to"):
                sources.grid.exports.append(source["stat_energy_to"])
            sources.grid.imports += [
                flow["stat_energy_from"] for flow in source.get("flow_from", [])
            ]
            sources.grid.exports += [flow["stat_energy_to"] for flow in source.get("flow_to", [])]
            _read_prices(sources.grid, source)
        elif kind == "battery":
            sources.batteries.append(
                BatterySource(
                    charge_energy=source["stat_energy_to"],
                    discharge_energy=source["stat_energy_from"],
                    state_of_charge=source.get("stat_soc"),
                    capacity_kwh=source.get("capacity"),
                )
            )
    sources.devices = [
        DeviceSource(
            energy=device["stat_consumption"],
            power=device.get("stat_rate"),
            name=device.get("name"),
        )
        for device in preferences.get("device_consumption", [])
    ]
    return sources
