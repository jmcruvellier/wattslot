"""Frise des équipements d'une vue (lot 5.1, PR 2) : barres prévues et réelles, bilan des
équipements (à l'heure, décalé, aucun cycle, hors planning).

Reprend ``_construire_lignes_gantt`` et ``_equipements_prevus`` de la v1 (Python) ainsi que
``afficherEquipementsReels`` et ``majBandeauEquipements`` (JavaScript de la page, exécuté dans le
navigateur), désormais calculés côté serveur.
"""

import math
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from wattslot.views.display import BATTERY, Context, find_item, is_runtime

SHIFT_MIN = 15  # écart de démarrage toléré (« à l'heure »)
ENERGY_GAP_PERCENT = 10  # écart d'énergie signalé au-delà
CYCLE_FRACTION = 0.3  # part de l'énergie prévue pour reconnaître un cycle


class Bar(BaseModel):
    start_hour: float  # heures depuis minuit, fractionnaires
    end_hour: float
    energy_kwh: float
    action: Literal["charge", "discharge"] | None = None  # batterie
    mode: str | None = None  # vitesse de la filtration


class TimelineRow(BaseModel):
    device: str  # nom de l'équipement dans le plan
    kind: Literal["battery", "cycle", "runtime"]
    planned: list[Bar]
    actual: list[Bar]


class DeviceStatus(BaseModel):
    """Bilan d'un équipement prévu, au dernier relevé."""

    device: str
    status: Literal["on_time", "shifted", "no_cycle", "planned"]
    planned_start_min: int
    planned_end_min: int
    planned_kwh: float
    actual_start_min: int | None = None
    actual_kwh: float | None = None
    running: bool = False
    energy_gap_percent: int | None = None  # au-delà de 10 %, cycle terminé seulement
    shift_min: int | None = None  # démarrage réel moins prévu


class Unplanned(BaseModel):
    """Équipement qui a tourné sans être prévu."""

    device: str
    start_min: int
    energy_kwh: float


class Timeline(BaseModel):
    rows: list[TimelineRow]  # lignes sans barre prévue ni réelle masquées
    empty: Literal["no_surplus", "nothing"] | None = None  # aucune barre prévue
    production_kwh: float  # prévue, pour le message d'une frise vide
    consumption_kwh: float
    statuses: list[DeviceStatus]
    unplanned: list[Unplanned]
    badge: Literal["on_time", "shifted"] | None = None  # au moins un équipement jugé
    cancelled: list[str] = []  # planifications annulées pour aujourd'hui (Aujourd'hui seule)


def _js_round(value: float) -> int:
    """``Math.round`` du JavaScript (demi vers le haut), pour les mêmes nombres que la page."""
    return math.floor(value + 0.5)


