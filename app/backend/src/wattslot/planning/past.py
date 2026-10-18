"""Entrées du calcul tirées de l'historique : ligne de base, meilleure production, historique
récent de la batterie et de la piscine (lot 2.2).

Mêmes règles que la v1 (``forme_horaire_solaire.py``), mais sur les **agrégats
horaires des compteurs d'énergie** du modèle de la maison au lieu des relevés de puissance aux
10 minutes :

- consommation de la maison par heure = production plus soutirage moins injection, plus
  décharge moins charge de la batterie ;
- **ligne de base** = cette consommation moins celle des équipements planifiés, calculée jour
  par jour puis moyennée (jamais de moyenne avant la soustraction : chaque valeur est un bilan
  réel d'un jour précis), sur les 6 derniers mêmes jours de semaine que le jour visé (tous les
  jours de la fenêtre tant qu'il n'y en a pas 6), au moins 3 jours par heure ;
- fenêtres bornées à minuit aujourd'hui : seules des journées complètes, résultat stable sur
  la journée.

Une heure n'entre dans la ligne de base que si le réseau et la batterie y ont un agrégat (la
production absente vaut 0 : la nuit, elle est réellement nulle).
"""

import itertools
from collections import defaultdict
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from wattslot.aggregation import HOUR, Aggregate
from wattslot.detection import DeviceKind, Role
from wattslot.home_model import HomeModel

SAME_WEEKDAY_OCCURRENCES = 6
SAFETY_WEEKS = 3  # marge contre les trous de données : fenêtre de 9 semaines (63 jours)
MIN_DAYS_PER_HOUR = 3
BEST_PRODUCTION_DAYS = 30
RECENT_DAYS = 14
FULL_CHARGE_PERCENT = 99.5
MIN_FILTRATION_KWH = 0.05  # par jour, pour compter comme filtré

# Équipements planifiés : leur consommation est retirée de la ligne de base (le calcul la
# compte explicitement).
PLANNED_KINDS = frozenset(
    {
        DeviceKind.WATER_HEATER,
        DeviceKind.WASHING_MACHINE,
        DeviceKind.DRYER,
        DeviceKind.DISHWASHER,
        DeviceKind.POOL_PUMP,
    }
)

DaySeries = dict[date, dict[int, float]]  # jour local → heure locale → valeur


class AggregateReader(Protocol):
    def read(
        self, entity_id: str, period: str, start: datetime, end: datetime
    ) -> list[Aggregate]: ...


@dataclass(frozen=True)
class BestProduction:
    max_kwh: float
    day: date
    days: int  # jours avec données


@dataclass(frozen=True)
class RecentHistory:
    last_full_charge: date | None
    days_without_filtration: int
    days: int


def sensors(
    model: HomeModel, roles: Iterable[Role], kinds: Iterable[DeviceKind] | None = None
) -> list[str]:
    wanted, allowed = set(roles), set(kinds) if kinds is not None else None
    return [
        sensor.entity_id
        for device in model.devices
        if allowed is None or device.kind in allowed
        for sensor in device.sensors
        if sensor.role in wanted
    ]


def window(today: date, days: int, zone: ZoneInfo) -> tuple[datetime, datetime]:
    """[minuit il y a ``days`` jours, minuit aujourd'hui), heure locale."""
    end = datetime.combine(today, time(), zone)
    return datetime.combine(today - timedelta(days=days), time(), zone), end


def series(
    reader: AggregateReader,
    entities: Sequence[str],
    start: datetime,
    end: datetime,
    zone: ZoneInfo,
    value: str = "energy_kwh",
    combine: str = "sum",
) -> DaySeries:
    """Agrégats horaires des entités, par jour et heure locaux : sommés (énergie) ou maximum."""
    found: dict[date, dict[int, float]] = defaultdict(dict)
    for entity_id in entities:
        for aggregate in reader.read(entity_id, HOUR, start, end):
            number = getattr(aggregate, value)
            if number is None:
                continue
            local = aggregate.start.astimezone(zone)
            day, hour = found[local.date()], local.hour
            if hour not in day:
                day[hour] = number
            elif combine == "sum":
                day[hour] += number
            else:
                day[hour] = max(day[hour], number)
    return dict(found)


