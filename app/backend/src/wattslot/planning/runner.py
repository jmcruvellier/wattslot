"""Un calcul complet, comme ``/planifier`` de la v1 : le jour, puis demain et l'horizon.

1. **Bascule** : si le plan gardé porte sur la veille, ses données réelles sont complétées
   jusqu'à minuit, puis il est archivé (vue Hier).
2. **Le jour** : entrée assemblée (``assemble.py``), complétée par le plan précédent de la
   journée : blocs déjà décidés (gelés), filtration déjà planifiée, SoC de départ de l'heure en
   cours (``merge.start_soc``), charge complète atteinte aujourd'hui ; tâches en attente
   affectées à un jour (``assignment.py``, mémoire d'un calcul à l'autre) ; plan du moteur,
   fusionné avec le passé du plan précédent (``merge.py``) ; données réelles depuis minuit
   (``actual.py``), superposées au plan par le dashboard.
3. **Demain** : part du SoC prévu en fin de journée ; **horizon** : jours suivants enchaînés
   (``horizon.py``). Un échec de demain ou de l'horizon n'annule pas le plan du jour.

Les plans sont gardés en base au format de la v1 (``store.py``), lus par le dashboard, avec
ce qu'il affiche en plus du plan : meilleure production des 30 derniers jours, prévision
initiale de la journée (premier calcul du jour), SoC de départ prévu la veille avant 18 h,
dernière exécution.
"""

import logging
import sqlite3
import time
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from datetime import time as day_time
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from wattslot import user_requests
from wattslot.aggregation import HOUR, QUARTER
from wattslot.configuration import Configuration
from wattslot.detection import DeviceKind, Role
from wattslot.home_assistant import HomeAssistantClient
from wattslot.home_model import HomeModel
from wattslot.objective_settings import Preset
from wattslot.planning import capture, choices, open_meteo, past
from wattslot.planning.actual import actual_day
from wattslot.planning.assemble import build_input, to_v1
from wattslot.planning.assignment import decide, launched_keys
from wattslot.planning.engine import (
    Goal,
    ImpossibleDataError,
    NoPlanError,
    Objective,
    Result,
    plan_day,
)
from wattslot.planning.horizon import DayForecast, compute_horizon, end_soc_kwh
from wattslot.planning.inputs import FrozenCycle, PlanningInput, RecentHistory
from wattslot.planning.journal import CycleJournal, cycle_appliances
from wattslot.planning.merge import BATTERY, POOL, merge_plans, pool_modes, start_soc
from wattslot.planning.past import AggregateReader
from wattslot.planning.plan import Plan
from wattslot.planning.problem import characteristics, from_input
from wattslot.planning.recommendation import recommendation
from wattslot.planning.sources import Forecasts, PlanningSettings, has_production
from wattslot.planning.store import PlanStore, StoredPlan
from wattslot.storage.raw import RawStores
from wattslot.views.day import stored_initial_forecast

logger = logging.getLogger(__name__)

ASSIGNMENT_DAYS = 3  # aujourd'hui et les 2 jours suivants (délai maximal d'une tâche)
FULL_CHARGE_PERCENT = 99.5
MIN_FILTRATION_KWH = 0.05
DEPARTURE_BEFORE_HOUR = 18  # départ de demain retenu s'il est prévu avant 18 h (v1)


class ImpossibleData(BaseModel):
    """Consommation de base impossible d'un jour, et le saut de compteur qui l'explique."""

    day: date
    hour: int
    consumption_kwh: float
    limit_kwh: float
    device: str | None = None  # capteur à l'origine ; None : pas retrouvé
    entity_id: str | None = None
    source_start: datetime | None = None  # heure locale du saut
    source_kwh: float | None = None
    until: date | None = None  # dernier jour dont la prévision en dépend

    def warning(self) -> dict[str, Any]:
        """Avertissement de l'horizon, à la place de « horizon_interrompu »."""
        params: dict[str, Any] = {
            "jour": self.day.isoformat(),
            "heure": self.hour,
            "kwh": self.consumption_kwh,
            "limite": self.limit_kwh,
        }
        if self.source_start is None:
            return {"code": "donnees_impossibles_sans_origine", "params": params}
        return {
            "code": "donnees_impossibles",
            "params": params
            | {
                "capteur": self.device,
                "entite": self.entity_id,
                "jour_source": self.source_start.date().isoformat(),
                "heure_source": self.source_start.hour,
                "kwh_source": self.source_kwh,
                "jour_fin": self.until.isoformat() if self.until else None,
            },
        }


