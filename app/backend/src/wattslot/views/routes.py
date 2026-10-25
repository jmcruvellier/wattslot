"""Routes des vues (lot 5.1) : ``/api/views/{yesterday|today|tomorrow}``.

Comme le dashboard de la v1, une vue ne déclenche jamais de calcul : elle lit le plan gardé en
base, avec le contexte de la maison au moment de la lecture.
"""

import asyncio
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from wattslot import configuration, home_model, notifications, quality, reminders
from wattslot.corrections import CorrectionStore
from wattslot.languages import language_of
from wattslot.objective_settings import Preset
from wattslot.planning.engine import Objective
from wattslot.planning.journal import cycle_appliances
from wattslot.planning.sources import has_production, load_settings
from wattslot.planning.store import PlanStore
from wattslot.tariff import off_peak_ranges
from wattslot.views.day import DayView, build_day
from wattslot.views.display import Context, recalculated_production
from wattslot.views.now import measure_now, next_action
from wattslot.views.week import WeekView, build_week

router = APIRouter()

DayKind = Literal["yesterday", "today", "tomorrow"]


def filtration_speeds(
    home: home_model.HomeModel, saved: configuration.Configuration
) -> dict[str, float] | None:
    """Vitesses réglées de la première durée à placer prise en compte ; ``None`` sans vitesse
    réglée (celles de la v1)."""
    for settings in configuration.effective(home, saved).devices:
        if settings.planned and settings.behavior is configuration.Behavior.RUNTIME:
            if settings.runtime is not None and settings.runtime.speeds:
                return {s.name: s.kw for s in settings.runtime.speeds}
            return None
    return None


def runtime_keys(home: home_model.HomeModel, saved: configuration.Configuration) -> set[str]:
    return configuration.keys_with(home, saved, frozenset({configuration.Behavior.RUNTIME}))


# Réglage du calcul d'avant le lot 3.6, quand la configuration n'a pas d'objectif.
FALLBACK_PRESETS = {
    Objective.COST: Preset.COST,
    Objective.IMPORT: Preset.AUTONOMY,
    Objective.SELF_CONSUMPTION: Preset.SELF_CONSUMPTION,
    Objective.CO2: Preset.CO2,
}


def objective_of(state: Any, saved: configuration.Configuration) -> Preset:
    """Objectif du calcul : celui de la configuration, sinon le réglage du calcul."""
    if saved.objective is not None:
        return saved.objective.preset
    return FALLBACK_PRESETS[load_settings(state.database).objective]


def _plausible(state: Any, content: Mapping[str, Any]) -> tuple[dict[str, Any], list[int]]:
    """Plan gardé avec les corrections en vigueur (Ma maison, onglet Données) appliquées à ses
    mesures horaires, puis sans ses mesures impossibles (qualité des données) : « Estimer » ou
    « Recalculer depuis le brut » comble le trou des courbes, « Écarter » le laisse."""
    home = home_model.load(state.graph)
    limit = quality.house_limit_kwh(home, configuration.load(state.graph))
    corrected = quality.corrected_actual(
        content, CorrectionStore(state.database).list(), home, state.raw.zone
    )
    return quality.plausible_actual(corrected, limit)


def house_context(state: Any, day: date) -> Context:
    """Contexte de la maison pour le jour affiché (heures creuses de ce jour) ; ``state`` :
    l'état de l'application (``app.state``)."""
    saved = configuration.load(state.graph)
    home = home_model.load(state.graph)
    context = Context(
        zone=state.raw.zone,
        off_peak=tuple(off_peak_ranges(configuration.tariff_of(saved), day)),
        battery=configuration.battery_of(saved),
        appliances=tuple(
            a.name for a in cycle_appliances(home, saved) if a.key not in runtime_keys(home, saved)
        ),
        objective=objective_of(state, saved).value,
        solar=has_production(home),
        tariff=configuration.tariff_of(saved),
    )
    speeds = filtration_speeds(home, saved)
    return replace(context, pool_speeds=speeds) if speeds is not None else context


class Versions(BaseModel):
    """Heure (horodatage) du dernier calcul de chaque vue ; la page recharge la sienne quand
    elle change. Semaine : la plus récente de l'horizon, du jour et de demain."""

    yesterday: float | None = None
    today: float | None = None
    tomorrow: float | None = None
    week: float | None = None


