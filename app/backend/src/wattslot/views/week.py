"""Vue Semaine (lot 5.1, PR 4) : demain et les jours suivants de l'horizon, précédés d'aujourd'hui
quand il est la veille du premier jour.

Reprend ``dashboard_semaine.py`` de la v1 : carte de chaque jour (``resume_jour``), séries
horaires bout à bout (``series_horaires``), aujourd'hui recalé sur le réel comme dans sa vue
(``_recaler_aujourdhui``), demain à jour (``avec_demain_a_jour``) et ligne du dernier relevé
(``_indice_releve``).
"""

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel

from wattslot.views.banners import Notice, notices, weather_quality
from wattslot.views.display import (
    BATTERY,
    Context,
    displayed_soc,
    find_item,
    planned_devices_hourly,
    recalculated_production,
)


class PlannedDevice(BaseModel):
    device: str
    start_min: int
    end_min: int


class WeekDay(BaseModel):
    day: date
    detail_view: Literal["today", "tomorrow"] | None = None  # vue détaillée de ce jour
    production_kwh: float
    weather: Literal["sunny", "mixed", "cloudy"] | None = None
    soc_start_percent: float | None = None
    soc_end_percent: float | None = None
    soc_max_percent: float | None = None
    grid_import_kwh: float
    grid_import_peak_kwh: float  # en heures pleines
    grid_export_kwh: float
    devices: list[PlannedDevice]
    notices: list[Notice] = []


class WeekPoint(BaseModel):
    day: date
    hour: int
    off_peak: bool
    soc_percent: float | None
    soc_kwh: float | None
    production_kwh: float
    consumption_kwh: float


class WeekView(BaseModel):
    computed_at: datetime | None = None
    manual: bool = False
    seconds: float | None = None  # durée du calcul de l'horizon
    days: list[WeekDay]
    points: list[WeekPoint]  # une heure par point, tous jours bout à bout
    floor_percent: float  # plancher de décharge de la batterie
    now_index: float | None = None  # position du dernier relevé sur l'axe des points
    notices: list[Notice] = []  # avertissements du calcul de l'horizon
    waiting_not_assigned: bool = False  # tâches en attente sans affectation à un jour


def _as_date(value: Any) -> Any:
    return date.fromisoformat(value) if isinstance(value, str) else value


def _with_date(state: Mapping[str, Any]) -> dict[str, Any]:
    return {**state, "date_cible": _as_date(state.get("date_cible"))}


def _off_peak(hour: int, context: Context) -> bool:
    return any(start <= hour < end for start, end in context.off_peak)


def _value(values: Mapping[Any, Any], h: Any) -> float | None:
    found = values.get(h, values.get(str(h)))
    return None if found is None else float(found)


def day_summary(state: Mapping[str, Any], context: Context) -> dict[str, Any]:
    """Chiffres d'un jour (``resume_jour``)."""
    planning = state.get("planning", [])
    battery = find_item(planning, BATTERY) or {}
    capacity = state.get("capacite_batterie_kwh") or 0

    def percent(kwh: float | None) -> float | None:
        return kwh / capacity * 100 if capacity and kwh is not None else None

    residual = state.get("residu_reseau_horaire", {}) or {}
    soc_by_hour = battery.get("soc_horaire_kwh", {}) or {}
    return {
        "date": state["date_cible"],
        "production_kwh": sum((state.get("production_solaire_horaire") or {}).values()),
        "soc_debut_pct": percent(battery.get("soc_initial_kwh")),
        "soc_fin_pct": percent(battery.get("soc_final_kwh")),
        "soc_max_pct": percent(max(soc_by_hour.values())) if soc_by_hour else None,
        "soutirage_kwh": -sum(v for v in residual.values() if v < 0),
        "soutirage_hp_kwh": -sum(
            v for h, v in residual.items() if v < 0 and not _off_peak(int(h), context)
        ),
        "injection_kwh": sum(v for v in residual.values() if v > 0),
        "equipements": sorted(
            (i for i in planning if "debut_min" in i and "fin_min" in i),
            key=lambda i: i["debut_min"],
        ),
        "avertissements": state.get("avertissements", []),
    }


def hourly_points(days: Sequence[Mapping[str, Any]], context: Context) -> list[dict[str, Any]]:
    """Points des courbes (``series_horaires``) : SoC prévu, production prévue, consommation de
    base et équipements prévus de chaque jour."""
    points = []
    for state in days:
        battery = find_item(state.get("planning", []), BATTERY) or {}
        capacity = state.get("capacite_batterie_kwh") or 0
        soc = battery.get("soc_horaire_kwh", {}) or {}
        production = state.get("production_solaire_horaire", {}) or {}
        baseline = state.get("consommation_baseline_horaire", {}) or {}
        devices = planned_devices_hourly(state.get("planning", []), None, context)
        for h in range(24):
            kwh = _value(soc, h)
            points.append(
                {
                    "jour": state["date_cible"],
                    "heure": h,
                    "creuse": _off_peak(h, context),
                    "pct": round(kwh / capacity * 100, 1) if kwh is not None and capacity else None,
                    "kwh": round(kwh, 2) if kwh is not None else None,
                    "production": round(_value(production, h) or 0.0, 3),
                    "consommation": round((_value(baseline, h) or 0.0) + devices.get(h, 0.0), 3),
                }
            )
    return points