def baseline(
    model: HomeModel,
    reader: AggregateReader,
    target: date,
    today: date,
    zone: ZoneInfo,
    occurrences: int = SAME_WEEKDAY_OCCURRENCES,
    planned: Collection[str] | None = None,
) -> dict[int, float]:
    """Consommation de base typique par heure locale (kWh), pour le jour ``target`` ; la
    consommation des équipements planifiés en est retirée : ceux dont la clé est dans
    ``planned`` (configuration, lot 3.4), sinon ceux des types ``PLANNED_KINDS``."""
    start, end = window(today, (occurrences + SAFETY_WEEKS) * 7, zone)

    def read(roles: Iterable[Role], kinds: Iterable[DeviceKind] | None = None) -> DaySeries:
        return series(reader, sensors(model, roles, kinds), start, end, zone)

    produced = read([Role.ENERGY_PRODUCED])
    imported, exported = read([Role.ENERGY_IMPORTED]), read([Role.ENERGY_EXPORTED])
    charged, discharged = read([Role.ENERGY_CHARGED]), read([Role.ENERGY_DISCHARGED])
    appliances = (
        series(
            reader,
            [
                sensor.entity_id
                for device in model.devices
                if device.key in planned
                for sensor in device.sensors
                if sensor.role is Role.ENERGY_CONSUMED
            ],
            start,
            end,
            zone,
        )
        if planned is not None
        else read([Role.ENERGY_CONSUMED], PLANNED_KINDS)
    )
    has_battery = bool(sensors(model, [Role.ENERGY_CHARGED, Role.ENERGY_DISCHARGED]))

    available = set(imported) | set(exported)
    same_weekday = sorted(
        (d for d in available if d.weekday() == target.weekday() and d != target), reverse=True
    )
    kept = set(same_weekday[:occurrences]) if len(same_weekday) >= occurrences else None

    values: dict[int, list[float]] = defaultdict(list)
    for day in sorted(available):
        if day == target or (kept is not None and day not in kept):
            continue
        grid_hours = set(imported.get(day, {})) | set(exported.get(day, {}))
        battery_hours = set(charged.get(day, {})) | set(discharged.get(day, {}))
        hours = grid_hours & battery_hours if has_battery else grid_hours
        for hour in hours:
            house = (
                produced.get(day, {}).get(hour, 0.0)
                + imported.get(day, {}).get(hour, 0.0)
                - exported.get(day, {}).get(hour, 0.0)
                + discharged.get(day, {}).get(hour, 0.0)
                - charged.get(day, {}).get(hour, 0.0)
            )
            values[hour].append(house - appliances.get(day, {}).get(hour, 0.0))
    return {
        hour: max(0.0, sum(found) / len(found))
        for hour, found in sorted(values.items())
        if len(found) >= MIN_DAYS_PER_HOUR
    }


def best_production(
    model: HomeModel, reader: AggregateReader, today: date, zone: ZoneInfo
) -> BestProduction | None:
    """Meilleure production journalière des 30 derniers jours complets."""
    start, end = window(today, BEST_PRODUCTION_DAYS, zone)
    produced = series(reader, sensors(model, [Role.ENERGY_PRODUCED]), start, end, zone)
    totals = {day: sum(by_hour.values()) for day, by_hour in produced.items()}
    if not totals:
        return None
    best = max(totals, key=lambda day: totals[day])
    return BestProduction(round(totals[best], 2), best, len(totals))


def recent_history(
    model: HomeModel, reader: AggregateReader, today: date, zone: ZoneInfo
) -> RecentHistory | None:
    """Dernière journée où la batterie a été pleine, et jours consécutifs sans filtration de la
    piscine, sur les 14 journées complètes précédentes ; None sans relevé de SoC."""
    start, end = window(today, RECENT_DAYS, zone)
    soc = series(reader, sensors(model, [Role.STATE_OF_CHARGE]), start, end, zone, "max", "max")
    if not soc:
        return None
    full = [day for day, by_hour in soc.items() if max(by_hour.values()) >= FULL_CHARGE_PERCENT]
    pool = sensors(model, [Role.ENERGY_CONSUMED], [DeviceKind.POOL_PUMP])
    without = days_without_running(reader, pool, today, zone)
    return RecentHistory(max(full) if full else None, without, RECENT_DAYS)


def days_without_running(
    reader: AggregateReader, entities: Sequence[str], today: date, zone: ZoneInfo
) -> int:
    """Journées complètes consécutives, avant aujourd'hui, où ces compteurs d'énergie n'ont pas
    bougé (moins de ``MIN_FILTRATION_KWH``), sur ``RECENT_DAYS`` jours au plus."""
    start, end = window(today, RECENT_DAYS, zone)
    energy = series(reader, entities, start, end, zone)
    without = 0
    for offset in range(1, RECENT_DAYS + 1):
        if sum(energy.get(today - timedelta(days=offset), {}).values()) >= MIN_FILTRATION_KWH:
            break
        without += 1
    return without


# --- Rendements de la batterie par sens ----------------------------------------------------

EFFICIENCY_DAYS = 30
STILL_COUNTER_KWH = 0.005  # variation d'un compteur sous laquelle il est immobile sur l'heure
MIN_EFFICIENCY_KWH = 5.0  # énergie minimale dans chaque sens pour retenir la mesure
MIN_PLAUSIBLE = 0.5  # en dessous : mesure aberrante ; au-dessus de 100 % : plafonnée


