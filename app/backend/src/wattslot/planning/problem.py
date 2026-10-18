"""Le problème à résoudre, posé à partir de l'entrée : ce qui est fixé et ce qui est à décider.

Mêmes règles que ``calculer_planning`` (v1) pour tout ce qui n'est pas le placement :

- **fixé** : la consommation restante des cycles décidés plus tôt dans la journée (« passé
  gelé ») et des cycles déjà lancés (recalés sur leur démarrage réel) ;
- **à décider** : le départ de chaque tâche restante (au plus tôt, puis chaque heure pile,
  sans franchir minuit ; le sèche-linge après la fin du lave-linge) et le mode de la pompe de
  piscine, heure par heure ;
- filtration minimale de la saison, jours « prioritaires » pour la charge complète
  hebdomadaire, prévision qui dévie ; batterie (plage active, rendements par sens).

Les tâches impossibles à placer et les profils manquants donnent les avertissements de la v1.
"""

import math
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from wattslot.battery_settings import floor_percent_at
from wattslot.planning.cycles import (
    DAY_MIN,
    PlannedCycle,
    Segment,
    Shape,
    free_from_hour,
    free_from_minute,
    measured_hourly,
    planned_hourly,
    realign,
    recognized_segment,
    remaining_hourly,
)
from wattslot.planning.inputs import FrozenCycle, PlanningInput, Runtime
from wattslot.planning.reference import REFERENCE, Reference, task_key
from wattslot.runtime_settings import season
from wattslot.time_constraints import TimeConstraint


@dataclass(frozen=True)
class Task:
    """Tâche à placer."""

    name: str
    key: str
    energy_kwh: float
    cycle_min: float  # durée du cycle
    slot_min: int  # durée du créneau placé
    shape: Shape | None
    priority: int  # 1 : récurrente du jour ; 3 : à la demande
    earliest_min: int
    depends_on: str | None = None  # clé d'une autre tâche à placer, à finir avant

    def cycle(self, start_min: int) -> PlannedCycle:
        return PlannedCycle(start_min, start_min + self.slot_min, self.energy_kwh, self.shape)

    def hourly_kwh(self, start_min: int) -> dict[int, float]:
        return planned_hourly(self.cycle(start_min))

    def candidates(self, earliest_min: int | None = None) -> list[int]:
        """Départs possibles : au plus tôt, puis chaque heure pile, sans franchir minuit."""
        earliest = self.earliest_min if earliest_min is None else earliest_min
        first_full_hour = math.ceil(earliest / 60) * 60
        starts = [earliest] + [m for m in range(first_full_hour, DAY_MIN, 60) if m != earliest]
        return [s for s in starts if s + self.slot_min <= DAY_MIN]


@dataclass(frozen=True)
class LaunchedCycle:
    """Tâche déjà lancée aujourd'hui : son créneau est calé sur le démarrage réel."""

    name: str
    priority: int
    energy_kwh: float
    cycle_min: float
    shape: Shape | None
    start: datetime
    end_hour: int
    end_min: int


@dataclass(frozen=True)
class BatteryModel:
    capacity_kwh: float
    stored_kwh: float
    soc_percent: float
    charge_max_kw: float
    discharge_max_kw: float
    active_from: int
    active_to: int
    charge_efficiency: float
    discharge_efficiency: float
    floor_kwh: float
    full_kwh: float
    full_priority: bool  # charge complète hebdomadaire due
    floor_by_hour: Mapping[int, float] = field(default_factory=dict)  # plages (lot 3.5), kWh

    def floor_at(self, hour: int) -> float:
        return self.floor_by_hour.get(hour, self.floor_kwh)


