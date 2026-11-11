"""Cycles des équipements : énergie par heure, recalage sur le démarrage réel.

Réécriture de ``recalage_cycles.py`` (v1), qui sert d'oracle aux tests différentiels.

- **Énergie d'un cycle par heure** : selon la forme mesurée du cycle (part de l'énergie par
  quart d'heure depuis le démarrage) quand elle est connue, sinon à puissance constante sur
  sa durée. La part postérieure à minuit n'est pas comptée, sauf à le demander (``days=2`` :
  heures 24, 25… du lendemain, pour un cycle qui déborde après minuit).
- **Recalage** : un équipement est souvent lancé à un autre moment que prévu. Dès qu'un cycle
  réel significatif apparaît dans les relevés du jour (au moins ``RECOGNIZED_FRACTION`` de
  l'énergie prévue), la fin prévue devient démarrage réel + durée du cycle (repoussée si le
  cycle dure plus longtemps), et l'énergie restante, énergie prévue moins énergie déjà mesurée.

Énergies consommée et restante arrondies au Wh, comme la v1.
"""

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

DAY_MIN = 24 * 60
# Écarte les relances de thermostat et les réveils de veille, sans attendre longtemps un vrai
# démarrage (lave-linge : 0,06 kWh pour quelques minutes de chauffe).
RECOGNIZED_FRACTION = 0.3
OVERRUN_MIN = 15  # cycle encore en cours au-delà de sa durée : fin repoussée d'autant
SHAPE_STEP = timedelta(minutes=15)  # pas de la forme d'un cycle

Shape = Sequence[float]


@dataclass(frozen=True)
class PlannedCycle:
    """Cycle placé dans la journée (minutes depuis minuit)."""

    start_min: int
    end_min: int
    energy_kwh: float
    shape: Shape | None = None


@dataclass(frozen=True)
class Segment:
    """Période d'activité réelle d'un équipement, tirée des relevés du jour."""

    start: datetime
    end: datetime  # dernier relevé de l'activité
    energy_kwh: float
    running: bool = False  # encore en marche au dernier relevé


@dataclass(frozen=True)
class Realignment:
    start: datetime
    expected_end: datetime
    running: bool
    consumed_kwh: float
    remaining_kwh: float


def spread(start: datetime, end: datetime, energy_kwh: float, days: int = 1) -> dict[int, float]:
    """kWh par heure, à puissance constante sur [start, end), jusqu'à minuit (``days=2`` :
    jusqu'au minuit suivant, heures du lendemain numérotées 24, 25…)."""
    hours = (end - start).total_seconds() / 3600
    if hours <= 0 or energy_kwh <= 0:
        return {}
    day = start.replace(hour=0, minute=0, second=0, microsecond=0)
    midnight = day + timedelta(days=days)
    by_hour: dict[int, float] = defaultdict(float)
    cursor = start
    while cursor < min(end, midnight):
        bound = min(end, cursor.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
        hour = cursor.hour + 24 * (cursor - day).days
        by_hour[hour] += energy_kwh * (bound - cursor).total_seconds() / 3600 / hours
        cursor = bound
    return dict(by_hour)


def spread_shape(
    start: datetime,
    shape: Shape | None,
    energy_kwh: float,
    since: datetime | None = None,
    until: datetime | None = None,
    days: int = 1,
) -> dict[int, float]:
    """kWh par heure selon la forme du cycle démarré à ``start``.

    Avec ``since`` / ``until``, seule la partie de la forme entre ces bornes sert, renormalisée
    pour porter toute l'énergie. Vide si cette partie est vide : l'appelant répartit alors à
    puissance constante.
    """
    pieces: list[tuple[datetime, datetime, float]] = []
    for index, part in enumerate(shape or []):
        low, high = start + SHAPE_STEP * index, start + SHAPE_STEP * (index + 1)
        low, high = max(low, since or low), min(high, until or high)
        if high > low and part > 0:
            # part fois durée est une durée, arrondie à la microseconde comme dans la v1 :
            # l'ordre des opérations est gardé pour des résultats identiques.
            pieces.append((low, high, part * (high - low) / SHAPE_STEP))
    total = sum(weight for _, _, weight in pieces)
    if total <= 0:
        return {}
    by_hour: dict[int, float] = defaultdict(float)
    for low, high, weight in pieces:
        # ``days=1`` : comme la v1 (oracle), une part d'après minuit retombe sur les heures du
        # même jour ; sinon, elle va aux heures du lendemain (24, 25…).
        offset = 24 * (low.date() - start.date()).days if days > 1 else 0
        for hour, kwh in spread(low, high, energy_kwh * weight / total, days).items():
            by_hour[hour + offset] += kwh
    return dict(by_hour)


def planned_hourly(cycle: PlannedCycle, days: int = 1) -> dict[int, float]:
    """kWh par heure d'un cycle placé, pas encore lancé (``days=2`` : avec sa part du
    lendemain, heures 24, 25…)."""
    day = datetime(2000, 1, 1)
    start = day + timedelta(minutes=cycle.start_min)
    by_hour = spread_shape(start, cycle.shape, cycle.energy_kwh, days=days)
    if by_hour or cycle.end_min <= cycle.start_min:
        return by_hour
    return spread(start, day + timedelta(minutes=cycle.end_min), cycle.energy_kwh, days)


def after_midnight(hourly: Mapping[int, float]) -> dict[int, float]:
    """Part du lendemain (heures 24, 25…) ramenée aux heures du lendemain (0, 1…)."""
    return {hour - 24: kwh for hour, kwh in hourly.items() if hour >= 24 and kwh > 0}


def recognized_segment(segments: Sequence[Segment], planned_kwh: float) -> Segment | None:
    """Dernière activité du jour reconnue comme le cycle de l'équipement."""
    threshold = RECOGNIZED_FRACTION * (planned_kwh or 0.0)
    recognized = [s for s in segments if s.energy_kwh >= threshold and s.energy_kwh > 0]
    return recognized[-1] if recognized else None


# Recommandation non suivie : délai après le départ annoncé, sans aucune activité mesurée de
# l'appareil, au-delà duquel le créneau n'est plus tenu pour commencé (comme le délai de la
# notification « cycle prévu non lancé », ``notification_events.LATE_MIN``).
UNFOLLOWED_MIN = 30


def ran_around(segments: Sequence[Segment], start_min: int, now: datetime) -> bool:
    """L'appareil a-t-il tourné autour du départ annoncé (``start_min``, minutes du jour de
    ``now``) : une activité mesurée qui dure encore, ou qui a fini au plus tôt
    ``UNFOLLOWED_MIN`` avant ce départ. Toute activité compte, reconnue comme le cycle prévu ou
    non : dans le doute, la recommandation est tenue pour suivie."""
    planned = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
        minutes=start_min - UNFOLLOWED_MIN
    )
    return any(segment.running or segment.end >= planned for segment in segments)


