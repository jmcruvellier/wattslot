"""Moteur du calcul : l'optimiseur (décision 11), sortie au format de la v1.

Programme linéaire en nombres entiers (HiGHS), repris du prototype de
l'optimiseur (lot 2.6). Décisions : départ de chaque tâche, mode de la pompe de piscine
par heure. La batterie, que l'application ne pilote pas, y suit son comportement réel
d'autoconsommation (variables binaires : elle ne peut pas garder d'énergie en réserve).

Objectif au choix (``Objective``) : coût d'abord (défaut, décision 10) ou soutirage d'abord ;
dans les deux cas, moins la valeur de l'énergie restant stockée à minuit, avec de petits
départages (moins d'injection, batterie pleine, prime forte les jours où la charge complète
hebdomadaire est due). Une tâche qui ne peut plus tenir dans la journée n'est pas placée
(avertissement), comme dans la v1.

La sortie suit le format de ``calculer_planning`` (v1) : la fusion passé/futur, le dashboard
et la comparaison avec la v1 la lisent sans adaptation. Le plan est ensuite simulé (batterie
de ``simulation.py``) : mouvements, SoC heure par heure et résidu réseau en viennent.
"""

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date
from enum import StrEnum
from typing import Any

import highspy

from wattslot.objective_settings import Weights
from wattslot.planning.explain import explain
from wattslot.planning.plan import (
    BATTERY,
    BatteryPlan,
    Indicators,
    RuntimePlan,
    RuntimeSegment,
    Slot,
)
from wattslot.planning.plan import Movement as PlannedMovement
from wattslot.planning.plan import Plan as DayPlan
from wattslot.planning.problem import Problem, Task
from wattslot.planning.simulation import BatteryRun, simulate
from wattslot.time_constraints import labels

IMPORT_TIE_EUR = 0.001  # coût d'abord : à coût égal, soutirer moins
IMPORT_WEIGHT = 1.0  # soutirage d'abord : poids d'un kWh soutiré
COST_TIE = 0.01  # soutirage d'abord : le coût ne fait que départager
EXPORT_PENALTY = 0.001  # par kWh injecté : à coût égal, consommer sur place
FULL_BONUS = 0.0001  # batterie pleine dans la journée : départage seulement (lot 7.3)
FULL_PRIORITY_BONUS = 2.0  # charge complète hebdomadaire due
SKIP_PENALTY = 100.0  # tâche non placée : seulement si elle ne tient plus
SOFT_PENALTY = 1.0  # contrainte souple violée, par heure (ou par créneau d'une tâche)
# Par kWh soutiré au-delà de la puissance souscrite (lot 7.3) : plus qu'une tâche non placée,
# le disjoncteur coupant toute la maison ; souple, le problème reste toujours soluble.
CONTRACT_PENALTY = 1000.0
# Puissance supposée sans puissance souscrite saisie, pour le seul contrôle des données
# impossibles : 36 kVA, le plus fort contrat résidentiel en France (lot 7.3).
DEFAULT_CONTRACT_KWH = 36.0
BIG_KWH = 50.0


class Objective(StrEnum):
    COST = "cost"  # coût d'abord
    IMPORT = "import"  # soutirage d'abord
    SELF_CONSUMPTION = "self_consumption"  # injection la plus faible d'abord (lot 3.6)
    CO2 = "co2"  # le moins de CO₂ soutiré (intensité du réseau), lot 3.6


# Objectif du calcul : un préréglage, ou des poids libres (équivalent euros, lot 3.6).
Goal = Objective | Weights


class NoPlanError(RuntimeError):
    """HiGHS ne rend pas de plan ; garde le problème et l'objectif pour le rejouer (capture du
    lot 7.3, ``planning/capture.py``)."""

    def __init__(self, status: str, problem: Problem, objective: Goal) -> None:
        super().__init__(f"pas de plan : {status}")
        self.problem = problem
        self.objective = objective