@dataclass(frozen=True)
class RuntimeModel:
    """Durée de fonctionnement à placer (lot 3.4) : chaque heure, arrêt ou une vitesse."""

    name: str
    speeds: tuple[tuple[str, float], ...]  # (mode, kW), de la plus basse à la plus haute
    min_hours: int  # durée minimale restant à faire aujourd'hui
    minimum_forced: bool  # vitesse la plus basse seulement, pas au-delà du minimum
    max_starts: int = 2
    skipped: bool = False  # journée sautée pour la charge complète de la batterie

    def kw(self, mode: str) -> float:
        return dict(self.speeds).get(mode, 0.0)


@dataclass(frozen=True)
class NeedModel:
    """Besoin d'énergie (lot 3.4) : ``energy_kwh`` entre ``start_hour`` et ``deadline_hour``."""

    name: str
    energy_kwh: float
    start_hour: int
    deadline_hour: int
    max_kw: float
    steps: bool = False


@dataclass
class Problem:
    day: date
    first_hour: int
    net_kwh: dict[int, float]
    production_kwh: dict[int, float]
    fixed_kwh: dict[int, float]
    tasks: list[Task]
    launched: list[LaunchedCycle]
    battery: BatteryModel
    runtimes: list[RuntimeModel]
    needs: list[NeedModel] = field(default_factory=list)
    constraints: Mapping[str, tuple[TimeConstraint, ...]] = field(default_factory=dict)
    co2_g_kwh: dict[int, float] = field(default_factory=dict)  # intensité du réseau (lot 3.6)

    def hard_blocks(self, name: str, start_min: int, end_min: int) -> bool:
        """Une contrainte dure de ``name`` interdit ``[start_min, end_min)``."""
        return any(c.hard and c.blocks(start_min, end_min) for c in self.constraints.get(name, ()))

    def soft_violated(self, name: str, start_min: int, end_min: int) -> list[TimeConstraint]:
        return [
            c for c in self.constraints.get(name, ()) if not c.hard and c.blocks(start_min, end_min)
        ]

    fixed_ends: dict[str, int] = field(default_factory=dict)  # fin (minute) des tâches fixées
    prices_eur_kwh: dict[int, float] = field(default_factory=dict)  # soutirage, par heure
    export_prices_eur_kwh: dict[int, float] = field(default_factory=dict)  # revente, par heure
    warnings: list[dict[str, Any]] = field(default_factory=list)

    @property
    def hours(self) -> range:
        return range(self.first_hour, 24)


def _frozen_cycle(item: FrozenCycle) -> PlannedCycle:
    start = item.start_min if item.start_min is not None else item.start_hour * 60
    cycle_min = item.cycle_min or (item.end_hour - item.start_hour) * 60
    end = item.end_min if item.end_min is not None else min(DAY_MIN, start + round(cycle_min))
    return PlannedCycle(start, end, item.energy_kwh, item.shape)


def characteristics(
    name: str, data: PlanningInput, reference: Reference = REFERENCE
) -> tuple[float, float] | None:
    """(énergie, durée en minutes) du cycle d'un équipement : profil de cycle mesuré, sinon
    estimation à partir de la consommation des jours d'usage réel ; None sans profil."""
    measured = data.cycle_profiles.get(name)
    if measured is not None:
        return measured.energy_kwh, measured.duration_min
    daily = data.daily_profiles.get(name)
    if daily is None:
        return None
    used: list[float] = []
    if daily.daily_kwh and daily.max_kwh:
        threshold = daily.max_kwh * reference.used_day_fraction
        used = [kwh for kwh in daily.daily_kwh if kwh >= threshold]
    energy = sum(used) / len(used) if used else daily.avg_kwh or daily.total_kwh or 0.2
    hours = reference.cycle_hours.get(task_key(name)) or reference.cycle_min_hours
    return energy, hours * 60


def _active_range(data: PlanningInput, reference: Reference) -> tuple[int, int]:
    """Plage active de la batterie : union des plannings d'autoconsommation (mode -1)."""
    plans = [s for s in data.battery.schedules if s[0] == -1]
    if not plans:
        return data.battery.active_from_hour, data.battery.active_to_hour
    return min(s[1] for s in plans), max(s[2] + (1 if s[3] > 0 else 0) for s in plans)


