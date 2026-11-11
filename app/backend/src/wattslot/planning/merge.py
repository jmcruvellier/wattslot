"""Fusion « passé gelé / futur recalculé » de deux plans d'une même journée.

Réécriture de ``fusion_planning.py`` (v1), son oracle dans les tests. Le calcul tourne
chaque heure et ne décide que les heures à partir de l'heure d'exécution. La fusion recolle
ce futur au passé du plan précédent de la même journée : avant l'heure d'exécution, tout vient
du plan précédent, ensuite du nouveau. Un plan d'une autre journée n'est pas fusionné.

- **Champs horaires** (surplus, net, production, ligne de base, résidu réseau) : découpe.
- **Batterie** : mouvements et SoC découpés ; SoC initial du tout premier calcul du jour.
- **Piscine** : modes découpés heure par heure, segments reconstruits.
- **Équipements** : un bloc commencé avant l'heure d'exécution est gelé, sauf si sa tâche a
  été retirée de HA sans que l'équipement ait tourné (annulation), ou si son cycle réel a
  démarré : le nouveau calcul le recale alors sur ce démarrage (écart à la v1).
- **Avertissements** : réunion sans doublon.

Le plan suit le format de la v1 (sortie du moteur, ``engine.output``), lu par le dashboard.
"""

import json
from collections.abc import Mapping
from datetime import date
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

PHASE_RESIDUAL = "residu_reseau_par_phase"

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
    # Calcul par phase : chaque groupe de batteries fusionné de même, quand le nouveau plan
    # les distingue encore.
    before = {group["phase"]: group for group in old.get("groupes") or []}
    groups = [
        {
            **group,
            "mouvements": [
                m
                for m in before.get(group["phase"], {}).get("mouvements", [])
                if m["heure"] < first_hour
            ]
            + [m for m in group.get("mouvements", []) if m["heure"] >= first_hour],
        }
        for group in new.get("groupes") or []
    ]
    return {
        **new,
        **({"groupes": groups} if groups else {}),
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
    chosen: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Équipements du plan fusionné.

    ``active_tasks`` : noms des tâches actives d'après la dernière lecture de HA (None : pas de
    filtre). Une tâche retirée n'est plus gelée, sauf si son équipement a tourné aujourd'hui
    (cycle réel reconnu dans ``real_segments``) : tâche terminée, pas annulée. ``chosen`` : noms
    des équipements dont l'utilisateur a choisi le départ — leur ancien créneau passé n'est pas
    gelé, le nouveau plan l'emporte.
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
        if (
            old_item
            and old_item["heure_debut"] < first_hour
            and still_active
            and (chosen is None or name not in chosen)
            and not _launched(new_by_name.get(name))
        ):
            merged.append(old_item)  # commencé ou décidé dans le passé : gelé
        elif name in new_by_name:
            merged.append(new_by_name[name])
        elif old_item and still_active:
            merged.append(old_item)
        # sinon : tâche annulée dans HA, et plus proposée par le nouveau calcul
    return merged


def _launched(item: Mapping[str, Any] | None) -> bool:
    """Bloc d'un cycle lancé, recalé par le nouveau calcul sur son démarrage réel : il remplace
    le bloc gelé, dont la fin ne suivait plus le cycle (pas dans la v1)."""
    reasons = ((item or {}).get("explication") or {}).get("raisons") or []
    return any(r.get("code") == "launched" for r in reasons if isinstance(r, Mapping))


def merge_plans(
    new: Plan,
    old: Plan | None,
    first_hour: int,
    real_segments: Mapping[str, list[Segment]] | None = None,
    chosen: set[str] | None = None,
) -> Plan:
    """Plan complet de la journée : passé de ``old``, futur de ``new``. ``chosen`` : noms des
    équipements dont l'utilisateur a choisi le départ aujourd'hui — leur ancien créneau passé
    n'est pas gelé, le nouveau plan les tient."""
    if not old or old.get("date_cible") != new.get("date_cible"):
        return new
    merged = dict(new)
    for field in HOURLY_FIELDS:
        merged[field] = merge_hourly(old.get(field, {}), new.get(field, {}), first_hour)
    if PHASE_RESIDUAL in new:  # échange de chaque phase : heure par heure, comme le total
        before = old.get(PHASE_RESIDUAL) or {}
        merged[PHASE_RESIDUAL] = {
            phase: merge_hourly(before.get(phase), hourly, first_hour)
            for phase, hourly in new[PHASE_RESIDUAL].items()
        }
    day = new.get("date_cible")
    day_iso = day.isoformat() if isinstance(day, date) else day
    active = {t["summary"] for t in new.get("taches_placees", []) if t.get("due") == day_iso} | {
        t["summary"] for t in new.get("taches_en_attente", [])
    }
    merged["planning"] = merge_planning(
        old.get("planning", []), new.get("planning", []), first_hour, active, real_segments, chosen
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
    chosen: set[str] | None = None,
) -> DayPlan:
    """``merge_plans`` sur des plans typés (algorithme de la v1, sur leur format de la v1)."""
    merged = merge_plans(
        new.to_v1(), old.to_v1() if old else None, first_hour, real_segments, chosen
    )
    return DayPlan.from_v1(merged)


def soc_at_hour_start(readings: Mapping[str, Any] | None, hour: int) -> float | None:
    """SoC mesuré (%) au début de l'heure : à minuit pour 0 h, sinon à la fin de l'heure
    précédente. None si la mesure manque."""
    readings = readings or {}
    if hour == 0:
        return readings.get("soc_pct_minuit")
    by_hour = readings.get("soc_pct_fin_heure") or {}
    return by_hour.get(hour - 1, by_hour.get(str(hour - 1)))
