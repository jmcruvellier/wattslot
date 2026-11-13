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

Calcul prolongé après minuit (``Problem.overnight``) : les premières heures du lendemain
s'ajoutent (24, 25…), avec leur tarif, leur consommation de base et la batterie qui continue
(plage active, plancher du lendemain) ; l'énergie restant stockée est alors valorisée à la fin
du prolongement. Un cycle qui démarre le soir et finit le lendemain y est chiffré au tarif du
lendemain. Le plan et sa simulation restent ceux de la journée (0 h à 24 h).

La sortie suit le format de ``calculer_planning`` (v1) : la fusion passé/futur, le dashboard
et la comparaison avec la v1 la lisent sans adaptation. Le plan est ensuite simulé (batterie
de ``simulation.py``) : mouvements, SoC heure par heure et résidu réseau en viennent.
"""

import math
import time
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import date
from enum import StrEnum
from typing import Any

import highspy

from wattslot.home_model import LINES, Phase, line_shares
from wattslot.objective_settings import Weights
from wattslot.planning.explain import explain
from wattslot.planning.plan import (
    BATTERY,
    BatteryGroup,
    BatteryPlan,
    Indicators,
    RuntimePlan,
    RuntimeSegment,
    Slot,
)
from wattslot.planning.plan import Movement as PlannedMovement
from wattslot.planning.plan import Plan as DayPlan
from wattslot.planning.problem import BatteryModel, Problem, Task
from wattslot.planning.simulation import BatteryRun, Movement, simulate
from wattslot.time_constraints import labels

IMPORT_TIE_EUR = 0.001  # coût d'abord : à coût égal, soutirer moins
IMPORT_WEIGHT = 1.0  # soutirage d'abord : poids d'un kWh soutiré
COST_TIE = 0.01  # soutirage d'abord : le coût ne fait que départager
EXPORT_PENALTY = 0.001  # par kWh injecté : à coût égal, consommer sur place
FULL_BONUS = 0.0001  # batterie pleine dans la journée : départage seulement (lot 7.3)
FULL_PRIORITY_BONUS = 2.0  # charge complète hebdomadaire due
SKIP_PENALTY = 100.0  # tâche non placée : seulement si elle ne tient plus
SOFT_PENALTY = 1.0  # contrainte souple violée, par heure (ou par créneau d'une tâche)
# Départ après le délai maximal derrière le cycle suivi (sèche-linge après lave-linge), par
# heure de retard : bien plus que ce qu'un autre créneau fait gagner, bien moins qu'une tâche
# non placée. Le cycle part alors au plus près, avec un avertissement.
LATE_PENALTY = 5.0
# Par kWh soutiré au-delà de la puissance souscrite (lot 7.3) : plus qu'une tâche non placée,
# le disjoncteur coupant toute la maison ; souple, le problème reste toujours soluble.
CONTRACT_PENALTY = 1000.0
# Par kWh que les équipements placés tirent ensemble sur une phase au-delà de sa part de la
# puissance souscrite (triphasé) : plus que tout écart de prix ou contrainte souple, moins qu'une
# tâche non placée. La consommation de base de la phase n'est pas toujours connue : un
# équipement qui dépasse seul reste placé, deux équipements de la même phase sont écartés l'un
# de l'autre.
PHASE_PENALTY = 10.0
# Départ déjà annoncé par le plan précédent : gardé tant qu'un autre ne fait pas gagner plus
# que cette part de ce que pèse le cycle dans l'objectif, à l'heure moyenne (10 % de son
# coût au prix moyen, pour l'objectif de coût). Même marge que le choix du jour
# (``assignment.STABILITY_MARGIN``). Sans elle, l'heure annoncée d'un appareil changeait
# d'un calcul horaire à l'autre pour quelques centimes.
KEEP_MARGIN = 0.10
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
    price = _scaled(problem.prices_eur_kwh, problem)
    return objective.battery * sum(price[h] for h in hours) / len(hours) if hours else 0.0


def extended_hours(problem: Problem) -> list[int]:
    """Heures du calcul : celles du jour, puis celles du prolongement après minuit."""
    later = list(problem.overnight.problem_hours) if problem.overnight else []
    return list(problem.hours) + later


def _extended(day: Mapping[int, float], night: Mapping[int, float] | None) -> dict[int, float]:
    """Valeurs par heure du jour, suivies de celles du lendemain (heures 24, 25…)."""
    return {**day, **{24 + h: v for h, v in (night or {}).items()}}


def _scaled(prices: dict[int, float], problem: Problem) -> dict[int, float]:
    """Prix ramenés à l'échelle de l'euro (``Problem.price_scale``), pour l'objectif seul."""
    if problem.price_scale == 1.0:
        return prices
    return {hour: value / problem.price_scale for hour, value in prices.items()}