def _context(data: PlanningInput, reference: Reference) -> tuple[bool, bool]:
    """(prévision qui dévie, journée prioritaire pour la charge complète) : règles du
    12/10/2026 de la v1."""
    drifting = False
    hour, measured = data.measured_at_hour, data.measured_production_kwh
    if hour is not None and measured is not None:
        full = int(hour)
        estimate = sum(data.production_kwh.get(h, 0.0) for h in range(full))
        if full < 24:
            estimate += data.production_kwh.get(full, 0.0) * (hour - full)
        drifting = (
            estimate >= reference.forecast_drift_min_kwh
            and (measured - estimate) / estimate * 100 < -reference.forecast_drift_percent
        )
    history = data.history
    days_since: int | None = None
    every = data.battery.full_charge_every_days  # None : pas de charge complète périodique
    if history is not None:
        if history.last_full_charge is not None:
            days_since = (data.day - history.last_full_charge).days
        else:
            days_since = (history.days if history.days is not None else every or 0) + 1
    priority = every is not None and days_since is not None and days_since >= every
    return drifting, priority


def _skip_allowed(data: PlanningInput, runtime: Runtime) -> bool:
    """Moins de jours sans fonctionnement que la saison n'en tolère : compteur de l'équipement
    (lot 3.5), sinon celui de la v1 (piscine, dans l'historique)."""
    history = data.history
    days = runtime.days_off
    if days is None:
        days = history.days_without_filtration if history else 0
    return days < runtime.skip_days.get(season(data.day, data.southern), 0)


def _needs(data: PlanningInput, warnings: list[dict[str, Any]]) -> list[NeedModel]:
    """Besoins d'énergie restant à couvrir : pas ceux déjà décidés plus tôt (gelés) ; une
    échéance passée est signalée comme un cycle qui ne tient plus."""
    frozen = {item.name for item in data.frozen}
    found = []
    for need in data.needs:
        if need.name in frozen:
            continue
        start = max(need.earliest_hour, data.first_hour)
        if start >= need.deadline_hour:
            warnings.append(
                {
                    "code": "heures_insuffisantes_du",
                    "params": {
                        "equipement": need.name,
                        "duree_min": 60 * max(1, round(need.energy_kwh / need.max_kw)),
                        "debut_min": data.first_hour * 60,
                    },
                }
            )
            continue
        found.append(
            NeedModel(
                need.name, need.energy_kwh, start, need.deadline_hour, need.max_kw, need.steps
            )
        )
    return found


