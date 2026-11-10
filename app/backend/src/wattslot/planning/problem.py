"""Le problème à résoudre, posé à partir de l'entrée : ce qui est fixé et ce qui est à décider.

Mêmes règles que ``calculer_planning`` (v1) pour tout ce qui n'est pas le placement :

- **fixé** : la consommation restante des cycles décidés plus tôt dans la journée (« passé
  gelé ») et des cycles déjà lancés (recalés sur leur démarrage réel) ;
- **à décider** : le départ de chaque tâche restante (au plus tôt, puis chaque heure pile ; le
  sèche-linge après la fin du lave-linge) et le mode de la pompe de piscine, heure par heure ;
- **débordement après minuit** : avec la prévision du lendemain (``PlanningInput.next_day``) et
  son tarif connu, un cycle peut démarrer avant minuit et finir le lendemain ; le calcul est
  alors prolongé de quelques heures (``Overnight``) : tarif, consommation de base, production
  et batterie (plage active, plancher) du lendemain. Sans elle, rien ne franchit minuit. La fin
  d'un cycle commencé la veille (``PlanningInput.carried``) est une consommation déjà décidée ;
- filtration minimale de la saison, jours « prioritaires » pour la charge complète
  hebdomadaire, prévision qui dévie ; batterie (plage active, rendements par sens).

Les tâches impossibles à placer et les profils manquants donnent les avertissements de la v1.
"""

import math
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from typing import Any

from wattslot import currency
from wattslot.battery_settings import floor_percent_at
from wattslot.home_model import LINES, Phase, line_shares
from wattslot.planning.cycles import (
    DAY_MIN,
    PlannedCycle,
    Segment,
    Shape,
    after_midnight,
    free_from_hour,
    free_from_minute,
    measured_hourly,
    planned_hourly,
    realign,
    recognized_segment,
    remaining_hourly,
)
from wattslot.planning.inputs import FrozenCycle, PlanningInput, Runtime
from wattslot.planning.plan import Reason
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
    chosen_min: int | None = None  # départ choisi par l'utilisateur, imposé au calcul
    # Minutes permises après minuit (calcul prolongé, ``Overnight``) ; 0 : finir avant minuit.
    overflow_min: int = 0

    def cycle(self, start_min: int) -> PlannedCycle:
        return PlannedCycle(start_min, start_min + self.slot_min, self.energy_kwh, self.shape)

    def hourly_kwh(self, start_min: int) -> dict[int, float]:
        """kWh par heure ; un cycle qui déborde a aussi ses heures du lendemain (24, 25…)."""
        overnight = start_min + self.slot_min > DAY_MIN
        return planned_hourly(self.cycle(start_min), days=2 if overnight else 1)

    def candidates(self, earliest_min: int | None = None, chosen: bool = True) -> list[int]:
        """Départs possibles : au plus tôt, puis chaque heure pile, avant minuit et sans
        dépasser ``overflow_min`` après ; le départ choisi seul s'il est encore possible
        (``chosen=False`` : sans en tenir compte)."""
        earliest = self.earliest_min if earliest_min is None else earliest_min
        chosen_min = self.chosen_min if chosen else None
        limit = DAY_MIN + self.overflow_min
        if (
            chosen_min is not None
            and earliest <= chosen_min < DAY_MIN
            and chosen_min + self.slot_min <= limit
        ):
            return [chosen_min]
        first_full_hour = math.ceil(earliest / 60) * 60
        starts = [earliest] + [m for m in range(first_full_hour, DAY_MIN, 60) if m != earliest]
        return [s for s in starts if s < DAY_MIN and s + self.slot_min <= limit]


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
    # Raisons de son placement dans le plan précédent (« passé gelé ») : gardées après « lancé ».
    planned: tuple[Reason, ...] = ()


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
    hour_elapsed: float = 0.0  # part écoulée de la première heure
    hour_change_kwh: float = 0.0  # contenu stocké : variation mesurée depuis son début

    def floor_at(self, hour: int) -> float:
        return self.floor_by_hour.get(hour, self.floor_kwh)


