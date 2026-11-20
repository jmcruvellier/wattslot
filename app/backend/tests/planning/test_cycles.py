"""Cycles des équipements : la réécriture donne les mêmes résultats que la v1 (oracle)."""

import math
import random
from datetime import datetime, timedelta

import pytest

from tests.v1_oracle import v1
from wattslot.planning.cycles import (
    PlannedCycle,
    Realignment,
    Segment,
    free_from_hour,
    free_from_minute,
    is_recognized,
    measured_hourly,
    planned_hourly,
    realign,
    remaining_hourly,
    spread,
    spread_shape,
)

V1 = "recalage_cycles."
DAY = datetime(2026, 10, 13)
CASES = range(300)


def same(actual: dict[int, float], expected: dict[int, float]) -> None:
    assert set(actual) == set(expected)
    for hour, value in expected.items():
        assert actual[hour] == pytest.approx(value, abs=1e-9), hour


def moment(rng: random.Random, low_min: int = 0, high_min: int = 24 * 60 - 1) -> datetime:
    return DAY + timedelta(minutes=rng.randint(low_min, high_min), seconds=rng.choice([0, 0, 17]))


def shape(rng: random.Random) -> list[float] | None:
    if rng.random() < 0.25:
        return None
    parts = [rng.choice([0.0, rng.random()]) for _ in range(rng.randint(0, 12))]
    total = math.fsum(parts)  # même somme en Python 3.11 et 3.12
    return [p / total for p in parts] if total else parts


@pytest.mark.parametrize("seed", CASES)
def test_spread_and_spread_shape(seed: int) -> None:
    rng = random.Random(seed)
    start = moment(rng)
    end = start + timedelta(minutes=rng.randint(-10, 400))
    energy = rng.choice([0.0, rng.uniform(0, 3)])
    same(spread(start, end, energy), v1(V1 + "repartir", start, end, energy))
    cycle_shape = shape(rng)
    since = moment(rng) if rng.random() < 0.4 else None
    until = moment(rng) if rng.random() < 0.4 else None
    same(
        spread_shape(start, cycle_shape, energy, since=since, until=until),
        v1(V1 + "repartir_forme", start, cycle_shape, energy, a_partir_de=since, jusqua=until),
    )


@pytest.mark.parametrize("seed", CASES)
def test_planned_hourly(seed: int) -> None:
    rng = random.Random(seed)
    start = rng.randint(0, 24 * 60 - 1)
    end = min(24 * 60, start + rng.randint(1, 240))
    energy, cycle_shape = rng.uniform(0, 3), shape(rng)
    item = {
        "heure_debut": start // 60,
        "heure_fin": -(-end // 60),
        "debut_min": start,
        "fin_min": end,
        "energie_kwh": energy,
        "forme_quart_heure": cycle_shape,
    }
    same(
        planned_hourly(PlannedCycle(start, end, energy, cycle_shape)),
        v1(V1 + "conso_horaire_prevue", item),
    )


def segments(rng: random.Random) -> list[Segment]:
    found = []
    cursor = 0
    for _ in range(rng.randint(0, 3)):
        start = DAY + timedelta(minutes=cursor + rng.randint(0, 300), seconds=rng.randint(0, 59))
        end = start + timedelta(minutes=rng.randint(1, 180), seconds=rng.randint(0, 59))
        cursor = int((end - DAY).total_seconds() // 60) + 1
        if cursor >= 24 * 60:
            break
        found.append(Segment(start, end, rng.uniform(0, 2), running=False))
    if found and rng.random() < 0.5:
        last = found[-1]
        found[-1] = Segment(last.start, last.end, last.energy_kwh, running=True)
    return found


def as_v1(segment: Segment) -> dict[str, object]:
    return {
        "debut_iso": segment.start.isoformat(),
        "fin_iso": segment.end.isoformat(),
        "energie_kwh": segment.energy_kwh,
        "en_cours": segment.running,
    }


@pytest.mark.parametrize("seed", CASES)
def test_realignment(seed: int) -> None:
    rng = random.Random(seed)
    segs = segments(rng)
    planned_kwh, cycle_min = rng.uniform(0.05, 2), rng.uniform(30, 240)
    now = (segs[-1].end if segs else DAY) + timedelta(minutes=rng.randint(0, 30))
    item = {
        "energie_kwh": planned_kwh,
        "duree_cycle_min": cycle_min,
        "heure_debut": 0,
        "heure_fin": 0,
    }

    expected = v1(V1 + "recaler", item, [as_v1(s) for s in segs], now)
    actual = realign(planned_kwh, cycle_min, segs, now)

    if expected is None:
        # Écart voulu à la v1 : sans cycle reconnu à son énergie, une activité encore en
        # cours au rythme du cycle est reconnue (``is_recognized``).
        paced = [s for s in segs if s.running and is_recognized(s, planned_kwh, cycle_min)]
        assert (actual is None) == (not paced)
        return
    assert actual == Realignment(
        start=datetime.fromisoformat(expected["debut_iso"]),
        expected_end=datetime.fromisoformat(expected["fin_prevue_iso"]),
        running=expected["en_cours"],
        consumed_kwh=expected["energie_consommee_kwh"],
        remaining_kwh=expected["energie_restante_kwh"],
    )
    assert free_from_minute(actual) == v1(V1 + "minute_fin_recalee", expected)
    assert free_from_hour(actual) == v1(V1 + "heure_fin_recalee", expected)
    cycle_shape = shape(rng)
    same(
        remaining_hourly(actual, now, cycle_shape),
        v1(V1 + "conso_restante_horaire", expected, now, cycle_shape),
    )
    segment = v1(V1 + "cycle_reel", [as_v1(s) for s in segs], planned_kwh)
    recognized = next(s for s in segs if s.start.isoformat() == segment["debut_iso"])
    same(
        measured_hourly(actual, recognized, cycle_shape),
        v1(V1 + "conso_mesuree_horaire", expected, segment, cycle_shape),
    )


def test_a_long_cycle_still_running_is_recognized_by_its_pace() -> None:
    """20/11/2026 : sèche-linge de 1,48 kWh sur 4 h, en marche depuis 59 minutes avec 0,40 kWh
    (seuil : 0,44 kWh). Le calcul le croyait pas encore lancé et le replaçait à 12 h 04."""
    start = DAY + timedelta(hours=10)

    def running(minutes: int, kwh: float, still: bool = True) -> Segment:
        return Segment(start, start + timedelta(minutes=minutes), kwh, still)

    assert is_recognized(running(59, 0.40), 1.48, 240)
    assert realign(1.48, 240, [running(59, 0.40)], start + timedelta(minutes=59)) is not None
    # Activité finie sous le seuil, ou sans durée de cycle connue : comme avant.
    assert not is_recognized(running(59, 0.40, still=False), 1.48, 240)
    assert not is_recognized(running(59, 0.40), 1.48)
    # Réveil de veille (quelques watts) ou tout début d'activité : pas encore un cycle.
    assert not is_recognized(running(59, 0.01), 1.48, 240)
    assert not is_recognized(running(10, 0.10), 1.48, 240)
    # Au-dessus du seuil d'énergie : reconnue, en cours ou non.
    assert is_recognized(running(30, 0.50, still=False), 1.48, 240)
