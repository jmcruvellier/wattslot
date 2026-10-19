"""Fusion « passé gelé / futur recalculé » de deux plans d'une même journée.

Réécriture de ``fusion_planning.py`` (v1), son oracle dans les tests. Le calcul tourne
chaque heure et ne décide que les heures à partir de l'heure d'exécution. La fusion recolle
ce futur au passé du plan précédent de la même journée : avant l'heure d'exécution, tout vient
du plan précédent, ensuite du nouveau. Un plan d'une autre journée n'est pas fusionné.

- **Champs horaires** (surplus, net, production, ligne de base, résidu réseau) : découpe.
- **Batterie** : mouvements et SoC découpés ; SoC initial du tout premier calcul du jour.
- **Piscine** : modes découpés heure par heure, segments reconstruits.
- **Équipements** : un bloc commencé avant l'heure d'exécution est gelé, sauf si sa tâche a
  été retirée de HA sans que l'équipement ait tourné (annulation).
- **Avertissements** : réunion sans doublon.

Le plan suit le format de la v1 (sortie du moteur, ``engine.output``), lu par le dashboard.
"""

import json
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from wattslot.planning.cycles import Segment, recognized_segment
from wattslot.planning.plan import BATTERY as BATTERY
from wattslot.planning.plan import POOL as POOL
from wattslot.planning.plan import Plan as DayPlan

HOURLY_FIELDS = (
    "surplus_horaire",
    "net_horaire_signe",
    "production_solaire_horaire",
    "consommation_baseline_horaire",
    "residu_reseau_horaire",
)

Plan = dict[str, Any]


def merge_hourly(
    old: Mapping[int, Any] | None, new: Mapping[int, Any] | None, first_hour: int
) -> dict[int, Any]:
    return {
        **{h: v for h, v in (old or {}).items() if h < first_hour},
        **{h: v for h, v in (new or {}).items() if h >= first_hour},
    }


def pool_modes(segments: list[dict[str, Any]] | None) -> dict[int, str]:
    modes: dict[int, str] = {}
    for segment in segments or []:
        for hour in range(segment["heure_debut"], segment["heure_fin"]):
            modes[hour] = segment["mode"]
    return modes


def pool_segments(modes: Mapping[int, str]) -> list[dict[str, Any]]:
    """Segments contigus sur la journée ; une heure absente compte comme arrêt."""
    if not modes:
        return []
    segments = []
    since = 0
    current: str | None = modes.get(0, "off")
    for hour in range(1, 25):
        mode = modes.get(hour, "off") if hour < 24 else None
        if mode != current:
            segments.append({"heure_debut": since, "heure_fin": hour, "mode": current})
            since, current = hour, mode
    return segments


def _merge_pool(
    old: dict[str, Any] | None, new: dict[str, Any] | None, first_hour: int
) -> dict[str, Any] | None:
    if old is None and new is None:
        return None
    old_modes = pool_modes(old["segments"]) if old else {}
    new_modes = pool_modes(new["segments"]) if new else {}
    modes = {
        **{h: m for h, m in old_modes.items() if h < first_hour},
        **{h: m for h, m in new_modes.items() if h >= first_hour},
    }
    base = new or old
    assert base is not None
    return {**base, "segments": pool_segments(modes)}


def _merge_battery(
    old: dict[str, Any] | None, new: dict[str, Any] | None, first_hour: int
) -> dict[str, Any] | None:
    if new is None:
        return old
    if old is None:
        return new
    movements = [m for m in old.get("mouvements", []) if m["heure"] < first_hour] + [
        m for m in new.get("mouvements", []) if m["heure"] >= first_hour
    ]
    soc = merge_hourly(old.get("soc_horaire_kwh", {}), new.get("soc_horaire_kwh", {}), first_hour)
    charged = sum(m["energie_kwh"] for m in movements if m["action"] == "charge")
    discharged = sum(m["energie_kwh"] for m in movements if m["action"] == "decharge")
    return {
        **new,
        "mouvements": movements,
        "soc_horaire_kwh": soc,
        "energie_chargee_kwh": round(charged, 3),
        "energie_dechargee_kwh": round(discharged, 3),
        # Point de départ du jour : celui du tout premier calcul, pas l'état « maintenant ».
        "soc_initial_kwh": old.get("soc_initial_kwh", new.get("soc_initial_kwh")),
        "soc_final_kwh": soc.get(23, new.get("soc_final_kwh", old.get("soc_final_kwh"))),
    }