class ImpossibleDataError(RuntimeError):
    """Une heure du jour demande plus que la maison ne peut tirer : réseau (puissance
    souscrite), décharge de la batterie et production réunis (lot 7.3). Presque toujours un
    saut de compteur dans l'historique, qui fausse la consommation de base."""

    def __init__(self, day: date, hour: int, consumption_kwh: float, limit_kwh: float) -> None:
        super().__init__(
            f"données impossibles : {consumption_kwh:.1f} kWh consommés à {hour} h le {day}, "
            f"pour {limit_kwh:.1f} kWh au plus"
        )
        self.day, self.hour = day, hour
        self.consumption_kwh, self.limit_kwh = consumption_kwh, limit_kwh


def impossible_hour(problem: Problem) -> ImpossibleDataError | None:
    """La première heure dont la consommation (de base et cycles lancés) dépasse ce que la
    maison peut tirer, ou ``None``."""
    battery = problem.battery
    contract = problem.contract_kwh if problem.contract_kwh is not None else DEFAULT_CONTRACT_KWH
    for hour in problem.hours:
        production = max(0.0, problem.production_kwh.get(hour, 0.0))
        consumption = production - problem.net_kwh.get(hour, 0.0) + problem.fixed_kwh.get(hour, 0.0)
        active = battery.capacity_kwh > 0 and battery.active_from <= hour < battery.active_to
        limit = contract + production + (battery.discharge_max_kw if active else 0.0)
        if consumption > limit + 1e-6:
            return ImpossibleDataError(problem.day, hour, consumption, limit)
    return None


@dataclass(frozen=True)
class Plan:
    starts: dict[str, int]  # tâche → départ (minutes depuis minuit) ; absente : non placée
    runtimes: dict[str, dict[int, str]]  # durée à placer → heure → "off" ou une vitesse
    needs: dict[str, dict[int, float]] = field(default_factory=dict)  # besoin → heure → kWh


@dataclass(frozen=True)
class Result:
    plan: Plan  # décision du solveur
    day: DayPlan  # plan typé de la journée
    output: dict[str, Any]  # son format de la v1 : planning, avertissements, résidu réseau
    battery: BatteryRun
    seconds: float


def _weights(objective: Goal) -> Weights:
    """Poids d'un préréglage pondéré, ou les poids libres eux-mêmes."""
    if objective is Objective.SELF_CONSUMPTION:
        return Weights(cost=COST_TIE, grid_export=IMPORT_WEIGHT)
    if objective is Objective.CO2:
        return Weights(cost=COST_TIE, co2=IMPORT_WEIGHT)
    assert isinstance(objective, Weights)
    return objective


def battery_cost(problem: Problem, objective: Goal) -> float:
    """Pénalité d'un kWh passé par la batterie (ménagement, poids libres) : au prix moyen."""
    if isinstance(objective, Objective) or objective.battery <= 0:
        return 0.0
    hours = list(problem.hours)
    price = problem.prices_eur_kwh
    return objective.battery * sum(price[h] for h in hours) / len(hours) if hours else 0.0


def _terms(problem: Problem, objective: Goal) -> tuple[dict[int, float], dict[int, float], float]:
    """(poids d'un kWh soutiré, d'un kWh injecté, par heure ; valeur d'un kWh restant stocké à
    minuit avant rendement) selon l'objectif."""
    hours = list(problem.hours)
    price = problem.prices_eur_kwh
    export_price = problem.export_prices_eur_kwh
    lowest = min(price.values())
    if objective is Objective.COST:
        weight = {hour: price[hour] + IMPORT_TIE_EUR for hour in hours}
        export_cost = {h: EXPORT_PENALTY - export_price.get(h, 0.0) for h in hours}
        return weight, export_cost, lowest
    if objective is Objective.IMPORT:
        weight = {hour: IMPORT_WEIGHT + COST_TIE * price[hour] for hour in hours}
        export_cost = {h: EXPORT_PENALTY - COST_TIE * export_price.get(h, 0.0) for h in hours}
        return weight, export_cost, IMPORT_WEIGHT + COST_TIE * lowest
    weights = _weights(objective)
    # Poids libres : un kWh soutiré ou injecté vaut le prix moyen du jour ; pour le CO₂, le
    # kWh d'une heure d'intensité moyenne aussi.
    mean = sum(price[h] for h in hours) / len(hours) if hours else 0.0
    carbon = {h: problem.co2_g_kwh.get(h, 0.0) for h in hours}
    mean_carbon = sum(carbon.values()) / len(hours) if hours else 0.0
    relative = {h: carbon[h] / mean_carbon if mean_carbon > 0 else 1.0 for h in hours}
    weight = {
        h: weights.cost * price[h]
        + weights.grid_import * mean
        + weights.co2 * mean * relative[h]
        + IMPORT_TIE_EUR
        for h in hours
    }
    export_cost = {
        h: EXPORT_PENALTY + weights.grid_export * mean - weights.cost * export_price.get(h, 0.0)
        for h in hours
    }
    return weight, export_cost, min(weight.values()) - IMPORT_TIE_EUR