@dataclass(frozen=True)
class Overnight:
    """Prolongement du calcul après minuit : les ``hours`` premières heures du lendemain,
    numérotées 24, 25… dans le problème. Données du lendemain, par heure du lendemain (0, 1…)."""

    hours: int
    net_kwh: Mapping[int, float]
    production_kwh: Mapping[int, float]
    prices_eur_kwh: Mapping[int, float]
    export_prices_eur_kwh: Mapping[int, float]
    co2_g_kwh: Mapping[int, float]
    floor_kwh: Mapping[int, float]  # plancher de la batterie
    fixed_kwh: Mapping[int, float] = field(default_factory=dict)  # cycles gelés ou lancés

    @property
    def problem_hours(self) -> range:
        return range(24, 24 + self.hours)


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
    # Blocs gelés libérés (``released``) : replacés par ce calcul, la fusion prend le nouveau.
    released: frozenset[str] = frozenset()
    prices_eur_kwh: dict[int, float] = field(default_factory=dict)  # soutirage, par heure
    export_prices_eur_kwh: dict[int, float] = field(default_factory=dict)  # revente, par heure
    warnings: list[dict[str, Any]] = field(default_factory=list)
    # Contrat (lot 7.3) : part de l'abonnement du jour (€) ; soutirage maximal d'une heure (kWh,
    # puissance souscrite à 1 kW par kVA), ``None`` : inconnu.
    subscription_eur: float = 0.0
    contract_kwh: float | None = None
    # Ordre de grandeur d'un euro dans la devise de la maison (lot 7.3) : les prix sont ramenés à
    # l'échelle de l'euro dans l'objectif, où pénalités et départages sont réglés en euros.
    price_scale: float = 1.0
    overnight: Overnight | None = None  # calcul prolongé après minuit (débordement)
    # Maison en triphasé : ce que les équipements placés peuvent tirer ensemble sur une phase en
    # une heure (kWh : un tiers de la puissance souscrite), ``None`` hors triphasé ou sans
    # contrat ; phase de chaque élément du plan, par nom ; part de la production sur chaque
    # phase ; consommation déjà décidée (cycles gelés ou lancés) par phase, les heures du
    # prolongement numérotées 24, 25…
    phase_limit_kwh: float | None = None
    phases: Mapping[str, Phase] = field(default_factory=dict)
    production_shares: Mapping[Phase, float] = field(default_factory=dict)
    fixed_by_phase: Mapping[Phase, Mapping[int, float]] = field(default_factory=dict)
    # Consommation de base de chaque phase, par heure du jour (kWh) ; vide : pas mesurée,
    # seuls les équipements placés comptent alors dans la limite.
    base_by_phase: Mapping[Phase, Mapping[int, float]] = field(default_factory=dict)

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


def _forecast_until_measure(data: PlanningInput) -> float | None:
    """Production prévue de minuit à l'heure du relevé ; None sans relevé du jour."""
    hour, measured = data.measured_at_hour, data.measured_production_kwh
    if hour is None or measured is None:
        return None
    full = int(hour)
    estimate = sum(data.production_kwh.get(h, 0.0) for h in range(full))
    if full < 24:
        estimate += data.production_kwh.get(full, 0.0) * (hour - full)
    return estimate


def forecast_ratio(data: PlanningInput, reference: Reference) -> float | None:
    """Rapport production mesurée / prévue depuis minuit, borné ; None tant que la prévision
    n'a pas assez produit pour en juger.

    La prévision du jour peut se tromper nettement (nuages non prévus) : sans recalage, chaque
    calcul horaire prévoyait une charge de la batterie sur un surplus qui ne venait pas."""
    estimate = _forecast_until_measure(data)
    measured = data.measured_production_kwh
    if estimate is None or measured is None or estimate < reference.forecast_correction_min_kwh:
        return None
    return min(
        reference.forecast_correction_max_ratio,
        max(reference.forecast_correction_min_ratio, measured / estimate),
    )


