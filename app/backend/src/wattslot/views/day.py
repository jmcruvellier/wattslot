"""Vue d'un jour : Hier, Aujourd'hui ou Demain (lot 5.1).

Séries horaires prévues et réelles, résumé de fin de journée (courbe recalée sur le réel et
prévision du premier calcul du jour), horodatages. La frise, les bandeaux, les avertissements et
les explications viennent compléter la vue dans les PR suivantes du lot.
"""

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel

from wattslot.planning.recommendation import recommendation
from wattslot.views.banners import (
    Departure,
    DeviceExplanation,
    Freshness,
    Indicators,
    Notice,
    WeatherBanner,
    as_stored,
    departure,
    explanations,
    freshness,
    notices,
    tomorrow_departure,
    weather,
)
from wattslot.views.cards import Cards, build_cards
from wattslot.views.display import (
    BATTERY,
    Context,
    day_summary,
    displayed_soc,
    find_item,
    initial_forecast_summary,
    recalculated_production,
)
from wattslot.views.now import NextAction, Now
from wattslot.views.timeline import Timeline, build_timeline

Kind = Literal["yesterday", "today", "tomorrow"]


class HourPoint(BaseModel):
    """Une heure : prévu (plan) et réel (relevés), en kWh sur l'heure ; SoC en fin d'heure."""

    hour: int
    off_peak: bool
    production_kwh: float
    consumption_kwh: float  # consommation de base et équipements prévus
    grid_import_kwh: float
    grid_export_kwh: float
    battery_charge_kwh: float
    battery_discharge_kwh: float
    soc_percent: float | None  # courbe affichée : recalée sur le réel quand il existe
    production_actual_kwh: float | None = None
    consumption_actual_kwh: float | None = None
    grid_import_actual_kwh: float | None = None
    grid_export_actual_kwh: float | None = None
    soc_actual_percent: float | None = None


class DaySummary(BaseModel):
    """Fin de journée : SoC final et maximal (et son heure), énergies de la journée."""

    soc_end_kwh: float
    soc_end_percent: float
    soc_max_kwh: float
    soc_max_percent: float
    soc_max_hour: int
    charge_kwh: float
    discharge_kwh: float
    grid_import_kwh: float
    grid_export_kwh: float
    production_kwh: float


# Clés du résumé de la v1 (``prevision_initiale`` gardée dans le plan du jour).
_V1_SUMMARY = {
    "soc_final_kwh": "soc_end_kwh",
    "soc_final_pct": "soc_end_percent",
    "soc_max_kwh": "soc_max_kwh",
    "soc_max_pct": "soc_max_percent",
    "heure_soc_max": "soc_max_hour",
    "charge_total": "charge_kwh",
    "decharge_total": "discharge_kwh",
    "soutire_total": "grid_import_kwh",
    "injecte_total": "grid_export_kwh",
    "production_totale": "production_kwh",
}


def stored_initial_forecast(state: Mapping[str, Any]) -> dict[str, Any]:
    """Prévision du premier calcul du jour, gardée dans le plan au format de la v1
    (``prevision_initiale``, ``resume_prevision_initiale`` de la v1)."""
    summary = initial_forecast_summary(state)
    return {old: summary[new] for old, new in _V1_SUMMARY.items()}


def summary_from_v1(found: Mapping[str, Any] | None) -> DaySummary | None:
    if not found:
        return None
    return DaySummary.model_validate({new: found[old] for old, new in _V1_SUMMARY.items()})


class DayView(BaseModel):
    kind: Kind
    day: date
    computed_at: datetime | None = None  # dernier calcul de ce plan
    manual: bool = False  # calcul lancé à la main
    actual_updated_at: datetime | None = None  # dernier relevé des données réelles
    battery_capacity_kwh: float | None = None  # aucune : maison sans batterie
    battery_floor_percent: float | None = None  # plancher de décharge (graphique du SoC)
    hours: list[HourPoint]
    summary: DaySummary  # courbe affichée
    initial_forecast: DaySummary | None = None  # premier calcul du jour (Aujourd'hui, Hier)
    production_recalculated_kwh: float | None = None  # mesurée puis prévue (avec relevé)
    timeline: Timeline
    departure: Departure | None = None  # maison avec batterie
    weather: WeatherBanner
    solar: bool = True  # faux : maison sans installation solaire, ni carte Soleil ni bandeau
    # Heures dont une mesure impossible a été écartée (qualité des données) : un trou dans les
    # courbes, rien dans les totaux.
    discarded_hours: list[int] = []
    notices: list[Notice] = []
    freshness: Freshness | None = None
    indicators: Indicators | None = None
    objective: str = "cost"  # objectif du calcul : indicateur mis en avant
    explanations: list[DeviceExplanation] = []
    recommendation: str | None = None  # texte du plan, dans la langue demandée
    cards: Cards | None = None  # Aujourd'hui et Hier : estimé et mesuré au relevé
    # Aujourd'hui (lot 6b.3) : le moment et le prochain appareil à lancer, ajoutés par les routes.
    now: Now | None = None
    next_action: NextAction | None = None