def solve(problem: Problem, objective: Goal = Objective.COST, time_limit_s: float = 30.0) -> Plan:
    impossible = impossible_hour(problem)
    if impossible is not None:
        raise impossible
    h = highspy.Highs()  # type: ignore[no-untyped-call]
    h.setOptionValue("output_flag", False)
    h.setOptionValue("time_limit", time_limit_s)
    hours = list(problem.hours)
    integer, continuous = highspy.HighsVarType.kInteger, highspy.HighsVarType.kContinuous

    def var(lb: float = 0.0, ub: float = highspy.kHighsInf, binary: bool = False) -> Any:
        return h.addVariable(lb=lb, ub=ub, type=integer if binary else continuous)

    # --- Tâches : un départ parmi les candidats, ou non placée ---------------------------
    by_key = {task.key: task for task in problem.tasks}
    choices: dict[str, dict[int, Any]] = {}
    skips: dict[str, Any] = {}
    penalties: list[Any] = []  # contraintes souples violées (lot 3.5)
    for task in problem.tasks:
        candidates = set(task.candidates())
        parent = by_key.get(task.depends_on or "")
        if parent is not None:  # peut aussi démarrer dès la fin exacte de la précédente
            candidates |= {
                s + parent.slot_min
                for s in parent.candidates()
                if s + parent.slot_min >= task.earliest_min
                and s + parent.slot_min + task.slot_min <= 24 * 60
            }
        allowed = {
            s for s in candidates if not problem.hard_blocks(task.name, s, s + task.slot_min)
        }
        choices[task.name] = {s: var(0, 1, True) for s in sorted(allowed)}
        for s, x in choices[task.name].items():
            violated = problem.soft_violated(task.name, s, s + task.slot_min)
            if violated:
                penalties.append(len(violated) * x)
        skips[task.name] = var(0, 1, True)
        h.addConstr(sum(choices[task.name].values()) + skips[task.name] == 1)
    for task in problem.tasks:
        parent = by_key.get(task.depends_on or "")
        if parent is not None:
            h.addConstr(skips[task.name] >= skips[parent.name])  # pas sans la précédente
            start = sum(s * x for s, x in choices[task.name].items())
            parent_end = sum((s + parent.slot_min) * x for s, x in choices[parent.name].items())
            h.addConstr(start >= parent_end - 24 * 60 * skips[task.name])

    load: dict[int, Any] = {hour: problem.fixed_kwh.get(hour, 0.0) for hour in hours}
    for task in problem.tasks:
        for start, x in choices[task.name].items():
            for hour, kwh in task.hourly_kwh(start).items():
                if hour in load and kwh:
                    load[hour] = load[hour] + kwh * x

    # --- Durées à placer (filtration…) : arrêt ou une vitesse, heure par heure ---------------
    shortfalls: list[Any] = []
    # Jours à minimum forcé : la vitesse la plus basse seulement, pas au-delà du minimum.
    modes: dict[str, dict[str, dict[int, Any]]] = {}
    for runtime in problem.runtimes:
        slowest = runtime.speeds[0][0] if runtime.speeds else None
        speeds = {
            mode: {
                hour: var(
                    0,
                    0
                    if (runtime.minimum_forced and mode != slowest)
                    or problem.hard_blocks(runtime.name, hour * 60, hour * 60 + 60)
                    else 1,
                    True,
                )
                for hour in hours
            }
            for mode, _ in runtime.speeds
        }
        modes[runtime.name] = speeds
        starts: list[Any] = []
        previous: Any = 0
        for hour in hours:
            on = sum(speeds[mode][hour] for mode in speeds)
            h.addConstr(on <= 1)
            started = var(0, 1, True)
            h.addConstr(started >= on - previous)
            starts.append(started)
            previous = on
            load[hour] = load[hour] + sum(kw * speeds[mode][hour] for mode, kw in runtime.speeds)
            violated = problem.soft_violated(runtime.name, hour * 60, hour * 60 + 60)
            if violated:
                penalties.append(len(violated) * on)
        on_hours = sum(speeds[mode][hour] for mode in speeds for hour in hours)
        if runtime.name in problem.constraints:
            # Contraintes : la durée minimale peut ne plus tenir (signalé), sans rendre le
            # problème impossible.
            missing = var(0, runtime.min_hours)
            shortfalls.append(missing)
            h.addConstr(on_hours + missing >= runtime.min_hours)
        else:
            h.addConstr(on_hours >= runtime.min_hours)
        if runtime.minimum_forced:
            h.addConstr(on_hours <= runtime.min_hours)
        h.addConstr(sum(starts) <= runtime.max_starts)

    # --- Besoins d'énergie avant une échéance : continus ou par paliers --------------------
    deliveries: dict[str, dict[int, Any]] = {}
    for need in problem.needs:
        window = [
            hour
            for hour in hours
            if need.start_hour <= hour < need.deadline_hour
            and not problem.hard_blocks(need.name, hour * 60, hour * 60 + 60)
        ]
        if need.steps:
            delivered = {hour: need.max_kw * var(0, 1, True) for hour in window}
        else:
            delivered = {hour: var(0, need.max_kw) for hour in window}
        short = var(0, need.energy_kwh)
        h.addConstr(sum(delivered.values()) + short >= need.energy_kwh)
        for hour, kwh in delivered.items():
            load[hour] = load[hour] + kwh
            violated = problem.soft_violated(need.name, hour * 60, hour * 60 + 60)
            if violated:
                penalties.append(len(violated) / need.max_kw * kwh)
        deliveries[need.name] = delivered
        shortfalls.append(short)

    # --- Batterie (comportement glouton) et réseau ---------------------------------------
    battery = problem.battery
    soc_previous: Any = battery.stored_kwh
    imports, exports, full_hours = {}, {}, []
    over_contract: list[Any] = []  # soutirage au-delà de la puissance souscrite (lot 7.3)
    throughput: list[Any] = []  # énergie qui passe par la batterie (ménagement)
    for hour in hours:
        imports[hour], exports[hour] = var(), var()
        if problem.contract_kwh is not None:
            over = var()
            h.addConstr(imports[hour] <= problem.contract_kwh + over)
            over_contract.append(over)
        balance = problem.net_kwh.get(hour, 0.0) - load[hour]
        if battery.active_from <= hour < battery.active_to and battery.capacity_kwh > 0:
            charge = var(0, battery.charge_max_kw)
            discharge = var(0, battery.discharge_max_kw)
            throughput.append(charge + discharge)
            charging = var(0, 1, True)
            h.addConstr(charge <= battery.charge_max_kw * charging)
            h.addConstr(discharge <= battery.discharge_max_kw * (1 - charging))
            h.addConstr(imports[hour] <= BIG_KWH * (1 - charging))
            h.addConstr(exports[hour] <= BIG_KWH * charging)
            soc = var(min(battery.floor_at(hour), battery.stored_kwh), battery.capacity_kwh)
            h.addConstr(
                soc
                == soc_previous
                + battery.charge_efficiency * charge
                - (1 / battery.discharge_efficiency) * discharge
            )
            # Injection seulement batterie à pleine puissance ou pleine ; soutirage seulement
            # à pleine puissance de décharge ou au plancher.
            charge_max, at_cap = var(0, 1, True), var(0, 1, True)
            h.addConstr(exports[hour] <= BIG_KWH * (charge_max + at_cap))
            h.addConstr(charge >= battery.charge_max_kw * charge_max)
            h.addConstr(soc >= battery.capacity_kwh * at_cap)
            discharge_max, at_floor = var(0, 1, True), var(0, 1, True)
            h.addConstr(imports[hour] <= BIG_KWH * (discharge_max + at_floor))
            h.addConstr(discharge >= battery.discharge_max_kw * discharge_max)
            h.addConstr(soc <= battery.floor_at(hour) + battery.capacity_kwh * (1 - at_floor))
            full = var(0, 1, True)
            h.addConstr(soc >= battery.full_kwh * full)
            full_hours.append(full)
            soc_previous = soc
            balance = balance - charge + discharge
        h.addConstr(balance == exports[hour] - imports[hour])
    full_day = var(0, 1, True)
    h.addConstr(full_day <= (sum(full_hours) if full_hours else 0))

    # Prix du tarif de la maison (lot 3.2) ; le kWh injecté rapporte son prix de revente.
    weight, export_cost, cheapest = _terms(problem, objective)
    # Un kWh stocké à minuit vaut le kWh soutiré le moins cher, pas plus : au-delà, le moteur
    # soutirerait la nuit pour garder la batterie pleine (mesuré au lot 2.6).
    stored_value = cheapest * battery.discharge_efficiency
    bonus = FULL_PRIORITY_BONUS if battery.full_priority else FULL_BONUS
    h.minimize(
        sum(weight[hour] * imports[hour] + export_cost[hour] * exports[hour] for hour in hours)
        - stored_value * soc_previous
        - bonus * full_day
        + SKIP_PENALTY * sum(skips.values())
        + SKIP_PENALTY * sum(shortfalls)  # par kWh manquant : seulement s'il ne tient plus
        + SOFT_PENALTY * sum(penalties)
        + CONTRACT_PENALTY * sum(over_contract)
        + battery_cost(problem, objective) * sum(throughput)
    )
    status = h.getModelStatus()
    if status == highspy.HighsModelStatus.kInfeasible:
        # Le problème a toujours une solution (tâche non placée, durée ou besoin manquant
        # pénalisés) : HiGHS 1.15 le déclare parfois impossible à tort, selon les coupes du
        # nœud racine (lot 7.3). Nouvel essai par un autre chemin : sans presolve, autre graine.
        h.setOptionValue("presolve", "off")
        h.setOptionValue("random_seed", 1)
        h.clearSolver()
        h.run()
        status = h.getModelStatus()
    if status not in (highspy.HighsModelStatus.kOptimal, highspy.HighsModelStatus.kTimeLimit):
        raise NoPlanError(h.modelStatusToString(status), problem, objective)
    return Plan(
        starts={
            name: max(options, key=lambda s: h.val(options[s]))
            for name, options in choices.items()
            if h.val(skips[name]) < 0.5
        },
        needs={
            name: {hour: round(h.val(kwh), 3) for hour, kwh in delivered.items()}
            for name, delivered in deliveries.items()
        },
        runtimes={
            name: {
                hour: next((mode for mode, xs in speeds.items() if h.val(xs[hour]) > 0.5), "off")
                for hour in hours
            }
            for name, speeds in modes.items()
        },
    )