def realign_today(
    state: Mapping[str, Any],
    summary: dict[str, Any],
    points: list[dict[str, Any]],
    context: Context,
) -> None:
    """Aujourd'hui comme dans sa vue (``_recaler_aujourdhui``) : SoC recalé sur le réel,
    consommation recalée sur les cycles réels, production recalée. Modifie en place."""
    actual = state.get("donnees_reelles_cache")
    curve = displayed_soc(state, actual, context)
    capacity = state.get("capacite_batterie_kwh") or 0
    for h, (point, percent) in enumerate(zip(points, curve.soc_percent, strict=False)):
        point["consommation"] = round(curve.baseline.get(h, 0) + curve.planned.get(h, 0), 3)
        point["pct"] = percent
        point["kwh"] = round(percent / 100 * capacity, 2) if capacity else point["kwh"]
    summary["soc_fin_pct"] = curve.soc_percent[-1]
    summary["soc_max_pct"] = max(curve.soc_percent)
    recalculated = recalculated_production(curve.production, actual)
    summary["production_kwh"] = recalculated if recalculated is not None else sum(curve.production)


def with_tomorrow_up_to_date(
    horizon: Mapping[str, Any], tomorrow: Mapping[str, Any] | None
) -> dict[str, Any]:
    """J+1 de la semaine : la prévision de la vue Demain, plus récente (``avec_demain_a_jour``).

    L'horizon de la v2 commence au lendemain de demain (``runner.py`` n'y garde que J+2…J+6) :
    demain y est alors ajouté en tête. Un horizon au format de la v1, qui commence à demain, voit
    son premier jour remplacé."""
    days = list(horizon.get("jours") or [])
    if not days or not tomorrow:
        return dict(horizon)
    day, first = _as_date(tomorrow.get("date_cible")), _as_date(days[0].get("date_cible"))
    if isinstance(day, date) and isinstance(first, date) and day == first - timedelta(days=1):
        return {**horizon, "jours": [tomorrow, *days]}
    if day != first:
        return dict(horizon)
    return {**horizon, "jours": [tomorrow, *days[1:]]}


def reading_index(state: Mapping[str, Any], context: Context) -> float | None:
    """Position du dernier relevé sur l'axe des points (``_indice_releve``)."""
    iso = (state.get("donnees_reelles_cache") or {}).get("heure_maj_iso")
    if not iso:
        return None
    try:
        moment = datetime.fromisoformat(iso).astimezone(context.zone)
    except (TypeError, ValueError):
        return None
    if moment.date() != _as_date(state.get("date_cible")):
        return None
    return round(max(0.0, moment.hour + moment.minute / 60 - 1), 3)


def build_week(
    horizon: Mapping[str, Any],
    tomorrow: Mapping[str, Any] | None,
    today: Mapping[str, Any] | None,
    context: Context,
    lang: str = "fr",
) -> WeekView:
    content = with_tomorrow_up_to_date(horizon, tomorrow)
    horizon_days = [_with_date(d) for d in content.get("jours") or []]
    first = horizon_days[0] if horizon_days else {}
    today_state = _with_date(today) if today else None
    with_today = bool(
        today_state
        and first
        and today_state.get("date_cible") == first["date_cible"] - timedelta(days=1)
    )
    days = ([today_state] if with_today and today_state else []) + horizon_days
    summaries = [day_summary(d, context) for d in days]
    points = hourly_points(days, context)
    if with_today and today_state:
        realign_today(today_state, summaries[0], points[:24], context)
    best = first.get("production_max_recente") or (today or {}).get("production_max_recente") or {}
    views: list[Literal["today", "tomorrow"]] = (
        (["today", "tomorrow"] if with_today else ["tomorrow"]) if horizon_days else []
    )
    week_days = [
        WeekDay(
            day=s["date"],
            detail_view=views[i] if i < len(views) else None,
            production_kwh=round(s["production_kwh"], 3),
            weather=weather_quality(s["production_kwh"], best.get("max_kwh")),
            soc_start_percent=_round(s["soc_debut_pct"]),
            soc_end_percent=_round(s["soc_fin_pct"]),
            soc_max_percent=_round(s["soc_max_pct"]),
            grid_import_kwh=round(s["soutirage_kwh"], 3),
            grid_import_peak_kwh=round(s["soutirage_hp_kwh"], 3),
            grid_export_kwh=round(s["injection_kwh"], 3),
            devices=[
                PlannedDevice(
                    device=i["equipement"], start_min=i["debut_min"], end_min=i["fin_min"]
                )
                for i in s["equipements"]
            ],
            notices=notices({"avertissements": s["avertissements"]}, "week", lang),
        )
        for i, s in enumerate(summaries)
    ]
    execution = content.get("derniere_execution") or {}
    computed_at = execution.get("heure_iso")
    return WeekView(
        computed_at=datetime.fromisoformat(computed_at) if isinstance(computed_at, str) else None,
        manual=bool(execution.get("manuel")),
        seconds=content.get("duree_s"),
        days=week_days,
        points=[
            WeekPoint(
                day=p["jour"],
                hour=p["heure"],
                off_peak=p["creuse"],
                soc_percent=p["pct"],
                soc_kwh=p["kwh"],
                production_kwh=p["production"],
                consumption_kwh=p["consommation"],
            )
            for p in points
        ],
        floor_percent=context.battery.floor_percent,
        now_index=reading_index(today_state, context) if with_today and today_state else None,
        notices=notices({"avertissements": content.get("avertissements", [])}, "week", lang),
        waiting_not_assigned=bool(first.get("taches_en_attente") and not first.get("affectations")),
    )


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 1)