def corrected_production(
    data: PlanningInput, reference: Reference
) -> tuple[dict[int, float], dict[int, float]]:
    """(production, net) des heures à décider recalées sur la production mesurée du jour ; les
    heures passées et les autres journées restent telles que prévues."""
    production, net = dict(data.production_kwh), dict(data.net_kwh)
    ratio = forecast_ratio(data, reference)
    if ratio is None:
        return production, net
    for hour, kwh in data.production_kwh.items():
        if hour < data.first_hour:
            continue
        corrected = round(kwh * ratio, 3)
        net[hour] = round(net.get(hour, 0.0) + corrected - kwh, 3)
        production[hour] = corrected
    return production, net


def with_corrected_forecast(data: PlanningInput, reference: Reference = REFERENCE) -> PlanningInput:
    """Entrée du jour dont la prévision des heures à décider est recalée : le calcul et le plan
    enregistré (courbes, cartes) voient la même production."""
    production, net = corrected_production(data, reference)
    return replace(data, production_kwh=production, net_kwh=net)


def _context(data: PlanningInput, reference: Reference) -> tuple[bool, bool]:
    """(prévision qui dévie, journée prioritaire pour la charge complète) : règles du
    12/10/2026 de la v1."""
    drifting = False
    estimate, measured = _forecast_until_measure(data), data.measured_production_kwh
    if estimate is not None and measured is not None:
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


def _cycle_min(item: FrozenCycle) -> float:
    return item.cycle_min or (item.end_hour - item.start_hour) * 60


def _real_end(
    name: str,
    energy_kwh: float,
    cycle_min: float,
    segments: Mapping[str, tuple[Segment, ...]],
    now: datetime | None,
) -> int | None:
    """Fin (minute) du cycle réel du jour de ``name`` recalé, None s'il n'a pas démarré."""
    if now is None:
        return None
    result = realign(energy_kwh, cycle_min, segments.get(task_key(name), ()), now)
    return free_from_minute(result) if result is not None else None


def _released(
    frozen: Mapping[str, FrozenCycle],
    data: PlanningInput,
    segments: Mapping[str, tuple[Segment, ...]],
    now: datetime | None,
    reference: Reference,
) -> frozenset[str]:
    """Blocs gelés à replacer : pas encore lancés, et la tâche à finir avant eux (``depend_de``)
    finit après leur départ prévu — un sèche-linge prévu à 10 h derrière un lave-linge qui
    tourne encore à 11 h. Libérés, ils redeviennent des tâches à placer après elle."""
    requests = [*data.waiting_tasks, *(t for t in data.due_tasks if t.on_demand)]
    depends = {t.name: task_key(t.depends_on) for t in requests if t.depends_on}
    names = {task_key(t.name): t.name for t in [*data.due_tasks, *data.waiting_tasks]}
    frozen_by_key = {task_key(name): item for name, item in frozen.items()}
    found = set()
    for name, item in frozen.items():
        key = depends.get(name)
        if (
            key is None
            or _real_end(name, item.energy_kwh, _cycle_min(item), segments, now) is not None
        ):
            continue
        end: int | None = None
        if key in frozen_by_key:
            dependency = frozen_by_key[key]
            end = _real_end(
                dependency.name, dependency.energy_kwh, _cycle_min(dependency), segments, now
            )
            end = _frozen_cycle(dependency).end_min if end is None else end
        elif key in names:
            characteristic = characteristics(names[key], data, reference)
            if characteristic is not None:
                end = _real_end(names[key], *characteristic, segments, now)
        if end is not None and end > _frozen_cycle(item).start_min:
            found.add(name)
    return frozenset(found)


