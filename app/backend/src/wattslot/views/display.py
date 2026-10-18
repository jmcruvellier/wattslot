"""Calculs d'affichage du dashboard de la v1, repris sans HTML (``dashboard.py``).

Mêmes formules et mêmes arrondis que la v1 : le test de parité les compare à ses fonctions
(``_equipements_planifies_horaire``, ``_equipements_reels_par_heure``,
``_resimuler_soc_estime_ajuste``, ``_resume_journee``, ``_production_recalee``). Le contexte de la
maison est passé en paramètre (``Context``), et non posé dans des variables globales comme pour le
dashboard copié.
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from wattslot.battery_settings import DEFAULT as DEFAULT_BATTERY
from wattslot.battery_settings import BatterySettings
from wattslot.planning.cycles import (
    PlannedCycle,
    Segment,
    measured_hourly,
    planned_hourly,
    realign,
    recognized_segment,
    remaining_hourly,
)
from wattslot.planning.inputs import V1_POOL
from wattslot.planning.reference import task_key
from wattslot.planning.simulation import simulate

BATTERY = "Batterie"


@dataclass(frozen=True)
class Context:
    """Ce que la vue sait de la maison, en plus du plan."""

    zone: ZoneInfo = field(default_factory=lambda: ZoneInfo("UTC"))
    off_peak: tuple[tuple[int, int], ...] = ()  # heures creuses [début, fin[ du jour affiché
    battery: BatterySettings = field(default_factory=lambda: DEFAULT_BATTERY)
    pool_speeds: Mapping[str, float] = field(default_factory=lambda: dict(V1_POOL.speeds))
    # Équipements à cycles de la maison : une ligne de la frise même sans créneau prévu.
    appliances: tuple[str, ...] = ()
    # Objectif du calcul (préréglage du lot 3.6) : l'indicateur mis en avant (point n° 5).
    objective: str = "cost"
    # Faux pour une maison sans installation solaire (lot 7.4) : rien de solaire à montrer.
    solar: bool = True

    def speed_kw(self, mode: str) -> float:
        """Puissance d'un mode de la filtration ; la plus haute pour « eco » et la plus basse
        pour « silence » si ses vitesses portent d'autres noms (comme la v1)."""
        if mode in self.pool_speeds:
            return self.pool_speeds[mode]
        if not self.pool_speeds:
            return 0.0
        speeds = self.pool_speeds.values()
        return max(speeds) if mode == "eco" else min(speeds)

    def off_peak_hours(self) -> list[bool]:
        return [any(start <= h < end for start, end in self.off_peak) for h in range(24)]


def find_item(planning: Sequence[dict[str, Any]], name: str) -> dict[str, Any] | None:
    return next((item for item in planning if item.get("equipement") == name), None)


def is_runtime(item: Mapping[str, Any]) -> bool:
    """Durée de fonctionnement à placer (la filtration) : placée en segments par vitesse."""
    return "segments" in item


def _now(actual: Mapping[str, Any] | None) -> datetime | None:
    if not actual or not actual.get("heure_maj_iso"):
        return None
    try:
        return datetime.fromisoformat(actual["heure_maj_iso"])
    except (TypeError, ValueError):
        return None


def _segments(raw: Sequence[Mapping[str, Any]] | None) -> list[Segment]:
    return [
        Segment(
            datetime.fromisoformat(s["debut_iso"]),
            datetime.fromisoformat(s["fin_iso"]),
            s.get("energie_kwh", 0.0),
            bool(s.get("en_cours")),
        )
        for s in raw or []
    ]


def _bounds(item: Mapping[str, Any]) -> tuple[int, int, float]:
    """(début, fin) du cycle en minutes et sa durée, comme ``recalage_cycles`` de la v1."""
    cycle_min = item.get("duree_cycle_min") or (item["heure_fin"] - item["heure_debut"]) * 60
    start = item.get("debut_min", item["heure_debut"] * 60)
    return start, item.get("fin_min", min(24 * 60, start + round(cycle_min))), cycle_min


