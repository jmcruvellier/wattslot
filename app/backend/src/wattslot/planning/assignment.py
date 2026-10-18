"""Affectation des tâches en attente à un seul jour (planning sur plusieurs jours).

Réécriture de ``affectation.py`` (v1), son oracle dans les tests. Une tâche en attente
(lave-linge, sèche-linge, lave-vaisselle sans échéance) est affectée à un jour, entre
aujourd'hui et sa date limite :

- **date de référence** : le besoin détecté (description de la tâche dans HA), sinon le jour
  où l'application a vu la tâche pour la première fois (mémorisé) ; elle ne bouge plus, une
  tâche ne peut donc pas être reportée indéfiniment ;
- **jours candidats** : d'aujourd'hui à référence + ``MAX_DELAY_DAYS`` (aujourd'hui seulement
  une fois la limite dépassée), parmi ceux dont la prévision est connue ;
- **couverture** d'un jour : part de l'énergie du cycle couverte par le surplus solaire sur
  le meilleur créneau de ce jour (pour aujourd'hui, sur les heures restantes) ;
- **score** = couverture moins ``DAY_PENALTY`` par jour de retard ; à égalité, le plus tôt ;
- **stabilité** : un jour déjà choisi n'est quitté que pour un score meilleur d'au moins
  ``STABILITY_MARGIN`` ;
- **verrouillage** : une tâche lancée aujourd'hui (bloc gelé ou cycle réel reconnu), ou qui
  dépend d'une tâche lancée, reste aujourd'hui.

Un sèche-linge qui dépend d'un lave-linge en attente lui est lié : le couple est évalué
ensemble et affecté au même jour. Le surplus est celui du jour avant la batterie, comme en v1.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from wattslot.planning.cycles import DAY_MIN, recognized_segment
from wattslot.planning.inputs import PlanningInput, TaskRequest
from wattslot.planning.problem import characteristics
from wattslot.planning.reference import REFERENCE, Reference, task_key

DAY_PENALTY = 0.25
STABILITY_MARGIN = 0.10
MAX_DELAY_DAYS = 2

Surplus = Mapping[int, float]  # kWh de surplus par heure (heures sans donnée absentes)
Cycle = tuple[int, float]  # (durée du créneau en minutes, puissance en kW)


@dataclass(frozen=True)
class Assignment:
    day: date
    reference: date
    task: str
    coverage: float | None  # couverture du jour choisi
    coverage_today: float | None


@dataclass(frozen=True)
class Previous:
    """Ce qu'on retient d'une affectation d'une exécution à l'autre."""

    day: date | None = None
    reference: date | None = None


def slot_minutes(cycle_min: float, reference: Reference = REFERENCE) -> int:
    return max(1, min(reference.cycle_max_hours * 60, round(cycle_min)))


def _starts(earliest_min: int) -> list[int]:
    first_full_hour = math.ceil(earliest_min / 60) * 60
    return [earliest_min] + [m for m in range(first_full_hour, DAY_MIN, 60) if m != earliest_min]


def slot_score(
    start_min: int, duration_min: int, surplus: Surplus, power_kw: float
) -> tuple[float, float]:
    """(surplus absorbable, surplus brut) sur le créneau, chaque heure pondérée par la part
    qu'en occupe le cycle."""
    end_min = start_min + duration_min
    raw = absorbed = 0.0
    for hour in range(start_min // 60, math.ceil(end_min / 60)):
        part = (min(end_min, (hour + 1) * 60) - max(start_min, hour * 60)) / 60
        raw += part * surplus.get(hour, 0.0)
        absorbed += part * min(surplus.get(hour, 0.0), power_kw)
    return absorbed, raw


def best_start(
    duration_min: int, surplus: Surplus, earliest_min: int, power_kw: float
) -> int | None:
    """Départ qui absorbe le plus de surplus (au plus tôt, puis chaque heure pile), ou None
    si le cycle ne tient plus dans la journée."""
    best: int | None = None
    best_score: tuple[float, float] | None = None
    for start in _starts(earliest_min):
        if start + duration_min > DAY_MIN:
            break
        score = slot_score(start, duration_min, surplus, power_kw)
        if best_score is None or score > best_score:
            best, best_score = start, score
    return best


def best_start_with_next(
    duration_min: int, power_kw: float, following: Cycle, surplus: Surplus, earliest_min: int
) -> int | None:
    """Départ d'une tâche choisi avec celui de la suivante (qui démarre dès sa fin au plus
    tôt) ; repli sur la tâche seule si aucun couple ne tient."""
    following_min, following_kw = following
    best: int | None = None
    best_score: tuple[float, ...] | None = None
    for start in _starts(earliest_min):
        if start + duration_min > DAY_MIN:
            break
        next_start = best_start(following_min, surplus, start + duration_min, following_kw)
        if next_start is None:
            break
        first = slot_score(start, duration_min, surplus, power_kw)
        second = slot_score(next_start, following_min, surplus, following_kw)
        score = tuple(x + y for x, y in zip(first, second, strict=True))
        if best_score is None or score > best_score:
            best_score, best = score, start
    if best is None:
        return best_start(duration_min, surplus, earliest_min, power_kw)
    return best


def coverage(surplus: Surplus, cycles: Sequence[Cycle], earliest_min: int) -> float | None:
    """Part (0 à 1) de l'énergie des cycles (un seul, ou un couple) couverte par le surplus
    sur le meilleur créneau du jour ; None s'ils ne tiennent pas."""
    (duration, power), *following = cycles
    if following:
        next_duration, next_power = following[0]
        start = best_start_with_next(
            duration, power, (next_duration, next_power), surplus, earliest_min
        )
        if start is None:
            return None
        next_start = best_start(next_duration, surplus, start + duration, next_power)
        if next_start is None:
            return None
        absorbed = (
            slot_score(start, duration, surplus, power)[0]
            + slot_score(next_start, next_duration, surplus, next_power)[0]
        )
        energy = power * duration / 60 + next_power * next_duration / 60
    else:
        start = best_start(duration, surplus, earliest_min, power)
        if start is None:
            return None
        absorbed = slot_score(start, duration, surplus, power)[0]
        energy = power * duration / 60
    return min(1.0, absorbed / energy) if energy > 0 else None


def _groups(tasks: Sequence[TaskRequest]) -> list[list[TaskRequest]]:
    """Un lave-linge et le sèche-linge en attente qui en dépend forment un groupe (le
    lave-linge d'abord) ; les autres tâches sont seules."""
    by_key = {task_key(t.name): t for t in tasks}
    parents: dict[int, TaskRequest] = {}
    for t in tasks:
        parent = task_key(t.depends_on or "")
        if parent and parent != task_key(t.name) and parent in by_key:
            parents[id(t)] = by_key[parent]
    groups: list[list[TaskRequest]] = []
    seen: set[int] = set()
    for t in tasks:
        if id(t) in seen or id(t) in parents:
            continue
        group = [t] + [d for d in tasks if parents.get(id(d)) is t]
        seen.update(id(x) for x in group)
        groups.append(group)
    groups += [[t] for t in tasks if id(t) not in seen]  # chaîne ou cycle : seules
    return groups


def reference_day(task: TaskRequest, memory: Mapping[str, Previous], today: date) -> date:
    if task.needed_since is not None:
        return task.needed_since
    known = memory.get(task.uid or "")
    return known.reference if known is not None and known.reference is not None else today


def decide(
    tasks: Sequence[TaskRequest],
    surplus_by_day: Mapping[date, Surplus],
    today: date,
    first_hour: int,
    cycles: Mapping[str, tuple[float, float]],
    memory: Mapping[str, Previous],
    locked: set[str],
    reference: Reference = REFERENCE,
    delays: Mapping[str, int] | None = None,
) -> tuple[dict[str, Assignment], list[dict[str, Any]]]:
    """(affectations par uid, avertissements de report).

    ``cycles`` : (énergie, durée en minutes) par nom de tâche, pour celles qui ont un profil ;
    ``memory`` : affectations précédentes ; ``locked`` : clés des équipements lancés ;
    ``delays`` : tolérance de report par nom de tâche (lot 3.5), sinon ``MAX_DELAY_DAYS``.
    """
    assignments: dict[str, Assignment] = {}
    reports: list[dict[str, Any]] = []
    for group in _groups([t for t in tasks if t.uid]):
        if any(t.name not in cycles for t in group):
            continue  # profil indisponible : le calcul l'avertit déjà
        group_cycles: list[Cycle] = []
        for t in group:
            energy, cycle_min = cycles[t.name]
            duration = slot_minutes(cycle_min, reference)
            group_cycles.append((duration, energy * 60 / duration))
        ref = min(reference_day(t, memory, today) for t in group)
        delay = min((delays or {}).get(t.name, MAX_DELAY_DAYS) for t in group)
        limit = max(today, ref + timedelta(days=delay))
        candidates = sorted(d for d in surplus_by_day if today <= d <= limit)
        coverages = {
            d: coverage(surplus_by_day[d], group_cycles, first_hour * 60 if d == today else 0)
            for d in candidates
        }
        scores = {
            d: c - DAY_PENALTY * (d - today).days for d, c in coverages.items() if c is not None
        }
        is_locked = any(
            task_key(t.name) in locked or task_key(t.depends_on or "") in locked for t in group
        )
        if is_locked or not scores:
            day = today  # lancé, ou aucun jour ne convient
        else:
            day = max(scores, key=lambda d: (scores[d], -d.toordinal()))
            previous = memory.get(group[0].uid or "")
            before = previous.day if previous is not None else None
            if (
                before in scores
                and before != day
                and scores[day] < scores[before] + STABILITY_MARGIN
            ):
                day = before
        for t in group:
            assignments[t.uid or ""] = Assignment(
                day=day,
                reference=ref,
                task=t.name,
                coverage=coverages.get(day),
                coverage_today=coverages.get(today),
            )
            if day > today:
                reports.append(_report(t.name, day, coverages.get(day), coverages.get(today)))
    return assignments, reports


def _report(
    task: str, day: date, coverage_day: float | None, coverage_today: float | None
) -> dict[str, Any]:
    if coverage_today is None:
        return {
            "code": "tache_reportee_sans_creneau",
            "params": {"equipement": task, "jour": day.isoformat()},
        }
    return {
        "code": "tache_reportee",
        "params": {
            "equipement": task,
            "jour": day.isoformat(),
            "pct_jour": f"{(coverage_day or 0.0) * 100:.0f}",
            "pct_auj": f"{coverage_today * 100:.0f}",
        },
    }


def task_cycles(
    data: PlanningInput, reference: Reference = REFERENCE
) -> dict[str, tuple[float, float]]:
    """(énergie, durée en minutes) des tâches en attente qui ont un profil exploitable."""
    found = {}
    for task in data.waiting_tasks:
        cycle = characteristics(task.name, data, reference)
        if cycle is not None:
            found[task.name] = cycle
    return found


def launched_keys(data: PlanningInput, reference: Reference = REFERENCE) -> set[str]:
    """Clés des équipements lancés aujourd'hui : bloc gelé d'une tâche active, ou cycle réel
    reconnu d'une tâche en attente (même seuil que le recalage)."""
    active = {t.name for t in data.due_tasks if t.due == data.day} | {
        t.name for t in data.waiting_tasks
    }
    keys = {task_key(item.name) for item in data.frozen if item.name in active}
    now = data.real_updated_at
    if now is None or now.date() != data.day:
        return keys
    segments = {task_key(name): segs for name, segs in data.real_segments.items()}
    for task in data.waiting_tasks:
        cycle = characteristics(task.name, data, reference)
        key = task_key(task.name)
        if cycle is not None and recognized_segment(segments.get(key, ()), cycle[0]) is not None:
            keys.add(key)
    return keys
