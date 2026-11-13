"""Plusieurs cycles d'un même équipement dans la journée (deux chauffes, deux lessives) : chaque
demande est placée sur son créneau, l'une après l'autre, et un cycle réel n'est attribué qu'à
une seule."""

from dataclasses import replace
from datetime import datetime, timedelta

from tests.v1_oracle import load, state_named
from wattslot.planning.assemble import to_v1
from wattslot.planning.assignment import launched_keys, launched_uids
from wattslot.planning.cycles import Segment
from wattslot.planning.engine import plan_day
from wattslot.planning.inputs import FrozenCycle, PlanningInput, TaskRequest, from_v1
from wattslot.planning.merge import merge_plans
from wattslot.planning.occurrences import Wanted, attribute, numbered, paired
from wattslot.planning.plan import Plan, Slot
from wattslot.planning.problem import from_input
from wattslot.planning.reference import ident, task_key

HEATER = "Chauffe-eau"
WASHER = "Lave-linge"
DRYER = "Sèche-linge"


def slots(day: Plan, device: str) -> list[Slot]:
    found = [i for i in day.items if isinstance(i, Slot) and i.device == device]
    return sorted(found, key=lambda s: s.rank or 1)


def frozen(slot: Slot) -> FrozenCycle:
    assert slot.start_hour is not None and slot.end_hour is not None
    return FrozenCycle(
        name=slot.device,
        start_hour=slot.start_hour,
        end_hour=slot.end_hour,
        energy_kwh=slot.energy_kwh or 0.0,
        start_min=slot.start_min,
        end_min=slot.end_min,
        cycle_min=slot.cycle_min,
        shape=tuple(slot.shape) if slot.shape else None,
        rank=slot.rank or 1,
        uid=slot.request,
    )


# --- Rangs ------------------------------------------------------------------------------------


def test_cycles_of_one_device_are_told_apart_by_their_rank() -> None:
    assert ident(WASHER) == ident(WASHER, 1) == WASHER
    assert ident(WASHER, 2) == "Lave-linge #2"
    assert Slot(device=WASHER, rank=2).ident == "Lave-linge #2"
    assert "rang" not in Slot(device=WASHER).to_v1()  # un seul cycle : le plan d'avant


def test_tasks_take_their_rank_in_order_and_keep_it() -> None:
    data = from_v1(load(state_named("synthetic_sunny_h00"))[0])
    washer = next(t for t in data.waiting_tasks if t.name == WASHER)
    again = replace(washer, uid="ll2")
    twice = replace(data, waiting_tasks=(*data.waiting_tasks, again))

    found = numbered(twice)
    assert [(t.name, t.rank) for t in found.waiting_tasks] == [
        (DRYER, 1),
        (WASHER, 1),
        (WASHER, 2),
    ]
    assert numbered(found) is found  # déjà numérotées

    # D'un calcul à l'autre, une tâche garde le rang de son bloc dans le plan précédent ; la
    # première demande close, la seconde ne devient pas « le » lave-linge.
    later = replace(twice, waiting_tasks=(again,), ranks={"ll1": 1, "ll2": 2})
    assert [t.rank for t in numbered(later).waiting_tasks] == [2]


def test_a_block_of_an_earlier_plan_goes_to_the_first_task_of_its_device() -> None:
    """Plan enregistré avant cette version : son bloc ne porte pas d'uid."""
    data = from_v1(load(state_named("synthetic_realignment_h13"))[0])
    assert all(block.uid is None for block in data.frozen)
    assert {t.name: t.rank for t in numbered(data).waiting_tasks} == {WASHER: 1, DRYER: 1}


# --- Cycles réels -----------------------------------------------------------------------------


def _segment(hour: int, kwh: float = 1.0, running: bool = False) -> Segment:
    start = datetime(2026, 11, 13, hour)
    return Segment(start, start + timedelta(hours=1), kwh, running)