def load_kwh(problem: Problem, plan: Plan) -> dict[int, float]:
    """Consommation fixée et décidée (tâches, piscine), heure par heure."""
    load = {hour: problem.fixed_kwh.get(hour, 0.0) for hour in problem.hours}
    by_name = {task.name: task for task in problem.tasks}
    for name, start in plan.starts.items():
        for hour, kwh in by_name[name].hourly_kwh(start).items():
            if hour in load:
                load[hour] += kwh
    for runtime in problem.runtimes:
        chosen = plan.runtimes.get(runtime.name, {})
        for hour in problem.hours:
            load[hour] += runtime.kw(chosen.get(hour, "off"))
    for delivered in plan.needs.values():
        for hour, kwh in delivered.items():
            if hour in load:
                load[hour] += kwh
    return load


def simulate_plan(problem: Problem, plan: Plan) -> BatteryRun:
    load = load_kwh(problem, plan)
    battery = problem.battery
    return simulate(
        {hour: problem.net_kwh.get(hour, 0.0) - load[hour] for hour in problem.hours},
        battery.stored_kwh,
        battery.capacity_kwh,
        battery.charge_max_kw,
        battery.discharge_max_kw,
        battery.active_from,
        battery.active_to,
        battery.charge_efficiency,
        battery.discharge_efficiency,
        battery.floor_kwh,
        first_hour=problem.first_hour,
        floor_by_hour=battery.floor_by_hour,
    )


