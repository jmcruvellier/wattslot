"""Horizon de planification : les jours qui suivent le premier jour prévu (demain).

Réécriture de ``horizon.py`` (v1) sur le moteur de la v2. Le premier jour est la
prévision de demain, calculée comme aujourd'hui ; les suivants en reprennent les tâches, les
profils et la batterie, et ne changent que la prévision solaire et la ligne de base. Chaque
jour part du SoC prévu en fin du jour précédent.

Tâches : les tâches datées qui concernent le jour (une tâche récurrente revient selon sa
règle, ``recurrence.py``) ; les tâches en attente seulement le jour auquel elles sont
affectées (``assignment.py``), sans quoi un lave-linge serait placé chaque jour.

Si la prévision d'un jour manque, ou si son calcul échoue, l'horizon s'arrête au dernier jour
calculé, avec un avertissement : les jours suivants dépendent de son SoC. Un problème que HiGHS
déclare impossible est passé à ``on_no_plan`` pour être capturé (``capture.py``, lot 7.3).
"""

import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from typing import Any

from wattslot.planning.engine import (
    Goal,
    ImpossibleDataError,
    NoPlanError,
    Objective,
    Result,
    plan_day,
)
from wattslot.planning.inputs import PlanningInput
from wattslot.planning.problem import from_input
from wattslot.planning.recurrence import tasks_of_day

HORIZON_DAYS = 6  # demain et les 5 jours suivants (prévisions sur 7 jours)


@dataclass(frozen=True)
class DayForecast:
    """Prévision d'un jour : net (production moins ligne de base) et production, par heure."""

    net_kwh: Mapping[int, float]
    production_kwh: Mapping[int, float]
    warnings: tuple[dict[str, Any], ...] = ()


ForecastOf = Callable[[date], Awaitable[DayForecast]]
OnNoPlan = Callable[[NoPlanError], None]
# Avertissement d'un jour aux données impossibles (lot 7.3), à la place de « horizon_interrompu ».
OnImpossible = Callable[[ImpossibleDataError], dict[str, Any]]


@dataclass
class Horizon:
    days: list[tuple[PlanningInput, Result]]
    warnings: list[dict[str, Any]] = field(default_factory=list)
    seconds: list[float] = field(default_factory=list)


def end_soc_kwh(result: Result) -> float | None:
    battery = result.day.battery
    return battery.end_kwh if battery else None


def next_day_input(
    first: PlanningInput, day: date, forecast: DayForecast, start_soc_kwh: float
) -> PlanningInput:
    """Entrée d'un jour de l'horizon au-delà du premier."""
    tasks, unsupported = tasks_of_day(list(first.due_tasks), day)
    assignments = first.assignments or {}
    capacity = first.battery.capacity_kwh
    return PlanningInput(
        day=day,
        first_hour=0,
        net_kwh={h: forecast.net_kwh.get(h, 0.0) for h in range(24)},
        production_kwh={h: forecast.production_kwh.get(h, 0.0) for h in range(24)},
        battery=replace(
            first.battery,
            stored_kwh=start_soc_kwh,
            soc_percent=start_soc_kwh / capacity * 100 if capacity > 0 else 0.0,
        ),
        due_tasks=tuple(tasks),
        waiting_tasks=tuple(
            t for t in first.waiting_tasks if t.uid is not None and assignments.get(t.uid) == day
        ),
        assignments=first.assignments,
        runtimes=tuple(replace(r, past={}) for r in first.runtimes),
        needs=tuple(n for n in first.needs if n.daily),
        constraints=first.constraints,
        max_delay_days=first.max_delay_days,
        southern=first.southern,
        tariff=first.tariff,
        tariff_context=first.tariff_context,
        co2=first.co2,
        cycle_profiles=first.cycle_profiles,
        daily_profiles=first.daily_profiles,
        profile_status=first.profile_status,
        forecast_warnings=tuple(forecast.warnings)
        + tuple(
            {"code": "regle_recurrence_non_geree", "params": {"equipement": name}}
            for name in dict.fromkeys(unsupported)
        ),
    )


async def compute_horizon(
    first: PlanningInput,
    first_result: Result,
    forecast_of: ForecastOf,
    objective: Goal = Objective.COST,
    days: int = HORIZON_DAYS,
    on_no_plan: OnNoPlan | None = None,
    on_impossible: OnImpossible | None = None,
) -> Horizon:
    """Le premier jour tel quel, puis au plus ``days - 1`` jours calculés à la suite."""
    horizon = Horizon(days=[(first, first_result)])
    for offset in range(1, days):
        day = first.day + timedelta(days=offset)
        soc = end_soc_kwh(horizon.days[-1][1])
        if soc is None:
            horizon.warnings.append(_interrupted(day, FAILED, "SoC de fin de journée inconnu"))
            break
        began = time.perf_counter()
        try:
            forecast = await forecast_of(day)
        except Exception as exc:  # noqa: BLE001 — l'horizon s'arrête au dernier jour connu
            horizon.warnings.append(_interrupted(day, NO_FORECAST, f"{type(exc).__name__} : {exc}"))
            break
        data = next_day_input(first, day, forecast, soc)
        try:
            result = plan_day(from_input(data), objective, explained=False)
        except Exception as exc:  # noqa: BLE001 — l'horizon s'arrête au dernier jour calculé
            if isinstance(exc, NoPlanError) and on_no_plan is not None:
                on_no_plan(exc)
            if isinstance(exc, ImpossibleDataError) and on_impossible is not None:
                horizon.warnings.append(on_impossible(exc))
            else:
                code = NO_SOLUTION if isinstance(exc, NoPlanError) else FAILED
                horizon.warnings.append(_interrupted(day, code, f"{type(exc).__name__} : {exc}"))
            break
        horizon.days.append((data, result))
        horizon.seconds.append(round(time.perf_counter() - began, 1))
    return horizon


# Arrêt de l'horizon, selon sa cause : un texte explicite pour chacune (« horizon_interrompu »,
# texte de la v1 avec la raison technique, reste lu dans les horizons enregistrés avant).
NO_SOLUTION = "horizon_sans_solution"  # aucun plan ne respecte les contraintes du jour
NO_FORECAST = "horizon_sans_prevision"  # prévision de production du jour illisible
FAILED = "horizon_calcul_echoue"  # autre échec, raison technique à l'appui


def _interrupted(day: date, code: str, reason: str) -> dict[str, Any]:
    return {"code": code, "params": {"jour": day.isoformat(), "raison": reason}}
