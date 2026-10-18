"""Cycles des équipements mesurés sur leurs relevés : segments d'activité, énergie, forme,
profil médian.

Réécriture des fonctions de ``forme_horaire_solaire.py`` (v1), leur oracle dans les
tests : ``_segments_activite_equipement``, ``_appliquer_energie_compteur``, ``_forme_cycle``,
``_forme_moyenne`` et ``profil_depuis_cycles``.

- **Détection** sur la puissance : chaque relevé est tenu jusqu'au suivant (capteurs rapportés
  sur changement) ; actif au-dessus d'un seuil par équipement ; coupures courtes fusionnées,
  activités parasites (afficheur, départ différé) écartées, puis pauses du programme fusionnées.
- **Énergie** mesurée au compteur de la prise quand il existe (plus juste que la puissance
  intégrée), lu quelques minutes après la fin du cycle.
- **Forme** : part de l'énergie par quart d'heure depuis le démarrage.
- **Profil** : énergie et durée médianes des cycles significatifs (au moins 30 % du plus gros
  et 0,05 kWh), forme moyenne ; au moins 3 cycles.
"""

import itertools
import math
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from statistics import median

from wattslot.detection import DeviceKind
from wattslot.planning.cycles import SHAPE_STEP

Observation = tuple[
    datetime, float
]  # (instant, valeur) : W pour la puissance, kWh pour un compteur

SHORT_GAP_MIN = 5  # coupure courte, toujours fusionnée
PARASITIC_KWH = 0.01  # activité parasite (afficheur, verrouillage, départ différé)
COUNTER_MARGIN_MIN = 5  # le compteur rapporte sa dernière hausse juste après la puissance
CYCLE_FRACTION = 0.3
MIN_CYCLE_KWH = 0.05
MIN_CYCLES = 3


@dataclass(frozen=True)
class KindRules:
    threshold_w: float  # au-dessus : en fonctionnement
    merge_min: float  # pauses d'un programme fusionnées en un seul cycle


DEFAULT_RULES = KindRules(15.0, SHORT_GAP_MIN)
# Règles de la v1 par équipement (valeurs de départ, non calibrées une à une).
RULES = {
    DeviceKind.WATER_HEATER: KindRules(20.0, 30),
    DeviceKind.WASHING_MACHINE: KindRules(15.0, 30),
    DeviceKind.DRYER: KindRules(15.0, 20),
    DeviceKind.DISHWASHER: KindRules(15.0, 30),
    DeviceKind.POOL_PUMP: KindRules(20.0, SHORT_GAP_MIN),
}


@dataclass(frozen=True)
class Cycle:
    start: datetime
    end: datetime
    energy_kwh: float
    running: bool = False  # encore en marche au dernier relevé
    from_counter: bool = False  # énergie lue au compteur (sinon : puissance intégrée)
    shape: tuple[float, ...] = ()

    @property
    def minutes(self) -> float:
        return (self.end - self.start).total_seconds() / 60


@dataclass(frozen=True)
class Profile:
    ok: bool
    cycles: tuple[Cycle, ...]  # cycles retenus
    energy_kwh: float | None = None  # médianes
    duration_min: int | None = None
    shape: tuple[float, ...] | None = None


def activity_segments(
    observations: Sequence[Observation],
    until: datetime | None,
    threshold_w: float,
    merge_min: float = SHORT_GAP_MIN,
    parasitic_kwh: float = 0.0,
) -> list[Cycle]:
    """Segments d'activité réels, triés ; énergie intégrée par palier sur la puissance."""
    if not observations:
        return []
    points = sorted(observations, key=lambda o: o[0])
    if until is not None and until > points[-1][0]:
        points.append((until, points[-1][1]))
    if len(points) < 2:
        return []
    raw: list[tuple[datetime, datetime]] = []
    start: datetime | None = None
    for (t0, v0), (_t1, _v1) in itertools.pairwise(points):
        active = v0 >= threshold_w
        if active and start is None:
            start = t0
        if not active and start is not None:
            raw.append((start, t0))
            start = None
    running_until: datetime | None = None
    if start is not None:
        raw.append((start, points[-1][0]))
        running_until = points[-1][0]
    if not raw:
        return []

    def merged(
        segments: list[tuple[datetime, datetime]], minutes: float
    ) -> list[tuple[datetime, datetime]]:
        found = [segments[0]]
        for begin, end in segments[1:]:
            last_begin, last_end = found[-1]
            if (begin - last_end).total_seconds() <= minutes * 60:
                found[-1] = (last_begin, end)
            else:
                found.append((begin, end))
        return found

    def energy(begin: datetime, end: datetime) -> float:
        total = 0.0
        for (t0, v0), (t1, _v1) in itertools.pairwise(points):
            low, high = max(t0, begin), min(t1, end)
            if high > low:
                total += v0 * (high - low).total_seconds() / 3600 / 1000
        return total

    segments = merged(raw, min(SHORT_GAP_MIN, merge_min))
    if parasitic_kwh > 0:
        segments = [
            (b, e) for b, e in segments if e == running_until or energy(b, e) >= parasitic_kwh
        ]
        if not segments:
            return []
    segments = merged(segments, merge_min)
    return [
        Cycle(
            b, e, round(energy(b, e), 3), running=running_until is not None and e == running_until
        )
        for b, e in segments
    ]


