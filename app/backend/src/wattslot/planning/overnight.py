"""Débordement après minuit : ce qui passe d'un jour au suivant.

Un cycle lancé le soir peut finir le lendemain (``problem.py``, calcul prolongé). Le calcul du
jour reçoit le **lendemain** (``NextDay`` : prévision, tarif connu ou non) ; celui du lendemain
reçoit la **fin des cycles** commencés la veille (``CarriedCycle``), consommation déjà décidée,
et ne prend pas cette fin, vue dans les relevés après minuit, pour un nouveau cycle du jour.
"""

from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import date, timedelta
from typing import Any

from wattslot.planning.cycles import DAY_MIN, PlannedCycle, after_midnight, planned_hourly
from wattslot.planning.inputs import CarriedCycle, NextDay, PlanningInput
from wattslot.planning.plan import Plan
from wattslot.planning.reference import REFERENCE, task_key
from wattslot.tariff import Tariff, TariffContext

CARRIED_KEY = "suite_veille"  # fins de cycles de la veille, gardées dans le plan du jour


def next_day(
    net_kwh: Mapping[int, float],
    production_kwh: Mapping[int, float],
    tariff: Tariff,
    context: TariffContext,
    day: date,
) -> NextDay:
    """Lendemain ``day`` pour prolonger le calcul : sa prévision, et si le tarif des premières
    heures (assez pour le plus long cycle) est connu."""
    return NextDay(
        net_kwh=dict(net_kwh),
        production_kwh=dict(production_kwh),
        prices_known=tariff.known(day, context, REFERENCE.cycle_max_hours),
    )


def carried_from(plan: Plan | None) -> tuple[CarriedCycle, ...]:
    """Fins des cycles du plan d'un jour qui débordent après minuit, pour le lendemain."""
    found: list[CarriedCycle] = []
    for slot in plan.slots if plan else []:
        if (
            slot.hourly_kwh is not None  # besoin d'énergie : heures du jour seulement
            or slot.start_min is None
            or slot.end_min is None
            or slot.end_min <= DAY_MIN
            or not slot.energy_kwh
        ):
            continue
        cycle = PlannedCycle(slot.start_min, slot.end_min, slot.energy_kwh, slot.shape)
        tail = after_midnight(planned_hourly(cycle, days=2))
        if tail:
            found.append(
                CarriedCycle(
                    name=slot.device,
                    end_min=slot.end_min - DAY_MIN,
                    hourly_kwh={h: round(kwh, 4) for h, kwh in tail.items()},
                    energy_kwh=slot.energy_kwh,
                )
            )
    return tuple(found)


def with_carried(data: PlanningInput, carried: Iterable[CarriedCycle]) -> PlanningInput:
    """Entrée du jour avec les fins de cycles de la veille ; les relevés de ces équipements qui
    commencent avant la fin prévue sont cette fin, pas un cycle du jour : ils sont écartés."""
    carried = tuple(carried)
    if not carried:
        return data
    ends = {task_key(c.name): c.end_min for c in carried}
    segments = {
        name: tuple(
            s
            for s in segs
            if task_key(name) not in ends
            or s.start.date() != data.day
            or s.start.hour * 60 + s.start.minute >= ends[task_key(name)]
        )
        for name, segs in data.real_segments.items()
    }
    return replace(data, carried=carried, real_segments=segments)


def stored(carried: Iterable[CarriedCycle]) -> list[dict[str, Any]]:
    """Fins de cycles de la veille, au format gardé dans le plan du jour : relues par les calculs
    suivants de la journée, et affichées."""
    return [
        {
            "equipement": c.name,
            "fin_min": c.end_min,
            "energie_kwh": round(sum(c.hourly_kwh.values()), 3),
            "energie_cycle_kwh": c.energy_kwh,
            "horaire": {str(h): kwh for h, kwh in c.hourly_kwh.items()},
        }
        for c in carried
    ]


def from_stored(found: Any) -> tuple[CarriedCycle, ...]:
    """Fins de cycles gardées dans un plan (``stored``) ; rien de lisible : aucune."""
    cycles: list[CarriedCycle] = []
    for item in found if isinstance(found, list) else []:
        try:
            cycles.append(
                CarriedCycle(
                    name=str(item["equipement"]),
                    end_min=int(item["fin_min"]),
                    hourly_kwh={int(h): float(v) for h, v in item.get("horaire", {}).items()},
                    energy_kwh=float(item.get("energie_cycle_kwh") or 0.0),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return tuple(cycles)


def carried_into(
    previous: tuple[date, Mapping[str, Any]] | None,
    planned: tuple[date, Mapping[str, Any]] | None,
    day: date,
) -> tuple[CarriedCycle, ...]:
    """Fins de cycles reçues par le calcul de ``day`` : celles déjà gardées dans son plan
    (calcul suivant de la journée), sinon tirées du plan de la veille (premier calcul après
    minuit), sinon celles du plan de ``day`` calculé la veille (vue Demain)."""
    if previous is not None and previous[0] == day:
        return from_stored(previous[1].get(CARRIED_KEY))
    if previous is not None and previous[0] == day - timedelta(days=1):
        return carried_from(Plan.from_v1(dict(previous[1])))
    if planned is not None and planned[0] == day:
        return from_stored(planned[1].get(CARRIED_KEY))
    return ()