def _hhmm(minutes: int) -> str:
    hours, rest = divmod(int(minutes), 60)
    return f"{hours}h{rest:02d}" if rest else f"{hours}h"


def _justification(plan: Plan, parent: Task | None) -> str:
    if parent is not None and parent.name in plan.starts:
        end = _hhmm(plan.starts[parent.name] + parent.slot_min)
        return f"Démarre après la fin de '{parent.name}' ({end}), le même jour."
    return "Placé par l'optimiseur au meilleur moment de la journée."


def _blocked(problem: Problem, task: Task) -> bool:
    """Tâche que ses contraintes dures empêchent de placer alors que le temps le permettait."""
    starts = task.candidates()
    return bool(starts) and all(
        problem.hard_blocks(task.name, s, s + task.slot_min) for s in starts
    )


def _impossible(problem: Problem, name: str) -> dict[str, Any]:
    hard = [c for c in problem.constraints.get(name, ()) if c.hard]
    return {
        "code": "contrainte_impossible",
        "params": {"equipement": name, "contraintes": labels(hard)},
    }


def _check_soft(
    problem: Problem,
    name: str,
    periods: list[tuple[int, int]],
    warnings: list[dict[str, Any] | str],
) -> None:
    """Avertit des contraintes souples que le placement ne respecte pas."""
    violated = {
        c.label(): c for start, end in periods for c in problem.soft_violated(name, start, end)
    }
    if violated:
        warnings.append(
            {
                "code": "contrainte_non_respectee",
                "params": {"equipement": name, "contraintes": labels(list(violated.values()))},
            }
        )