def apply_counter(cycles: Sequence[Cycle], counter: Sequence[Observation]) -> list[Cycle]:
    """Énergie de chaque cycle lue au compteur cumulatif (dernier relevé à l'instant voulu),
    sinon gardée telle qu'intégrée (compteur sans relevé avant, ou remis à zéro)."""
    points = sorted(counter)
    times = [t for t, _ in points]

    def value_at(moment: datetime) -> float | None:
        index = bisect_right(times, moment)
        return points[index - 1][1] if index else None

    found = []
    for index, cycle in enumerate(cycles):
        read_at = cycle.end + timedelta(minutes=COUNTER_MARGIN_MIN)
        if index + 1 < len(cycles):
            read_at = min(read_at, cycles[index + 1].start)
        first, last = value_at(cycle.start), value_at(read_at)
        if first is not None and last is not None and last >= first:
            cycle = replace(cycle, energy_kwh=round(last - first, 3), from_counter=True)
        else:
            cycle = replace(cycle, from_counter=False)
        found.append(cycle)
    return found


def cycle_shape(points: Sequence[Observation], start: datetime, end: datetime) -> tuple[float, ...]:
    """Part de l'énergie du cycle par quart d'heure depuis son début (somme 1), intégrée par
    palier sur la puissance ; vide si l'énergie est nulle. ``points`` triés."""
    times = [t for t, _ in points]
    slices = [0.0] * max(1, math.ceil((end - start) / SHAPE_STEP))
    index = max(0, bisect_right(times, start) - 1)
    while index < len(points) and points[index][0] < end:
        t0, v0 = points[index]
        t1 = points[index + 1][0] if index + 1 < len(points) else end
        cursor, bound_end = max(t0, start), min(t1, end)
        while cursor < bound_end:
            k = min(len(slices) - 1, int((cursor - start) / SHAPE_STEP))
            bound = min(bound_end, start + SHAPE_STEP * (k + 1))
            slices[k] += v0 * (bound - cursor).total_seconds()
            cursor = bound
        index += 1
    total = sum(slices)
    return tuple(x / total for x in slices) if total > 0 else ()


def average_shape(shapes: Sequence[Sequence[float]], duration_min: float) -> tuple[float, ...]:
    """Moyenne des formes ramenée à la durée médiane (au-delà : reporté sur la dernière tranche)."""
    count = max(1, math.ceil(duration_min / (SHAPE_STEP.total_seconds() / 60)))
    sums = [0.0] * count
    for shape in shapes:
        for k, part in enumerate(shape):
            sums[min(k, count - 1)] += part
    total = sum(sums)
    return tuple(round(x / total, 4) for x in sums) if total > 0 else ()


def profile_from_cycles(cycles: Sequence[Cycle]) -> Profile:
    """Énergie et durée médianes des cycles significatifs, forme moyenne."""
    biggest = max((c.energy_kwh for c in cycles), default=0.0)
    threshold = max(MIN_CYCLE_KWH, biggest * CYCLE_FRACTION)
    kept = tuple(c for c in cycles if c.energy_kwh >= threshold)
    if len(kept) < MIN_CYCLES:
        return Profile(ok=False, cycles=kept)
    duration = round(median(round(c.minutes) for c in kept))
    shapes = [c.shape for c in kept if c.shape]
    return Profile(
        ok=True,
        cycles=kept,
        energy_kwh=round(median(c.energy_kwh for c in kept), 3),
        duration_min=duration,
        shape=average_shape(shapes, duration) if shapes else None,
    )


def measure_cycles(
    kind: DeviceKind,
    power: Sequence[Observation],
    counter: Sequence[Observation],
    until: datetime,
    window_start: datetime | None = None,
) -> list[Cycle]:
    """Cycles d'un équipement sur une fenêtre : détectés sur la puissance, mesurés au compteur,
    avec leur forme. Avec ``window_start``, les cycles coupés par un bord de la fenêtre
    (déjà en marche au début, ou encore en marche à la fin) sont écartés : énergie partielle."""
    rules = RULES.get(kind, DEFAULT_RULES)
    cycles = activity_segments(power, until, rules.threshold_w, rules.merge_min, PARASITIC_KWH)
    if window_start is not None:
        ordered = sorted(power, key=lambda o: o[0])
        if cycles and ordered and ordered[0][1] >= rules.threshold_w:
            cycles = cycles[1:]
        cycles = [c for c in cycles if c.end < until]
    points = sorted(power, key=lambda o: o[0])
    shaped = [replace(c, shape=cycle_shape(points, c.start, c.end)) for c in cycles]
    return apply_counter(shaped, counter) if counter else shaped