@dataclass
class Context:
    client: HomeAssistantClient
    model: HomeModel
    reader: AggregateReader
    raw: RawStores
    database: sqlite3.Connection
    settings: PlanningSettings
    # Configuration enregistrée de la maison ; ``None`` : comme en phase 2 (toutes les
    # tâches, filtration planifiée).
    configuration: Configuration | None = None
    # Dossier des données : capture des problèmes sans plan (lot 7.3) ; ``None`` : sans capture.
    data_dir: Path | None = None

    def capture_no_plan(self, error: NoPlanError) -> None:
        if self.data_dir is not None:
            capture.save(self.data_dir, error)

    def impossible(self, error: ImpossibleDataError, today: date) -> ImpossibleData:
        """Le saut de compteur à l'origine d'une consommation impossible, s'il est retrouvé."""
        found = past.spike(
            self.model, self.reader, error.day, error.hour, today, self.raw.zone, error.limit_kwh
        )
        about = ImpossibleData(
            day=error.day,
            hour=error.hour,
            consumption_kwh=round(error.consumption_kwh, 1),
            limit_kwh=round(error.limit_kwh, 1),
        )
        if found is None:
            return about
        return about.model_copy(
            update={
                "device": found.device,
                "entity_id": found.entity_id,
                "source_start": found.start,
                "source_kwh": round(found.energy_kwh, 1),
                "until": found.start.date() + timedelta(days=7 * past.SAME_WEEKDAY_OCCURRENCES),
            }
        )


class RunReport(BaseModel):
    day: date
    started_at: datetime
    manual: bool
    seconds_today: float
    seconds_tomorrow: float | None = None
    seconds_horizon: float | None = None
    horizon_days: int = 0
    errors: list[str] = []
    # Jours non calculés à cause d'une consommation impossible (lot 7.3), avec son origine.
    impossible: list[ImpossibleData] = []


def frozen_cycles(old: Plan | None, first_hour: int) -> tuple[FrozenCycle, ...]:
    """Blocs des équipements déjà commencés dans le plan précédent de la journée."""
    if old is None:
        return ()
    return tuple(
        FrozenCycle(
            name=slot.device,
            start_hour=slot.start_hour,
            end_hour=slot.end_hour if slot.end_hour is not None else slot.start_hour + 1,
            energy_kwh=slot.energy_kwh or 0.0,
            start_min=slot.start_min,
            end_min=slot.end_min,
            cycle_min=slot.cycle_min,
            shape=tuple(slot.shape) if slot.shape is not None else None,
            priority=slot.priority if slot.priority is not None else 3,
        )
        for slot in old.slots
        if slot.start_hour is not None and slot.start_hour < first_hour
    )


def past_runtimes(old: Plan | None, first_hour: int) -> dict[str, dict[int, str]]:
    """Modes des durées à placer déjà planifiés plus tôt dans la journée, par équipement."""
    found: dict[str, dict[int, str]] = {}
    for runtime in old.runtimes if old else []:
        modes = pool_modes([s.to_v1() for s in runtime.segments])
        found[runtime.device] = {h: m for h, m in modes.items() if h < first_hour}
    return found


def past_pool(old: Plan | None, first_hour: int) -> dict[int, str]:
    """Filtration déjà planifiée plus tôt dans la journée (la piscine de la v1)."""
    return past_runtimes(old, first_hour).get(POOL, {})