def test_a_real_cycle_goes_to_one_cycle_only() -> None:
    morning, noon = _segment(9), _segment(12)
    first, second = Wanted("X", 1.0), Wanted("X #2", 1.0)

    assert attribute([morning], [first, second]) == {"X": morning}
    assert attribute([morning, noon], [first, second]) == {"X": morning, "X #2": noon}
    # Seul, un cycle prend la dernière activité reconnue, comme avant.
    assert attribute([morning, noon], [first]) == {"X": noon}
    # Trop peu d'énergie : pas un cycle.
    assert attribute([_segment(9, 0.1)], [first]) == {}


def test_a_request_never_takes_an_activity_started_before_it() -> None:
    morning, noon = _segment(9), _segment(12)
    asked = Wanted("X", 1.0, since=datetime(2026, 11, 13, 10))
    assert attribute([morning], [asked]) == {}
    assert attribute([morning, noon], [asked]) == {"X": noon}
    # Tâche close : pas une activité démarrée après la fin de son créneau.
    closed = Wanted("X", 1.0, before=datetime(2026, 11, 13, 11))
    assert attribute([noon], [closed]) == {}
    assert attribute([morning, noon], [closed, Wanted("X #2", 1.0)]) == {
        "X": morning,
        "X #2": noon,
    }


# --- Une seconde demande après un cycle déjà fait ----------------------------------------------


def heater_done_then_asked_again() -> tuple[PlanningInput, Slot]:
    """Journée 02 à midi : le chauffe-eau a tourné, sa tâche est close, son bloc est dans le
    plan ; il est redemandé pour aujourd'hui."""
    data = from_v1(load(state_named("today_h12_water_heater"))[0])
    done = slots(plan_day(from_input(data)).day, HEATER)[0]
    assert done.justification is not None and done.justification.startswith("Lancé à ")
    first = next(t for t in data.due_tasks if t.name == HEATER)
    assert done.request == first.uid
    again = replace(first, uid="again")
    asked = replace(
        data,
        due_tasks=tuple(again if t is first else t for t in data.due_tasks),
        frozen=(*data.frozen, frozen(done)),
        ranks={first.uid or "": 1},
    )
    return asked, done


def test_a_second_request_is_placed_after_the_cycle_already_done() -> None:
    """Le constat du 09/11/2026 : la seconde demande était recalée sur le cycle déjà fait."""
    asked, done = heater_done_then_asked_again()

    problem = from_input(asked)
    assert [c.name for c in problem.launched] == [HEATER]
    assert [t.name for t in problem.tasks] == ["Chauffe-eau #2"]

    first, second = slots(plan_day(problem).day, HEATER)
    assert (first.start_min, first.end_min) == (done.start_min, done.end_min)
    assert second.rank == 2 and second.request == "again"
    assert second.start_min is not None and first.end_min is not None
    assert second.start_min >= first.end_min  # un cycle à la fois
    assert second.justification is not None and not second.justification.startswith("Lancé")
    # Le cycle fait n'est pas celui de la nouvelle demande : elle n'est pas lancée.
    assert launched_uids(asked) == set()
    assert task_key(HEATER) not in launched_keys(asked)


def test_the_second_cycle_keeps_its_own_block_in_the_merged_plan() -> None:
    asked, done = heater_done_then_asked_again()
    old = {"date_cible": asked.day.isoformat(), "planning": [done.to_v1()]}
    result = plan_day(from_input(asked))
    new = {**to_v1(numbered(asked)), **result.output, "date_cible": asked.day.isoformat()}

    merged = merge_plans(new, old, asked.first_hour)
    heaters = [i for i in merged["planning"] if i["equipement"] == HEATER]
    blocks = sorted((i.get("rang") or 1, i["debut_min"]) for i in heaters)
    second = slots(result.day, HEATER)[1]
    assert blocks == [(1, done.start_min), (2, second.start_min)]