def planned_devices_hourly(
    planning: Sequence[dict[str, Any]], actual: Mapping[str, Any] | None, context: Context
) -> dict[int, float]:
    """kWh par heure des équipements prévus (batterie exclue), recalés sur leur cycle réel s'il
    a commencé (``_equipements_planifies_horaire`` de la v1)."""
    by_hour: dict[int, float] = defaultdict(float)
    now = _now(actual)
    measured = (
        {
            task_key(name): _segments(segs)
            for name, segs in ((actual or {}).get("equipements_reels_horaire") or {}).items()
        }
        if now
        else {}
    )
    for item in planning:
        if item["equipement"] == BATTERY:
            continue
        if is_runtime(item):
            for segment in item.get("segments", []):
                if segment["mode"] == "off":
                    continue
                power = context.speed_kw(segment["mode"])
                for h in range(segment["heure_debut"], segment["heure_fin"]):
                    by_hour[h] += power
            continue
        segments = measured.get(task_key(item["equipement"]), [])
        start, end, cycle_min = _bounds(item)
        energy = item.get("energie_kwh", 0.0)
        shape = item.get("forme_quart_heure")
        realignment = realign(energy, cycle_min, segments, now) if now else None
        sources: tuple[dict[int, float], ...]
        if realignment is not None and now is not None:
            segment = recognized_segment(segments, energy)
            assert segment is not None
            sources = (
                measured_hourly(realignment, segment, shape),
                remaining_hourly(realignment, now, shape),
            )
        else:
            sources = (planned_hourly(PlannedCycle(start, end, energy, shape)),)
        for source in sources:
            for h, kwh in source.items():
                by_hour[h] += kwh
    return dict(by_hour)


def actual_devices_hourly(segments_by_device: Mapping[str, Any] | None) -> dict[int, float]:
    """kWh par heure de l'énergie mesurée des équipements, à puissance constante sur chaque
    segment (``_equipements_reels_par_heure`` de la v1)."""
    by_hour: dict[int, float] = defaultdict(float)
    for segments in (segments_by_device or {}).values():
        for segment in segments:
            try:
                start = datetime.fromisoformat(segment["debut_iso"])
                end = datetime.fromisoformat(segment["fin_iso"])
            except (KeyError, ValueError, TypeError):
                continue
            hours = (end - start).total_seconds() / 3600
            if hours <= 0:
                continue
            power = segment.get("energie_kwh", 0.0) / hours
            cursor = start
            while cursor < end:
                next_hour = cursor.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
                bound = min(end, next_hour)
                by_hour[cursor.hour] += power * (bound - cursor).total_seconds() / 3600
                cursor = bound
    return dict(by_hour)


def active_range(state: Mapping[str, Any], context: Context) -> tuple[int, int]:
    """Plage d'autoconsommation des plannings actifs de la batterie, sinon celle des réglages."""
    ranges = [
        s
        for s in state.get("schedules_batterie_actifs") or []
        if s.get("mode") == -1 and s.get("start") and s.get("end")
    ]
    if not ranges:
        return context.battery.active_from_hour, context.battery.active_to_hour
    starts = [s["start"]["heure"] for s in ranges]
    ends = [s["end"]["heure"] + (1 if s["end"]["minute"] > 0 else 0) for s in ranges]
    return min(starts), max(ends)


def _efficiencies(state: Mapping[str, Any]) -> tuple[float, float]:
    measured = state.get("rendements_batterie") or {}
    if measured.get("status") == "ok":
        return (
            measured["rendement_charge_percent"] / 100,
            measured["rendement_decharge_percent"] / 100,
        )
    round_trip = state.get("rendement_round_trip_percent")
    per_way = (round_trip / 100) ** 0.5 if round_trip else 1.0
    return per_way, per_way


def resimulated_soc(
    state: Mapping[str, Any],
    actual: Mapping[str, Any] | None,
    production: Sequence[float],
    baseline: Mapping[int, float],
    planned: Mapping[int, float],
    context: Context,
) -> list[float] | None:
    """SoC estimé (%) recalé heure par heure sur le SoC réel, avec la consommation réelle des
    équipements pour les heures passées (``_resimuler_soc_estime_ajuste`` de la v1) ; ``None``
    sans relevé ou sans batterie."""
    now = _now(actual)
    battery = find_item(state.get("planning", []), BATTERY)
    if now is None or battery is None or actual is None:
        return None
    limit, remaining_fraction = now.hour, 1 - now.minute / 60
    capacity = state.get("capacite_batterie_kwh", 1.0) or 1.0
    current = battery.get("soc_initial_kwh", 0.0)
    charge_kw = state.get("puissance_charge_max_w", 0.0) / 1000
    discharge_kw = state.get("puissance_decharge_max_w", 0.0) / 1000
    start, end = active_range(state, context)
    charge_eff, discharge_eff = _efficiencies(state)
    devices = actual_devices_hourly(actual.get("equipements_reels_horaire", {}))
    measured = {
        int(h): pct / 100 * capacity
        for h, pct in (actual.get("soc_pct_fin_heure") or actual.get("soc_pct_reel") or {}).items()
    }
    found = []
    for h in range(24):
        fraction = 1.0
        if h == limit and h in measured:
            current, fraction = measured[h], remaining_fraction
        elif h > 0 and (h - 1) in measured and h - 1 < limit:
            current = measured[h - 1]
        used = devices.get(h, 0.0) if h < limit else planned.get(h, 0.0)
        net = {h: (production[h] - baseline.get(h, 0.0) - used) * fraction}
        run = simulate(
            net,
            current,
            capacity,
            charge_kw,
            discharge_kw,
            start,
            end,
            charge_eff,
            discharge_eff,
            capacity * context.battery.floor_percent / 100,
            h,
        )
        current = run.end_kwh
        found.append(round(current / capacity * 100, 1))
    return found