def battery_blocks(movements: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Mouvements horaires regroupés en blocs contigus de même action
    (``_grouper_mouvements_batterie`` de la v1)."""
    if not movements:
        return []
    ordered = sorted(movements, key=lambda m: m["heure"])
    blocks = [
        {
            "debut": ordered[0]["heure"],
            "fin": ordered[0]["heure"] + 1,
            "action": ordered[0]["action"],
            "energie_kwh": ordered[0]["energie_kwh"],
        }
    ]
    for movement in ordered[1:]:
        last = blocks[-1]
        if movement["action"] == last["action"] and movement["heure"] == last["fin"]:
            last["fin"] = movement["heure"] + 1
            last["energie_kwh"] += movement["energie_kwh"]
        else:
            blocks.append(
                {
                    "debut": movement["heure"],
                    "fin": movement["heure"] + 1,
                    "action": movement["action"],
                    "energie_kwh": movement["energie_kwh"],
                }
            )
    return blocks


def cycle_bounds(item: Mapping[str, Any]) -> tuple[int, int]:
    """(début, fin) du cycle en minutes (``bornes_minutes`` de la v1)."""
    cycle_min = item.get("duree_cycle_min") or (item["heure_fin"] - item["heure_debut"]) * 60
    start = item.get("debut_min", item["heure_debut"] * 60)
    return start, item.get("fin_min", min(24 * 60, start + round(cycle_min)))


def planned_devices(
    planning: Sequence[Mapping[str, Any]], context: Context
) -> list[dict[str, Any]]:
    """Équipements prévus (créneau en minutes et énergie), la filtration résumée de son premier
    à son dernier segment (``_equipements_prevus`` de la v1)."""
    found = []
    for item in planning:
        name = item["equipement"]
        if name == BATTERY:
            continue
        if is_runtime(item):
            segments = [s for s in item.get("segments", []) if s["mode"] != "off"]
            if not segments:
                continue
            energy = sum(
                (s["heure_fin"] - s["heure_debut"]) * context.speed_kw(s["mode"]) for s in segments
            )
            start = min(s["heure_debut"] for s in segments) * 60
            end = max(s["heure_fin"] for s in segments) * 60
        else:
            start, end = cycle_bounds(item)
            energy = item.get("energie_kwh", 0.0)
        found.append(
            {"nom": name, "debut_min": start, "fin_min": end, "energie_kwh": round(energy, 3)}
        )
    return sorted(found, key=lambda p: p["debut_min"])


def _local(iso: str, context: Context) -> datetime:
    moment = datetime.fromisoformat(iso)
    return moment.astimezone(context.zone) if moment.tzinfo else moment


def _minutes(iso: str, context: Context) -> int:
    moment = _local(iso, context)
    return moment.hour * 60 + moment.minute


def _hours(iso: str, context: Context) -> float:
    moment = _local(iso, context)
    return moment.hour + moment.minute / 60 + moment.second / 3600


def _actual_bars(segments: Sequence[Mapping[str, Any]], context: Context) -> list[Bar]:
    bars = []
    for segment in segments:
        try:
            start, end = _hours(segment["debut_iso"], context), _hours(segment["fin_iso"], context)
        except (KeyError, TypeError, ValueError):
            continue
        action = {"charge": "charge", "decharge": "discharge"}.get(segment.get("action", ""))
        bars.append(
            Bar(
                start_hour=round(start, 4),
                end_hour=round(end, 4),
                energy_kwh=round(segment.get("energie_kwh", 0.0), 3),
                action=action,  # type: ignore[arg-type]
                mode=segment.get("mode"),
            )
        )
    return bars


def statuses(
    planned: Sequence[Mapping[str, Any]],
    actual: Mapping[str, Any] | None,
    reference_hour: float,
    runtime_names: set[str],
    context: Context,
) -> tuple[list[DeviceStatus], list[Unplanned], str | None]:
    """Bilan des équipements prévus au dernier relevé (``majBandeauEquipements`` de la v1)."""
    measured = (actual or {}).get("equipements_reels_horaire") or {}
    now_min = reference_hour * 60
    found: list[DeviceStatus] = []
    judged = shifted = 0
    for plan in planned:
        segments = measured.get(plan["nom"]) or []
        cycle: dict[str, Any] | None = None
        if plan["nom"] in runtime_names:
            if segments:
                cycle = {
                    "start": _minutes(segments[0]["debut_iso"], context),
                    "kwh": sum(s.get("energie_kwh") or 0 for s in segments),
                    "running": any(s.get("en_cours") for s in segments),
                }
        else:
            recognized = [
                s
                for s in segments
                if (
                    (s.get("energie_kwh") or 0) >= CYCLE_FRACTION * plan["energie_kwh"]
                    and (s.get("energie_kwh") or 0) > 0
                )
                or s.get("en_cours")
            ]
            recognized.sort(
                key=lambda s: abs(_minutes(s["debut_iso"], context) - plan["debut_min"])
            )
            if recognized:
                cycle = {
                    "start": _minutes(recognized[0]["debut_iso"], context),
                    "kwh": recognized[0].get("energie_kwh") or 0,
                    "running": bool(recognized[0].get("en_cours")),
                }
        common = {
            "device": plan["nom"],
            "planned_start_min": plan["debut_min"],
            "planned_end_min": plan["fin_min"],
            "planned_kwh": plan["energie_kwh"],
        }
        if cycle is not None:
            judged += 1
            gap = cycle["start"] - plan["debut_min"]
            percent = None
            if not cycle["running"] and plan["energie_kwh"] > 0:
                value = _js_round((cycle["kwh"] - plan["energie_kwh"]) / plan["energie_kwh"] * 100)
                percent = value if abs(value) > ENERGY_GAP_PERCENT else None
            on_time = abs(gap) <= SHIFT_MIN
            shifted += 0 if on_time else 1
            found.append(
                DeviceStatus(
                    **common,
                    status="on_time" if on_time else "shifted",
                    actual_start_min=cycle["start"],
                    actual_kwh=round(cycle["kwh"], 3),
                    running=cycle["running"],
                    energy_gap_percent=percent,
                    shift_min=None if on_time else gap,
                )
            )
        elif actual and now_min >= plan["fin_min"]:
            judged += 1
            shifted += 1
            found.append(DeviceStatus(**common, status="no_cycle"))
        else:
            found.append(DeviceStatus(**common, status="planned"))
    names = {p["nom"] for p in planned}
    unplanned = [
        Unplanned(
            device=name,
            start_min=_minutes(segments[0]["debut_iso"], context),
            energy_kwh=round(sum(s.get("energie_kwh") or 0 for s in segments), 3),
        )
        for name, segments in measured.items()
        if name not in names and segments
    ]
    badge = None if not judged else ("shifted" if shifted else "on_time")
    return found, unplanned, badge


def build_timeline(
    state: Mapping[str, Any],
    actual: Mapping[str, Any] | None,
    reference_hour: float,
    production_kwh: float,
    consumption_kwh: float,
    context: Context,
) -> Timeline:
    """Frise d'un plan ; ``reference_hour`` : heure du dernier relevé (24 pour Hier)."""
    planning = state.get("planning", [])
    measured = dict((actual or {}).get("equipements_reels_horaire") or {})
    rows: list[TimelineRow] = []
    battery = find_item(planning, BATTERY)
    if battery is not None:
        planned_bars = [
            Bar(
                start_hour=b["debut"],
                end_hour=b["fin"],
                energy_kwh=round(b["energie_kwh"], 3),
                action="charge" if b["action"] == "charge" else "discharge",
            )
            for b in battery_blocks(battery.get("mouvements", []))
        ]
        rows.append(
            TimelineRow(
                device=BATTERY,
                kind="battery",
                planned=planned_bars,
                actual=_actual_bars((actual or {}).get("batterie_reelle_segments") or [], context),
            )
        )
    rendered = set()
    for item in planning:
        if item["equipement"] == BATTERY or is_runtime(item):
            continue
        start, end = cycle_bounds(item)
        rows.append(
            TimelineRow(
                device=item["equipement"],
                kind="cycle",
                planned=[
                    Bar(
                        start_hour=start / 60,
                        end_hour=end / 60,
                        energy_kwh=round(item.get("energie_kwh", 0.0), 3),
                    )
                ],
                actual=_actual_bars(measured.get(item["equipement"]) or [], context),
            )
        )
        rendered.add(item["equipement"])
    runtimes = [item for item in planning if is_runtime(item)]
    runtime_names = {item["equipement"] for item in runtimes}
    for name in context.appliances:
        if name not in rendered and name not in runtime_names:
            rows.append(
                TimelineRow(
                    device=name,
                    kind="cycle",
                    planned=[],
                    actual=_actual_bars(measured.get(name) or [], context),
                )
            )
    for item in runtimes:
        bars = [
            Bar(
                start_hour=s["heure_debut"],
                end_hour=s["heure_fin"],
                energy_kwh=round(
                    (s["heure_fin"] - s["heure_debut"]) * context.speed_kw(s["mode"]), 3
                ),
                mode=s["mode"],
            )
            for s in item.get("segments", [])
            if s["mode"] != "off"
        ]
        rows.append(
            TimelineRow(
                device=item["equipement"],
                kind="runtime",
                planned=bars,
                actual=_actual_bars(measured.get(item["equipement"]) or [], context),
            )
        )
    any_planned = any(row.planned for row in rows)
    empty = None
    if not any_planned:
        empty = "no_surplus" if production_kwh < consumption_kwh else "nothing"
    found, unplanned, badge = statuses(
        planned_devices(planning, context), actual, reference_hour, runtime_names, context
    )
    return Timeline(
        rows=[row for row in rows if row.planned or row.actual],
        empty=empty,  # type: ignore[arg-type]
        production_kwh=round(production_kwh, 3),
        consumption_kwh=round(consumption_kwh, 3),
        statuses=found,
        unplanned=unplanned,
        badge=badge,  # type: ignore[arg-type]
    )
