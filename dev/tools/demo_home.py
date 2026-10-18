"""Maison de démonstration des captures (lot 7.2) : entièrement synthétique, déterministe.

Aucune donnée réelle : ni états capturés de la v1, ni journées de ``dev/donnees`` (tirées d'une
capture de la maison de référence). Une maison type du nord de la France, début juin :

- toit solaire de 4,5 kWc plein sud, courbe en cloche (lever 5 h 50, coucher 21 h 50) ;
- consommation de base d'une famille (nuit 230 W, pics du matin, du midi et du soir) ;
- batterie de 5 kWh en autoconsommation (surplus chargé, déficit couvert jusqu'à 10 %) ;
- chauffe-eau, lave-linge, sèche-linge et lave-vaisselle, programmes en paliers de puissance.

``House`` avance minute par minute et rend les valeurs des capteurs, comme une intégration de HA ;
la météo et l'historique des appareils sont tirés d'un générateur à graine fixe.
"""

import math
import random
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("Europe/Paris")
DAY = date(2026, 6, 10)  # mercredi : la journée des captures
NOW = datetime.combine(DAY, time(14, 30), ZONE)  # heure figée des captures
HISTORY_DAYS = 31  # historique simulé avant le jour J (profils de cycle sur 30 jours)
FORECAST_DAYS = 9  # prévision solaire au-delà du jour J (horizon de 7 jours après demain)
SEED = 2026

# --- Capteurs (entités génériques, comme les profils de ``wattslot/profiles``) -------------

SOLAR_POWER = "sensor.solar_power"
SOLAR_ENERGY = "sensor.solar_energy"
GRID_IMPORT = "sensor.grid_import_energy"
GRID_EXPORT = "sensor.grid_export_energy"
BATTERY_CHARGE = "sensor.battery_charge_energy"
BATTERY_DISCHARGE = "sensor.battery_discharge_energy"
BATTERY_LEVEL = "sensor.battery_level"
BATTERY_CAPACITY = "sensor.battery_capacity"

WATER_HEATER = "water_heater"
WASHING_MACHINE = "washing_machine"
DRYER = "dryer"
DISHWASHER = "dishwasher"
APPLIANCES = (WATER_HEATER, WASHING_MACHINE, DRYER, DISHWASHER)


def power_entity(appliance: str) -> str:
    return f"sensor.{appliance}_power"


def energy_entity(appliance: str) -> str:
    return f"sensor.{appliance}_energy"


# Noms des appareils de HA (registre), dans la langue des captures.
NAMES: dict[str, dict[str, str]] = {
    "en": {
        "solar": "Solar panels",
        "grid": "Grid",
        "battery": "Home battery",
        WATER_HEATER: "Water heater",
        WASHING_MACHINE: "Washing machine",
        DRYER: "Dryer",
        DISHWASHER: "Dishwasher",
    },
    "fr": {
        "solar": "Panneaux solaires",
        "grid": "Réseau",
        "battery": "Batterie maison",
        WATER_HEATER: "Chauffe-eau",
        WASHING_MACHINE: "Lave-linge",
        DRYER: "Sèche-linge",
        DISHWASHER: "Lave-vaisselle",
    },
}

# --- Physique ----------------------------------------------------------------------------

PEAK_W = 3500.0  # crête d'une belle journée de juin pour 4,5 kWc (pertes comprises)
SUNRISE_H = 5.83
SUNSET_H = 21.87
SHAPE_EXPONENT = 2.4  # environ 26 kWh par ciel clair
CAPACITY_KWH = 5.0
BATTERY_MAX_W = 2500.0
FLOOR_PERCENT = 10.0
EFFICIENCY = 0.95  # par sens : 90 % aller-retour
START_SOC = 45.0
STANDBY_W = (0.4, 0.7, 1.1)

# Consommation de base par heure (W), hors appareils suivis : environ 13 kWh par jour, dont une
# soirée (cuisine, four, télévision) que la batterie ne couvre pas tout à fait.
BASE_W = (
    230, 225, 220, 220, 225, 240, 330, 620, 520, 360, 330, 380,
    690, 520, 360, 330, 380, 560, 950, 1550, 1450, 1150, 850, 520,
)  # fmt: skip

# Programmes en paliers (minutes, W) : énergie et durée d'appareils courants.
PROGRAMS: dict[str, tuple[tuple[int, float], ...]] = {
    # Ballon de 200 L réchauffé : résistance de 2,2 kW, thermostat qui coupe à la fin.
    WATER_HEATER: ((95, 2200.0), (10, 1400.0), (8, 600.0)),
    # Coton 40 °C : chauffe de l'eau, lavage, rinçages, essorage.
    WASHING_MACHINE: ((16, 2050.0), (38, 210.0), (24, 160.0), (12, 480.0), (4, 60.0)),
    # Sèche-linge à condensation : chauffe, puis refroidissement.
    DRYER: ((70, 1950.0), (12, 900.0), (8, 180.0)),
    # Programme éco : chauffe du lavage, lavage, chauffe du rinçage, séchage.
    DISHWASHER: ((18, 1900.0), (50, 95.0), (14, 1850.0), (40, 25.0)),
}