def _terms(problem: Problem, objective: Goal) -> tuple[dict[int, float], dict[int, float], float]:
    """(poids d'un kWh soutiré, d'un kWh injecté, par heure ; valeur d'un kWh restant stocké à
    minuit avant rendement) selon l'objectif."""
    hours = extended_hours(problem)
    night = problem.overnight
    price = _scaled(
        _extended(problem.prices_eur_kwh, night.prices_eur_kwh if night else None), problem
    )
    export_price = _scaled(
        _extended(problem.export_prices_eur_kwh, night.export_prices_eur_kwh if night else None),
        problem,
    )
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
    co2 = _extended(problem.co2_g_kwh, night.co2_g_kwh if night else None)
    carbon = {h: co2.get(h, 0.0) for h in hours}
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
    by_name = {task.name: task for task in problem.tasks}
    choices: dict[str, dict[int, Any]] = {}
    skips: dict[str, Any] = {}
    penalties: list[Any] = []  # contraintes souples violées (lot 3.5)
    lateness: list[Any] = []  # minutes de retard sur le délai maximal après le cycle suivi
    for task in problem.tasks:
        candidates = set(task.candidates())
        # Cycles à finir avant : celui dont la tâche dépend (sèche-linge après lave-linge), et
        # le cycle précédent du même équipement.
        before = [by_key.get(task.depends_on or ""), by_name.get(task.follows or "")]
        # Départ choisi par l'utilisateur : lui seul ; sinon, aussi dès la fin de la précédente.
        for parent in before:
            if parent is not None and task.chosen_min is None:
                candidates |= {
                    s + parent.slot_min
                    for s in parent.candidates()
                    if s + parent.slot_min >= task.earliest_min
                    and s + parent.slot_min < 24 * 60
                    and s + parent.slot_min + task.slot_min <= 24 * 60 + task.overflow_min
                }
        allowed = {
            s for s in candidates if not problem.hard_blocks(task.label, s, s + task.slot_min)
        }
        choices[task.name] = {s: var(0, 1, True) for s in sorted(allowed)}
        for s, x in choices[task.name].items():
            violated = problem.soft_violated(task.label, s, s + task.slot_min)
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
        if task.within_min is not None and (parent is not None or task.after_end_min is not None):
            # Délai maximal après la fin du cycle suivi : le retard (minutes) est pénalisé.
            start = sum(s * x for s, x in choices[task.name].items())
            after_end: Any = (
                sum((s + parent.slot_min) * x for s, x in choices[parent.name].items())
                if parent is not None
                else task.after_end_min
            )
            late = var()
            h.addConstr(late >= start - after_end - task.within_min - 48 * 60 * skips[task.name])
            lateness.append(late)
        preceding = by_name.get(task.follows or "")
        if preceding is not None:
            # Un cycle à la fois : celui-ci après la fin du précédent, s'il est placé (un cycle
            # non placé finit à 0) ; non placé lui-même, rien ne le retient.
            start = sum(s * x for s, x in choices[task.name].items())
            preceding_end = sum(
                (s + preceding.slot_min) * x for s, x in choices[preceding.name].items()
            )
            limit = 24 * 60 + preceding.overflow_min
            h.addConstr(start >= preceding_end - limit * skips[task.name])

    load: dict[int, Any] = {hour: problem.fixed_kwh.get(hour, 0.0) for hour in hours}
    night = problem.overnight
    later = list(night.problem_hours) if night else []
    for hour in later:  # prolongement : parts du lendemain des cycles gelés ou lancés
        load[hour] = night.fixed_kwh.get(hour - 24, 0.0) if night else 0.0
    # Triphasé : ce que les équipements placés tirent sur chaque phase, heure par heure.
    # Suivi pour la limite de puissance par phase, et pour les batteries qui ne compensent
    # que leur phase.
    limited = problem.phase_limit_kwh is not None
    tracked = limited or bool(problem.line_batteries) or problem.separate_phases
    phase_load: dict[tuple[Phase, int], Any] = {
        (line, hour): problem.fixed_by_phase.get(line, {}).get(hour, 0.0)
        + problem.base_by_phase.get(line, {}).get(hour % 24, 0.0)
        for line in (LINES if tracked else ())
        for hour in hours + later
    }
    decided: set[tuple[Phase, int]] = set()  # heures d'une phase où quelque chose se décide

    def on_phase(name: str, hour: int, kwh: Any) -> None:
        for line, share in line_shares(problem.phases.get(name)).items():
            if (line, hour) in phase_load:
                phase_load[line, hour] = phase_load[line, hour] + share * kwh
                decided.add((line, hour))

    for task in problem.tasks:
        for start, x in choices[task.name].items():
            for hour, kwh in task.hourly_kwh(start).items():
                if hour in load and kwh:
                    load[hour] = load[hour] + kwh * x
                    on_phase(task.label, hour, kwh * x)

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
            drawn = sum(kw * speeds[mode][hour] for mode, kw in runtime.speeds)
            load[hour] = load[hour] + drawn
            on_phase(runtime.name, hour, drawn)
            violated = problem.soft_violated(runtime.name, hour * 60, hour * 60 + 60)
            if violated:
                penalties.append(len(violated) * on)
        on_hours = sum(speeds[mode][hour] for mode in speeds for hour in hours)
        # La durée minimale peut ne plus tenir (contraintes horaires, ou trop peu d'heures
        # restantes : premier calcul tard le soir) : l'heure manquante est pénalisée et
        # signalée, sans rendre le problème impossible.
        missing = var(0, runtime.min_hours)
        shortfalls.append(missing)
        h.addConstr(on_hours + missing >= runtime.min_hours)
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
            on_phase(need.name, hour, kwh)
            violated = problem.soft_violated(need.name, hour * 60, hour * 60 + 60)
            if violated:
                penalties.append(len(violated) / need.max_kw * kwh)
        deliveries[need.name] = delivered
        shortfalls.append(short)

    # --- Triphasé : limite de puissance de chaque phase, souple -------------------------------
    over_phase: list[Any] = []
    production = _extended(problem.production_kwh, night.production_kwh if night else None)
    for line, hour in sorted(decided if limited else (), key=lambda key: (key[1], key[0])):
        over = var()
        solar = problem.production_shares.get(line, 0.0) * max(0.0, production.get(hour, 0.0))
        h.addConstr(phase_load[line, hour] - solar <= problem.phase_limit_kwh + over)
        over_phase.append(over)

    # --- Batterie (comportement glouton) et réseau ---------------------------------------
    full_hours: list[Any] = []
    throughput: list[Any] = []  # énergie qui passe par la batterie (ménagement)

    def battery_hour(
        battery: BatteryModel, stored: Any, hour: int, drawn: Any, injected: Any, floor: float
    ) -> tuple[Any, Any]:
        """Une heure d'une batterie qui compense ce qui est soutiré (``drawn``) et injecté
        (``injected``) là où elle est branchée : le réseau, ou sa seule phase. Renvoie son
        contenu en fin d'heure et ce qu'elle échange côté maison (positif : charge)."""
        charge = var(0, battery.charge_max_kw)
        discharge = var(0, battery.discharge_max_kw)
        throughput.append(charge + discharge)
        charging = var(0, 1, True)
        h.addConstr(charge <= battery.charge_max_kw * charging)
        h.addConstr(discharge <= battery.discharge_max_kw * (1 - charging))
        h.addConstr(drawn <= BIG_KWH * (1 - charging))
        h.addConstr(injected <= BIG_KWH * charging)
        soc = var(0, battery.capacity_kwh)
        h.addConstr(
            soc
            == stored
            + battery.charge_efficiency * charge
            - (1 / battery.discharge_efficiency) * discharge
        )
        # Plancher : la batterie n'y descend pas. Déjà dessous (départ bas, ou plage plus
        # haute qui commence), elle cesse de se décharger, comme dans la simulation, au lieu
        # de rendre le problème impossible. Batterie sous le plancher sans décharger en
        # heure de déficit : seulement si le contenu était déjà au plancher ou dessous (le
        # soutirage exige sinon la pleine puissance de décharge, ci-dessous).
        if floor > 0:
            below = var(0, 1, True)
            h.addConstr(soc >= floor - floor * below)
            h.addConstr(discharge <= battery.discharge_max_kw * (1 - below))
        # Injection seulement batterie à pleine puissance ou pleine ; soutirage seulement
        # à pleine puissance de décharge ou au plancher.
        charge_max, at_cap = var(0, 1, True), var(0, 1, True)
        h.addConstr(injected <= BIG_KWH * (charge_max + at_cap))
        h.addConstr(charge >= battery.charge_max_kw * charge_max)
        h.addConstr(soc >= battery.capacity_kwh * at_cap)
        discharge_max, at_floor = var(0, 1, True), var(0, 1, True)
        h.addConstr(drawn <= BIG_KWH * (discharge_max + at_floor))
        h.addConstr(discharge >= battery.discharge_max_kw * discharge_max)
        h.addConstr(soc <= floor + battery.capacity_kwh * (1 - at_floor))
        if hour < 24:  # batterie pleine dans la journée seulement
            full = var(0, 1, True)
            h.addConstr(soc >= battery.full_kwh * full)
            full_hours.append(full)
        return soc, charge - discharge

    def active(battery: BatteryModel, clock: int) -> bool:
        return battery.active_from <= clock < battery.active_to and battery.capacity_kwh > 0

    # Batteries qui ne compensent que leur phase : chaque groupe voit le bilan de sa phase.
    # Celle qui compense le total (toutes, hors triphasé) passe après elles.
    battery = problem.total_battery
    soc_previous: Any = battery.stored_kwh
    line_stored: dict[Phase, Any] = {
        line: group.stored_kwh for line, group in problem.line_batteries.items()
    }
    imports, exports = {}, {}
    # Compteur qui compte chaque phase à part : soutirage et injection de chaque phase.
    bought: dict[int, list[Any]] = defaultdict(list)
    sold: dict[int, list[Any]] = defaultdict(list)
    over_contract: list[Any] = []  # soutirage au-delà de la puissance souscrite (lot 7.3)
    net = _extended(problem.net_kwh, night.net_kwh if night else None)
    for hour in hours + later:
        imports[hour], exports[hour] = var(), var()
        if problem.contract_kwh is not None:
            over = var()
            h.addConstr(imports[hour] <= problem.contract_kwh + over)
            over_contract.append(over)
        balance = net.get(hour, 0.0) - load[hour]
        clock = hour % 24  # heure du lendemain dans le prolongement
        # Échange de chaque phase, avant ce qui n'est sur aucune (ci-dessous).
        line_residual: dict[Phase, Any] = {
            line: problem.production_shares.get(line, 0.0) * max(0.0, production.get(hour, 0.0))
            - phase_load[line, hour]
            for line in (LINES if tracked else ())
        }
        for line, group in problem.line_batteries.items():
            if not active(group, clock):
                continue
            drawn, injected = var(), var()  # échanges de la phase, après sa batterie
            solar = problem.production_shares.get(line, 0.0) * max(0.0, production.get(hour, 0.0))
            line_residual[line] = injected - drawn
            line_stored[line], exchanged = battery_hour(
                group, line_stored[line], hour, drawn, injected, group.floor_at(clock)
            )
            h.addConstr(solar - phase_load[line, hour] - exchanged == injected - drawn)
            balance = balance - exchanged
        if active(battery, clock):
            if problem.line_batteries:
                floor = battery.floor_at(clock)
            elif night and hour >= 24:
                floor = night.floor_kwh.get(clock, battery.floor_kwh)
            else:
                floor = battery.floor_at(hour)
            soc_previous, exchanged = battery_hour(
                battery, soc_previous, hour, imports[hour], exports[hour], floor
            )
            balance = balance - exchanged
        else:
            # Soutirer et injecter la même heure : exclu (les heures de batterie l'excluent déjà
            # par ``charging``). Sinon, un prix de soutirage négatif ou une revente plus chère que
            # l'achat rendent ce va-et-vient rentable sans fin : problème non borné, ou objectif
            # faussé jusqu'à la puissance souscrite.
            exporting = var(0, 1, True)
            h.addConstr(exports[hour] <= BIG_KWH * exporting)
            h.addConstr(imports[hour] <= BIG_KWH * (1 - exporting))
        h.addConstr(balance == exports[hour] - imports[hour])
        if problem.separate_phases:
            # Ce qui n'est sur aucune phase (équipement ou production sans phase, batterie
            # qui compense le total) : réparti à parts égales sur les trois.
            rest = exports[hour] - imports[hour] - sum(line_residual.values())
            for line in LINES:
                drawn, injected, selling = var(), var(), var(0, 1, True)
                h.addConstr(line_residual[line] + (1 / 3) * rest == injected - drawn)
                h.addConstr(injected <= BIG_KWH * selling)
                h.addConstr(drawn <= BIG_KWH * (1 - selling))
                bought[hour].append(drawn)
                sold[hour].append(injected)
    full_day = var(0, 1, True)
    h.addConstr(full_day <= (sum(full_hours) if full_hours else 0))

    # Prix du tarif de la maison (lot 3.2) ; le kWh injecté rapporte son prix de revente.
    weight, export_cost, cheapest = _terms(problem, objective)
    # Un kWh stocké à minuit vaut le kWh soutiré le moins cher, pas plus : au-delà, le moteur
    # soutirerait la nuit pour garder la batterie pleine (mesuré au lot 2.6).
    stored_value = cheapest * battery.discharge_efficiency
    bonus = FULL_PRIORITY_BONUS if battery.full_priority else FULL_BONUS
    mean_weight = sum(weight[hour] for hour in hours) / len(hours) if hours else 0.0
    kept = [
        KEEP_MARGIN * task.energy_kwh * mean_weight * choices[task.name][task.announced_min]
        for task in problem.tasks
        if task.chosen_min is None
        and task.announced_min is not None
        and task.announced_min in choices[task.name]
    ]
    h.minimize(
        sum(
            # Compteur qui compte chaque phase à part : le coût porte sur chacune.
            weight[hour] * sum(bought[hour]) + export_cost[hour] * sum(sold[hour])
            if problem.separate_phases
            else weight[hour] * imports[hour] + export_cost[hour] * exports[hour]
            for hour in hours + later
        )
        - stored_value * (soc_previous + sum(line_stored.values()))
        - bonus * full_day
        - sum(kept)
        + SKIP_PENALTY * sum(skips.values())
        + SKIP_PENALTY * sum(shortfalls)  # par kWh manquant : seulement s'il ne tient plus
        + SOFT_PENALTY * sum(penalties)
        + LATE_PENALTY / 60 * sum(lateness)
        + CONTRACT_PENALTY * sum(over_contract)
        + PHASE_PENALTY * sum(over_phase)
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
    if h.getInfo().primal_solution_status != highspy.SolutionStatus.kSolutionStatusFeasible:
        # Limite de temps atteinte avant toute solution : les valeurs lues seraient des zéros,
        # pris pour un plan (tâches au premier départ). Le plan précédent reste en place.
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


def phase_excess(problem: Problem, plan: Plan) -> dict[Phase, list[int]]:
    """Triphasé : heures du jour où les équipements placés (et les cycles déjà décidés) tirent
    ensemble, sur une phase, plus que sa part de la puissance souscrite, avec la consommation
    de base de la phase si elle est mesurée, la production branchée sur cette phase déduite.
    Seules les heures où un équipement placé ou décidé tourne sur la phase : la consommation de
    base seule n'est pas l'affaire du plan. Phases sans dépassement absentes."""
    if problem.phase_limit_kwh is None:
        return {}
    drawn, busy = _phase_drawn(problem, plan)
    found: dict[Phase, list[int]] = {}
    for line in LINES:
        share = problem.production_shares.get(line, 0.0)
        over = [
            hour
            for hour in problem.hours
            if hour in busy[line]
            and drawn[line][hour]
            + problem.base_by_phase.get(line, {}).get(hour, 0.0)
            - share * max(0.0, problem.production_kwh.get(hour, 0.0))
            > problem.phase_limit_kwh + 0.001
        ]
        if over:
            found[line] = over
    return found


def _phase_drawn(
    problem: Problem, plan: Plan
) -> tuple[dict[Phase, dict[int, float]], dict[Phase, set[int]]]:
    """(ce que les équipements placés et les cycles déjà décidés tirent sur chaque phase, par
    heure ; heures où l'un d'eux tourne sur la phase). Sans la consommation de base."""
    drawn: dict[Phase, dict[int, float]] = {
        line: defaultdict(float, problem.fixed_by_phase.get(line, {})) for line in LINES
    }
    busy = {line: {hour for hour, kwh in drawn[line].items() if kwh > 0} for line in LINES}

    def on_phase(name: str, hour: int, kwh: float) -> None:
        for line, share in line_shares(problem.phases.get(name)).items():
            drawn[line][hour] += share * kwh
            if kwh > 0:
                busy[line].add(hour)

    by_name = {task.name: task for task in problem.tasks}
    for name, start in plan.starts.items():
        for hour, kwh in by_name[name].hourly_kwh(start).items():
            on_phase(by_name[name].label, hour, kwh)
    for runtime in problem.runtimes:
        for hour, mode in plan.runtimes.get(runtime.name, {}).items():
            on_phase(runtime.name, hour, runtime.kw(mode))
    for name, delivered in plan.needs.items():
        for hour, kwh in delivered.items():
            on_phase(name, hour, kwh)
    return drawn, busy


def simulate_plan(problem: Problem, plan: Plan) -> BatteryRun:
    """Batterie simulée sur le plan. Avec des batteries qui ne compensent que leur phase :
    chaque groupe sur le bilan de sa phase (production de la phase, moins sa consommation de
    base et ses équipements), puis celle qui compense le total sur ce qui reste ; le résultat
    réunit les groupes (``BatteryRun.lines`` garde chacun). Dès que le calcul distingue les
    phases : l'échange de chaque phase (``BatteryRun.phase_residual_kwh``)."""
    load = load_kwh(problem, plan)
    net = {hour: problem.net_kwh.get(hour, 0.0) - load[hour] for hour in problem.hours}
    if not problem.line_batteries and not problem.separate_phases:
        return _simulate(problem.battery, net, problem.first_hour)
    drawn, _ = _phase_drawn(problem, plan)
    lines: dict[Phase, BatteryRun] = {}
    line_residual: dict[Phase, Mapping[int, float]] = {}
    exchanged: dict[int, float] = defaultdict(float)  # côté maison, positif : charge
    for line in LINES:
        share = problem.production_shares.get(line, 0.0)
        line_net = {
            hour: share * max(0.0, problem.production_kwh.get(hour, 0.0))
            - drawn[line][hour]
            - problem.base_by_phase.get(line, {}).get(hour, 0.0)
            for hour in problem.hours
        }
        line_residual[line] = line_net
        group = problem.line_batteries.get(line)
        if group is None:
            continue
        lines[line] = _simulate(group, line_net, problem.first_hour)
        line_residual[line] = lines[line].residual_kwh
        for hour in problem.hours:
            taken = line_net[hour] - lines[line].residual_kwh[hour]
            exchanged[hour] += taken
            net[hour] -= taken
    shared = _simulate(problem.total_battery, net, problem.first_hour)
    # Ce qui n'est sur aucune phase (équipement ou production sans phase, batterie qui compense
    # le total) : réparti à parts égales sur les trois, comme dans le moteur.
    by_phase = {
        line: {
            hour: line_residual[line][hour]
            + (shared.residual_kwh[hour] - sum(line_residual[n][hour] for n in LINES)) / 3
            for hour in problem.hours
        }
        for line in LINES
    }
    if not lines:
        return replace(shared, phase_residual_kwh=by_phase)
    for hour in problem.hours:
        exchanged[hour] += net[hour] - shared.residual_kwh[hour]
    runs = [shared, *lines.values()]
    return BatteryRun(
        phase_residual_kwh=by_phase,
        # Une charge et une décharge de la même heure, sur deux phases, se compensent ici.
        movements=[
            Movement(hour, "charge" if kwh > 0 else "decharge", round(abs(kwh), 3))
            for hour, kwh in sorted(exchanged.items())
            if round(abs(kwh), 3) > 0
        ],
        end_kwh=sum(run.end_kwh for run in runs),
        soc_kwh={hour: sum(run.soc_kwh[hour] for run in runs) for hour in shared.soc_kwh},
        residual_kwh=shared.residual_kwh,
        lines=lines,
        shared=shared,
    )


def _simulate(battery: BatteryModel, net: Mapping[int, float], first_hour: int) -> BatteryRun:
    return simulate(
        net,
        battery.stored_kwh,
        battery.capacity_kwh,
        battery.charge_max_kw,
        battery.discharge_max_kw,
        battery.active_from,
        battery.active_to,
        battery.charge_efficiency,
        battery.discharge_efficiency,
        battery.floor_kwh,
        first_hour=first_hour,
        floor_by_hour=battery.floor_by_hour,
        elapsed=battery.hour_elapsed,
        elapsed_change_kwh=battery.hour_change_kwh,
    )


def overnight_kwh(problem: Problem, plan: Plan) -> dict[int, float]:
    """Consommation du prolongement après minuit, par heure du lendemain : parts du lendemain
    des cycles fixés et des tâches placées."""
    night = problem.overnight
    if night is None:
        return {}
    load = {hour: night.fixed_kwh.get(hour, 0.0) for hour in range(night.hours)}
    by_name = {task.name: task for task in problem.tasks}
    for name, start in plan.starts.items():
        for hour, kwh in by_name[name].hourly_kwh(start).items():
            if hour - 24 in load:
                load[hour - 24] += kwh
    return load


def with_overnight(problem: Problem, plan: Plan, run: BatteryRun, day: Indicators) -> Indicators:
    """Indicateurs de la journée augmentés de ceux du prolongement après minuit (batterie
    simulée à partir de la fin de journée, tarif du lendemain) : pour comparer des départs dont
    l'un déborde. Sans prolongement : ceux de la journée."""
    night = problem.overnight
    if night is None:
        return day
    battery = problem.battery
    load = overnight_kwh(problem, plan)
    later = simulate(
        {hour: night.net_kwh.get(hour, 0.0) - load[hour] for hour in load},
        run.end_kwh,
        battery.capacity_kwh,
        battery.charge_max_kw,
        battery.discharge_max_kw,
        battery.active_from,
        battery.active_to,
        battery.charge_efficiency,
        battery.discharge_efficiency,
        battery.floor_kwh,
        floor_by_hour=night.floor_kwh,
    )
    imported = {h: max(0.0, -kwh) for h, kwh in later.residual_kwh.items() if h in load}
    exported = {h: max(0.0, kwh) for h, kwh in later.residual_kwh.items() if h in load}
    price, export_price = night.prices_eur_kwh, night.export_prices_eur_kwh
    cost = sum(price.get(h, 0.0) * kwh for h, kwh in imported.items()) - sum(
        export_price.get(h, 0.0) * kwh for h, kwh in exported.items()
    )
    co2 = sum(night.co2_g_kwh.get(h, 0.0) * kwh for h, kwh in imported.items()) / 1000
    return day.model_copy(
        update={
            "cost_eur": round(day.cost_eur + cost, 3),
            "import_kwh": round(day.import_kwh + sum(imported.values()), 3),
            "export_kwh": round(day.export_kwh + sum(exported.values()), 3),
            "battery_throughput_kwh": round(
                day.battery_throughput_kwh
                + sum(m.energy_kwh for m in later.movements if m.hour in load),
                3,
            ),
            "co2_kg": round(day.co2_kg + co2, 3) if day.co2_kg is not None else None,
        }
    )


def _hhmm(minutes: int) -> str:
    hours, rest = divmod(int(minutes), 60)
    hours %= 24  # fin le lendemain (débordement après minuit) : « 1h », pas « 25h »
    return f"{hours}h{rest:02d}" if rest else f"{hours}h"


def _justification(plan: Plan, parent: Task | None) -> str:
    if parent is not None and parent.name in plan.starts:
        end = _hhmm(plan.starts[parent.name] + parent.slot_min)
        return f"Démarre après la fin de '{parent.label}' ({end}), le même jour."
    return "Placé par l'optimiseur au meilleur moment de la journée."


def _occurrence(rank: int, uid: str | None) -> dict[str, Any]:
    """Rang d'un créneau (à partir du deuxième cycle de l'équipement) et tâche dont il est le
    cycle : écrits seulement s'ils sont connus, le plan d'un seul cycle reste celui d'avant."""
    return {**({"rank": rank} if rank > 1 else {}), **({"request": uid} if uid else {})}


def _blocked(problem: Problem, task: Task) -> bool:
    """Tâche que ses contraintes dures empêchent de placer alors que le temps le permettait."""
    starts = task.candidates()
    return bool(starts) and all(
        problem.hard_blocks(task.label, s, s + task.slot_min) for s in starts
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
                device=launched.label,
                **_occurrence(launched.rank, launched.uid),
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
            warnings.append(_impossible(problem, task.label))
            continue
        if start is None:
            warnings.append(
                {
                    "code": "heures_insuffisantes_" + ("du" if task.priority == 1 else "attente"),
                    "params": {
                        "equipement": task.label,
                        "duree_min": task.slot_min,
                        "debut_min": task.earliest_min,
                    },
                }
            )
            continue
        end = start + task.slot_min
        _check_soft(problem, task.label, [(start, end)], warnings)
        parent = by_key.get(task.depends_on or "")
        after_end = (
            plan.starts[parent.name] + parent.slot_min
            if parent is not None and parent.name in plan.starts
            else task.after_end_min
        )
        if (
            task.within_min is not None
            and after_end is not None
            and start > after_end + task.within_min
        ):
            warnings.append(
                {
                    "code": "delai_apres_depasse",
                    "params": {
                        "equipement": task.label,
                        "apres": task.after_label or "",
                        "delai_min": task.within_min,
                        "attente_min": start - after_end,
                    },
                }
            )
        items.append(
            Slot(
                device=task.label,
                **_occurrence(task.rank, task.uid),
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

    def planned(found: BatteryRun) -> list[PlannedMovement]:
        return [
            PlannedMovement(hour=m.hour, action=m.action, energy_kwh=m.energy_kwh)
            for m in found.movements
        ]

    # Calcul par phase : la prévision de chaque groupe de batteries, pour une ligne de la frise
    # chacune ; celles qui compensent le total (phase 0) seulement s'il y en a.
    def group(phase: int, found: BatteryRun, capacity_kwh: float) -> BatteryGroup:
        return BatteryGroup(
            phase=phase,
            movements=planned(found),
            soc_kwh={hour: round(v, 3) for hour, v in found.soc_kwh.items()},
            capacity_kwh=round(capacity_kwh, 3),
        )

    groups = [
        group(LINES.index(line) + 1, run.lines[line], problem.line_batteries[line].capacity_kwh)
        for line in LINES
        if line in run.lines
    ]
    if groups and run.shared is not None and problem.total_battery.capacity_kwh > 0:
        groups.append(group(0, run.shared, problem.total_battery.capacity_kwh))
    charges = [m for m in run.movements if m.action == "charge"]
    discharges = [m for m in run.movements if m.action == "decharge"]
    whole = BatteryPlan(
        device=BATTERY,
        movements=planned(run),
        soc_kwh={hour: round(v, 3) for hour, v in run.soc_kwh.items()},
        charged_kwh=round(sum(m.energy_kwh for m in charges), 3),
        discharged_kwh=round(sum(m.energy_kwh for m in discharges), 3),
        # Début de la première heure : mesuré maintenant, moins sa part déjà écoulée.
        start_kwh=round(battery.stored_kwh - battery.hour_change_kwh, 3),
        end_kwh=round(run.end_kwh, 3),
        priority=2,
        justification=(
            f"Autoconsommation simulée heure par heure à partir de {problem.first_hour}h "
            f"(SoC {battery.soc_percent}%, {battery.stored_kwh} kWh) ; plage active "
            f"{battery.active_from}h-{battery.active_to}h."
        ),
    )
    items.append(whole.model_copy(update={"groups": groups}) if groups else whole)
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
        if len(running) < runtime.min_hours:
            warnings.append(
                _impossible(problem, runtime.name)
                if runtime.name in problem.constraints
                else {
                    "code": "duree_minimale_non_tenue",
                    "params": {
                        "equipement": runtime.name,
                        "heures": len(running),
                        "minimum": runtime.min_hours,
                    },
                }
            )
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
    for line, phase_hours in phase_excess(problem, plan).items():
        warnings.append(
            {
                "code": "phase_depassee",
                "params": {
                    "phase": str(LINES.index(line) + 1),
                    "kva": f"{problem.phase_limit_kwh:g}",
                    "heures": ", ".join(str(hour) for hour in phase_hours),
                },
            }
        )
    # Calcul par phase : ce que les écrans doivent en savoir, absent sinon.
    by_phase: dict[str, Any] = {}
    if run.phase_residual_kwh:
        by_phase["phase_residual_kwh"] = {
            LINES.index(line) + 1: {h: round(kwh, 3) for h, kwh in hourly.items()}
            for line, hourly in run.phase_residual_kwh.items()
        }
    if problem.separate_phases:
        by_phase["separate_phases"] = True
    if problem.line_batteries:
        by_phase["phase_batteries"] = True
    return DayPlan(
        items=items,
        warnings=warnings,
        residual_kwh=dict(run.residual_kwh),
        indicators=indicators(problem, run),
        **by_phase,
    )


def _over_contract(problem: Problem, run: BatteryRun) -> list[int]:
    """Heures où le soutirage simulé dépasse la puissance souscrite (lot 7.3)."""
    if problem.contract_kwh is None:
        return []
    limit = problem.contract_kwh + 0.001
    return sorted(hour for hour, kwh in run.residual_kwh.items() if -kwh > limit)


def indicators(problem: Problem, run: BatteryRun) -> Indicators:
    """Indicateurs du plan (lot 3.6) sur les heures calculées : échanges avec le réseau après
    la batterie simulée, au tarif de la maison. Avec un compteur qui compte chaque phase à
    part, soutirage et injection sont ceux de chaque phase, additionnés : ce que le compteur
    facture."""
    # Sans compteur par phase : un seul échange, celui de la maison.
    counted = (
        list(run.phase_residual_kwh.values())
        if problem.separate_phases and run.phase_residual_kwh
        else [run.residual_kwh]
    )
    imported = {h: sum(max(0.0, -phase[h]) for phase in counted) for h in run.residual_kwh}
    exported = {h: sum(max(0.0, phase[h]) for phase in counted) for h in run.residual_kwh}
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


def _score(objective: Goal, price_scale: float = 1.0) -> Callable[[Indicators], float]:
    """Note d'un plan selon l'objectif (plus bas : meilleur), pour choisir une alternative ; le
    coût est ramené à l'échelle de l'euro (``Problem.price_scale``) face aux kWh valorisés."""
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
        weights.cost * found.cost_eur / price_scale
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
            changed = replace(plan, starts=starts)
            day_run = simulate_plan(problem, changed)
            return with_overnight(problem, changed, day_run, indicators(problem, day_run))

        name = objective.value if isinstance(objective, Objective) else "custom"
        day = explain(
            problem,
            day,
            plan.starts,
            load_kwh(problem, plan),
            name,
            evaluate,
            _score(objective, problem.price_scale),
        )
    return Result(
        plan=plan,
        day=day,
        output=day.to_v1(),
        battery=run,
        seconds=time.perf_counter() - began,
    )