def _soc_today(
    model: HomeModel, reader: AggregateReader, now: datetime, ctx: Context
) -> tuple[dict[int, float], float | None, float]:
    """(SoC en fin de chaque heure close aujourd'hui, SoC à minuit, maximum du jour)."""
    zone = ctx.raw.zone
    midnight = datetime.combine(now.astimezone(zone).date(), day_time(), zone)
    by_hour: dict[int, float] = {}
    at_midnight: float | None = None
    maximum = 0.0
    for entity_id in past.sensors(model, [Role.STATE_OF_CHARGE]):
        for aggregate in reader.read(entity_id, HOUR, midnight - timedelta(hours=1), now):
            if aggregate.last is None:
                continue
            local = aggregate.start.astimezone(zone)
            if local < midnight:
                at_midnight = aggregate.last
            else:
                by_hour[local.hour] = aggregate.last
                maximum = max(maximum, aggregate.max or aggregate.last)
        break  # une batterie : le premier capteur de SoC
    return by_hour, at_midnight, maximum


def with_past(
    data: PlanningInput, old: Mapping[str, Any] | None, now: datetime, ctx: Context
) -> PlanningInput:
    """Complète l'entrée du jour avec le plan précédent de la journée et les mesures du jour."""
    earlier = past_runtimes(Plan.from_v1(dict(old)) if old else None, data.first_hour)
    by_hour, at_midnight, maximum = _soc_today(ctx.model, ctx.reader, now, ctx)
    current = data.battery.soc_percent
    readings: dict[str, Any] = {
        "soc_pct_fin_heure": {**by_hour, data.first_hour: current},
        "heure_maj_iso": now.astimezone(ctx.raw.zone).isoformat(),
    }
    if at_midnight is not None:
        readings["soc_pct_minuit"] = at_midnight
    battery = data.battery
    start = start_soc(readings, data.first_hour, dict(old) if old else None)
    if start is not None and battery.capacity_kwh > 0:
        battery = replace(
            battery, soc_percent=round(start, 1), stored_kwh=start * battery.capacity_kwh / 100
        )
    history = data.history
    if max(maximum, current) >= FULL_CHARGE_PERCENT:
        history = replace(
            history or RecentHistory(days=past.RECENT_DAYS), last_full_charge=data.day
        )
    return replace(
        data,
        battery=battery,
        frozen=frozen_cycles(Plan.from_v1(dict(old)) if old else None, data.first_hour),
        runtimes=tuple(
            replace(runtime, past=earlier.get(runtime.name, {})) for runtime in data.runtimes
        ),
        history=history,
    )


async def day_forecast(forecasts: Forecasts, ctx: Context, day: date, today: date) -> DayForecast:
    production, warnings = await forecasts.hourly(day)
    baseline = past.baseline(ctx.model, ctx.reader, day, today, ctx.raw.zone)
    return DayForecast(
        net_kwh={h: production.get(h, 0.0) - baseline.get(h, 0.0) for h in range(24)},
        production_kwh={h: production.get(h, 0.0) for h in range(24)},
        warnings=tuple(warnings),
    )


async def with_assignments(
    data: PlanningInput, forecasts: Forecasts, ctx: Context, store: PlanStore
) -> tuple[PlanningInput, list[dict[str, Any]]]:
    """Affecte chaque tâche en attente à un jour et mémorise ce choix ; renvoie aussi les
    avertissements de report."""
    today = data.day
    surplus: dict[date, dict[int, float]] = {}
    for offset in range(ASSIGNMENT_DAYS):
        day = today + timedelta(days=offset)
        try:
            forecast = await day_forecast(forecasts, ctx, day, today)
        except Exception:  # noqa: BLE001 — jour sans prévision : pas candidat
            continue
        surplus[day] = {h: v for h, v in forecast.net_kwh.items() if v > 0}
    cycles = {}
    for task in data.waiting_tasks:
        found = characteristics(task.name, data)
        if found is not None:
            cycles[task.name] = found
    assignments, reports = decide(
        list(data.waiting_tasks),
        surplus,
        today,
        data.first_hour,
        cycles,
        store.assignments(today),
        launched_keys(data),
        delays=data.max_delay_days,
    )
    store.save_assignments(assignments)
    return replace(data, assignments={uid: a.day for uid, a in assignments.items()}), reports


