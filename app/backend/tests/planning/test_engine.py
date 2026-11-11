"""Moteur : même problème que la v1, plan au moins aussi bon (décision 11), sortie au format v1.

Oracles, figés sur les 13 journées types : le problème que pose le prototype du lot 2.6 avec les
fonctions de la v1, le plan de la v1 et ses indicateurs selon l'évaluateur du prototype (repris
dans ``evaluation.py``, qui juge aussi le plan de la v2).
"""

import copy
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import pytest

from tests.planning import evaluation
from tests.v1_oracle import STATES, load, state_named, v1
from wattslot.objective_settings import Weights
from wattslot.planning.engine import (
    DEFAULT_CONTRACT_KWH,
    Goal,
    ImpossibleDataError,
    Objective,
    Plan,
    impossible_hour,
    indicators,
    plan_day,
    simulate_plan,
    solve,
)
from wattslot.planning.inputs import from_v1
from wattslot.planning.merge import merge_plans
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

    data = from_v1(state)
    problem = from_input(data)

    assert problem.first_hour == expected["first_hour"]
    for hour in range(24):
        assert problem.fixed_kwh[hour] == pytest.approx(expected["fixed_kwh"][hour], abs=1e-9)
    ours = [{f: getattr(t, f) for f in FIELDS} for t in problem.tasks]
    # Écart voulu à la v1 : le départ au plus tôt est l'instant du calcul, pas le début de
    # l'heure en cours (un calcul de 7 h 59 ne place plus un départ à 7 h 00). Ramené ici au
    # début de l'heure pour comparer le reste du problème.
    now = data.real_updated_at
    if now is not None and now.hour == problem.first_hour:
        for ours_task in ours:
            if ours_task["earliest_min"] == now.hour * 60 + now.minute:
                ours_task["earliest_min"] = now.hour * 60
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
        # Même écart : le départ « tout de suite » n'existe pas en v1, qui avait à sa place le
        # début de l'heure en cours.
        run_min = now.hour * 60 + now.minute if now is not None else None
        candidates = [s for s in task.candidates() if s != run_min or s in oracle["hourly"]]
        assert set(candidates) <= set(oracle["hourly"])
        for start in candidates:
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
    # Mêmes équipements que la v1, plus les blocs gelés dont le cycle a démarré : recalés sur
    # le démarrage réel (la v1 les laissait au plan précédent, repris par la fusion).
    realigned = {c.name for c in problem.launched} - set(expected_by_name)
    assert realigned <= {item["equipement"] for item in state.get("equipements_geles") or []}
    assert set(by_name) - realigned == set(expected_by_name)
    for name, item in by_name.items():
        if name not in realigned:
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


# --- Contrat (lot 7.3) : abonnement et puissance souscrite --------------------------------


def _imports(problem: Problem, plan: Plan) -> dict[int, float]:
    run = simulate_plan(problem, plan)
    return {hour: max(0.0, -kwh) for hour, kwh in run.residual_kwh.items()}


@pytest.mark.parametrize("path", STATES, ids=[p.stem for p in STATES])
def test_the_plan_keeps_under_the_contract_power_or_says_so(path: Path) -> None:
    """Puissance souscrite juste sous le pic du plan sans contrat, mais au-dessus de la seule
    consommation de base (en dessous, la journée est impossible) : le plan s'y tient, ou
    signale les heures de dépassement ; jamais d'échec du calcul."""
    problem = from_input(from_v1(load(path)[0]))
    peak = max(_imports(problem, solve(problem)).values(), default=0.0)
    base = max(
        problem.production_kwh.get(h, 0.0)
        - problem.net_kwh.get(h, 0.0)
        + problem.fixed_kwh.get(h, 0.0)
        for h in problem.hours
    )
    limited = replace(problem, contract_kwh=max(0.05, round(peak * 0.8, 3), round(base, 3)))

    result = plan_day(limited, explained=False)

    over = sorted(
        hour
        for hour, kwh in _imports(limited, result.plan).items()
        if kwh > limited.contract_kwh + 0.001  # type: ignore[operator]
    )
    found = [w for w in result.day.warnings if isinstance(w, dict)]
    exceeded = [w for w in found if w["code"] == "puissance_souscrite_depassee"]
    if over:
        assert exceeded and exceeded[0]["params"]["heures"] == ", ".join(map(str, over))
    else:
        assert not exceeded