def realign(
    planned_kwh: float, cycle_min: float, segments: Sequence[Segment], now: datetime
) -> Realignment | None:
    """Recalage d'un cycle prévu sur son cycle réel du jour, s'il y en a un."""
    segment = recognized_segment(segments, planned_kwh)
    if segment is None:
        return None
    if segment.running:
        expected_end = max(
            segment.start + timedelta(minutes=cycle_min), now + timedelta(minutes=OVERRUN_MIN)
        )
        remaining = max(0.0, (planned_kwh or 0.0) - segment.energy_kwh)
    else:
        expected_end, remaining = segment.end, 0.0
    return Realignment(
        start=segment.start,
        expected_end=expected_end,
        running=segment.running,
        consumed_kwh=round(segment.energy_kwh, 3),
        remaining_kwh=round(remaining, 3),
    )


def free_from_minute(realignment: Realignment, capped: bool = True) -> int:
    """Minute du jour (arrondie au-dessus, au plus minuit sauf ``capped=False``) où
    l'équipement est libre."""
    start, end = realignment.start, realignment.expected_end
    minutes = (end.date() - start.date()).days * DAY_MIN + end.hour * 60 + end.minute
    if end.second or end.microsecond:
        minutes += 1
    return min(DAY_MIN, minutes) if capped else minutes


def free_from_hour(realignment: Realignment) -> int:
    return math.ceil(free_from_minute(realignment) / 60)


def remaining_hourly(
    realignment: Realignment, now: datetime, shape: Shape | None = None, days: int = 1
) -> dict[int, float]:
    """kWh par heure de l'énergie restante du cycle, de maintenant à sa fin prévue
    (``days=2`` : avec sa part du lendemain, heures 24, 25…, du jour de ``now``)."""
    if not realignment.running:
        return {}
    by_hour = spread_shape(
        realignment.start, shape, realignment.remaining_kwh, since=now, days=days
    )
    if by_hour and realignment.start.date() != now.date():
        shift = 24 * (realignment.start.date() - now.date()).days
        by_hour = {hour + shift: kwh for hour, kwh in by_hour.items()}
    return by_hour or spread(now, realignment.expected_end, realignment.remaining_kwh, days)


def measured_hourly(
    realignment: Realignment, segment: Segment, shape: Shape | None = None
) -> dict[int, float]:
    """kWh par heure de l'énergie déjà mesurée du cycle, jusqu'au dernier relevé."""
    energy = realignment.consumed_kwh
    return spread_shape(segment.start, shape, energy, until=segment.end) or spread(
        segment.start, segment.end, energy
    )