def plan_state(
    data: PlanningInput, result: Result, extra: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Plan au format de la v1 : entrée, sortie du moteur, horodatage."""
    return {
        **to_v1(data),
        **result.output,
        "date_cible": data.day.isoformat(),
        "duree_calcul_s": round(result.seconds, 2),
        **(extra or {}),
    }


def _actual(ctx: Context, day: date, until: datetime, manual: bool = False) -> Any:
    """Données réelles du jour ; un échec n'empêche pas le calcul (le dashboard s'en passe)."""
    try:
        return actual_day(ctx.model, ctx.raw, day, until, manual, ctx.configuration)
    except Exception:
        logger.exception("Données réelles du %s illisibles", day)
        return None


def archive(
    ctx: Context,
    day: date,
    content: dict[str, Any],
    seconds: float,
    manual: bool,
    now: datetime,
) -> None:
    """Plan de la veille complété de ses données réelles jusqu'à minuit, puis archivé."""
    store = PlanStore(ctx.database)
    actual = _actual(ctx, day, now)
    if actual is not None:
        store.save("today", day, {**content, "donnees_reelles_cache": actual}, seconds, manual)
    store.archive_yesterday()


def refresh_actual(
    model: HomeModel,
    raw: RawStores,
    database: sqlite3.Connection,
    now: datetime,
    configuration: Configuration | None = None,
    manual: bool = True,
) -> dict[str, Any] | None:
    """Bouton « Rafraîchir » (``manual``) ou relecture périodique du planificateur : données
    réelles du plan du jour relues sur le brut, sans calcul ; ``None`` si le plan gardé ne porte
    pas sur aujourd'hui (calcul complet à faire)."""
    store = PlanStore(database)
    today = now.astimezone(raw.zone).date()
    current = store.load("today")
    if current is None or current.day != today:
        return None
    actual = actual_day(model, raw, today, now, manual=manual, configuration=configuration)
    content = {**current.content, "donnees_reelles_cache": actual}
    store.save("today", today, content, current.seconds, current.manual)
    return actual


def _best_production(ctx: Context, today: date) -> dict[str, Any] | None:
    """Meilleure production des 30 derniers jours (bandeau météo), au format de la v1."""
    try:
        best = past.best_production(ctx.model, ctx.reader, today, ctx.raw.zone)
    except Exception:
        logger.exception("Meilleure production récente illisible")
        return None
    if best is None:
        return None
    return {"max_kwh": best.max_kwh, "date": best.day.isoformat(), "nb_jours": best.days}


def _departure(
    state: dict[str, Any], now: datetime, previous: StoredPlan | None, tomorrow: date
) -> dict[str, Any] | None:
    """SoC de départ de demain prévu avant 18 h (bandeau « départ » du lendemain) : celui de
    ce calcul avant 18 h, sinon celui déjà retenu ; jamais un départ approximatif."""
    kept = (
        previous.content.get("depart_memorise")
        if previous is not None and previous.day == tomorrow
        else None
    )
    if now.hour >= DEPARTURE_BEFORE_HOUR:
        return kept
    battery = next((i for i in state["planning"] if i.get("equipement") == BATTERY), None)
    approximate = any(
        isinstance(w, dict) and w.get("code") == "soc_depart_approximatif"
        for w in state.get("avertissements", [])
    )
    if battery is None or battery.get("soc_initial_kwh") is None or approximate:
        return kept
    return {"kwh": battery["soc_initial_kwh"], "heure_iso": now.isoformat()}


def _pool_ran(ctx: Context, now: datetime) -> bool:
    zone = ctx.raw.zone
    midnight = datetime.combine(now.astimezone(zone).date(), day_time(), zone)
    energy = 0.0
    for entity_id in past.sensors(ctx.model, [Role.ENERGY_CONSUMED], [DeviceKind.POOL_PUMP]):
        energy += sum(
            a.energy_kwh or 0.0 for a in ctx.reader.read(entity_id, QUARTER, midnight, now)
        )
    return energy >= MIN_FILTRATION_KWH


PRESETS = {
    Preset.COST: Objective.COST,
    Preset.AUTONOMY: Objective.IMPORT,
    Preset.SELF_CONSUMPTION: Objective.SELF_CONSUMPTION,
    Preset.CO2: Objective.CO2,
}