def test_a_second_request_lets_the_first_one_be_launched_alone() -> None:
    """Deux demandes ouvertes, un seul cycle réel : la première est lancée, pas la seconde."""
    data = from_v1(load(state_named("today_h12_water_heater"))[0])
    first = next(t for t in data.due_tasks if t.name == HEATER)
    twice = replace(data, due_tasks=(*data.due_tasks, replace(first, uid="again")))

    problem = from_input(twice)
    assert [c.name for c in problem.launched] == [HEATER]
    assert [t.name for t in problem.tasks] == ["Chauffe-eau #2"]


# --- Deux lessives ----------------------------------------------------------------------------


def two_loads() -> PlanningInput:
    """Journée 12 à minuit : deux lave-linges et deux sèche-linges demandés."""
    data = from_v1(load(state_named("synthetic_sunny_h00"))[0])
    washer = next(t for t in data.waiting_tasks if t.name == WASHER)
    dryer = next(t for t in data.waiting_tasks if t.name == DRYER)
    more = (replace(washer, uid="ll2"), replace(dryer, uid="sl2"))
    return replace(data, waiting_tasks=(*data.waiting_tasks, *more))


def test_two_loads_follow_each_other() -> None:
    """Deux lave-linges à la suite ; le premier sèche-linge après le premier lave-linge (en
    même temps que le second si le calcul le veut), le second après le second lave-linge et
    après le premier sèche-linge."""
    problem = from_input(two_loads())
    by_name = {t.name: t for t in problem.tasks}
    assert set(by_name) == {HEATER, WASHER, "Lave-linge #2", DRYER, "Sèche-linge #2"}
    assert by_name["Lave-linge #2"].follows == WASHER
    assert by_name["Sèche-linge #2"].follows == DRYER
    assert by_name[DRYER].depends_on == by_name[WASHER].key
    assert by_name["Sèche-linge #2"].depends_on == by_name["Lave-linge #2"].key

    day = plan_day(problem).day
    washers, dryers = slots(day, WASHER), slots(day, DRYER)
    assert [s.rank for s in washers] == [None, 2] and [s.rank for s in dryers] == [None, 2]

    def start(slot: Slot) -> int:
        assert slot.start_min is not None
        return slot.start_min

    def end(slot: Slot) -> int:
        assert slot.end_min is not None
        return slot.end_min

    assert start(washers[1]) >= end(washers[0])
    assert start(dryers[0]) >= end(washers[0])
    assert start(dryers[1]) >= end(washers[1])
    assert start(dryers[1]) >= end(dryers[0])
    # Les réglages et les textes restent ceux de l'équipement.
    assert not any("#" in str(w) for w in day.warnings)


def test_cycles_are_paired_in_order() -> None:
    assert paired([1, 2], [1, 2]) == {1: 1, 2: 2}
    assert paired([1, 2], [1]) == {1: 1}  # un sèche-linge de plus : il ne suit que le précédent
    assert paired([1], [1, 2]) == {1: 1}


def test_one_request_gives_the_plan_of_before() -> None:
    """Sans second cycle, rien ne change : mêmes tâches, mêmes noms, pas de rang."""
    data = from_v1(load(state_named("synthetic_sunny_h00"))[0])
    problem = from_input(data)
    assert all(t.follows is None and t.rank == 1 and t.name == t.label for t in problem.tasks)
    assert all(s.rank is None for s in plan_day(problem).day.slots)


def test_a_task_request_carries_its_rank_in_the_stored_plan() -> None:
    stored = to_v1(numbered(two_loads()))["taches_en_attente"]
    assert [(t["summary"], t.get("rang")) for t in stored] == [
        (DRYER, None),
        (WASHER, None),
        (WASHER, 2),
        (DRYER, 2),
    ]
    again = from_v1({**to_v1(numbered(two_loads())), "date_cible": two_loads().day})
    assert [t.rank for t in again.waiting_tasks] == [None, None, 2, 2]
    assert TaskRequest(name=WASHER, rank=2).ident == "Lave-linge #2"
