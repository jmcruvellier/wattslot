"""Débordement après minuit : un cycle lancé le soir peut finir le lendemain, chiffré au tarif,
à la consommation de base et à la batterie du lendemain (calcul prolongé)."""

from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta

from tests.v1_oracle import STATES, load
from wattslot.planning import overnight
from wattslot.planning.cycles import DAY_MIN, PlannedCycle, Segment, after_midnight, planned_hourly
from wattslot.planning.engine import indicators, plan_day, with_overnight
from wattslot.planning.inputs import CarriedCycle, NextDay, PlanningInput, from_v1
from wattslot.planning.plan import Plan, Slot
from wattslot.planning.problem import from_input
from wattslot.tariff import V1, Tariff, TariffContext, TariffKind
from wattslot.time_constraints import ConstraintKind, TimeConstraint

HEATER = "Chauffe-eau"  # tâche due de l'état capturé n° 0
# Lendemain sans soleil la nuit : consommation de base seulement.
NIGHT = NextDay(net_kwh={h: -0.3 for h in range(24)}, production_kwh=dict.fromkeys(range(24), 0.0))


def evening(hour: int = 21, battery_kwh: float = 0.0, **changes: object) -> PlanningInput:
    """L'état n° 0 (chauffe-eau à placer, tarif de la v1 : heures creuses 22 h-6 h) recalculé
    le soir à ``hour``, batterie à ``battery_kwh`` (au plus sa capacité)."""
    data, _ = load(STATES[0])
    found = from_v1(data)
    found = replace(
        found,
        first_hour=hour,
        net_kwh={h: (-0.3 if h >= 19 else v) for h, v in found.net_kwh.items()},
        battery=replace(
            found.battery,
            stored_kwh=battery_kwh,
            soc_percent=battery_kwh / found.battery.capacity_kwh * 100,
        ),
        due_tasks=tuple(t for t in found.due_tasks if t.name == HEATER),
        waiting_tasks=(),
        frozen=(),
    )
    return replace(found, **changes)  # type: ignore[arg-type]


def slot(day: Plan, name: str = HEATER) -> Slot:
    found = next(i for i in day.items if i.device == name)
    assert isinstance(found, Slot)
    return found


def test_a_cycle_hourly_energy_can_run_past_midnight() -> None:
    cycle = PlannedCycle(22 * 60, 25 * 60, 3.0)
    assert planned_hourly(cycle) == {22: 1.0, 23: 1.0}  # comme la v1 : coupé à minuit
    assert planned_hourly(cycle, days=2) == {22: 1.0, 23: 1.0, 24: 1.0}
    assert after_midnight(planned_hourly(cycle, days=2)) == {0: 1.0}


def test_without_the_next_day_nothing_crosses_midnight() -> None:
    data = evening()
    problem = from_input(data)
    heater = next(t for t in problem.tasks if t.name == HEATER)
    assert problem.overnight is None and heater.overflow_min == 0
    assert all(s + heater.slot_min <= DAY_MIN for s in heater.candidates())


def test_the_heater_asked_at_9_pm_starts_in_off_peak_hours_and_ends_tomorrow() -> None:
    """21 h, chauffe-eau de plusieurs heures, heures creuses à partir de 22 h : finir avant
    minuit oblige à démarrer en heures pleines ; avec le lendemain, il démarre à 22 h."""
    before = slot(plan_day(from_input(evening())).day)
    data = evening(next_day=NIGHT)
    problem = from_input(data)
    heater = next(t for t in problem.tasks if t.name == HEATER)
    assert heater.slot_min > 120  # plus de deux heures : ne tient pas entre 22 h et minuit
    assert problem.overnight is not None and problem.overnight.hours * 60 >= heater.slot_min

    after = slot(plan_day(problem).day)

    assert (before.end_min or 0) <= DAY_MIN and (before.start_min or 0) < 22 * 60
    assert (after.start_min or 0) == 22 * 60 and (after.end_min or 0) > DAY_MIN


def test_overflow_is_chosen_only_when_tomorrow_is_cheaper() -> None:
    """Nuit du lendemain très chère : déborder coûterait plus, le cycle finit avant minuit."""
    data = evening(next_day=NIGHT)
    bands = [
        b if b.start_hour == 22 else b.model_copy(update={"eur_kwh": 1.0})
        for b in data.tariff.bands
    ]
    found = slot(
        plan_day(
            from_input(replace(data, tariff=data.tariff.model_copy(update={"bands": bands})))
        ).day
    )
    assert (found.end_min or 0) <= DAY_MIN


def _night_import(data: PlanningInput) -> float:
    """kWh soutirés pendant le prolongement après minuit du plan retenu."""
    problem = from_input(data)
    result = plan_day(problem)
    day = indicators(problem, result.battery)
    return with_overnight(problem, result.plan, result.battery, day).import_kwh - day.import_kwh