@dataclass(frozen=True)
class SocCurve:
    soc_percent: list[float]  # fin de chaque heure, recalé sur le réel s'il y en a
    production: list[float]
    baseline: dict[int, float]
    planned: dict[int, float]


def displayed_soc(
    state: Mapping[str, Any], actual: Mapping[str, Any] | None, context: Context
) -> SocCurve:
    """Courbe du SoC affichée et les séries dont elle dépend (``_courbe_soc_affichee``)."""
    planning = state.get("planning", [])
    battery = find_item(planning, BATTERY)
    capacity = state.get("capacite_batterie_kwh", 1.0) or 1.0
    by_hour = battery.get("soc_horaire_kwh", {}) if battery else {}
    soc = [round(_hour(by_hour, h) / capacity * 100, 1) for h in range(24)]
    production_by_hour = state.get("production_solaire_horaire", {})
    production = [round(_hour(production_by_hour, h), 3) for h in range(24)]
    baseline = {int(h): v for h, v in (state.get("consommation_baseline_horaire") or {}).items()}
    planned = planned_devices_hourly(planning, actual, context)
    resimulated = resimulated_soc(state, actual, production, baseline, planned, context)
    return SocCurve(resimulated if resimulated is not None else soc, production, baseline, planned)


def _hour(values: Mapping[Any, float], h: int) -> float:
    """Valeur d'une heure, que les clés soient des entiers ou du texte (JSON)."""
    return float(values.get(h, values.get(str(h), 0.0)))


def day_summary(state: Mapping[str, Any], soc_percent: Sequence[float]) -> dict[str, Any]:
    """Valeurs de fin de journée (``_resume_journee`` de la v1)."""
    capacity = state.get("capacite_batterie_kwh", 1.0) or 1.0
    battery = find_item(state.get("planning", []), BATTERY)
    initial = battery["soc_initial_kwh"] if battery else 0
    initial_pct = initial / capacity * 100 if capacity else 0
    soc_max = max(soc_percent) if soc_percent else 0
    if not soc_percent or initial_pct >= soc_max:
        soc_max, max_hour = initial_pct, 0
    else:
        max_hour = list(soc_percent).index(soc_max) + 1
    final_pct = soc_percent[23] if soc_percent else initial_pct
    residual = state.get("residu_reseau_horaire", {})
    movements = battery.get("mouvements", []) if battery else []
    return {
        "soc_end_kwh": round(final_pct / 100 * capacity, 3),
        "soc_end_percent": round(final_pct, 1),
        "soc_max_kwh": round(soc_max / 100 * capacity, 3),
        "soc_max_percent": round(soc_max, 1),
        "soc_max_hour": max_hour,
        "charge_kwh": round(sum(m["energie_kwh"] for m in movements if m["action"] == "charge"), 3),
        "discharge_kwh": round(
            sum(m["energie_kwh"] for m in movements if m["action"] == "decharge"), 3
        ),
        "grid_import_kwh": round(-sum(v for v in residual.values() if v < 0), 3),
        "grid_export_kwh": round(sum(v for v in residual.values() if v > 0), 3),
        "production_kwh": round(sum((state.get("production_solaire_horaire") or {}).values()), 3),
    }


def initial_forecast_summary(state: Mapping[str, Any]) -> dict[str, Any]:
    """Fin de journée de la simulation brute du plan (``resume_prevision_initiale``)."""
    capacity = state.get("capacite_batterie_kwh", 1.0) or 1.0
    battery = find_item(state.get("planning", []), BATTERY)
    by_hour = battery.get("soc_horaire_kwh", {}) if battery else {}
    return day_summary(state, [round(_hour(by_hour, h) / capacity * 100, 1) for h in range(24)])


def recalculated_production(
    production: Sequence[float], actual: Mapping[str, Any] | None
) -> float | None:
    """Production de la journée : mesurée jusqu'au relevé puis prévue (``_production_recalee``)."""
    now = _now(actual)
    if now is None or actual is None:
        return None
    x = now.hour + now.minute / 60 + now.second / 3600
    h = int(x)
    rest = sum(production[h + 1 :]) + production[h] * (1 - (x - h))
    return float(sum((actual.get("production_reelle_horaire") or {}).values()) + rest)