def day_plan(problem: Problem, plan: Plan, run: BatteryRun) -> DayPlan:
    """Plan typé de la journée ; ``to_v1`` en donne le format de ``calculer_planning`` (v1)."""
    items: list[Slot | BatteryPlan | RuntimePlan] = []
    warnings: list[dict[str, Any] | str] = list(problem.warnings)
    for launched in problem.launched:
        start_min = launched.start.hour * 60 + launched.start.minute
        items.append(
            Slot(
                device=launched.name,
                energy_kwh=launched.energy_kwh,
                cycle_min=launched.cycle_min,
                shape=list(launched.shape) if launched.shape is not None else None,
                priority=launched.priority,
                start_hour=launched.start.hour,
                end_hour=launched.end_hour,
                start_min=start_min,
                end_min=launched.end_min,
                justification=f"Lancé à {launched.start:%Hh%M}, créneau calé sur le "
                "démarrage réel.",
            )
        )
    by_key = {task.key: task for task in problem.tasks}
    for task in problem.tasks:
        start = plan.starts.get(task.name)
        if start is None and _blocked(problem, task):
            warnings.append(_impossible(problem, task.name))
            continue
        if start is None:
            warnings.append(
                {
                    "code": "heures_insuffisantes_" + ("du" if task.priority == 1 else "attente"),
                    "params": {
                        "equipement": task.name,
                        "duree_min": task.slot_min,
                        "debut_min": task.earliest_min,
                    },
                }
            )
            continue
        end = start + task.slot_min
        _check_soft(problem, task.name, [(start, end)], warnings)
        parent = by_key.get(task.depends_on or "")
        items.append(
            Slot(
                device=task.name,
                start_hour=start // 60,
                end_hour=math.ceil(end / 60),
                start_min=start,
                end_min=end,
                energy_kwh=task.energy_kwh,
                cycle_min=task.cycle_min,
                shape=list(task.shape) if task.shape is not None else None,
                priority=task.priority,
                justification=_justification(plan, parent),
            )
        )
    battery = problem.battery
    charges = [m for m in run.movements if m.action == "charge"]
    discharges = [m for m in run.movements if m.action == "decharge"]
    items.append(
        BatteryPlan(
            device=BATTERY,
            movements=[
                PlannedMovement(hour=m.hour, action=m.action, energy_kwh=m.energy_kwh)
                for m in run.movements
            ],
            soc_kwh={hour: round(v, 3) for hour, v in run.soc_kwh.items()},
            charged_kwh=round(sum(m.energy_kwh for m in charges), 3),
            discharged_kwh=round(sum(m.energy_kwh for m in discharges), 3),
            start_kwh=round(battery.stored_kwh, 3),
            end_kwh=round(run.end_kwh, 3),
            priority=2,
            justification=(
                f"Autoconsommation simulée heure par heure à partir de {problem.first_hour}h "
                f"(SoC {battery.soc_percent}%, {battery.stored_kwh} kWh) ; plage active "
                f"{battery.active_from}h-{battery.active_to}h."
            ),
        )
    )
    for need in problem.needs:
        delivered = {h: kwh for h, kwh in plan.needs.get(need.name, {}).items() if kwh > 0.0005}
        total = round(sum(delivered.values()), 3)
        _check_soft(problem, need.name, [(h * 60, h * 60 + 60) for h in delivered], warnings)
        if total < need.energy_kwh - 0.01 and need.name in problem.constraints:
            warnings.append(_impossible(problem, need.name))
        elif total < need.energy_kwh - 0.01:
            warnings.append(
                {
                    "code": "heures_insuffisantes_du",
                    "params": {
                        "equipement": need.name,
                        "duree_min": 60 * (need.deadline_hour - need.start_hour),
                        "debut_min": need.start_hour * 60,
                    },
                }
            )
        if not delivered:
            continue
        first_hour, last_hour = min(delivered), max(delivered) + 1
        items.append(
            Slot(
                device=need.name,
                start_hour=first_hour,
                end_hour=last_hour,
                start_min=first_hour * 60,
                end_min=last_hour * 60,
                energy_kwh=total,
                priority=1,
                hourly_kwh=delivered,
                justification=f"{total:.2f} kWh fournis avant {need.deadline_hour}h, aux heures "
                "les moins chères ou de surplus solaire.",
            )
        )
    first = problem.first_hour
    for runtime in problem.runtimes:
        chosen = plan.runtimes.get(runtime.name, {})
        running = [hour for hour, mode in chosen.items() if mode != "off"]
        _check_soft(problem, runtime.name, [(h * 60, h * 60 + 60) for h in running], warnings)
        if runtime.name in problem.constraints and len(running) < runtime.min_hours:
            warnings.append(_impossible(problem, runtime.name))
        segments: list[RuntimeSegment] = []
        current, since = chosen.get(first, "off"), first
        for hour in range(first + 1, 25):
            mode = chosen.get(hour) if hour < 24 else None
            if mode != current:
                segments.append(RuntimeSegment(start_hour=since, end_hour=hour, mode=current))
                current, since = mode or "off", hour
        note = (
            "Pas de filtration aujourd'hui : la charge complète hebdomadaire de la batterie "
            "est due."
            if runtime.skipped
            else "Modes choisis par l'optimiseur : filtration minimale de la saison garantie, "
            "surplus absorbé plutôt qu'injecté."
        )
        items.append(
            RuntimePlan(device=runtime.name, segments=segments, priority=4, justification=note)
        )
    over = _over_contract(problem, run)
    if over:
        warnings.append(
            {
                "code": "puissance_souscrite_depassee",
                "params": {
                    "kva": f"{problem.contract_kwh:g}",
                    "heures": ", ".join(str(hour) for hour in over),
                },
            }
        )
    return DayPlan(
        items=items,
        warnings=warnings,
        residual_kwh=dict(run.residual_kwh),
        indicators=indicators(problem, run),
    )