@router.get("/api/views/versions")
def view_versions(request: Request) -> Versions:
    store = PlanStore(request.app.state.database)
    found = {kind: store.load(kind) for kind in ("yesterday", "today", "tomorrow", "horizon")}
    stamps = {k: p.computed_at.timestamp() if p is not None else None for k, p in found.items()}
    week = [v for k, v in stamps.items() if k in ("horizon", "today", "tomorrow") and v is not None]
    return Versions(
        yesterday=stamps["yesterday"],
        today=stamps["today"],
        tomorrow=stamps["tomorrow"],
        week=max(week) if week else None,
    )


async def week_view_of(state: Any, lang: str = "fr") -> WeekView | None:
    """Vue Semaine, ``None`` sans horizon (aussi pour le serveur MCP, lot 6.1)."""
    store = PlanStore(state.database)
    horizon = store.load("horizon")
    if horizon is None:
        return None
    today, tomorrow = store.load("today"), store.load("tomorrow")
    context = house_context(state, today.day if today else datetime.now(UTC).date())
    # Les heures impossibles du jour sont écartées de la semaine comme de sa vue, et servent
    # au message « Mesure impossible écartée » de l'onglet Semaine (mesures plus anciennes : rien).
    today_content, today_discarded = (
        _plausible(state, today.content) if today is not None else (None, [])
    )
    return await asyncio.to_thread(
        build_week,
        horizon.content,
        tomorrow.content if tomorrow else None,
        today_content,
        context,
        language_of(lang),
        today_discarded,
    )


async def day_view_of(state: Any, kind: DayKind, lang: str = "fr") -> DayView | None:
    """Vue d'un jour, ``None`` sans plan (aussi pour le serveur MCP, lot 6.1)."""
    plan = PlanStore(state.database).load(kind)
    if plan is None:
        return None
    context = house_context(state, plan.day)
    content, discarded = _plausible(state, plan.content)
    today_estimate = None
    if kind == "tomorrow":
        today = PlanStore(state.database).load("today")
        if today is not None and today.day == plan.day - timedelta(days=1):
            production = [
                round(float(today.content.get("production_solaire_horaire", {}).get(h, 0)), 3)
                for h in range(24)
            ]
            recalculated = recalculated_production(
                production, _plausible(state, today.content)[0].get("donnees_reelles_cache")
            )
            today_estimate = recalculated if recalculated is not None else sum(production)
    language = language_of(lang)
    view = await asyncio.to_thread(build_day, content, kind, context, language, today_estimate)
    view = view.model_copy(update={"discarded_hours": discarded})
    if kind != "today":
        return view
    # Aujourd'hui (lot 6b.3) : le moment, d'après les agrégats, et le prochain appareil à lancer.
    moment = datetime.now(UTC)
    explanations = {e.device: e.text for e in view.explanations}
    details = {e.device: e.explanation for e in view.explanations}
    action = next_action(view.timeline, explanations, moment, context, details)
    if action is not None:
        action = action.model_copy(
            update={
                "reminder": action.device in reminders.pending(state.database, plan.day),
                "can_remind": notifications.load(state.database).service_of("device_now")
                is not None,
            }
        )
    return view.model_copy(
        update={
            "now": await asyncio.to_thread(measure_now, state, moment, context, language),
            "next_action": action,
        }
    )


@router.get("/api/views/week")
async def week_view(request: Request, lang: str = "fr") -> WeekView:
    """Vue Semaine : les 7 jours de l'horizon, précédés d'aujourd'hui ; 404 sans horizon."""
    found = await week_view_of(request.app.state, lang)
    if found is None:
        raise HTTPException(status_code=404, detail="no_plan")
    return found


@router.get("/api/views/{kind}")
async def day_view(request: Request, kind: DayKind, lang: str = "fr") -> DayView:
    """Vue d'un jour : séries prévues et réelles, résumé de fin de journée ; 404 sans plan."""
    found = await day_view_of(request.app.state, kind, lang)
    if found is None:
        raise HTTPException(status_code=404, detail="no_plan")
    return found