def goal(configuration: Configuration | None, fallback: Objective) -> Goal:
    """Objectif de la configuration (lot 3.6) : préréglage ou poids libres ; sans objectif
    configuré, le réglage du calcul ``fallback``."""
    settings = configuration.objective if configuration is not None else None
    if settings is None:
        return fallback
    if settings.preset is Preset.CUSTOM and settings.weights is not None:
        return settings.weights
    return PRESETS.get(settings.preset, Objective.COST)


async def run(ctx: Context, now: datetime, manual: bool = False) -> RunReport:
    """Calcul complet ; le plan du jour est gardé même si demain ou l'horizon échouent."""
    zone = ctx.raw.zone
    today = now.astimezone(zone).date()
    store = PlanStore(ctx.database)
    journal = CycleJournal(ctx.database, ctx.raw, ctx.reader)
    fallback = open_meteo.fallback_for(ctx.database, ctx.configuration, ctx.client)
    forecasts = Forecasts(ctx.client, zone, ctx.settings, fallback, has_production(ctx.model))
    objective = goal(ctx.configuration, ctx.settings.objective)
    began = time.perf_counter()

    previous = store.load("today")
    previous_tomorrow = store.load("tomorrow")
    departure = (
        previous_tomorrow.content.get("depart_memorise")
        if previous_tomorrow is not None and previous_tomorrow.day == today
        else None
    )
    if previous is not None and previous.day != today:
        archive(ctx, previous.day, previous.content, previous.seconds, previous.manual, now)
        previous = None
    old = previous.content if previous else None

    user_requests.settle(ctx.database, today, now)
    data = await build_input(
        today,
        now,
        ctx.client,
        ctx.model,
        ctx.reader,
        ctx.raw,
        journal,
        ctx.settings,
        forecasts,
        ctx.configuration,
        ctx.database,
    )
    data = with_past(data, old, now, ctx)
    data = replace(data, chosen_starts=choices.load(ctx.database, today))
    data, reports = await with_assignments(data, forecasts, ctx, store)
    user_requests.mark_launched(
        ctx.database, cycle_appliances(ctx.model, ctx.configuration), launched_keys(data), today
    )
    try:
        result = plan_day(from_input(data), objective)
    except NoPlanError as exc:
        ctx.capture_no_plan(exc)
        raise
    state = plan_state(
        data,
        result,
        {
            "reports": reports,
            "derniere_execution": {"heure_iso": now.astimezone(zone).isoformat(), "manuel": manual},
        },
    )
    merged = merge_plans(
        state, old, data.first_hour, {k: list(v) for k, v in data.real_segments.items()}
    )
    merged["donnees_reelles_cache"] = _actual(ctx, today, now)
    execution = {"heure_iso": now.astimezone(zone).isoformat(), "manuel": manual}
    best = _best_production(ctx, today)
    if best is None and old is not None:
        best = old.get("production_max_recente")
    if best is not None:
        merged["production_max_recente"] = best
    departure = departure or (old or {}).get("depart_prevu")
    if departure:
        merged["depart_prevu"] = departure
    if old is None:
        merged["prevision_initiale"] = {
            **stored_initial_forecast(merged),
            "heure_iso": now.astimezone(zone).isoformat(),
        }
    elif old.get("prevision_initiale"):
        merged["prevision_initiale"] = old["prevision_initiale"]
    merged["texte_recommandation"] = recommendation(merged)
    seconds_today = time.perf_counter() - began
    store.save("today", today, merged, seconds_today, manual)
    report = RunReport(
        day=today, started_at=now, manual=manual, seconds_today=round(seconds_today, 2)
    )
    logger.info("Calcul du jour : %.1f s", seconds_today)

    try:
        began = time.perf_counter()
        tomorrow = today + timedelta(days=1)
        merged_plan = Plan.from_v1(merged)
        end_kwh = merged_plan.battery.end_kwh if merged_plan.battery else None
        start_kwh = end_kwh if end_kwh is not None else data.battery.stored_kwh
        pool_planned = any(
            segment.mode != "off"
            for runtime in merged_plan.runtimes[:1]  # le compteur de la première durée à placer
            for segment in runtime.segments
        )
        running = {
            runtime.device
            for runtime in merged_plan.runtimes
            if any(segment.mode != "off" for segment in runtime.segments)
        }
        history = data.history
        if history is not None:
            ran = _pool_ran(ctx, now) or pool_planned
            history = replace(
                history, days_without_filtration=0 if ran else history.days_without_filtration + 1
            )
        data_t = await build_input(
            tomorrow,
            now,
            ctx.client,
            ctx.model,
            ctx.reader,
            ctx.raw,
            journal,
            ctx.settings,
            forecasts,
            ctx.configuration,
            ctx.database,
        )
        capacity = data_t.battery.capacity_kwh
        data_t = replace(
            data_t,
            battery=replace(
                data_t.battery,
                stored_kwh=start_kwh,
                soc_percent=round(start_kwh / capacity * 100, 1) if capacity > 0 else 0.0,
            ),
            assignments=data.assignments,
            history=history,
            # Une durée à placer qui tourne aujourd'hui (prévu) n'a pas de jour sans demain.
            runtimes=tuple(
                replace(r, days_off=0) if r.days_off is not None and r.name in running else r
                for r in data_t.runtimes
            ),
        )
        result_t = plan_day(from_input(data_t), objective)
        state_t = plan_state(data_t, result_t, {"derniere_execution": execution})
        state_t["texte_recommandation"] = recommendation(state_t)
        if best is not None:
            state_t["production_max_recente"] = best
        memorised = _departure(state_t, now.astimezone(zone), previous_tomorrow, tomorrow)
        if memorised:
            state_t["depart_memorise"] = memorised
        store.save("tomorrow", tomorrow, state_t, time.perf_counter() - began, manual)
        report.seconds_tomorrow = round(time.perf_counter() - began, 2)
    except ImpossibleDataError as exc:
        found = ctx.impossible(exc, today)
        logger.warning("Prévision de demain impossible : %s (%s)", exc, found)
        report.impossible.append(found)
        return report
    except Exception as exc:
        if isinstance(exc, NoPlanError):
            ctx.capture_no_plan(exc)
        logger.exception("Prévision de demain impossible")
        report.errors.append(f"demain : {type(exc).__name__}: {exc}")
        return report

    try:
        began = time.perf_counter()

        async def forecast_of(day: date) -> DayForecast:
            return await day_forecast(forecasts, ctx, day, today)

        def on_impossible(error: ImpossibleDataError) -> dict[str, Any]:
            found = ctx.impossible(error, today)
            logger.warning("Horizon arrêté : %s (%s)", error, found)
            report.impossible.append(found)
            return found.warning()

        horizon = await compute_horizon(
            data_t,
            result_t,
            forecast_of,
            objective,
            on_no_plan=ctx.capture_no_plan,
            on_impossible=on_impossible,
        )
        days = [plan_state(d, r) for d, r in horizon.days[1:]]
        store.save(
            "horizon",
            tomorrow,
            {
                "jours": days,
                "avertissements": horizon.warnings,
                "fin_demain_kwh": end_soc_kwh(result_t),
                "derniere_execution": execution,
                "duree_s": round(time.perf_counter() - began + (report.seconds_tomorrow or 0), 1),
            },
            time.perf_counter() - began,
            manual,
        )
        report.seconds_horizon = round(time.perf_counter() - began, 2)
        report.horizon_days = len(days)
    except Exception as exc:
        logger.exception("Horizon impossible")
        report.errors.append(f"horizon : {type(exc).__name__}: {exc}")
    return report


def stored_plan(database: sqlite3.Connection, kind: str) -> dict[str, Any] | None:
    plan = PlanStore(database).load(kind)
    if plan is None:
        return None
    return {
        "kind": plan.kind,
        "day": plan.day.isoformat(),
        "computed_at": plan.computed_at.astimezone(UTC).isoformat(),
        "manual": plan.manual,
        "seconds": plan.seconds,
        "content": plan.content,
    }