def test_the_subscription_is_part_of_the_cost_of_the_day() -> None:
    problem = from_input(from_v1(load(STATES[0])[0]))
    plan = solve(problem)
    with_subscription = replace(problem, subscription_eur=0.5)

    found = _indicators(with_subscription, plan)

    assert found.subscription_eur == 0.5
    assert found.cost_eur == pytest.approx(_indicators(problem, plan).cost_eur + 0.5, abs=0.001)


# --- Données impossibles (lot 7.3) : saut de compteur dans la consommation de base -----------


@pytest.mark.parametrize("path", STATES, ids=[p.stem for p in STATES])
def test_real_days_are_never_impossible(path: Path) -> None:
    problem = from_input(from_v1(load(path)[0]))

    assert impossible_hour(problem) is None
    assert impossible_hour(replace(problem, contract_kwh=6.0)) is None


def test_an_impossible_baseline_stops_the_calculation_with_its_hour() -> None:
    problem = from_input(from_v1(load(STATES[0])[0]))
    hour = problem.hours[-2]
    jumped = replace(problem, net_kwh={**problem.net_kwh, hour: -10674.1}, contract_kwh=9.0)

    with pytest.raises(ImpossibleDataError) as raised:
        solve(jumped)

    error = raised.value
    assert (error.day, error.hour) == (problem.day, hour)
    production = max(0.0, problem.production_kwh.get(hour, 0.0))
    assert error.consumption_kwh == pytest.approx(
        production + 10674.1 + problem.fixed_kwh.get(hour, 0.0)
    )
    battery = problem.battery
    active = battery.capacity_kwh > 0 and battery.active_from <= hour < battery.active_to
    assert error.limit_kwh == pytest.approx(
        9.0 + production + (battery.discharge_max_kw if active else 0.0)
    )
    unknown = replace(jumped, contract_kwh=None)
    assert impossible_hour(unknown).limit_kwh == pytest.approx(  # type: ignore[union-attr]
        error.limit_kwh - 9.0 + DEFAULT_CONTRACT_KWH
    )


# --- Devise de la maison (lot 7.3) : mêmes priorités quelle que soit l'échelle des prix -------


def _in_yen(problem: Problem) -> Problem:
    """La même journée en yens : prix et abonnement multipliés par 160, échelle de la devise 160."""
    return replace(
        problem,
        prices_eur_kwh={h: p * 160 for h, p in problem.prices_eur_kwh.items()},
        export_prices_eur_kwh={h: p * 160 for h, p in problem.export_prices_eur_kwh.items()},
        subscription_eur=problem.subscription_eur * 160,
        price_scale=160.0,
    )


@pytest.mark.parametrize("path", STATES, ids=[p.stem for p in STATES])
@pytest.mark.parametrize(
    "objective",
    [Objective.COST, Weights(cost=1.0, grid_import=0.5, battery=0.2)],
    ids=["cost", "weights"],
)
def test_the_plan_does_not_depend_on_the_currency(path: Path, objective: Goal) -> None:
    """Pénalités et départages réglés en euros : des prix 160 fois plus grands (yen), ramenés
    à l'échelle de l'euro, donnent un plan aussi bon (un plan équivalent peut être choisi à la
    tolérance de HiGHS près), au coût 160 fois plus grand."""
    problem = from_input(from_v1(load(path)[0]))
    in_yen = _in_yen(problem)

    euro = _indicators(problem, solve(problem, objective))
    yen = _indicators(problem, solve(in_yen, objective))  # évalué en euros

    assert set(solve(in_yen, objective).starts) == set(solve(problem, objective).starts)
    assert yen.cost_eur == pytest.approx(euro.cost_eur, abs=0.005)
    assert yen.import_kwh == pytest.approx(euro.import_kwh, abs=0.05)
    assert _indicators(in_yen, solve(in_yen, objective)).cost_eur == pytest.approx(
        yen.cost_eur * 160, abs=0.2
    )