def test_the_battery_keeps_running_after_midnight() -> None:
    """Batterie chargée, active la nuit : elle fournit la part du lendemain ; « en attente »
    hors de sa plage active (6 h-24 h) ou vide, c'est le réseau."""
    data = evening(battery_kwh=5.2, next_day=NIGHT)
    active = replace(
        data, battery=replace(data.battery, schedules=(), active_from_hour=0, active_to_hour=24)
    )
    waiting = replace(
        data, battery=replace(data.battery, schedules=(), active_from_hour=6, active_to_hour=24)
    )
    empty = replace(
        active, battery=replace(active.battery, stored_kwh=0.5, soc_percent=0.5 / 5.31 * 100)
    )
    assert _night_import(active) < 0.01
    assert _night_import(waiting) > 0.5
    assert _night_import(empty) > 0.5


def test_unknown_prices_for_tomorrow_forbid_overflow() -> None:
    data = evening(next_day=replace(NIGHT, prices_known=False))
    assert from_input(data).overnight is None
    assert (slot(plan_day(from_input(data)).day).end_min or 0) <= DAY_MIN


def test_time_constraints_apply_to_the_part_after_midnight() -> None:
    """Interdit de 0 h à 6 h : la part du lendemain le violerait, le cycle finit avant minuit."""
    night = TimeConstraint(kind=ConstraintKind.FORBIDDEN, start_hour=0, end_hour=6)
    data = evening(next_day=NIGHT, constraints={HEATER: (night,)})
    found = slot(plan_day(from_input(data)).day)
    assert (found.end_min or 0) <= DAY_MIN


def test_the_end_of_yesterday_s_cycle_is_already_decided() -> None:
    """Fin du chauffe-eau d'hier (0 h-1 h) : consommation fixée, et un cycle qui en dépend
    attend sa fin."""
    data, _ = load(STATES[0])
    found = replace(
        from_v1(data),
        first_hour=0,
        carried=(CarriedCycle(name=HEATER, end_min=60, hourly_kwh={0: 1.2}, energy_kwh=3.0),),
    )
    base = from_input(replace(found, carried=()))
    problem = from_input(found)
    assert problem.fixed_kwh[0] == base.fixed_kwh[0] + 1.2
    assert problem.fixed_ends["chauffeeau"] == 60


def test_the_end_of_a_cycle_is_carried_to_the_next_day() -> None:
    plan = Plan.model_validate(
        {
            "planning": [
                {
                    "equipement": HEATER,
                    "debut_min": 22 * 60,
                    "fin_min": 25 * 60,
                    "energie_kwh": 3.0,
                },
                {"equipement": "Lave-linge", "debut_min": 600, "fin_min": 690, "energie_kwh": 1.0},
            ]
        }
    )
    carried = overnight.carried_from(plan)
    assert carried == (CarriedCycle(name=HEATER, end_min=60, hourly_kwh={0: 1.0}, energy_kwh=3.0),)
    again = overnight.from_stored(overnight.stored(carried))
    assert again == carried


def test_the_carried_end_seen_after_midnight_is_not_a_new_cycle() -> None:
    data, _ = load(STATES[0])
    found = from_v1(data)
    midnight = datetime.combine(found.day, time(0, 0), tzinfo=UTC)
    tail = Segment(start=midnight, end=midnight + timedelta(minutes=55), energy_kwh=1.0)
    later = Segment(
        start=midnight + timedelta(hours=14), end=midnight + timedelta(hours=16), energy_kwh=2.0
    )
    found = replace(found, real_segments={HEATER: (tail, later)})
    carried = (CarriedCycle(name=HEATER, end_min=60, hourly_kwh={0: 1.0}),)

    kept = overnight.with_carried(found, carried)

    assert kept.carried == carried and kept.real_segments[HEATER] == (later,)
    assert overnight.with_carried(found, ()) is found


def test_tomorrow_prices_are_known_or_not() -> None:
    day = date(2026, 11, 10)
    assert V1.known(day)
    dynamic = Tariff(kind=TariffKind.DYNAMIC, base_eur_kwh=0.2, price_entity="sensor.price")
    assert not dynamic.known(day, TariffContext(), 4)
    assert dynamic.known(day, TariffContext(prices={day: {h: 0.1 for h in range(4)}}), 4)
    colors = Tariff(
        kind=TariffKind.DAY_COLOR,
        base_eur_kwh=0.2,
        color_entity="sensor.color",
        color_day_start_hour=6,
    )
    # Avant 6 h, la couleur est celle de la veille : connue dès que celle du jour l'est.
    assert colors.known(day, TariffContext(colors={day - timedelta(days=1): "bleu"}), 4)
    assert not colors.known(day, TariffContext(), 4)
