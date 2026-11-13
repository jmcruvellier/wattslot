"""Plusieurs cycles d'un même équipement dans la journée (deux lessives, deux chauffes).

Le calcul a longtemps reconnu un cycle au nom de son équipement : une seconde demande du jour
était confondue avec le cycle déjà fait. Chaque cycle a désormais une identité propre :

- **rang** : sa place parmi les cycles du même équipement dans la journée. Le premier garde le
  nom de l'équipement (``reference.ident``), les suivants le portent avec leur rang. Une tâche
  garde d'un calcul à l'autre le rang de son bloc dans le plan précédent (reconnu à son uid) ;
  une nouvelle prend le premier rang libre. Un bloc d'un plan d'avant, sans uid, revient à la
  première tâche du même équipement qui n'a pas de bloc.
- **cycle réel** : une activité mesurée n'est attribuée qu'à un seul cycle, dans l'ordre des
  rangs. Elle n'est jamais celle d'une demande faite après son démarrage, ni celle d'un bloc
  dont la tâche est close et qui était fini avant elle.
- **dépendance** (sèche-linge après lave-linge) : les cycles des deux équipements sont appariés
  dans l'ordre des rangs — le premier sèche-linge suit le premier lave-linge, le deuxième le
  deuxième. Un sèche-linge de plus que de lave-linge n'attend que la fin du sèche-linge
  précédent. L'appariement d'un cycle ne change donc pas quand une demande s'ajoute.
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime

from wattslot.planning.cycles import RECOGNIZED_FRACTION, Segment
from wattslot.planning.inputs import PlanningInput, TaskRequest
from wattslot.planning.reference import task_key


def today_tasks(data: PlanningInput) -> list[TaskRequest]:
    """Tâches qui peuvent tourner le jour calculé : datées de ce jour, et en attente."""
    return [t for t in data.due_tasks if t.due == data.day] + list(data.waiting_tasks)


def numbered(data: PlanningInput) -> PlanningInput:
    """Entrée dont les tâches du jour portent leur rang ; sans effet si elles l'ont déjà."""
    tasks = today_tasks(data)
    if all(task.rank is not None for task in tasks):
        return data
    known = dict(data.ranks)
    taken: dict[str, set[int]] = defaultdict(set)
    unclaimed: dict[str, list[int]] = defaultdict(list)  # blocs sans uid (plan d'avant)
    for block in data.frozen:
        taken[task_key(block.name)].add(block.rank)
        if block.uid:
            known.setdefault(block.uid, block.rank)
        else:
            unclaimed[task_key(block.name)].append(block.rank)
    ranks: dict[int, int] = {}
    pending: list[TaskRequest] = []
    for task in tasks:
        if task.rank is not None:
            ranks[id(task)] = task.rank
        elif task.uid and task.uid in known:
            ranks[id(task)] = known[task.uid]
        else:
            pending.append(task)
            continue
        taken[task_key(task.name)].add(ranks[id(task)])
    for task in pending:
        key = task_key(task.name)
        if unclaimed[key]:
            rank = min(unclaimed[key])
            unclaimed[key].remove(rank)
        else:
            rank = next(r for r in range(1, len(taken[key]) + 2) if r not in taken[key])
        taken[key].add(rank)
        ranks[id(task)] = rank

    def ranked(task: TaskRequest) -> TaskRequest:
        return replace(task, rank=ranks[id(task)]) if id(task) in ranks else task

    return replace(
        data,
        due_tasks=tuple(ranked(task) for task in data.due_tasks),
        waiting_tasks=tuple(ranked(task) for task in data.waiting_tasks),
    )


@dataclass(frozen=True)
class Wanted:
    """Cycle d'un équipement qui cherche son activité réelle du jour."""

    name: str  # identité du cycle
    energy_kwh: float
    since: datetime | None = None  # demande faite à ce moment : pas une activité d'avant
    before: datetime | None = None  # tâche close : pas une activité démarrée après


def _within(segment: Segment, wanted: Wanted) -> bool:
    try:
        if wanted.since is not None and segment.start < wanted.since:
            return False
        return wanted.before is None or segment.start < wanted.before
    except TypeError:  # heures avec et sans fuseau : pas comparables, l'activité est gardée
        return True


def attribute(segments: Sequence[Segment], wanted: Sequence[Wanted]) -> dict[str, Segment]:
    """Activité réelle de chaque cycle d'un équipement (``wanted``, dans l'ordre des rangs) :
    reconnue au même seuil que le recalage (``cycles.recognized_segment``), chacune pour un
    seul cycle. Le dernier cycle prend la dernière activité qui lui convient, comme quand il
    est seul ; les autres la première, et le suivant cherche après elle."""
    found: dict[str, Segment] = {}
    free = list(segments)
    for index, cycle in enumerate(wanted):
        threshold = RECOGNIZED_FRACTION * (cycle.energy_kwh or 0.0)
        fitting = [
            s for s in free if s.energy_kwh >= threshold and s.energy_kwh > 0 and _within(s, cycle)
        ]
        if not fitting:
            continue
        segment = fitting[-1] if index == len(wanted) - 1 else fitting[0]
        found[cycle.name] = segment
        free = [s for s in free if s.start > segment.start]
    return found


def paired(children: Iterable[int], parents: Iterable[int]) -> dict[int, int]:
    """Rang du cycle à finir avant, pour chaque rang d'un équipement qui en suit un autre :
    appariés dans l'ordre des rangs."""
    return dict(zip(sorted(children), sorted(parents), strict=False))