def _about(warning: Any, placed: set[str]) -> bool:
    """Avertissement d'un calcul précédent sur un équipement que le plan place désormais
    (profil devenu disponible, temps suffisant…) : périmé, il n'est pas gardé."""
    if not isinstance(warning, dict):
        return False
    return warning.get("params", {}).get("equipement") in placed


def _deduplicated(warnings: list[Any]) -> list[Any]:
    """Sans doublon, ordre préservé (avertissements structurés ou anciens textes)."""
    seen: dict[Any, Any] = {}
    for warning in warnings:
        key = (
            json.dumps(warning, sort_keys=True, ensure_ascii=False)
            if isinstance(warning, dict)
            else warning
        )
        seen.setdefault(key, warning)
    return list(seen.values())


def merge_planning(
    old: list[dict[str, Any]] | None,
    new: list[dict[str, Any]] | None,
    first_hour: int,
    active_tasks: set[str] | None = None,
    real_segments: Mapping[str, list[Segment]] | None = None,
) -> list[dict[str, Any]]:
    """Équipements du plan fusionné.

    ``active_tasks`` : noms des tâches actives d'après la dernière lecture de HA (None : pas de
    filtre). Une tâche retirée n'est plus gelée, sauf si son équipement a tourné aujourd'hui
    (cycle réel reconnu dans ``real_segments``) : tâche terminée, pas annulée.
    """
    old_by_name = {item["equipement"]: item for item in old or []}
    new_by_name = {item["equipement"]: item for item in new or []}
    merged: list[dict[str, Any]] = []
    battery = _merge_battery(old_by_name.get(BATTERY), new_by_name.get(BATTERY), first_hour)
    if battery:
        merged.append(battery)
    # Durées à placer (filtration…) : reconnues à leurs segments, modes fusionnés heure par heure.
    runtimes = [
        name
        for name, item in {**old_by_name, **new_by_name}.items()
        if "segments" in item and name != BATTERY
    ]
    for name in runtimes:
        runtime = _merge_pool(old_by_name.get(name), new_by_name.get(name), first_hour)
        if runtime:
            merged.append(runtime)
    for name in (set(old_by_name) | set(new_by_name)) - {BATTERY, *runtimes}:
        old_item = old_by_name.get(name)
        still_active = (
            active_tasks is None
            or name in active_tasks
            or (
                old_item is not None
                and recognized_segment(
                    (real_segments or {}).get(name, []), old_item.get("energie_kwh", 0.0)
                )
                is not None
            )
        )
        if old_item and old_item["heure_debut"] < first_hour and still_active:
            merged.append(old_item)  # commencé ou décidé dans le passé : gelé
        elif name in new_by_name:
            merged.append(new_by_name[name])
        elif old_item and still_active:
            merged.append(old_item)
        # sinon : tâche annulée dans HA, et plus proposée par le nouveau calcul
    return merged