def program_minutes(appliance: str) -> int:
    return sum(minutes for minutes, _ in PROGRAMS[appliance])


def program_kwh(appliance: str) -> float:
    return sum(minutes * watts for minutes, watts in PROGRAMS[appliance]) / 60_000


def _rng(*key: object) -> random.Random:
    return random.Random(f"{SEED}:{':'.join(map(str, key))}")


# --- Météo ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Weather:
    forecast: float  # part du ciel clair annoncée par la prévision
    actual: float  # part du ciel clair réellement produite
    clouds: tuple[tuple[float, float, float], ...] = ()  # (début h, fin h, facteur) passages


# Jour J et suivants : un jour J ensoleillé (un passage nuageux en fin de matinée), une semaine
# variée pour la vue Semaine.
WEATHER_AHEAD: dict[int, Weather] = {
    0: Weather(0.97, 0.95, ((10.3, 11.1, 0.55),)),
    1: Weather(0.92, 0.92),
    2: Weather(0.58, 0.58),
    3: Weather(0.34, 0.34),
    4: Weather(0.71, 0.71),
    5: Weather(0.96, 0.96),
    6: Weather(0.9, 0.9),
    7: Weather(0.84, 0.84),
    8: Weather(0.93, 0.93),
    9: Weather(0.9, 0.9),
}


def weather(day: date) -> Weather:
    offset = (day - DAY).days
    if offset >= 0:
        return WEATHER_AHEAD.get(offset, Weather(0.9, 0.9))
    rng = _rng("weather", day)
    sky = rng.choice((1.0, 0.97, 0.94, 0.9, 0.86, 0.8, 0.72, 0.6, 0.45))
    clouds = tuple(
        (start, start + rng.uniform(0.3, 1.2), rng.uniform(0.35, 0.7))
        for start in sorted(rng.uniform(8, 18) for _ in range(rng.randint(0, 3)))
    )
    return Weather(round(min(1.0, sky * rng.uniform(0.95, 1.08)), 3), sky, clouds)


def clear_sky_w(hour: float) -> float:
    if not SUNRISE_H < hour < SUNSET_H:
        return 0.0
    angle = math.pi * (hour - SUNRISE_H) / (SUNSET_H - SUNRISE_H)
    return PEAK_W * math.sin(angle) ** SHAPE_EXPONENT


def solar_w(day: date, minute: int) -> float:
    """Production réelle (W) à la minute ``minute`` de la journée."""
    hour = minute / 60
    sky = weather(day)
    factor = sky.actual
    for start, end, dip in sky.clouds:
        if start <= hour < end:
            factor *= dip
    # Petites variations lentes (voile, température des panneaux).
    factor *= 1 + 0.025 * math.sin(minute / 23) * math.sin(minute / 71 + day.toordinal())
    return round(clear_sky_w(hour) * factor, 1)


def forecast_wh(day: date) -> dict[int, float]:
    """Prévision horaire (Wh), comme le tableau Énergie de HA (début de chaque heure)."""
    sky = weather(day)
    found: dict[int, float] = {}
    for hour in range(24):
        wh = sum(clear_sky_w(hour + m / 60) for m in range(0, 60, 5)) / 12 * sky.forecast
        if wh > 0:
            found[hour] = round(wh)
    return found