def from_input(data: PlanningInput, reference: Reference = REFERENCE) -> Problem:
    day, first_hour = data.day, data.first_hour
    warnings: list[dict[str, Any]] = list(data.forecast_warnings)
    fixed: dict[int, float] = defaultdict(float)
    tail: dict[int, float] = defaultdict(float)  # cycles fixés : part du lendemain
    ends: dict[str, int] = {}
    fixed_phase: dict[Phase, dict[int, float]] = {line: defaultdict(float) for line in LINES}

    def on_phase(name: str, hour: int, kwh: float) -> None:
        """Compte une consommation déjà décidée sur la phase de son équipement."""
        for line, share in line_shares(data.phases.get(name)).items():
            fixed_phase[line][hour] += kwh * share

    for carried in data.carried:  # fin d'un cycle commencé la veille avant minuit
        for hour, kwh in carried.hourly_kwh.items():
            if hour >= first_hour:
                fixed[hour] += kwh
                on_phase(carried.name, hour, kwh)
        key = task_key(carried.name)
        ends[key] = max(ends.get(key, 0), carried.end_min)

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
    released = _released(frozen, data, segments, now, reference)
    for name in released:
        del frozen[name]
        ends.pop(task_key(name), None)

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
        for hour, kwh in after_midnight(remaining_hourly(result, now, shape, days=2)).items():
            tail[hour] += kwh
            on_phase(name, 24 + hour, kwh)
        segment = recognized_segment(segs, energy_kwh)
        measured = measured_hourly(result, segment, shape) if segment else {}
        remaining[first_hour] = remaining.get(first_hour, 0.0) + measured.get(first_hour, 0.0)
        for hour, kwh in remaining.items():
            if hour >= first_hour:
                fixed[hour] += kwh
                on_phase(name, hour, kwh)
        ends[task_key(name)] = free_from_minute(result)
        launched_end_hours[name] = free_from_hour(result)
        # Fin réelle, après minuit pour un cycle lancé le soir qui déborde.
        launched_end_mins[name] = free_from_minute(result, capped=False)
        return result.start

    launched_end_hours: dict[str, int] = {}
    launched_end_mins: dict[str, int] = {}
    launched: list[LaunchedCycle] = []
    for item in frozen.values():
        cycle = _frozen_cycle(item)
        cycle_min = item.cycle_min or (item.end_hour - item.start_hour) * 60
        started = launched_now(item.name, item.energy_kwh, cycle_min, item.shape)
        if started is None:
            for hour, kwh in planned_hourly(cycle).items():
                if hour >= first_hour:
                    fixed[hour] += kwh
                    on_phase(item.name, hour, kwh)
            if item.end_min is not None and item.end_min > DAY_MIN:
                whole = PlannedCycle(cycle.start_min, item.end_min, item.energy_kwh, item.shape)
                for hour, kwh in after_midnight(planned_hourly(whole, days=2)).items():
                    tail[hour] += kwh
                    on_phase(item.name, 24 + hour, kwh)
            continue
        # Bloc gelé dont le cycle réel a démarré : recalé à chaque calcul (démarrage réel, fin
        # repoussée tant qu'il tourne), le plan fusionné prend ce bloc plutôt que l'ancien.
        launched.append(
            LaunchedCycle(
                name=item.name,
                priority=item.priority,
                energy_kwh=item.energy_kwh,
                cycle_min=cycle_min,
                shape=item.shape,
                start=started,
                end_hour=max(started.hour + 1, math.ceil(launched_end_mins[item.name] / 60)),
                end_min=max(started.hour * 60 + started.minute, launched_end_mins[item.name]),
                planned=data.planned_reasons.get(item.name, ()),
            )
        )
    # Cycle lancé dont la tâche est close depuis (« Fait », tâche de HA cochée, nouvelle demande
    # du même équipement) : il a bien tourné aujourd'hui. Le plan le garde, recalé sur le réel,
    # sans le replacer : sinon son bloc et sa consommation prévue disparaîtraient de la journée.
    # Un bloc gelé jamais lancé (demande annulée) disparaît, lui, comme avant.
    others = {need.name for need in data.needs} | {runtime.name for runtime in data.runtimes}
    for item in data.frozen:
        if item.name in active_names or item.name in others or item.name in released:
            continue
        cycle_min = item.cycle_min or (item.end_hour - item.start_hour) * 60
        started = launched_now(item.name, item.energy_kwh, cycle_min, item.shape)
        if started is None:
            continue
        launched.append(
            LaunchedCycle(
                name=item.name,
                priority=item.priority,
                energy_kwh=item.energy_kwh,
                cycle_min=cycle_min,
                shape=item.shape,
                start=started,
                end_hour=max(started.hour + 1, math.ceil(launched_end_mins[item.name] / 60)),
                end_min=max(started.hour * 60 + started.minute, launched_end_mins[item.name]),
                planned=data.planned_reasons.get(item.name, ()),
            )
        )

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
                        end_hour=max(
                            start.hour + 1, math.ceil(launched_end_mins[request.name] / 60)
                        ),
                        end_min=max(
                            start.hour * 60 + start.minute, launched_end_mins[request.name]
                        ),
                        planned=data.planned_reasons.get(request.name, ()),
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
                    chosen_min=data.chosen_starts.get(request.name),
                )
            )

    overnight = _overnight(data, tasks, tail, reference)
    if overnight is not None:
        tasks = [replace(task, overflow_min=overnight.hours * 60) for task in tasks]
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
            hour_elapsed=battery.hour_elapsed,
            hour_change_kwh=battery.hour_change_kwh,
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
        released=released,
        warnings=warnings,
        prices_eur_kwh=data.tariff.hourly(day, data.tariff_context),
        export_prices_eur_kwh=data.tariff.export_hourly(day, data.tariff_context),
        subscription_eur=data.tariff.subscription_eur(day),
        contract_kwh=data.tariff.contract_kva,
        price_scale=currency.scale(),
        co2_g_kwh=data.co2.hourly(day),
        overnight=overnight,
        phase_limit_kwh=data.tariff.contract_kva / 3
        if data.three_phase and data.tariff.contract_kva is not None
        else None,
        phases=dict(data.phases),
        production_shares=dict(data.production_shares),
        fixed_by_phase={line: dict(hourly) for line, hourly in fixed_phase.items()},
        base_by_phase={line: dict(hourly) for line, hourly in data.base_by_phase.items()}
        if data.three_phase
        else {},
    )