def test_an_expensive_currency_does_not_skip_appliances() -> None:
    """Journée 01 sans soleil, en forints (prix multipliés par 400) : sans l'échelle de la devise,
    chauffer l'eau coûtait plus que la pénalité d'une tâche non placée, et le chauffe-eau
    n'était plus placé."""
    problem = from_input(from_v1(load(state_named("today_h06_no_measured_efficiency"))[0]))
    dark = replace(
        problem,
        net_kwh=dict.fromkeys(problem.hours, -0.4),
        production_kwh=dict.fromkeys(problem.hours, 0.0),
        battery=replace(problem.battery, stored_kwh=problem.battery.floor_kwh),
    )
    in_forint = replace(
        dark,
        prices_eur_kwh={h: p * 400 for h, p in dark.prices_eur_kwh.items()},
        export_prices_eur_kwh={h: p * 400 for h, p in dark.export_prices_eur_kwh.items()},
        price_scale=400.0,
    )

    assert set(solve(in_forint).starts) == set(solve(dark).starts) == {"Chauffe-eau"}
    assert solve(replace(in_forint, price_scale=1.0)).starts == {}  # le défaut corrigé


def test_the_forecast_of_the_day_follows_the_measured_production() -> None:
    """Prévision trop optimiste (nuages non prévus) : les heures restantes suivent le rapport
    mesuré / prévu depuis minuit, sinon chaque calcul horaire prévoyait une charge de la
    batterie sur un surplus qui ne venait pas."""
    from wattslot.planning.problem import (
        corrected_production,
        forecast_ratio,
        with_corrected_forecast,
    )
    from wattslot.planning.reference import REFERENCE

    data = from_v1(load(state_named("today_h06_no_measured_efficiency"))[0])
    production = {h: (0.5 if 8 <= h < 16 else 0.0) for h in range(24)}
    net = {h: round(production[h] - 0.4, 3) for h in range(24)}
    cloudy = replace(
        data,
        first_hour=11,
        production_kwh=production,
        net_kwh=net,
        measured_at_hour=11.0,
        measured_production_kwh=0.45,  # 1,5 kWh prévus de 8h à 11h
    )

    assert forecast_ratio(cloudy, REFERENCE) == 0.3
    corrected, corrected_net = corrected_production(cloudy, REFERENCE)
    assert corrected[10] == 0.5 and corrected_net[10] == net[10]  # heure passée : telle quelle
    assert corrected[12] == 0.15 and corrected_net[12] == -0.25
    corrected_input = with_corrected_forecast(cloudy)
    assert corrected_input.production_kwh[12] == 0.15 and corrected_input.net_kwh[12] == -0.25
    assert from_input(corrected_input).production_kwh[12] == 0.15

    # Trop tôt pour juger, ou bornes : 0,2 à 1,5.
    early = replace(cloudy, measured_at_hour=8.5, measured_production_kwh=0.0)
    assert forecast_ratio(early, REFERENCE) is None
    assert corrected_production(early, REFERENCE) == (production, net)
    assert forecast_ratio(replace(cloudy, measured_production_kwh=0.0), REFERENCE) == 0.2
    assert forecast_ratio(replace(cloudy, measured_production_kwh=9.0), REFERENCE) == 1.5