def base_w(day: date, minute: int) -> float:
    """Consommation de base de la maison (W) : courbe horaire, réfrigérateur, petits appareils."""
    hour = minute // 60
    rng = _rng("base", day, hour)
    watts = BASE_W[hour] * rng.uniform(0.85, 1.15)
    watts += 70 if (minute // 20) % 2 == 0 else 0  # compresseur du réfrigérateur
    if hour in (7, 12, 19) and rng.random() < 0.6:  # bouilloire, plaque, four
        burst = rng.randint(5, 50)
        if burst <= minute % 60 < burst + rng.randint(3, 9):
            watts += 1800
    return round(watts, 1)


# --- Historique des appareils (avant le jour J) ---------------------------------------------


def past_starts(day: date) -> dict[str, datetime]:
    """Démarrages des appareils un jour d'historique : solaire les beaux jours, heures creuses
    sinon (comme un foyer qui suit déjà ses recommandations)."""
    rng = _rng("appliances", day)
    sunny = weather(day).actual >= 0.75
    found: dict[str, datetime] = {}

    def at(hour: float) -> datetime:
        minutes = int(hour * 60) // 5 * 5
        return datetime.combine(day, time(), ZONE) + timedelta(minutes=minutes)

    if (DAY - day).days % 2 == 0:  # tous les deux jours, dont le jour J
        found[WATER_HEATER] = at(rng.uniform(11.0, 12.5) if sunny else 22.25)
    if rng.random() < 0.5:
        washer = at(rng.uniform(9.5, 13.0) if sunny else 20.5)
        found[WASHING_MACHINE] = washer
        if rng.random() < 0.6:
            found[DRYER] = washer + timedelta(minutes=program_minutes(WASHING_MACHINE) + 10)
    if rng.random() < 0.75:
        found[DISHWASHER] = at(rng.uniform(13.0, 15.0) if sunny else 21.5)
    return found


# --- Simulation ---------------------------------------------------------------------------


@dataclass
class Counters:
    solar: float = 18_350.0
    grid_import: float = 9_812.0
    grid_export: float = 6_027.0
    charge: float = 2_461.0
    discharge: float = 2_198.0
    appliances: dict[str, float] = field(
        default_factory=lambda: {
            WATER_HEATER: 3_105.0,
            WASHING_MACHINE: 412.0,
            DRYER: 655.0,
            DISHWASHER: 497.0,
        }
    )


@dataclass
class House:
    """Maison simulée : ``step`` avance d'une minute et rend les valeurs des capteurs."""

    soc: float = START_SOC
    counters: Counters = field(default_factory=Counters)
    cycles: list[tuple[str, datetime]] = field(default_factory=list)  # démarrages prévus

    def start(self, appliance: str, moment: datetime) -> None:
        # Les cycles finis depuis plus d'un jour ne comptent plus (simulation plus rapide).
        self.cycles = [c for c in self.cycles if c[1] > moment - timedelta(days=2)]
        self.cycles.append((appliance, moment))

    def started(self, appliance: str, day: date) -> bool:
        return any(a == appliance and m.astimezone(ZONE).date() == day for a, m in self.cycles)

    def appliance_w(self, appliance: str, moment: datetime) -> float:
        for name, start in self.cycles:
            if name != appliance or moment < start:
                continue
            elapsed = (moment - start).total_seconds() / 60
            for minutes, watts in PROGRAMS[appliance]:
                if elapsed < minutes:
                    return watts
                elapsed -= minutes
        # Veille de la prise (afficheur, électronique) : quelques dixièmes de watt qui varient,
        # donc des relevés même entre deux cycles.
        return STANDBY_W[int(moment.timestamp()) // 420 % len(STANDBY_W)]

    def step(self, moment: datetime) -> dict[str, float]:
        """État des capteurs au début de la minute ``moment``, puis bilan de la minute."""
        local = moment.astimezone(ZONE)
        minute = local.hour * 60 + local.minute
        hours = 1 / 60
        pv = solar_w(local.date(), minute)
        loads = {a: self.appliance_w(a, moment) for a in APPLIANCES}
        load = base_w(local.date(), minute) + sum(loads.values())
        stored = self.soc / 100 * CAPACITY_KWH
        floor = FLOOR_PERCENT / 100 * CAPACITY_KWH
        charge = discharge = grid_in = grid_out = 0.0
        if pv >= load:
            room_w = max(0.0, (CAPACITY_KWH - stored) / EFFICIENCY / hours * 1000)
            charge = min(pv - load, BATTERY_MAX_W, room_w)
            grid_out = pv - load - charge
        else:
            available_w = max(0.0, (stored - floor) * EFFICIENCY / hours * 1000)
            discharge = min(load - pv, BATTERY_MAX_W, available_w)
            grid_in = load - pv - discharge
        c = self.counters
        values = {
            SOLAR_POWER: round(pv),
            SOLAR_ENERGY: round(c.solar, 3),
            GRID_IMPORT: round(c.grid_import, 3),
            GRID_EXPORT: round(c.grid_export, 3),
            BATTERY_CHARGE: round(c.charge, 3),
            BATTERY_DISCHARGE: round(c.discharge, 3),
            BATTERY_LEVEL: float(round(self.soc)),
        }
        for appliance, watts in loads.items():
            values[power_entity(appliance)] = round(watts, 1)
            values[energy_entity(appliance)] = round(c.appliances[appliance], 3)
        # Bilan de la minute : compteurs et niveau du début de la minute suivante.
        stored += (charge * EFFICIENCY - discharge / EFFICIENCY) * hours / 1000
        self.soc = min(100.0, max(0.0, stored / CAPACITY_KWH * 100))
        c.solar += pv * hours / 1000
        c.grid_import += grid_in * hours / 1000
        c.grid_export += grid_out * hours / 1000
        c.charge += charge * hours / 1000
        c.discharge += discharge * hours / 1000
        for appliance, watts in loads.items():
            c.appliances[appliance] += watts * hours / 1000
        return values


ENERGY_ENTITIES = frozenset(
    {
        SOLAR_ENERGY,
        GRID_IMPORT,
        GRID_EXPORT,
        BATTERY_CHARGE,
        BATTERY_DISCHARGE,
        *(energy_entity(a) for a in APPLIANCES),
    }
)


def changed(entity_id: str, value: float, last: float | None, minute: int) -> bool:
    """Relevé envoyé par l'intégration : puissance et niveau à chaque changement, compteurs toutes
    les 5 minutes s'ils ont bougé (comme un compteur qui rapporte par paliers)."""
    if last is None:
        return True
    if entity_id in ENERGY_ENTITIES:
        return minute % 5 == 0 and value != last
    return value != last
