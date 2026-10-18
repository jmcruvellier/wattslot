"""Assemblage de l'entrée du calcul à partir des données de la v2 et de HA (lot 2.2).

Chaque champ de l'entrée de la v1 a sa source dans la v2 (lot 2.2) :

- prévision de production : HA (``sources.Forecasts``) ; ligne de base : agrégats
  horaires (``past.baseline``) ; net = prévision moins ligne de base, heure par heure ;
- tâches : liste de HA ; chaque tâche est rattachée à un équipement du modèle par son nom
  (« Lave-linge » → lave-linge), pour son profil de cycle et ses cycles réels du jour ;
- profils de cycle : journal des cycles (``journal.py``) ; cycles réels : brut du jour ;
- batterie : SoC lu dans HA, capacité du modèle, rendements mesurés (``past``), puissances
  des réglages ;
- historique récent, production mesurée depuis minuit (prévision qui dévie).

Pas encore ici : blocs gelés, filtration déjà faite et affectations, qui viennent du plan
précédent de la journée (lot 2.3, exécution planifiée).
"""

import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from wattslot import configuration as config
from wattslot import user_requests
from wattslot.aggregation import QUARTER
from wattslot.battery_settings import BatterySettings
from wattslot.configuration import Behavior, Configuration, DeviceSettings
from wattslot.detection import DeviceKind, Role, classify_appliance
from wattslot.home_assistant import HomeAssistantClient
from wattslot.home_model import HomeDevice, HomeModel
from wattslot.planning import past
from wattslot.planning.appliances import DEFAULT_RULES, RULES
from wattslot.planning.co2_sources import co2_context
from wattslot.planning.inputs import (
    Battery,
    CycleProfile,
    Need,
    PlanningInput,
    RecentHistory,
    Runtime,
    TaskRequest,
)
from wattslot.planning.journal import (
    ALL_KINDS,
    Appliance,
    CycleJournal,
    appliances,
    cycle_appliances,
    real_cycles,
)
from wattslot.planning.past import AggregateReader
from wattslot.planning.reference import task_key
from wattslot.planning.sources import Forecasts, PlanningSettings, has_production, read_tasks
from wattslot.planning.tariff_sources import needs_states, tariff_context
from wattslot.recurrence_settings import Recurrence, next_due
from wattslot.runtime_settings import DEFAULT as RUNTIME_DEFAULT
from wattslot.runtime_settings import MEASURED_SPEED
from wattslot.storage.raw import RawStores
from wattslot.tariff import TariffContext
from wattslot.time_constraints import TimeConstraint

# Comportements dont les tâches sont placées par le calcul (le chauffe-eau reste traité
# comme un cycle jusqu'au lot 3.4).
SCHEDULED = frozenset({Behavior.CYCLE, Behavior.ENERGY_BY_DEADLINE})


def appliance_for(task: TaskRequest, candidates: Sequence[Appliance]) -> Appliance | None:
    """Équipement d'une tâche (lot 3.4) : celui qui porte son nom (casse, accents et séparateurs
    ignorés), sinon l'unique équipement du type reconnu dans son nom ; aucun si plusieurs
    équipements de ce type pourraient convenir."""
    key = task_key(task.name)
    named = [a for a in candidates if task_key(a.name) == key]
    if named:
        return named[0]
    of_kind = [a for a in candidates if a.kind is task_kind(task)]
    return of_kind[0] if len(of_kind) == 1 else None


def task_kind(task: TaskRequest) -> DeviceKind:
    """Type d'équipement d'une tâche, d'après son nom (mêmes mots que la détection)."""
    return classify_appliance(task.name)


def battery_state(model: HomeModel, states: Sequence[dict[str, Any]]) -> tuple[float, float, float]:
    """(capacité, énergie stockée, SoC en %) des batteries du modèle, d'après HA."""
    by_id = {s.get("entity_id"): s for s in states}
    capacity = stored = 0.0
    for device in model.devices:
        if device.kind is not DeviceKind.BATTERY or not device.capacity_kwh:
            continue
        for sensor in device.sensors:
            if sensor.role is not Role.STATE_OF_CHARGE:
                continue
            try:
                soc = float(str((by_id.get(sensor.entity_id) or {}).get("state")))
            except (TypeError, ValueError):
                continue
            capacity += device.capacity_kwh
            stored += soc * device.capacity_kwh / 100
            break
    return capacity, stored, (stored / capacity * 100 if capacity > 0 else 0.0)


