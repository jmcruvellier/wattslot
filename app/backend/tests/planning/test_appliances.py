"""Cycles des équipements mesurés : la réécriture donne les mêmes résultats que la v1."""

import itertools
import math
import random
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from tests.v1_oracle import v1
from wattslot.detection import DeviceKind
from wattslot.planning.appliances import (
    PARASITIC_KWH,
    RULES,
    Cycle,
    activity_segments,
    apply_counter,
    cycle_shape,
    measure_cycles,
    profile_from_cycles,
)

V1 = "forme_horaire_solaire."
PARIS = ZoneInfo("Europe/Paris")
START = datetime(2026, 10, 13, 22, tzinfo=UTC)  # minuit à Paris


def utc(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def power_series(rng: random.Random, hours: int = 24) -> list[tuple[datetime, float]]:
    """Relevés de puissance irréguliers : veille, cycles, pauses, parasites."""
    points, moment = [], START + timedelta(seconds=rng.randint(0, 600))
    end = START + timedelta(hours=hours)
    level = rng.choice([0.0, 3.0, 1500.0])
    while moment < end:
        points.append((moment, level))
        moment += timedelta(seconds=rng.choice([20, 60, 90, 300, 600, 1200, 2400]))
        roll = rng.random()
        if roll < 0.3:
            level = rng.choice([0.0, 2.0, 8.0])
        elif roll < 0.8:
            level = rng.uniform(15, 2500)
        else:
            level = rng.choice([14.9, 15.0, 19.9, 20.0])
    return points


def counter_series(
    rng: random.Random, power: list[tuple[datetime, float]]
) -> list[tuple[datetime, float]]:
    total, found = rng.uniform(100, 200), []
    for (t0, v0), (t1, _) in itertools.pairwise(power):
        total += v0 * (t1 - t0).total_seconds() / 3_600_000 * rng.uniform(0.6, 1.0)
        found.append((t1 + timedelta(seconds=rng.randint(0, 400)), round(total, 3)))
        if rng.random() < 0.01:
            total = 0.0  # compteur remis à zéro
    return sorted(found)


def as_cycle(segment: dict[str, Any]) -> Cycle:
    return Cycle(
        start=datetime.fromisoformat(segment["debut_iso"]),
        end=datetime.fromisoformat(segment["fin_iso"]),
        energy_kwh=segment["energie_kwh"],
        running=bool(segment.get("en_cours")),
        from_counter=segment.get("source_energie") == "compteur",
    )


def as_segment(cycle: Cycle) -> dict[str, Any]:
    segment: dict[str, Any] = {
        "debut_iso": cycle.start.astimezone(PARIS).isoformat(),
        "fin_iso": cycle.end.astimezone(PARIS).isoformat(),
        "energie_kwh": cycle.energy_kwh,
    }
    if cycle.running:
        segment["en_cours"] = True
    return segment


@pytest.mark.parametrize("seed", range(300))
def test_activity_segments_same_as_v1(seed: int) -> None:
    rng = random.Random(seed)
    power = power_series(rng)
    until = rng.choice([None, power[-1][0] + timedelta(minutes=rng.randint(0, 90))])
    threshold = rng.choice([15.0, 20.0])
    merge = rng.choice([5, 20, 30])
    parasitic = rng.choice([0.0, PARASITIC_KWH])

    expected = v1(
        V1 + "_segments_activite_equipement",
        [(utc(t), v) for t, v in power],
        utc(until) if until else None,
        threshold,
        merge,
        parasitic,
    )

    assert activity_segments(power, until, threshold, merge, parasitic) == [
        as_cycle(s) for s in expected
    ]


@pytest.mark.parametrize("seed", range(300))
def test_counter_energy_and_shape_same_as_v1(seed: int) -> None:
    rng = random.Random(seed)
    power = power_series(rng)
    counter = counter_series(rng, power)
    cycles = activity_segments(power, power[-1][0], 15.0, 30, PARASITIC_KWH)

    expected = v1(
        V1 + "_appliquer_energie_compteur",
        [as_segment(c) for c in cycles],
        [(utc(t), v) for t, v in counter],
    )
    assert apply_counter(cycles, counter) == [as_cycle(s) for s in expected]

    # Formes de la v1 (``_forme_cycle`` sur les relevés passés à l'heure locale).
    shapes = v1(
        V1 + "formes_cycles",
        [(utc(t), v) for t, v in power],
        [(cycle.start, cycle.end) for cycle in cycles],
    )
    for cycle, shape in zip(cycles, shapes, strict=True):
        assert cycle_shape(power, cycle.start, cycle.end) == pytest.approx(tuple(shape), abs=1e-12)


@pytest.mark.parametrize("seed", range(300))
def test_profile_same_as_v1(seed: int) -> None:
    rng = random.Random(seed)
    cycles = []
    for _ in range(rng.randint(0, 8)):
        start = START + timedelta(minutes=rng.randint(0, 30 * 24 * 60))
        minutes = rng.randint(20, 240)
        shape = tuple(rng.random() for _ in range(rng.randint(0, 12)))
        total = math.fsum(shape)  # même somme en Python 3.11 et 3.12
        cycles.append(
            Cycle(
                start,
                start + timedelta(minutes=minutes, seconds=rng.randint(0, 59)),
                round(rng.uniform(0, 2), 3),
                shape=tuple(x / total for x in shape) if total else (),
            )
        )

    expected = v1(
        V1 + "profil_depuis_cycles", [{**as_segment(c), "forme": list(c.shape)} for c in cycles]
    )
    profile = profile_from_cycles(cycles)

    assert profile.ok == (expected["status"] == "ok")
    assert [round(c.minutes) for c in profile.cycles] == [
        c["duree_min"] for c in expected["cycles"]
    ]
    assert profile.energy_kwh == expected.get("energie_kwh")
    assert profile.duration_min == expected.get("duree_min")
    expected_shape = expected.get("forme_quart_heure")
    assert profile.shape == (tuple(expected_shape) if expected_shape else None)


@pytest.mark.parametrize("seed", range(200))
def test_measure_cycles_same_as_v1_profile_window(seed: int) -> None:
    """Mêmes étapes que ``calculer_profil_cycles`` de la v1 sur une fenêtre."""
    rng = random.Random(seed)
    kind = rng.choice(list(RULES))
    power = power_series(rng, hours=48)
    counter = counter_series(rng, power)
    until = START + timedelta(hours=48)
    rules = RULES[kind]

    # Étapes de la v1 : segments d'activité, le premier écarté s'il a commencé avant la fenêtre,
    # segments finis seulement, formes, puis énergie des compteurs.
    expected = v1(
        V1 + "cycles_fenetre",
        [(utc(t), v) for t, v in power],
        until,
        rules.threshold_w,
        rules.merge_min,
        PARASITIC_KWH,
        [(utc(t), v) for t, v in counter],
    )

    actual = measure_cycles(kind, power, counter, until, window_start=START)

    assert [(c.start, c.end, c.energy_kwh, c.from_counter) for c in actual] == [
        (
            datetime.fromisoformat(s["debut_iso"]),
            datetime.fromisoformat(s["fin_iso"]),
            s["energie_kwh"],
            s["source_energie"] == "compteur",
        )
        for s in expected
    ]
    for cycle, segment in zip(actual, expected, strict=True):
        assert cycle.shape == pytest.approx(tuple(segment["forme"]), abs=1e-12)


def test_rules_follow_v1() -> None:
    thresholds = v1(V1 + "SEUIL_PUISSANCE_ACTIVITE_W")
    assert RULES[DeviceKind.WATER_HEATER].threshold_w == thresholds["chauffe_eau"]
    merges = v1(V1 + "FUSION_COUPURE_CYCLE_MINUTES")
    assert RULES[DeviceKind.DRYER].merge_min == merges["seche_linge"]