def from_input(data: PlanningInput, reference: Reference = REFERENCE) -> Problem:
    day, first_hour = data.day, data.first_hour
    warnings: list[dict[str, Any]] = list(data.forecast_warnings)
    fixed: dict[int, float] = defaultdict(float)
    ends: dict[str, int] = {}

    active_names = {t.name for t in data.due_tasks if t.due == day} | {
        t.name for t in data.waiting_tasks
    }
    frozen = {item.name: item for item in data.frozen if item.name in active_names}
    for name, item in frozen.items():
        ends[task_key(name)] = _frozen_cycle(item).end_min

    now = data.real_updated_at
    if now is not None and now.date() != day:
        now = None
    segments: dict[str, tuple[Segment, ...]] = (
        {task_key(name): segs for name, segs in data.real_segments.items()} if now else {}
    )

    def launched_now(
        name: str, energy_kwh: float, cycle_min: float, shape: Shape | None
    ) -> datetime | None:
        """Recale un cycle sur son démarrage réel : compte sa consommation restante (et celle
        déjà mesurée dans l'heure en cours), retient sa fin. Renvoie le démarrage réel."""
        if now is None:
            return None
        segs = segments.get(task_key(name), ())
        result = realign(energy_kwh, cycle_min, segs, now)
        if result is None:
            return None
        remaining = dict(remaining_hourly(result, now, shape))
        segment = recognized_segment(segs, energy_kwh)
        measured = measured_hourly(result, segment, shape) if segment else {}
        remaining[first_hour] = remaining.get(first_hour, 0.0) + measured.get(first_hour, 0.0)
        for hour, kwh in remaining.items():
            if hour >= first_hour:
                fixed[hour] += kwh
        ends[task_key(name)] = free_from_minute(result)
        launched_end_hours[name] = free_from_hour(result)
        return result.start

    launched_end_hours: dict[str, int] = {}
    for item in frozen.values():
        cycle = _frozen_cycle(item)
        cycle_min = item.cycle_min or (item.end_hour - item.start_hour) * 60
        if launched_now(item.name, item.energy_kwh, cycle_min, item.shape) is None:
            for hour, kwh in planned_hourly(cycle).items():
                if hour >= first_hour:
                    fixed[hour] += kwh

    due_today = [t for t in data.due_tasks if t.due == day]
    on_demand = [t for t in due_today if t.on_demand]
    assignments = data.assignments or {}
    waiting = on_demand + [
        t
        for t in data.waiting_tasks
        if t.uid is None or t.uid not in assignments or assignments[t.uid] == day
    ]
    recurring = [t for t in due_today if not t.on_demand]
    waiting_keys = {task_key(t.name) for t in waiting}

    tasks: list[Task] = []
    launched: list[LaunchedCycle] = []
    for priority, group, suffix in ((1, recurring, "du"), (3, waiting, "attente")):
        for request in group:
            if request.name in frozen:
                continue
            found = characteristics(request.name, data, reference)
            if found is None:
                warnings.append(
                    {
                        "code": f"profil_indisponible_{suffix}",
                        "params": {
                            "equipement": request.name,
                            "status": data.profile_status.get(request.name, "absent"),
                        },
                    }
                )
                continue
            energy, cycle_min = found
            shape = (
                data.cycle_profiles[request.name].shape
                if request.name in data.cycle_profiles
                else None
            )
            start = launched_now(request.name, energy, cycle_min, shape)
            if start is not None:
                launched.append(
                    LaunchedCycle(
                        name=request.name,
                        priority=priority,
                        energy_kwh=energy,
                        cycle_min=cycle_min,
                        shape=shape,
                        start=start,
                        end_hour=max(start.hour + 1, launched_end_hours[request.name]),
                        end_min=max(start.hour * 60 + start.minute, ends[task_key(request.name)]),
                    )
                )
                continue
            tasks.append(
                Task(
                    name=request.name,
                    key=task_key(request.name),
                    energy_kwh=energy,
                    cycle_min=cycle_min,
                    slot_min=max(1, min(reference.cycle_max_hours * 60, round(cycle_min))),
                    shape=shape,
                    priority=priority,
                    earliest_min=first_hour * 60,
                    depends_on=task_key(request.depends_on)
                    if priority == 3 and request.depends_on
                    else None,
                )
            )

    tasks = _resolve_dependencies(tasks, ends, waiting_keys, warnings)

    drifting, priority_day = _context(data, reference)
    runtimes = []
    for runtime in data.runtimes:
        skipped = priority_day and _skip_allowed(data, runtime)
        past_hours = sum(
            1 for hour, mode in runtime.past.items() if hour < first_hour and mode != "off"
        )
        needed = runtime.minimum_hours.get(season(day, data.southern), 0)
        runtimes.append(
            RuntimeModel(
                name=runtime.name,
                speeds=runtime.speeds,
                min_hours=0 if skipped else max(0, needed - past_hours),
                minimum_forced=drifting or priority_day,
                max_starts=runtime.max_starts,
                skipped=skipped,
            )
        )
    battery = data.battery
    measured_ok = (
        battery.charge_efficiency_percent is not None
        and battery.discharge_efficiency_percent is not None
    )
    per_direction = (battery.round_trip_percent / 100) ** 0.5 if battery.round_trip_percent else 1.0
    active_from, active_to = _active_range(data, reference)
    return Problem(
        day=day,
        first_hour=first_hour,
        net_kwh=dict(data.net_kwh),
        production_kwh=dict(data.production_kwh),
        fixed_kwh={hour: fixed.get(hour, 0.0) for hour in range(24)},
        tasks=tasks,
        launched=launched,
        battery=BatteryModel(
            capacity_kwh=battery.capacity_kwh,
            stored_kwh=battery.stored_kwh,
            soc_percent=battery.soc_percent,
            charge_max_kw=battery.charge_max_w / 1000,
            discharge_max_kw=battery.discharge_max_w / 1000,
            active_from=active_from,
            active_to=active_to,
            charge_efficiency=(battery.charge_efficiency_percent or 0) / 100 or per_direction
            if measured_ok
            else per_direction,
            discharge_efficiency=(battery.discharge_efficiency_percent or 0) / 100 or per_direction
            if measured_ok
            else per_direction,
            floor_kwh=battery.capacity_kwh * battery.floor_percent / 100,
            full_kwh=battery.capacity_kwh * reference.full_percent / 100,
            full_priority=priority_day,
            floor_by_hour={
                hour: battery.capacity_kwh
                * floor_percent_at(battery.floor_percent, battery.floor_ranges, hour)
                / 100
                for hour in range(24)
                if battery.floor_ranges
            },
        ),
        runtimes=runtimes,
        needs=_needs(data, warnings),
        constraints={name: tuple(found) for name, found in data.constraints.items() if found},
        fixed_ends=ends,
        warnings=warnings,
        prices_eur_kwh=data.tariff.hourly(day, data.tariff_context),
        export_prices_eur_kwh=data.tariff.export_hourly(day, data.tariff_context),
        co2_g_kwh=data.co2.hourly(day),
    )