def measured_production(
    model: HomeModel, reader: AggregateReader, now: datetime, zone: ZoneInfo
) -> tuple[float | None, float | None]:
    """(production mesurée depuis minuit en kWh, heure de la mesure) sur les quarts d'heure
    clos ; (None, None) sans mesure."""
    midnight = datetime.combine(now.astimezone(zone).date(), time(), zone)
    total, last_end = 0.0, None
    for entity_id in past.sensors(model, [Role.ENERGY_PRODUCED]):
        for aggregate in reader.read(entity_id, QUARTER, midnight, now):
            if aggregate.energy_kwh is not None:
                total += aggregate.energy_kwh
                end = aggregate.start + timedelta(minutes=15)
                last_end = end if last_end is None else max(last_end, end)
    if last_end is None:
        return None, None
    local = last_end.astimezone(zone)
    hour = (local - midnight).total_seconds() / 3600
    return round(total, 3), hour


async def build_input(
    day: date,
    now: datetime,
    client: HomeAssistantClient,
    model: HomeModel,
    reader: AggregateReader,
    raw: RawStores,
    journal: CycleJournal,
    settings: PlanningSettings,
    forecasts: Forecasts | None = None,
    configuration: Configuration | None = None,
    database: sqlite3.Connection | None = None,
) -> PlanningInput:
    """Entrée du calcul pour ``day`` (aujourd'hui : à partir de l'heure en cours).

    Avec la configuration de la maison (lot 3.1) : les tâches d'un équipement non pris en
    compte par le calcul, ou réglé en consommation non pilotable, sont écartées ; la filtration
    n'est planifiée que pour une piscine du modèle, réglée en durée à placer et prise en compte.
    Sans configuration, comme en phase 2 : toutes les tâches, et la filtration."""
    zone = raw.zone
    today = now.astimezone(zone).date()
    forecasts = forecasts or Forecasts(client, zone, settings, production=has_production(model))
    forecast, warnings = await forecasts.hourly(day)
    planned = (
        config.keys_with(model, configuration, config.SCHEDULED)
        if configuration is not None
        else None
    )
    baseline = past.baseline(model, reader, day, today, zone, planned=planned)
    production = {h: forecast.get(h, 0.0) for h in range(24)}
    net = {h: production[h] - baseline.get(h, 0.0) for h in range(24)}

    due, waiting = await read_tasks(client, settings.todo_entity)
    candidates = cycle_appliances(model, configuration)
    if database is not None:  # demandes déclarées dans l'application (lot 4.5)
        app_due, app_waiting = user_requests.tasks(database, candidates, [*due, *waiting], today)
        due, waiting = [*due, *app_due], [*waiting, *app_waiting]
    if configuration is not None:
        last = {
            appliance.key: journal.last_cycle_day(appliance, today)
            for appliance in recurring_appliances(model, configuration, candidates)
        }
        due = recurring_tasks(due, model, configuration, last, today, day)
    profiles: dict[str, CycleProfile] = {}
    status: dict[str, str] = {}
    for task in [*due, *waiting]:
        appliance = appliance_for(task, candidates)
        if appliance is None:
            status[task.name] = "absent"
            continue
        profile = journal.profile(appliance, today)
        status[task.name] = "ok" if profile.ok else "insuffisant"
        if profile.ok and profile.energy_kwh is not None and profile.duration_min is not None:
            profiles[task.name] = CycleProfile(
                profile.energy_kwh, profile.duration_min, profile.shape
            )

    real: dict[str, Any] = {}
    if day == today:
        by_device = real_cycles(model, raw, now, configuration)
        for task in [*due, *waiting]:
            appliance = appliance_for(task, candidates)
            if appliance is not None and by_device.get(appliance.name):
                real[task.name] = by_device[appliance.name]

    states = await client.command("get_states")
    tariff = config.tariff_of(configuration)
    context = tariff_context(tariff, states or [], today, zone) if needs_states(tariff) else None
    capacity, stored, soc = battery_state(model, states or [])
    battery_settings = config.battery_of(configuration)
    charge_w, discharge_w = battery_settings.powers_w(capacity)
    efficiencies = past.battery_efficiencies(model, reader, today, zone)
    history = past.recent_history(model, reader, today, zone)
    produced, at_hour = (
        measured_production(model, reader, now, zone) if day == today else (None, None)
    )
    data = PlanningInput(
        day=day,
        tariff=tariff,
        tariff_context=context or TariffContext(),
        first_hour=now.astimezone(zone).hour if day == today else 0,
        net_kwh=net,
        production_kwh=production,
        battery=Battery(
            capacity_kwh=capacity,
            stored_kwh=stored,
            soc_percent=round(soc, 1),
            charge_max_w=charge_w,
            discharge_max_w=discharge_w,
            floor_percent=battery_settings.floor_percent,
            active_from_hour=battery_settings.active_from_hour,
            active_to_hour=battery_settings.active_to_hour,
            full_charge_every_days=battery_settings.full_charge_every_days,
            charge_efficiency_percent=efficiencies.charge_percent if efficiencies.ok else None,
            discharge_efficiency_percent=efficiencies.discharge_percent
            if efficiencies.ok
            else None,
            efficiency_days=round(efficiencies.days) if efficiencies.ok else None,
        ),
        due_tasks=tuple(due),
        waiting_tasks=tuple(waiting),
        cycle_profiles=profiles,
        daily_profiles={},
        profile_status=status,
        real_segments=real,
        real_updated_at=now.astimezone(zone) if day == today else None,
        history=RecentHistory(
            last_full_charge=history.last_full_charge,
            days=history.days,
            days_without_filtration=history.days_without_filtration,
        )
        if history
        else None,
        measured_production_kwh=produced,
        measured_at_hour=at_hour,
        forecast_warnings=tuple(warnings),
    )
    if configuration is None:
        return data
    objective = configuration.objective
    data = replace(
        data,
        southern=southern(client),
        co2=co2_context(states or [], objective.co2_entity if objective else None, zone),
    )
    return configured(
        data,
        model,
        configuration,
        measured_speeds(model, configuration, reader, today, zone),
        runtime_days_off(model, configuration, reader, today, zone),
    )