@dataclass(frozen=True)
class BatteryEfficiencies:
    """Rendements de la batterie par sens, rapportés à l'énergie stockée qu'elle annonce."""

    ok: bool
    message: str | None = None
    charge_percent: float | None = None
    discharge_percent: float | None = None
    raw_charge_percent: float | None = None
    raw_discharge_percent: float | None = None
    charged_kwh: float = 0.0
    discharged_kwh: float = 0.0
    charge_hours: int = 0
    discharge_hours: int = 0
    days: float = 0.0


def efficiencies_from_hours(
    stored_end: dict[datetime, float],
    charged: dict[datetime, float],
    discharged: dict[datetime, float],
) -> BatteryEfficiencies:
    """Méthode de la v1 (``rendements_depuis_releves``) sur des heures : une heure où seule la
    charge avance compte pour la charge (rendement = hausse du stock / énergie chargée), une
    heure où seule la décharge avance compte pour la décharge (énergie restituée / baisse du
    stock). Les heures mixtes ou immobiles sont écartées. Clés : début des heures (UTC) ;
    ``stored_end`` : énergie stockée à la fin de chaque heure."""
    hours = sorted(stored_end)
    if not hours or not charged or not discharged:
        return BatteryEfficiencies(ok=False, message="capteur sans relevé")
    totals = {"charge_ac": 0.0, "charge_stock": 0.0, "discharge_ac": 0.0, "discharge_stock": 0.0}
    counts = {"charge": 0, "discharge": 0}
    for previous, hour in itertools.pairwise(hours):
        if hour - previous != timedelta(hours=1):
            continue  # trou dans les mesures : pas de variation du stock sur l'heure
        d_stock = stored_end[hour] - stored_end[previous]
        d_charge, d_discharge = charged.get(hour, 0.0), discharged.get(hour, 0.0)
        if d_charge < 0 or d_discharge < 0:
            continue
        charging, discharging = d_charge > STILL_COUNTER_KWH, d_discharge > STILL_COUNTER_KWH
        if charging and not discharging:
            totals["charge_ac"] += d_charge
            totals["charge_stock"] += d_stock
            counts["charge"] += 1
        elif discharging and not charging:
            totals["discharge_ac"] += d_discharge
            totals["discharge_stock"] -= d_stock
            counts["discharge"] += 1
    base = BatteryEfficiencies(
        ok=False,
        charged_kwh=round(totals["charge_ac"], 2),
        discharged_kwh=round(totals["discharge_ac"], 2),
        charge_hours=counts["charge"],
        discharge_hours=counts["discharge"],
        days=round((hours[-1] - hours[0]).total_seconds() / 86400, 1),
    )
    if (
        min(totals["charge_ac"], totals["discharge_ac"]) < MIN_EFFICIENCY_KWH
        or totals["discharge_stock"] <= 0
    ):
        return replace(base, message="pas assez d'énergie échangée")
    raw_charge = totals["charge_stock"] / totals["charge_ac"]
    raw_discharge = totals["discharge_ac"] / totals["discharge_stock"]
    base = replace(
        base,
        raw_charge_percent=round(raw_charge * 100, 1),
        raw_discharge_percent=round(raw_discharge * 100, 1),
    )
    if min(raw_charge, raw_discharge) < MIN_PLAUSIBLE:
        return replace(base, message="rendement mesuré aberrant")
    return replace(
        base,
        ok=True,
        charge_percent=round(min(1.0, raw_charge) * 100, 1),
        discharge_percent=round(min(1.0, raw_discharge) * 100, 1),
    )


def battery_efficiencies(
    model: HomeModel, reader: AggregateReader, today: date, zone: ZoneInfo
) -> BatteryEfficiencies:
    """Rendements par sens sur les 30 derniers jours complets. L'énergie stockée en fin d'heure
    vient du SoC en fin d'heure (``wattslot:last`` des agrégats) et de la capacité de la batterie ;
    les statistiques reprises de HA n'en ont pas : la mesure commence avec l'ingestion."""
    start, end = window(today, EFFICIENCY_DAYS, zone)
    stored: dict[datetime, float] = defaultdict(float)
    charged: dict[datetime, float] = defaultdict(float)
    discharged: dict[datetime, float] = defaultdict(float)
    for device in model.devices:
        if device.kind is not DeviceKind.BATTERY:
            continue
        for sensor in device.sensors:
            for aggregate in reader.read(sensor.entity_id, HOUR, start, end):
                hour = aggregate.start.astimezone(UTC)
                if sensor.role is Role.STATE_OF_CHARGE and aggregate.last is not None:
                    if device.capacity_kwh:
                        stored[hour] += aggregate.last * device.capacity_kwh / 100
                elif sensor.role is Role.ENERGY_CHARGED and aggregate.energy_kwh is not None:
                    charged[hour] += aggregate.energy_kwh
                elif sensor.role is Role.ENERGY_DISCHARGED and aggregate.energy_kwh is not None:
                    discharged[hour] += aggregate.energy_kwh
    return efficiencies_from_hours(dict(stored), dict(charged), dict(discharged))
