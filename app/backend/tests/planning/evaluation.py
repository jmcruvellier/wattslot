"""Évaluateur du banc de l'optimiseur (lot 2.6) : un plan (départs des tâches, modes de la
piscine) → indicateurs, sur le problème de la v1 figé pour une journée type.

Le plan de la v1 et celui de la v2 passent par le même évaluateur, qui suit la simulation de la
batterie de la v1 (mode autoconsommation : charge sur le surplus, décharge sur le déficit, dans
les limites de puissance, de capacité et du plancher). Toute la consommation (piscine comprise)
est comptée avant la batterie. La simulation est celle de la v2, identique à celle de la v1
(``test_simulation.py``), comme la consommation d'un cycle par heure (``test_cycles.py``) ; les
tests vérifient en plus, sur chaque journée, que cet évaluateur redonne les indicateurs figés du
plan de la v1.

``problem`` : le problème figé de la v1 (``v1("prototype.problem", state)``), en données simples.
"""

from dataclasses import dataclass
from typing import Any

from wattslot.planning.cycles import PlannedCycle, planned_hourly
from wattslot.planning.simulation import simulate

# Tarif de référence pour comparer les coûts (heures creuses 0 h - 6 h et 22 h - 24 h) : prix
# indicatifs, seul l'écart entre les deux plans compte.
PRICE_PEAK_EUR = 0.27
PRICE_OFF_PEAK_EUR = 0.21
OFF_PEAK_HOURS = frozenset(range(0, 6)) | frozenset(range(22, 24))
DAY_MIN = 24 * 60


def price(hour: int) -> float:
    return PRICE_OFF_PEAK_EUR if hour in OFF_PEAK_HOURS else PRICE_PEAK_EUR


@dataclass(frozen=True)
class Plan:
    starts: dict[str, int]  # nom de la tâche → départ (minutes depuis minuit)
    pool: dict[int, str]  # heure → "off" | "silence" | "eco"


@dataclass(frozen=True)
class Indicators:
    import_kwh: float
    export_kwh: float
    cost_eur: float
    self_consumption_percent: float | None  # part de la production consommée sur place
    end_soc_percent: float
    peak_soc_percent: float
    battery_full: bool
    pool_hours: int
    pool_kwh: float
    violations: tuple[str, ...]  # contraintes non respectées


def hours(problem: dict[str, Any]) -> range:
    return range(problem["first_hour"], 24)


def load_kwh(problem: dict[str, Any], plan: Plan) -> dict[int, float]:
    """Consommation décidée (tâches, piscine) et fixée, heure par heure."""
    load = {h: problem["fixed_kwh"].get(h, 0.0) for h in hours(problem)}
    by_name = {task["name"]: task for task in problem["tasks"]}
    for name, start in plan.starts.items():
        task = by_name[name]
        cycle = PlannedCycle(start, start + task["slot_min"], task["energy_kwh"], task["shape"])
        for hour, kwh in planned_hourly(cycle).items():
            if hour in load:
                load[hour] += kwh
    pool = problem["pool"]
    for hour in hours(problem):
        mode = plan.pool.get(hour, "off")
        load[hour] += {"eco": pool["eco_kw"], "silence": pool["silence_kw"]}.get(mode, 0.0)
    return load


def violations(problem: dict[str, Any], plan: Plan) -> list[str]:
    found = []
    by_key = {task["key"]: task for task in problem["tasks"]}
    ends = dict(problem["fixed_ends"])
    for task in problem["tasks"]:
        start = plan.starts.get(task["name"])
        if start is None:
            found.append(f"{task['name']} non placé")
            continue
        ends[task["key"]] = start + task["slot_min"]
        if start < task["earliest_min"] or start + task["slot_min"] > DAY_MIN:
            found.append(f"{task['name']} hors de la journée ou trop tôt")
    for task in problem["tasks"]:
        start = plan.starts.get(task["name"])
        parent = task["depends_on"]
        if start is not None and parent in by_key and start < ends.get(parent, 0):
            found.append(f"{task['name']} démarre avant la fin de {by_key[parent]['name']}")
    on = [h for h in hours(problem) if plan.pool.get(h, "off") != "off"]
    if len(on) < problem["pool"]["min_hours"]:
        found.append(f"filtration {len(on)} h < minimum {problem['pool']['min_hours']} h")
    return found


def evaluate(problem: dict[str, Any], plan: Plan) -> Indicators:
    load = load_kwh(problem, plan)
    net = {h: problem["net_kwh"].get(h, 0.0) - load[h] for h in hours(problem)}
    battery = problem["battery"]
    run = simulate(
        net,
        battery["stored_kwh"],
        battery["capacity_kwh"],
        battery["charge_max_kw"],
        battery["discharge_max_kw"],
        battery["active_from"],
        battery["active_to"],
        battery["charge_efficiency"],
        battery["discharge_efficiency"],
        battery["floor_kwh"],
        first_hour=problem["first_hour"],
    )
    residual = run.residual_kwh
    imported = {h: max(0.0, -residual[h]) for h in hours(problem)}
    exported = {h: max(0.0, residual[h]) for h in hours(problem)}
    production = sum(max(0.0, problem["production_kwh"].get(h, 0.0)) for h in hours(problem))
    capacity = battery["capacity_kwh"] or 1.0
    peak = max(run.soc_kwh.values()) if run.soc_kwh else battery["stored_kwh"]
    pool = problem["pool"]
    pool_on = [h for h in hours(problem) if plan.pool.get(h, "off") != "off"]
    return Indicators(
        import_kwh=sum(imported.values()),
        export_kwh=sum(exported.values()),
        cost_eur=sum(price(h) * kwh for h, kwh in imported.items()),
        self_consumption_percent=(
            100 * (production - sum(exported.values())) / production if production > 0.01 else None
        ),
        end_soc_percent=100 * run.end_kwh / capacity,
        peak_soc_percent=100 * peak / capacity,
        battery_full=100 * peak / capacity >= problem["full_percent"],
        pool_hours=len(pool_on),
        pool_kwh=sum(
            pool["eco_kw"] if plan.pool[h] == "eco" else pool["silence_kw"] for h in pool_on
        ),
        violations=tuple(violations(problem, plan)),
    )