def to_v1(data: PlanningInput) -> dict[str, Any]:
    """Entrée au format de la v1 (JSON), pour la comparaison croisée avec ses captures."""

    def task(t: TaskRequest) -> dict[str, Any]:
        description: dict[str, Any] = {"type": "a_la_demande" if t.on_demand else "recurrent"}
        if t.rule:
            description["regle"] = t.rule
        if t.depends_on:
            description["depend_de"] = t.depends_on
        if t.needed_since:
            description["besoin_detecte"] = t.needed_since.isoformat()
        found: dict[str, Any] = {"summary": t.name, "uid": t.uid, "description": description}
        if t.due:
            found["due"] = t.due.isoformat()
        return found

    battery = data.battery
    efficiencies = (
        {
            "status": "ok",
            "rendement_charge_percent": battery.charge_efficiency_percent,
            "rendement_decharge_percent": battery.discharge_efficiency_percent,
            "nb_jours": battery.efficiency_days,
        }
        if battery.charge_efficiency_percent is not None
        else {"status": "insuffisant"}
    )
    return {
        "date_cible": data.day.isoformat(),
        "heure_execution": data.first_hour,
        "net_horaire_signe": dict(data.net_kwh),
        "production_solaire_horaire": dict(data.production_kwh),
        "consommation_baseline_horaire": {
            h: data.production_kwh.get(h, 0.0) - data.net_kwh.get(h, 0.0) for h in range(24)
        },
        "avertissements_prevision": list(data.forecast_warnings),
        "taches_placees": [task(t) for t in data.due_tasks],
        "taches_en_attente": [task(t) for t in data.waiting_tasks],
        "profils_cycles": {
            name: {
                "status": "ok",
                "energie_kwh": p.energy_kwh,
                "duree_min": p.duration_min,
                "forme_quart_heure": list(p.shape) if p.shape else None,
            }
            for name, p in data.cycle_profiles.items()
        },
        "cycles_reels": {
            "heure_maj_iso": data.real_updated_at.isoformat() if data.real_updated_at else None,
            "segments": {
                name: [
                    {
                        "debut_iso": s.start.isoformat(),
                        "fin_iso": s.end.isoformat(),
                        "energie_kwh": s.energy_kwh,
                        "en_cours": s.running,
                    }
                    for s in segs
                ]
                for name, segs in data.real_segments.items()
            },
        },
        "soc_percent": battery.soc_percent,
        "stored_energy_kwh": round(battery.stored_kwh, 3),
        "capacite_batterie_kwh": battery.capacity_kwh,
        "puissance_charge_max_w": battery.charge_max_w,
        "puissance_decharge_max_w": battery.discharge_max_w,
        "rendements_batterie": efficiencies,
        "historique_recent": {
            "derniere_charge_complete": data.history.last_full_charge.isoformat()
            if data.history and data.history.last_full_charge
            else None,
            "jours_sans_filtration": data.history.days_without_filtration if data.history else 0,
            "nb_jours": data.history.days if data.history else None,
        },
        "production_reelle_cumul_kwh": data.measured_production_kwh,
        "heure_releve": data.measured_at_hour,
        "generated_at": datetime.now(UTC).isoformat(),
    }