def merge_plans(
    new: Plan,
    old: Plan | None,
    first_hour: int,
    real_segments: Mapping[str, list[Segment]] | None = None,
) -> Plan:
    """Plan complet de la journée : passé de ``old``, futur de ``new``."""
    if not old or old.get("date_cible") != new.get("date_cible"):
        return new
    merged = dict(new)
    for field in HOURLY_FIELDS:
        merged[field] = merge_hourly(old.get(field, {}), new.get(field, {}), first_hour)
    day = new.get("date_cible")
    day_iso = day.isoformat() if isinstance(day, date) else day
    active = {t["summary"] for t in new.get("taches_placees", []) if t.get("due") == day_iso} | {
        t["summary"] for t in new.get("taches_en_attente", [])
    }
    merged["planning"] = merge_planning(
        old.get("planning", []), new.get("planning", []), first_hour, active, real_segments
    )
    placed = {item["equipement"] for item in merged["planning"]}
    merged["avertissements"] = _deduplicated(
        [w for w in old.get("avertissements", []) if not _about(w, placed)]
        + new.get("avertissements", [])
    )
    merged["avertissements_prevision"] = _deduplicated(
        old.get("avertissements_prevision", []) + new.get("avertissements_prevision", [])
    )
    return merged


def merge_day(
    new: DayPlan,
    old: DayPlan | None,
    first_hour: int,
    real_segments: Mapping[str, list[Segment]] | None = None,
) -> DayPlan:
    """``merge_plans`` sur des plans typés (algorithme de la v1, sur leur format de la v1)."""
    merged = merge_plans(new.to_v1(), old.to_v1() if old else None, first_hour, real_segments)
    return DayPlan.from_v1(merged)


def soc_at_hour_start(readings: Mapping[str, Any] | None, hour: int) -> float | None:
    """SoC mesuré (%) au début de l'heure : à minuit pour 0 h, sinon à la fin de l'heure
    précédente. None si la mesure manque."""
    readings = readings or {}
    if hour == 0:
        return readings.get("soc_pct_minuit")
    by_hour = readings.get("soc_pct_fin_heure") or {}
    return by_hour.get(hour - 1, by_hour.get(str(hour - 1)))


def start_soc(
    readings: Mapping[str, Any] | None, hour: int, old: Plan | None = None
) -> float | None:
    """SoC de départ (%) du calcul, qui simule l'heure ``hour`` en entier.

    On part du SoC mesuré au relevé, moins la part déjà écoulée de l'action de la batterie que
    le plan précédent prévoyait pour cette heure (rendements compris) : la simulation de
    l'heure entière retrouve ainsi le SoC mesuré, puis n'ajoute que la fin de l'heure. Sans
    plan précédent de la même journée ou sans relevé dans l'heure : SoC du début de l'heure.
    Borné à [0, 100].
    """
    readings = readings or {}
    by_hour = readings.get("soc_pct_fin_heure") or {}
    measured = by_hour.get(hour, by_hour.get(str(hour)))
    battery = next(
        (i for i in (old or {}).get("planning", []) if i.get("equipement") == BATTERY), None
    )
    capacity = (old or {}).get("capacite_batterie_kwh")
    try:
        at: datetime | None = datetime.fromisoformat(readings.get("heure_maj_iso") or "")
    except ValueError:
        at = None
    if measured is None or battery is None or not capacity or at is None or at.hour != hour:
        return soc_at_hour_start(readings, hour)
    round_trip = (old or {}).get("rendement_round_trip_percent")
    per_direction = (round_trip / 100) ** 0.5 if round_trip else 1.0
    efficiencies = (old or {}).get("rendements_batterie") or {}
    measured_ok = efficiencies.get("status") == "ok"
    charge = (efficiencies["rendement_charge_percent"] / 100 if measured_ok else 0) or per_direction
    discharge = (
        efficiencies["rendement_decharge_percent"] / 100 if measured_ok else 0
    ) or per_direction
    change_kwh = sum(
        m["energie_kwh"] * charge if m["action"] == "charge" else -m["energie_kwh"] / discharge
        for m in battery.get("mouvements", [])
        if m.get("heure") == hour
    )
    elapsed = at.minute / 60
    percent: float = float(measured) - elapsed * change_kwh / float(capacity) * 100
    return min(100.0, max(0.0, percent))
