"""Moteur : même problème que la v1, plan au moins aussi bon (décision 11), sortie au format v1.

Oracles, figés sur les 13 journées types : le problème que pose le prototype du lot 2.6 avec les
fonctions de la v1, le plan de la v1 et ses indicateurs selon l'évaluateur du prototype (repris
dans ``evaluation.py``, qui juge aussi le plan de la v2).
"""

from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import pytest

from tests.planning import evaluation
from tests.v1_oracle import STATES, load, state_named, v1
from wattslot.planning.engine import (
    Objective,
    Plan,
    indicators,
    plan_day,
    simulate_plan,
    solve,
)
from wattslot.planning.inputs import from_v1
from wattslot.planning.plan import POOL, Indicators
from wattslot.planning.problem import Problem, from_input

IDS = [p.stem for p in STATES]
CASES = [(path, objective) for path in STATES for objective in Objective]
TOLERANCE_KWH, TOLERANCE_EUR, TOLERANCE_POINTS = 0.05, 0.02, 1.0


FIELDS = (
    "name",
    "key",
    "energy_kwh",
    "cycle_min",
    "slot_min",
    "shape",
    "priority",
    "earliest_min",
    "depends_on",
)


def _tasks(tasks: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    """Tâches à placer, triées : l'ordre n'a pas d'effet sur l'optimiseur. Une dépendance vers
    une tâche qui n'est pas à placer (gelée ou lancée) ne compte que par l'heure au plus tôt :
    le prototype la garde, la réécriture la retire."""
    keys = {t["key"] for t in tasks}
    return sorted(
        (*(t[f] for f in FIELDS[:-1]), t["depends_on"] if t["depends_on"] in keys else None)
        for t in tasks
    )


@pytest.mark.parametrize("path", STATES, ids=IDS)
def test_problem_is_the_problem_of_v1(path: Path) -> None:
    state, _ = load(path)
    expected = v1("prototype.problem", state)

    problem = from_input(from_v1(state))

    assert problem.first_hour == expected["first_hour"]
    for hour in range(24):
        assert problem.fixed_kwh[hour] == pytest.approx(expected["fixed_kwh"][hour], abs=1e-9)
    ours = [{f: getattr(t, f) for f in FIELDS} for t in problem.tasks]
    assert _tasks(ours) == _tasks(expected["tasks"])
    battery, expected_battery = problem.battery, expected["battery"]
    assert (battery.active_from, battery.active_to) == (
        expected_battery["active_from"],
        expected_battery["active_to"],
    )
    assert battery.charge_efficiency == pytest.approx(expected_battery["charge_efficiency"])
    assert battery.discharge_efficiency == pytest.approx(expected_battery["discharge_efficiency"])
    assert battery.floor_kwh == pytest.approx(expected_battery["floor_kwh"])
    pool = problem.runtimes[0]
    assert (pool.min_hours, pool.minimum_forced) == (
        expected["pool"]["min_hours"],
        expected["pool"]["minimum_forced"],
    )
    for task in problem.tasks:
        oracle = next(t for t in expected["tasks"] if t["name"] == task.name)
        assert set(task.candidates()) <= set(oracle["hourly"])
        for start in task.candidates():
            assert task.hourly_kwh(start) == pytest.approx(oracle["hourly"][start], abs=1e-9)


@pytest.mark.parametrize(("path", "objective"), CASES, ids=[f"{p.stem}-{o}" for p, o in CASES])
def test_plan_meets_decision_11(path: Path, objective: Objective) -> None:
    """Critère principal de l'objectif au moins aussi bon que la v1, autres indicateurs dans les
    tolérances du banc du prototype, contraintes respectées : jugé par la simulation de la v1."""
    state, _ = load(path)
    expected = v1("prototype.problem", state)
    of_v1 = v1("prototype.plan_of_v1", state)
    v1_plan = evaluation.Plan(starts=of_v1["starts"], pool=of_v1["pool"])
    result = plan_day(from_input(from_v1(state)), objective)
    ours = evaluation.Plan(starts=result.plan.starts, pool=result.plan.runtimes[POOL])

    a, b = evaluation.evaluate(expected, v1_plan), evaluation.evaluate(expected, ours)

    # L'évaluateur redonne les indicateurs du plan de la v1 selon celui du prototype.
    found, frozen = asdict(a), of_v1["indicators"]
    assert found.pop("violations") == frozen.pop("violations")
    assert found == pytest.approx(frozen, abs=1e-9)

    assert b.violations == ()
    if objective is Objective.SELF_CONSUMPTION:
        # Lot 3.6 : jugé sur son seul critère principal ; le coût et le soutirage peuvent y
        # céder (autoconsommer plus peut vouloir dire consommer en heures pleines).
        assert a.self_consumption_percent is None or (
            b.self_consumption_percent is not None
            and b.self_consumption_percent + 1e-6 >= a.self_consumption_percent
        )
        return
    if objective is Objective.CO2:
        # Sans intensité du réseau dans les captures : intensité uniforme, critère principal
        # le soutirage.
        assert b.import_kwh <= a.import_kwh + 1e-6
        return
    import_slack = 1e-6 if objective is Objective.IMPORT else TOLERANCE_KWH
    cost_slack = 1e-6 if objective is Objective.COST else TOLERANCE_EUR
    assert b.import_kwh <= a.import_kwh + import_slack
    assert b.cost_eur <= a.cost_eur + cost_slack
    if a.self_consumption_percent is not None:
        assert b.self_consumption_percent is not None
        assert b.self_consumption_percent + TOLERANCE_POINTS >= a.self_consumption_percent
    assert b.end_soc_percent + TOLERANCE_POINTS >= a.end_soc_percent


@pytest.mark.parametrize("path", STATES, ids=IDS)
def test_output_has_the_format_of_v1(path: Path) -> None:
    state, expected_output = load(path)
    problem = from_input(from_v1(state))

    output = plan_day(problem).output

    assert set(output) - {"indicateurs"} == set(expected_output)  # indicateurs : lot 3.6
    assert sorted(output["residu_reseau_horaire"]) == list(problem.hours)
    by_name = {item["equipement"]: item for item in output["planning"]}
    expected_by_name = {item["equipement"]: item for item in expected_output["planning"]}
    assert set(by_name) == set(expected_by_name)  # mêmes équipements que la v1
    for name, item in by_name.items():
        assert set(item) - {"explication"} == set(expected_by_name[name]), name  # lot 3.7
    assert sorted(by_name["Batterie"]["soc_horaire_kwh"]) == list(problem.hours)
    segments = by_name["Piscine (filtration)"]["segments"]
    assert segments[0]["heure_debut"] == problem.first_hour
    assert segments[-1]["heure_fin"] == 24


# --- Journées types modifiées : écarts trouvés par le balayage du lot 7.3 -------------------
# Propres à la v2 (sans résultat figé de la v1) : chaque journée publiée reçoit les valeurs
# d'une variante bruitée où le moteur faisait moins bien que la v1, ou plantait.


def _modified(stem: str, **battery: Any) -> Problem:
    problem = from_input(from_v1(load(state_named(stem))[0]))
    return replace(problem, battery=replace(problem.battery, **battery))


def _indicators(problem: Problem, plan: Plan) -> Indicators:
    return indicators(problem, simulate_plan(problem, plan))


def _pool_at(problem: Problem, hour: int) -> dict[str, dict[int, str]]:
    return {POOL: {h: "silence" if h == hour else "off" for h in problem.hours}}


@pytest.mark.parametrize("objective", list(Objective))
def test_plan_found_when_highs_wrongly_finds_no_plan(objective: Objective) -> None:
    """Journée 13, batterie, production et sèche-linge d'une variante : HiGHS 1.15 y déclare
    le problème impossible (objectif soutirage) alors qu'il a toujours une solution ; le moteur
    refait le calcul sans presolve."""
    problem = _modified(
        "synthetic_realignment_h13",
        capacity_kwh=5.33,
        stored_kwh=4.06,
        charge_max_kw=2.22,
        discharge_max_kw=0.71,
        charge_efficiency=0.9176,
        discharge_efficiency=0.9176,
        floor_kwh=0.6396,
        full_kwh=5.30335,
    )
    net = (1.879, 1.499, 1.221, 0.861, 0.579, 0.261, -0.081, -0.35, -0.356, -0.344, -0.196)
    problem = replace(
        problem,
        net_kwh=dict(zip(problem.hours, net, strict=True)),
        fixed_kwh={**problem.fixed_kwh, 13: 0.177, 14: 0.023},
        tasks=[replace(task, energy_kwh=1.016) for task in problem.tasks],
    )

    plan = solve(problem, objective)

    assert set(plan.starts) == {task.name for task in problem.tasks}


def test_full_battery_does_not_cost_import() -> None:
    """Journée 02, 2,41 kWh en batterie : filtrer à 22 h plutôt qu'à 13 h (plan de la v1)
    remplit la batterie mais soutire 0,13 kWh. La batterie pleine ne fait que départager."""
    problem = _modified("today_h12_water_heater", stored_kwh=2.41)
    of_v1 = Plan(starts={}, runtimes=_pool_at(problem, 13))

    plan = solve(problem, Objective.IMPORT)

    assert _indicators(problem, plan).import_kwh <= _indicators(problem, of_v1).import_kwh + 1e-6


def test_full_battery_does_not_cost_end_charge() -> None:
    """Journée 01, batterie de 5 kWh : décaler chauffe-eau et filtration (plan de la v1 :
    12 h et 13 h) la remplit, à coût égal, pour 4 à 5 points de SoC de moins à minuit."""
    problem = _modified("today_h06_no_measured_efficiency", capacity_kwh=5.0, full_kwh=4.975)
    of_v1 = Plan(starts={"Chauffe-eau": 720}, runtimes=_pool_at(problem, 13))

    found, expected = _indicators(problem, solve(problem)), _indicators(problem, of_v1)

    assert found.end_soc_percent is not None and expected.end_soc_percent is not None
    assert found.cost_eur <= expected.cost_eur + 1e-6
    assert found.end_soc_percent + TOLERANCE_POINTS >= expected.end_soc_percent