def _value(values: Mapping[Any, Any] | None, h: int) -> float | None:
    if not values:
        return None
    found = values.get(h, values.get(str(h)))
    return None if found is None else round(float(found), 3)


def _datetime(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def build_day(
    state: Mapping[str, Any],
    kind: Kind,
    context: Context,
    lang: str = "fr",
    today_estimate_kwh: float | None = None,
) -> DayView:
    """Vue d'un plan gardé en base (format de la v1). Les données réelles du plan ne servent
    pas à la vue Demain ; ``today_estimate_kwh`` : production estimée d'aujourd'hui, comparée
    à celle de demain."""
    actual = None if kind == "tomorrow" else state.get("donnees_reelles_cache") or None
    planning = state.get("planning", [])
    battery = find_item(planning, BATTERY)
    curve = displayed_soc(state, actual, context)
    residual = state.get("residu_reseau_horaire", {}) or {}
    charge = [0.0] * 24
    discharge = [0.0] * 24
    for movement in battery.get("mouvements", []) if battery else []:
        (charge if movement["action"] == "charge" else discharge)[movement["heure"]] += movement[
            "energie_kwh"
        ]
    off_peak = context.off_peak_hours()
    soc_actual = (actual or {}).get("soc_pct_fin_heure") or (actual or {}).get("soc_pct_reel")
    hours = []
    for h in range(24):
        exchange = -round(_value(residual, h) or 0.0, 3)  # positif : acheté au réseau
        hours.append(
            HourPoint(
                hour=h,
                off_peak=off_peak[h],
                production_kwh=curve.production[h],
                consumption_kwh=round(curve.baseline.get(h, 0) + curve.planned.get(h, 0), 3),
                grid_import_kwh=round(max(exchange, 0), 3),
                grid_export_kwh=round(max(-exchange, 0), 3),
                battery_charge_kwh=round(charge[h], 3),
                battery_discharge_kwh=round(discharge[h], 3),
                soc_percent=curve.soc_percent[h] if battery else None,
                production_actual_kwh=_value((actual or {}).get("production_reelle_horaire"), h),
                consumption_actual_kwh=_value((actual or {}).get("consommation_reelle_horaire"), h),
                grid_import_actual_kwh=_value((actual or {}).get("reseau_reel_soutire_horaire"), h),
                grid_export_actual_kwh=_value((actual or {}).get("reseau_reel_injecte_horaire"), h),
                soc_actual_percent=_value(soc_actual, h),
            )
        )
    updated_at = _datetime((actual or {}).get("heure_maj_iso"))
    if kind == "yesterday":
        reference_hour = 24.0
    else:
        moment = (updated_at or datetime.now(context.zone)).astimezone(context.zone)
        reference_hour = moment.hour + moment.minute / 60
    timeline = build_timeline(
        state,
        actual,
        reference_hour,
        sum(curve.production),
        sum(point.consumption_kwh for point in hours),
        context,
    )
    execution = state.get("derniere_execution") or {}
    computed_at = _datetime(execution.get("heure_iso"))
    capacity = state.get("capacite_batterie_kwh", 1.0) or 1.0
    initial = battery.get("soc_initial_kwh", 0.0) if battery else 0.0
    if battery is None:
        start = None
    elif kind == "tomorrow":
        start = tomorrow_departure(state, capacity, initial, context)
    else:
        start = departure(state, actual, capacity, initial, context)
    indicators, explained = explanations(state, lang)
    summary = day_summary(state, curve.soc_percent)
    cards = None
    if kind != "tomorrow":
        cards = build_cards(
            state,
            actual,
            kind,
            reference_hour,
            curve.soc_percent,
            {
                "charge": [p.battery_charge_kwh for p in hours],
                "discharge": [p.battery_discharge_kwh for p in hours],
                "grid_import": [p.grid_import_kwh for p in hours],
                "grid_export": [p.grid_export_kwh for p in hours],
                "production": [p.production_kwh for p in hours],
            },
            {old: summary[new] for old, new in _V1_SUMMARY.items()},
            state.get("prevision_initiale"),
            battery,
        )
    day = state.get("date_cible")
    return DayView(
        kind=kind,
        day=day if isinstance(day, date) else date.fromisoformat(str(day)),
        computed_at=computed_at,
        manual=bool(execution.get("manuel")),
        actual_updated_at=_datetime((actual or {}).get("heure_maj_iso")),
        battery_capacity_kwh=state.get("capacite_batterie_kwh") if battery else None,
        battery_floor_percent=context.battery.floor_percent if battery else None,
        hours=hours,
        summary=DaySummary.model_validate(summary),
        initial_forecast=summary_from_v1(state.get("prevision_initiale"))
        if kind != "tomorrow"
        else None,
        production_recalculated_kwh=recalculated_production(curve.production, actual),
        timeline=timeline,
        departure=start,
        weather=weather(state, actual, curve.production, kind, today_estimate_kwh),
        solar=context.solar,
        notices=notices(state, kind, lang),
        freshness=freshness(computed_at, kind, datetime.now(context.zone)),
        indicators=indicators,
        objective=context.objective,
        explanations=explained,
        recommendation=recommendation(as_stored(state), lang) if state.get("planning") else None,
        cards=cards,
    )