def test_frozen_slot_realigned_on_its_real_start() -> None:
    """Bloc gelé (12 h 00 → 13 h 57, plan précédent) dont le cycle réel a démarré à 13 h 04 et
    tourne encore : le calcul le recale sur ce démarrage (fin : 13 h 04 + 117 min) et la fusion
    garde ce bloc recalé plutôt que l'ancien, dont la fin ne suivait plus le cycle."""
    state, _ = load(state_named("06_today_h13_dishwasher_running"))
    (frozen,) = state["equipements_geles"]
    problem = from_input(from_v1(state))

    output = plan_day(problem).output
    (slot,) = [i for i in output["planning"] if i["equipement"] == "Lave-vaisselle"]

    assert (slot["debut_min"], slot["fin_min"]) == (13 * 60 + 4, 15 * 60 + 2)
    assert slot["explication"]["raisons"][0]["code"] == "launched"
    old = {**output, "planning": [frozen]}
    merged = merge_plans(output, old, problem.first_hour)
    (kept,) = [i for i in merged["planning"] if i["equipement"] == "Lave-vaisselle"]
    assert kept["fin_min"] == 15 * 60 + 2


def _laundry_state(washer: dict[str, Any]) -> dict[str, Any]:
    """Journée type 06 (calcul de 13 h 59) : lave-linge gelé 12 h 00 → 12 h 24, sèche-linge
    gelé 12 h 30 → 14 h 45 derrière lui (``depend_de``), ``washer`` : cycle réel du lave-linge."""
    state, _ = load(state_named("06_today_h13_dishwasher_running"))
    state = copy.deepcopy(state)
    for task in state["taches_placees"]:
        if task["summary"] in ("Lave-linge", "Sèche-linge"):
            task["due"] = "2025-10-14"
    common = {"priorite": 3, "justification": ""}
    state["equipements_geles"] += [
        {"equipement": "Lave-linge", "heure_debut": 12, "heure_fin": 13, "debut_min": 720,
         "fin_min": 744, "energie_kwh": 0.22, "duree_cycle_min": 24, **common},
        {"equipement": "Sèche-linge", "heure_debut": 12, "heure_fin": 15, "debut_min": 750,
         "fin_min": 885, "energie_kwh": 1.1, "duree_cycle_min": 135, **common},
    ]  # fmt: skip
    state["cycles_reels"]["segments"]["Lave-linge"] = [washer]
    return state


def test_frozen_slot_released_when_its_dependency_overruns() -> None:
    """Le lave-linge, lancé à 12 h 00, tourne encore à 13 h 59 : le sèche-linge gelé à 12 h 30,
    pas lancé, est replacé après sa fin, et la fusion garde ce nouveau créneau."""
    state = _laundry_state(
        {"debut_iso": "2025-10-14T12:00:00+02:00", "fin_iso": "2025-10-14T13:59:00+02:00",
         "energie_kwh": 0.3, "en_cours": True}
    )  # fmt: skip
    problem = from_input(from_v1(state))

    output = plan_day(problem).output
    by_name = {i["equipement"]: i for i in output["planning"]}

    assert problem.released == {"Sèche-linge"}
    assert by_name["Sèche-linge"]["debut_min"] >= by_name["Lave-linge"]["fin_min"] > 13 * 60 + 59
    old = {**output, "planning": state["equipements_geles"]}
    merged = merge_plans(output, old, problem.first_hour, chosen=set(problem.released))
    kept = {i["equipement"]: i for i in merged["planning"]}
    assert kept["Sèche-linge"]["debut_min"] == by_name["Sèche-linge"]["debut_min"]


def test_frozen_slot_kept_when_its_dependency_ended_in_time() -> None:
    """Lave-linge fini à 12 h 20, avant le départ prévu du sèche-linge : celui-ci reste gelé."""
    state = _laundry_state(
        {"debut_iso": "2025-10-14T12:00:00+02:00", "fin_iso": "2025-10-14T12:20:00+02:00",
         "energie_kwh": 0.22}
    )  # fmt: skip

    assert from_input(from_v1(state)).released == frozenset()
