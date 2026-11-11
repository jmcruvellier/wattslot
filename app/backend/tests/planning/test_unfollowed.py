"""Recommandation non suivie : un départ annoncé resté sans activité mesurée n'est pas un
lancement.

Jusqu'ici (comme en v1), un créneau dont l'heure était passée était tenu pour commencé : la
demande était marquée « lancée aujourd'hui » et fermée le lendemain, que l'appareil ait tourné
ou non (vu sur une installation réelle le 11/11/2026). Pour un appareil mesuré, le créneau est
maintenant libéré et l'appareil replacé."""

from dataclasses import replace
from datetime import datetime, timedelta

from tests.v1_oracle import load, state_named
from wattslot.planning.assignment import launched_keys
from wattslot.planning.cycles import Segment, ran_around
from wattslot.planning.inputs import FrozenCycle, PlanningInput, from_v1
from wattslot.planning.merge import merge_planning
from wattslot.planning.problem import from_input
from wattslot.planning.reference import task_key

DEVICE = "Lave-vaisselle"


def _morning(start_min: int = 6 * 60) -> PlanningInput:
    """Journée type calculée à 7 h 59, le lave-vaisselle annoncé plus tôt par le plan précédent
    (6 h par défaut) : son créneau est passé."""
    state, _ = load(state_named("05_today_h07_morning"))
    data = from_v1(state)
    assert data.real_updated_at is not None and data.real_updated_at.hour == 7
    block = FrozenCycle(
        name=DEVICE,
        start_hour=start_min // 60,
        end_hour=start_min // 60 + 2,
        energy_kwh=0.71,
        start_min=start_min,
        end_min=start_min + 117,
        cycle_min=117,
        shape=None,
        priority=3,
    )
    return replace(data, frozen=(block,), real_segments={})


def _activity(data: PlanningInput, hour: int, minute: int, minutes: int = 40) -> Segment:
    now = data.real_updated_at
    assert now is not None
    start = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return Segment(start, start + timedelta(minutes=minutes), 0.3)


def test_an_unmeasured_appliance_is_still_held_as_started() -> None:
    data = _morning()

    problem = from_input(data)

    assert DEVICE not in {task.name for task in problem.tasks}
    assert not problem.unfollowed
    assert task_key(DEVICE) in launched_keys(data)


def test_a_measured_appliance_that_did_not_run_is_placed_again() -> None:
    data = replace(_morning(), measured=frozenset({DEVICE}))

    problem = from_input(data)

    assert problem.unfollowed == {DEVICE} and DEVICE in problem.released
    task = next(task for task in problem.tasks if task.name == DEVICE)
    assert task.earliest_min == 7 * 60 + 59  # à partir de maintenant
    assert task_key(DEVICE) not in launched_keys(data)


def test_a_measured_appliance_that_ran_keeps_its_slot() -> None:
    data = replace(_morning(), measured=frozenset({DEVICE}))
    data = replace(data, real_segments={DEVICE: (_activity(data, 6, 5),)})

    problem = from_input(data)

    assert not problem.unfollowed
    assert DEVICE not in {task.name for task in problem.tasks}
    assert task_key(DEVICE) in launched_keys(data)


def test_a_start_announced_less_than_half_an_hour_ago_waits() -> None:
    """7 h 30 annoncé, il est 7 h 59 : pas encore en retard, le créneau reste."""
    data = replace(_morning(7 * 60 + 30), measured=frozenset({DEVICE}))

    assert not from_input(data).unfollowed
    assert from_input(replace(_morning(7 * 60 + 29), measured=frozenset({DEVICE}))).unfollowed


def test_any_activity_around_the_announced_start_counts() -> None:
    now = datetime(2026, 11, 11, 15, 5)
    start = 14 * 60

    def segment(hour: int, minute: int, end_hour: int, end_minute: int, running: bool = False):  # type: ignore[no-untyped-def]
        return Segment(
            now.replace(hour=hour, minute=minute),
            now.replace(hour=end_hour, minute=end_minute),
            0.2,
            running,
        )

    assert not ran_around((), start, now)
    assert not ran_around((segment(9, 0, 10, 30),), start, now)  # un cycle du matin, fini
    assert ran_around((segment(12, 50, 13, 40),), start, now)  # lancé en avance
    assert ran_around((segment(14, 20, 14, 50),), start, now)  # lancé en retard
    assert ran_around((segment(8, 0, 8, 5, running=True),), start, now)  # tourne encore


def test_an_unfollowed_slot_that_no_longer_fits_is_not_kept_in_the_past() -> None:
    old = [{"equipement": DEVICE, "heure_debut": 6, "debut_min": 360, "energie_kwh": 0.71}]

    kept = merge_planning(old, [], 8, {DEVICE})
    dropped = merge_planning(old, [], 8, {DEVICE}, None, None, frozenset({DEVICE}))

    assert [item["equipement"] for item in kept] == [DEVICE]
    assert dropped == []
