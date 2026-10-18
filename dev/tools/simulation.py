"""Physique de la maison simulée, sans entrée-sortie (testée par dev/tools/tests).

Une journée (fichier JSON de dev/donnees/) donne, heure par heure, la production solaire et la
consommation de base, plus les cycles des équipements (démarrage, énergie, forme au quart
d'heure). ``House.step`` avance le temps : la batterie, en autoconsommation, charge le surplus
et couvre le déficit ; le réseau fournit ou reçoit le reste ; les compteurs intègrent l'énergie.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

QUARTER_S = 900
HOUR_S = 3600
DAY_S = 24 * HOUR_S


@dataclass(frozen=True)
class Cycle:
    device: str
    start_s: int
    energy_kwh: float
    shape: tuple[float, ...]  # part de l'énergie par quart d'heure depuis le démarrage

    def power_w(self, t_s: float) -> float:
        quarter = int((t_s - self.start_s) // QUARTER_S)
        if t_s < self.start_s or quarter >= len(self.shape):
            return 0.0
        total = sum(self.shape)
        return self.energy_kwh * self.shape[quarter] / total * 1000 * HOUR_S / QUARTER_S


@dataclass(frozen=True)
class Battery:
    capacity_kwh: float
    initial_soc_pct: float
    min_soc_pct: float
    max_charge_w: float
    max_discharge_w: float
    efficiency: float  # par sens


@dataclass(frozen=True)
class Day:
    name: str
    solar_kwh: tuple[float, ...]  # 24 valeurs
    base_load_kwh: tuple[float, ...]  # 24 valeurs
    cycles: tuple[Cycle, ...]
    battery: Battery | None

    @classmethod
    def load(cls, path: Path) -> "Day":
        data = json.loads(path.read_text(encoding="utf-8"))
        battery = data.get("battery")
        return cls(
            name=data["name"],
            solar_kwh=tuple(data["hourly"]["solar_kwh"]),
            base_load_kwh=tuple(data["hourly"]["base_load_kwh"]),
            cycles=tuple(
                Cycle(
                    device=c["device"],
                    start_s=_seconds(c["start"]),
                    energy_kwh=c["energy_kwh"],
                    shape=tuple(c["shape_per_quarter"]),
                )
                for c in data["cycles"]
            ),
            battery=Battery(**battery) if battery else None,
        )


def _seconds(hh_mm: str) -> int:
    hours, minutes = hh_mm.split(":")
    return int(hours) * HOUR_S + int(minutes) * 60


def hourly_power_w(values_kwh: tuple[float, ...], t_s: float) -> float:
    """Puissance moyenne de l'heure en cours (kWh par heure → W)."""
    return values_kwh[int(t_s % DAY_S) // HOUR_S] * 1000


@dataclass
class House:
    day: Day
    solar_energy_kwh: float = 0.0
    grid_import_kwh: float = 0.0
    grid_export_kwh: float = 0.0
    battery_charge_kwh: float = 0.0
    battery_discharge_kwh: float = 0.0
    device_energy_kwh: dict[str, float] = field(default_factory=dict)
    stored_kwh: float = 0.0
    readings: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.day.battery:
            self.stored_kwh = self.day.battery.capacity_kwh * self.day.battery.initial_soc_pct / 100

    def step(self, t_s: float, dt_s: float) -> dict[str, float]:
        """Avance de ``dt_s`` secondes à partir de ``t_s`` (secondes depuis minuit)."""
        hours = dt_s / HOUR_S
        solar_w = hourly_power_w(self.day.solar_kwh, t_s)
        devices_w = {cycle.device: 0.0 for cycle in self.day.cycles}
        for cycle in self.day.cycles:
            devices_w[cycle.device] += cycle.power_w(t_s)
        home_w = hourly_power_w(self.day.base_load_kwh, t_s) + sum(devices_w.values())

        battery_w = 0.0  # > 0 : décharge, < 0 : charge
        battery = self.day.battery
        if battery:
            surplus_w = solar_w - home_w
            if surplus_w > 0:
                room_kwh = battery.capacity_kwh - self.stored_kwh
                charge_w = min(
                    surplus_w, battery.max_charge_w, room_kwh / battery.efficiency / hours
                )
                self.stored_kwh += charge_w * hours / 1000 * battery.efficiency
                self.battery_charge_kwh += charge_w * hours / 1000
                battery_w = -charge_w
            else:
                usable_kwh = self.stored_kwh - battery.capacity_kwh * battery.min_soc_pct / 100
                discharge_w = min(
                    -surplus_w,
                    battery.max_discharge_w,
                    max(usable_kwh, 0) * battery.efficiency / hours,
                )
                self.stored_kwh -= discharge_w * hours / 1000 / battery.efficiency
                self.battery_discharge_kwh += discharge_w * hours / 1000
                battery_w = discharge_w

        grid_w = home_w - solar_w - battery_w  # > 0 : soutirage, < 0 : injection
        self.solar_energy_kwh += solar_w * hours / 1000
        if grid_w > 0:
            self.grid_import_kwh += grid_w * hours / 1000
        else:
            self.grid_export_kwh += -grid_w * hours / 1000
        for device, w in devices_w.items():
            self.device_energy_kwh[device] = (
                self.device_energy_kwh.get(device, 0.0) + w * hours / 1000
            )

        self.readings = {
            "solar_w": solar_w,
            "home_w": home_w,
            "grid_w": grid_w,
            "battery_w": battery_w,
            **{f"{device}_w": w for device, w in devices_w.items()},
        }
        return self.readings

    @property
    def soc_pct(self) -> float | None:
        if not self.day.battery:
            return None
        return self.stored_kwh / self.day.battery.capacity_kwh * 100