def _over_contract(problem: Problem, run: BatteryRun) -> list[int]:
    """Heures où le soutirage simulé dépasse la puissance souscrite (lot 7.3)."""
    if problem.contract_kwh is None:
        return []
    limit = problem.contract_kwh + 0.001
    return sorted(hour for hour, kwh in run.residual_kwh.items() if -kwh > limit)


def indicators(problem: Problem, run: BatteryRun) -> Indicators:
    """Indicateurs du plan (lot 3.6) sur les heures calculées : échanges avec le réseau après
    la batterie simulée, au tarif de la maison."""
    imported = {h: max(0.0, -kwh) for h, kwh in run.residual_kwh.items()}
    exported = {h: max(0.0, kwh) for h, kwh in run.residual_kwh.items()}
    price, export_price = problem.prices_eur_kwh, problem.export_prices_eur_kwh
    produced = sum(max(0.0, problem.production_kwh.get(h, 0.0)) for h in problem.hours)
    capacity = problem.battery.capacity_kwh
    return Indicators(
        cost_eur=round(
            sum(price.get(h, 0.0) * kwh for h, kwh in imported.items())
            - sum(export_price.get(h, 0.0) * kwh for h, kwh in exported.items())
            + problem.subscription_eur,
            3,
        ),
        subscription_eur=round(problem.subscription_eur, 3),
        import_kwh=round(sum(imported.values()), 3),
        export_kwh=round(sum(exported.values()), 3),
        self_consumption_percent=round(100 * (produced - sum(exported.values())) / produced, 1)
        if produced > 0.01
        else None,
        end_soc_percent=round(100 * run.end_kwh / capacity, 1) if capacity > 0 else None,
        battery_throughput_kwh=round(sum(m.energy_kwh for m in run.movements), 3),
        co2_kg=round(
            sum(problem.co2_g_kwh.get(h, 0.0) * kwh for h, kwh in imported.items()) / 1000, 3
        )
        if problem.co2_g_kwh
        else None,
    )