def recurring_appliances(
    model: HomeModel, configuration: Configuration, candidates: Sequence[Appliance]
) -> list[Appliance]:
    """Équipements à cycles qui ont une récurrence réglée et sont pris en compte (lot 3.5)."""
    effective = config.effective(model, configuration)
    return [
        a
        for a in candidates
        if (found := effective.of(a.key)) is not None
        and found.planned
        and found.behavior is Behavior.CYCLE
        and found.recurrence is not None
    ]


def recurring_tasks(
    due: Sequence[TaskRequest],
    model: HomeModel,
    configuration: Configuration,
    last_cycles: Mapping[str, date | None],
    today: date,
    day: date | None = None,
) -> list[TaskRequest]:
    """Tâches datées avec les récurrences de la configuration (lot 3.5) : pour chaque équipement
    réglé ainsi (clés de ``last_cycles``, avec son dernier cycle réel), sa prochaine échéance
    remplace ses tâches récurrentes de HA ; ses autres tâches datées restent. Pour un jour
    suivant (``day``), une échéance d'aujourd'hui est supposée faite aujourd'hui."""
    effective = config.effective(model, configuration)
    every = appliances(model, ALL_KINDS)
    kept = [
        task
        for task in due
        if not (
            task.rule
            and (appliance := appliance_for(task, every)) is not None
            and appliance.key in last_cycles
        )
    ]
    for device in model.devices:
        found = effective.of(device.key)
        if device.key not in last_cycles or found is None or found.recurrence is None:
            continue
        when = next_due(found.recurrence, last_cycles[device.key], today)
        if day is not None and day > today and when is not None and when <= today:
            when = next_due(found.recurrence, today, day)
        if when is not None:
            kept.append(
                TaskRequest(
                    name=device.name,
                    uid=f"recurrence:{device.key}",
                    due=when,
                    rule=found.recurrence.rule,
                )
            )
    return kept


class TaskRules(BaseModel):
    """Règles d'un équipement reprises des descriptions JSON des tâches de HA (v1)."""

    key: str
    recurrence: Recurrence | None = None
    after: str | None = None  # clé de l'équipement à suivre


def rules_from_tasks(tasks: Sequence[TaskRequest], model: HomeModel) -> list[TaskRules]:
    """Reprise des descriptions JSON (lot 3.5) : la règle d'une tâche récurrente devient la
    récurrence de son équipement (semaine de départ : son échéance), sa dépendance devient
    « démarre après » ; tâches sans équipement ignorées."""
    every = appliances(model, ALL_KINDS)
    found: dict[str, TaskRules] = {}
    for task in tasks:
        appliance = appliance_for(task, every)
        if appliance is None:
            continue
        rules = found.setdefault(appliance.key, TaskRules(key=appliance.key))
        if task.rule and rules.recurrence is None:
            rules.recurrence = Recurrence(rule=task.rule, start=task.due)
        if task.depends_on and rules.after is None:
            parent = appliance_for(TaskRequest(name=task.depends_on), every)
            if parent is not None and parent.key != appliance.key:
                rules.after = parent.key
    return [r for r in found.values() if r.recurrence is not None or r.after is not None]


