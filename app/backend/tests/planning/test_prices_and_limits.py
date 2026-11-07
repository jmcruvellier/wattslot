"""Prix négatifs ou revente plus chère que l'achat, limite de temps sans solution : le moteur
ne soutire et n'injecte jamais la même heure, et ne lit pas un plan qu'il n'a pas trouvé.
Problèmes construits à la main, sans journée type.
"""

from dataclasses import replace
from datetime import date

import pytest

from wattslot.planning.engine import NoPlanError, solve
from wattslot.planning.problem import BatteryModel, Problem, Task

NO_BATTERY = BatteryModel(
    capacity_kwh=0.0,
    stored_kwh=0.0,
    soc_percent=0.0,
    charge_max_kw=0.0,
    discharge_max_kw=0.0,
    active_from=0,
    active_to=24,
    charge_efficiency=1.0,
    discharge_efficiency=1.0,
    floor_kwh=0.0,
    full_kwh=0.0,
    full_priority=False,
)
WASHER = Task(
    name="Lave-linge",
    key="washer",
    energy_kwh=1.0,
    cycle_min=60,
    slot_min=60,
    shape=None,
    priority=1,
    earliest_min=8 * 60,
    depends_on=None,
)


def _problem(**changes: object) -> Problem:
    hours = range(8, 24)
    values: dict[str, object] = {
        "day": date(2026, 7, 1),
        "first_hour": 8,
        # Surplus solaire de 12 h à 15 h, déficit le reste du temps.
        "net_kwh": {hour: 2.0 if 12 <= hour < 15 else -0.5 for hour in hours},
        "production_kwh": {hour: 2.5 if 12 <= hour < 15 else 0.0 for hour in hours},
        "fixed_kwh": {hour: 0.0 for hour in hours},
        "tasks": [WASHER],
        "launched": [],
        "battery": NO_BATTERY,
        "runtimes": [],
        "prices_eur_kwh": {hour: 0.2 for hour in hours},
    }
    values.update(changes)
    return Problem(**values)  # type: ignore[arg-type]


def test_a_negative_import_price_keeps_a_plan() -> None:
    """Prix dynamique négatif : soutirer et réinjecter la même énergie rapportait sans fin
    (problème non borné, aucun plan). L'appareil va à l'heure où le soutirage rapporte."""
    prices = {hour: -0.05 if hour == 20 else 0.2 for hour in range(8, 24)}
    problem = _problem(prices_eur_kwh=prices)

    plan = solve(problem)

    assert plan.starts == {"Lave-linge": 20 * 60}


def test_a_resale_above_the_purchase_price_keeps_a_plan() -> None:
    """Revente plus chère que l'achat (entité de prix de revente, contrat d'injection) : soutirer
    pour réinjecter rapportait sans fin, sans puissance souscrite pour le borner. L'appareil ne
    fait plus que quitter le surplus, qui se revend mieux qu'il ne s'économise."""
    hours = range(8, 24)
    problem = _problem(
        prices_eur_kwh={hour: 0.1 for hour in hours},
        export_prices_eur_kwh={hour: 0.2 for hour in hours},
    )

    plan = solve(problem)

    assert not 12 * 60 <= plan.starts["Lave-linge"] < 15 * 60


def test_no_plan_is_read_when_the_time_limit_finds_none() -> None:
    """Limite de temps atteinte sans solution : HiGHS rend 0 pour chaque variable, ce qui se
    lisait comme un plan (tâches au premier départ, rien d'autre) sans avertissement."""
    problem = replace(_problem(), tasks=[WASHER, replace(WASHER, name="Sèche-linge", key="dryer")])

    with pytest.raises(NoPlanError):
        solve(problem, time_limit_s=0.0)