def _resolve_dependencies(
    tasks: list[Task],
    ends: Mapping[str, int],
    waiting_keys: set[str],
    warnings: list[dict[str, Any]],
) -> list[Task]:
    """Applique ``depend_de`` comme la v1, et écarte les tâches impossibles à placer.

    Dépendance vers une tâche fixée (gelée ou lancée) : départ au plus tôt à sa fin. Vers une
    tâche à placer : contrainte du moteur. Vers une tâche en attente mais impossible à placer :
    la tâche n'est pas placée (avertissement). Vers une tâche absente (déjà cochée dans HA) :
    aucune contrainte.
    """
    placeable: list[Task] = []
    for task in tasks:
        earliest = task.earliest_min
        depends = task.depends_on
        if depends is not None and depends in ends:
            earliest, depends = max(earliest, ends[depends]), None
        updated = Task(**{**task.__dict__, "earliest_min": earliest, "depends_on": depends})
        if not updated.candidates():
            warnings.append(
                {
                    "code": "heures_insuffisantes_" + ("du" if task.priority == 1 else "attente"),
                    "params": {
                        "equipement": task.name,
                        "duree_min": task.slot_min,
                        "debut_min": earliest,
                    },
                }
            )
            continue
        placeable.append(updated)
    keys = {task.key for task in placeable}
    names = {task.key: task.name for task in tasks}
    resolved: list[Task] = []
    for task in placeable:
        if task.depends_on is not None and task.depends_on not in keys:
            if task.depends_on in waiting_keys:
                warnings.append(
                    {
                        "code": "dependance_non_placee",
                        "params": {
                            "equipement": task.name,
                            "depend_de": names.get(task.depends_on, task.depends_on),
                        },
                    }
                )
                continue
            task = Task(**{**task.__dict__, "depends_on": None})
        resolved.append(task)
    return resolved