def configured(
    data: PlanningInput,
    model: HomeModel,
    configuration: Configuration,
    measured_kw: Mapping[str, float] | None = None,
    days_off: Mapping[str, int] | None = None,
) -> PlanningInput:
    """Entrée selon la configuration de la maison : tâches d'un équipement non pris en compte
    ou non pilotable écartées, avec leurs profils et cycles réels (lot 3.1) ; durées à placer
    (lot 3.4) : chaque équipement réglé ainsi et pris en compte, avec ses vitesses (sans vitesse
    réglée : une seule, de la puissance mesurée ``measured_kw``), ses durées par saison et ce
    qu'il a déjà fait aujourd'hui ; tarif et batterie.
    """
    effective = config.effective(model, configuration)
    every = appliances(model, ALL_KINDS)

    def planned(task: TaskRequest) -> bool:
        appliance = appliance_for(task, every)
        found = effective.of(appliance.key) if appliance else None
        return found is None or (found.planned and found.behavior in SCHEDULED)

    left_out = {t.name for t in [*data.due_tasks, *data.waiting_tasks] if not planned(t)}
    needs, as_need = _needs(data, model, effective, every)
    runtimes = tuple(
        _runtime(
            device,
            found,
            (measured_kw or {}).get(device.key),
            data.runtimes,
            (days_off or {}).get(device.key, 0) if days_off is not None else None,
        )
        for device in model.devices
        if (found := effective.of(device.key)) is not None
        and found.planned
        and found.behavior is Behavior.RUNTIME
    )
    return replace(
        data,
        due_tasks=tuple(t for t in data.due_tasks if planned(t) and t.name not in as_need),
        waiting_tasks=_ordered(
            tuple(t for t in data.waiting_tasks if planned(t) and t.name not in as_need),
            effective,
            every,
        ),
        max_delay_days={
            task.name: settings.max_delay_days
            for task in data.waiting_tasks
            if (settings := _settings_of(task, effective, every)) is not None
            and settings.max_delay_days is not None
        },
        cycle_profiles={k: v for k, v in data.cycle_profiles.items() if k not in left_out},
        real_segments={k: v for k, v in data.real_segments.items() if k not in left_out},
        profile_status={
            **{k: v for k, v in data.profile_status.items() if k not in left_out},
            **dict.fromkeys(left_out, "non_planifie"),
        },
        runtimes=runtimes,
        needs=needs,
        constraints=_constraints(data, model, effective, every),
        tariff=config.tariff_of(configuration),
        battery=_with_settings(data.battery, config.battery_of(configuration)),
    )


def _needs(
    data: PlanningInput,
    model: HomeModel,
    effective: Configuration,
    every: Sequence[Any],
) -> tuple[tuple[Need, ...], set[str]]:
    """Besoins d'énergie (lot 3.4) des équipements réglés ainsi et pris en compte : chaque jour,
    ou seulement les jours où une de leurs tâches le demande ; ces tâches ne sont alors plus des
    cycles à démarrer (noms renvoyés à part)."""
    needs: list[Need] = []
    as_need: set[str] = set()
    for device in model.devices:
        found = effective.of(device.key)
        if (
            found is None
            or not found.planned
            or found.behavior is not Behavior.ENERGY_BY_DEADLINE
            or found.energy is None
        ):
            continue
        asked = {
            t.name
            for t in [*data.due_tasks, *data.waiting_tasks]
            if (appliance := appliance_for(t, every)) is not None and appliance.key == device.key
        }
        as_need |= asked
        if found.energy.daily or asked:
            energy = found.energy
            needs.append(
                Need(
                    name=device.name,
                    energy_kwh=energy.energy_kwh,
                    earliest_hour=energy.earliest_hour,
                    deadline_hour=energy.deadline_hour,
                    max_kw=energy.max_kw,
                    steps=energy.steps,
                    daily=energy.daily,
                )
            )
    return tuple(needs), as_need


def _settings_of(
    task: TaskRequest, effective: Configuration, every: Sequence[Any]
) -> DeviceSettings | None:
    appliance = appliance_for(task, every)
    return effective.of(appliance.key) if appliance is not None else None


def _ordered(
    waiting: tuple[TaskRequest, ...], effective: Configuration, every: Sequence[Any]
) -> tuple[TaskRequest, ...]:
    """« Démarre après la fin de » (lot 3.5) : une tâche en attente d'un équipement réglé ainsi
    suit celle de l'autre équipement, si elle est aussi en attente ; sans réglage, la
    dépendance de la description de la tâche (v1) reste."""
    found = []
    for task in waiting:
        settings = _settings_of(task, effective, every)
        if settings is None or settings.after is None:
            found.append(task)
            continue
        parent = next(
            (
                other
                for other in waiting
                if other is not task
                and (appliance := appliance_for(other, every)) is not None
                and appliance.key == settings.after
            ),
            None,
        )
        found.append(replace(task, depends_on=parent.name if parent is not None else None))
    return tuple(found)