def output(problem: Problem, plan: Plan, run: BatteryRun) -> dict[str, Any]:
    """Sortie au format de ``calculer_planning`` (v1)."""
    return day_plan(problem, plan, run).to_v1()


def _score(objective: Goal) -> Callable[[Indicators], float]:
    """Note d'un plan selon l'objectif (plus bas : meilleur), pour choisir une alternative."""
    if objective is Objective.COST:
        return lambda found: found.cost_eur
    if objective is Objective.IMPORT:
        return lambda found: found.import_kwh
    if objective is Objective.SELF_CONSUMPTION:
        return lambda found: found.export_kwh
    if objective is Objective.CO2:
        return lambda found: found.co2_kg if found.co2_kg is not None else found.import_kwh
    assert isinstance(objective, Weights)
    weights = objective
    return lambda found: (
        weights.cost * found.cost_eur
        + (weights.grid_import + weights.co2) * found.import_kwh * 0.2
        + weights.grid_export * found.export_kwh * 0.2
        + weights.battery * found.battery_throughput_kwh * 0.2
    )


def plan_day(problem: Problem, objective: Goal = Objective.COST, explained: bool = True) -> Result:
    """Plan de la journée : décision, simulation, sortie au format de la v1 ; avec les
    explications de chaque élément (lot 3.7), sauf pour les jours de l'horizon au-delà de
    demain (``explained``)."""
    began = time.perf_counter()
    plan = solve(problem, objective)
    run = simulate_plan(problem, plan)
    day = day_plan(problem, plan, run)
    if explained:

        def evaluate(starts: dict[str, int]) -> Indicators:
            return indicators(problem, simulate_plan(problem, replace(plan, starts=starts)))

        name = objective.value if isinstance(objective, Objective) else "custom"
        day = explain(
            problem, day, plan.starts, load_kwh(problem, plan), name, evaluate, _score(objective)
        )
    return Result(
        plan=plan,
        day=day,
        output=day.to_v1(),
        battery=run,
        seconds=time.perf_counter() - began,
    )
