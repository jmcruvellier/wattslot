"""Le moteur a toujours un plan : plancher de batterie qui monte dans la journée, durée minimale
qui ne tient plus dans les heures restantes. Problèmes construits à la main, sans journée type.
"""

from datetime import date

from wattslot.planning.engine import plan_day, simulate_plan, solve
from wattslot.planning.problem import BatteryModel, Problem, RuntimeModel

PUMP = "Pompe"


def _battery(**changes: object) -> BatteryModel:
    values: dict[str, object] = {
        "capacity_kwh": 10.0,
        "stored_kwh": 8.0,
        "soc_percent": 80.0,
        "charge_max_kw": 3.0,
        "discharge_max_kw": 3.0,
        "active_from": 0,
        "active_to": 24,
        "charge_efficiency": 1.0,
        "discharge_efficiency": 1.0,
        "floor_kwh": 1.0,
        "full_kwh": 10.0,
        "full_priority": False,
    }
    values.update(changes)
    return BatteryModel(**values)  # type: ignore[arg-type]


def _problem(first_hour: int, battery: BatteryModel, **changes: object) -> Problem:
    hours = range(first_hour, 24)
    values: dict[str, object] = {
        "day": date(2026, 7, 1),
        "first_hour": first_hour,
        "net_kwh": {hour: -1.0 for hour in hours},  # maison en déficit toute la journée
        "production_kwh": {hour: 0.0 for hour in hours},
        "fixed_kwh": {hour: 0.0 for hour in hours},
        "tasks": [],
        "launched": [],
        "battery": battery,
        "runtimes": [],
        "prices_eur_kwh": {hour: 0.2 for hour in hours},
    }
    values.update(changes)
    return Problem(**values)  # type: ignore[arg-type]


def test_a_floor_rising_in_the_evening_keeps_a_plan() -> None:
    """Plancher à 10 %, plage 18-22 h à 50 % : la batterie, déchargée par le déficit de la
    journée, est sous le plancher du soir ; elle cesse de se décharger, comme dans la
    simulation, au lieu de rendre le problème impossible."""
    floors = {hour: 5.0 for hour in range(18, 22)}
    problem = _problem(8, _battery(floor_by_hour=floors))

    plan = solve(problem)
    run = simulate_plan(problem, plan)

    assert run.soc_kwh[17] >= 1.0 - 1e-6
    assert all(run.soc_kwh[hour] == run.soc_kwh[17] for hour in range(18, 22))


def test_a_battery_below_its_floor_does_not_discharge() -> None:
    """Batterie déjà sous le plancher au départ : pas de décharge, ni dans le plan ni dans la
    simulation."""
    problem = _problem(8, _battery(stored_kwh=0.5, soc_percent=5.0))

    indicators = plan_day(problem).day.indicators

    assert indicators is not None and indicators.end_soc_percent == 5.0


def test_a_runtime_longer_than_the_hours_left_keeps_a_plan() -> None:
    """Premier calcul à 23 h, deux heures de filtration à faire : la dernière heure est prise,
    l'heure manquante est signalée, au lieu de rendre le problème impossible."""
    pump = RuntimeModel(name=PUMP, speeds=(("normal", 1.0),), min_hours=2, minimum_forced=False)
    problem = _problem(23, _battery(), runtimes=[pump])

    plan = solve(problem)
    warnings = plan_day(problem).day.warnings

    assert plan.runtimes[PUMP] == {23: "normal"}
    assert {
        "code": "duree_minimale_non_tenue",
        "params": {"equipement": PUMP, "heures": 1, "minimum": 2},
    } in warnings