def _overnight(
    data: PlanningInput,
    tasks: list[Task],
    tail: Mapping[int, float],
    reference: Reference,
) -> Overnight | None:
    """Prolongement après minuit : assez d'heures pour le plus long cycle à placer et les parts
    du lendemain des cycles fixés ; aucun sans prévision ou tarif connu du lendemain."""
    next_day = data.next_day
    if next_day is None or not next_day.prices_known:
        return None
    longest = max((task.slot_min for task in tasks), default=0)
    hours = max(math.ceil(longest / 60), max(tail, default=-1) + 1)
    hours = min(hours, reference.cycle_max_hours, 24)
    if hours <= 0:
        return None
    tomorrow = data.day + timedelta(days=1)
    prices = data.tariff.hourly(tomorrow, data.tariff_context)
    exports = data.tariff.export_hourly(tomorrow, data.tariff_context)
    co2 = data.co2.hourly(tomorrow)
    battery = data.battery
    return Overnight(
        hours=hours,
        net_kwh={h: next_day.net_kwh.get(h, 0.0) for h in range(hours)},
        production_kwh={h: next_day.production_kwh.get(h, 0.0) for h in range(hours)},
        prices_eur_kwh={h: prices[h] for h in range(hours)},
        export_prices_eur_kwh={h: exports.get(h, 0.0) for h in range(hours)},
        co2_g_kwh={h: co2[h] for h in range(hours) if h in co2},
        floor_kwh={
            h: battery.capacity_kwh
            * floor_percent_at(battery.floor_percent, battery.floor_ranges, h)
            / 100
            for h in range(hours)
        },
        fixed_kwh={h: kwh for h, kwh in tail.items() if h < hours},
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