def _constraints(
    data: PlanningInput,
    model: HomeModel,
    effective: Configuration,
    every: Sequence[Any],
) -> dict[str, tuple[TimeConstraint, ...]]:
    """Contraintes horaires (lot 3.5) par nom d'élément du plan : tâches de l'équipement,
    son besoin d'énergie ou sa durée à placer (au nom de l'équipement)."""
    found: dict[str, tuple[TimeConstraint, ...]] = {}
    for device in model.devices:
        settings = effective.of(device.key)
        if settings is None or not settings.constraints:
            continue
        constraints = tuple(settings.constraints)
        found[device.name] = constraints
        for task in [*data.due_tasks, *data.waiting_tasks]:
            appliance = appliance_for(task, every)
            if appliance is not None and appliance.key == device.key:
                found[task.name] = constraints
    return found


DEFAULT_SPEED_KW = 0.5  # vitesse non réglée et jamais mesurée


def _runtime(
    device: HomeDevice,
    settings: DeviceSettings,
    measured: float | None,
    current: Sequence[Runtime],
    days_off: int | None = None,
) -> Runtime:
    rules = settings.runtime or RUNTIME_DEFAULT
    speeds = tuple(sorted(((s.name, s.kw) for s in rules.speeds), key=lambda s: s[1])) or (
        (MEASURED_SPEED, measured or DEFAULT_SPEED_KW),
    )
    return Runtime(
        name=device.name,
        speeds=speeds,
        minimum_hours=dict(rules.minimum_hours),
        skip_days=dict(rules.skip_days),
        max_starts=rules.max_starts,
        past=next((r.past for r in current if r.name == device.name), {}),
        days_off=days_off,
    )


def measured_speeds(
    model: HomeModel,
    configuration: Configuration,
    reader: AggregateReader,
    today: date,
    zone: ZoneInfo,
) -> dict[str, float]:
    """Puissance (kW) des durées à placer sans vitesse réglée : médiane, sur 30 jours, des
    quarts d'heure où l'équipement tourne (au-dessus du seuil d'activité de son type)."""
    effective = config.effective(model, configuration)
    start, end = past.window(today, past.BEST_PRODUCTION_DAYS, zone)
    found: dict[str, float] = {}
    for device in model.devices:
        settings = effective.of(device.key)
        if settings is None or settings.behavior is not Behavior.RUNTIME:
            continue
        if settings.runtime is not None and settings.runtime.speeds:
            continue
        threshold = RULES.get(device.kind, DEFAULT_RULES).threshold_w
        means = [
            aggregate.mean
            for sensor in device.sensors
            if sensor.role is Role.POWER_CONSUMED
            for aggregate in reader.read(sensor.entity_id, QUARTER, start, end)
            if aggregate.mean is not None and aggregate.mean >= threshold
        ]
        if means:
            found[device.key] = round(median(means) / 1000, 3)
    return found


def runtime_days_off(
    model: HomeModel,
    configuration: Configuration,
    reader: AggregateReader,
    today: date,
    zone: ZoneInfo,
) -> dict[str, int]:
    """Jours consécutifs sans fonctionnement de chaque durée à placer (lot 3.5), d'après son
    compteur d'énergie ; sans compteur : 0 (le saut reste permis)."""
    effective = config.effective(model, configuration)
    found: dict[str, int] = {}
    for device in model.devices:
        settings = effective.of(device.key)
        if settings is None or settings.behavior is not Behavior.RUNTIME:
            continue
        counters = [s.entity_id for s in device.sensors if s.role is Role.ENERGY_CONSUMED]
        if counters:
            found[device.key] = past.days_without_running(reader, counters, today, zone)
    return found


def southern(client: HomeAssistantClient) -> bool:
    """Hémisphère sud, d'après la latitude de HA."""
    snapshot = getattr(client, "snapshot", None)
    latitude = (getattr(snapshot, "config", None) or {}).get("latitude")
    return isinstance(latitude, int | float) and latitude < 0


def _with_settings(battery: Battery, settings: BatterySettings) -> Battery:
    """Batterie de l'entrée avec les réglages de la configuration (capacité et SoC inchangés)."""
    charge_w, discharge_w = settings.powers_w(battery.capacity_kwh)
    return replace(
        battery,
        charge_max_w=charge_w,
        discharge_max_w=discharge_w,
        floor_percent=settings.floor_percent,
        active_from_hour=settings.active_from_hour,
        active_to_hour=settings.active_to_hour,
        full_charge_every_days=settings.full_charge_every_days,
        floor_ranges=tuple((r.start_hour, r.end_hour, r.percent) for r in settings.floor_ranges),
    )
