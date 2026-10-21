"""Entrée du calcul, typée.

Mêmes informations que l'entrée de ``calculer_planning`` (v1) : le lot 2.2 la construira à
partir des données de la v2. ``from_v1`` la lit dans le format de la v1 (états capturés).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import Any

from wattslot.planning.co2_sources import Co2Context
from wattslot.planning.cycles import Segment, Shape
from wattslot.planning.plan import POOL
from wattslot.tariff import V1 as V1_TARIFF
from wattslot.tariff import Tariff, TariffContext
from wattslot.time_constraints import TimeConstraint


@dataclass(frozen=True)
class TaskRequest:
    """Tâche de la liste de HA : un équipement à faire tourner."""

    name: str
    uid: str | None = None
    due: date | None = None  # tâche datée (récurrente, ou à la demande avec échéance)
    on_demand: bool = False  # « à la demande » (linge, lave-vaisselle), sinon récurrente
    depends_on: str | None = None  # nom de la tâche à finir avant (sèche-linge)
    needed_since: date | None = None  # besoin détecté (affectation à un jour)
    rule: str | None = None  # règle de récurrence (RFC 5545) d'une tâche récurrente


@dataclass(frozen=True)
class CycleProfile:
    """Cycle mesuré d'un équipement (médiane des cycles réels sur 30 jours)."""

    energy_kwh: float
    duration_min: float
    shape: Shape | None = None


@dataclass(frozen=True)
class DailyProfile:
    """Consommation journalière d'un équipement, repli sans cycle mesuré."""

    daily_kwh: tuple[float, ...] = ()
    max_kwh: float | None = None
    avg_kwh: float | None = None
    total_kwh: float | None = None


@dataclass(frozen=True)
class FrozenCycle:
    """Cycle décidé plus tôt dans la journée (« passé gelé »), gardé tel quel."""

    name: str
    start_hour: int
    end_hour: int
    energy_kwh: float
    start_min: int | None = None
    end_min: int | None = None
    cycle_min: float | None = None
    shape: Shape | None = None
    priority: int = 3


@dataclass(frozen=True)
class Battery:
    capacity_kwh: float
    stored_kwh: float
    soc_percent: float
    charge_max_w: float
    discharge_max_w: float
    round_trip_percent: float | None = None
    charge_efficiency_percent: float | None = None  # mesurés par sens, s'ils sont connus
    discharge_efficiency_percent: float | None = None
    efficiency_days: int | None = None
    # Plannings actifs : (mode, heure de début, heure de fin, minute de fin) ; -1 = autoconso.
    # Ceux de l'entrée de la v1 ; sans planning, la plage active ci-dessous.
    schedules: tuple[tuple[int, int, int, int], ...] = ()
    # Réglages (lot 3.3) ; par défaut ceux de la v1, pour une entrée au format de la v1.
    floor_percent: float = 12.0
    active_from_hour: int = 6
    active_to_hour: int = 24
    full_charge_every_days: int | None = 6
    floor_ranges: tuple[tuple[int, int, float], ...] = ()  # (début, fin exclue, %), lot 3.5


@dataclass(frozen=True)
class Runtime:
    """Durée de fonctionnement à placer (lot 3.4) : filtration de piscine, déshumidificateur…"""

    name: str  # nom de l'équipement, celui de l'élément du plan
    speeds: tuple[tuple[str, float], ...]  # (mode, kW), de la plus basse à la plus haute
    minimum_hours: Mapping[str, int]  # par saison (``runtime_settings.season``)
    skip_days: Mapping[str, int]  # jours sans fonctionnement tolérés, par saison
    max_starts: int = 2
    past: Mapping[int, str] = field(default_factory=dict)  # heure → mode déjà planifié
    # Jours consécutifs sans fonctionnement (lot 3.5) ; None : compteur de la v1 (historique).
    days_off: int | None = None


@dataclass(frozen=True)
class Need:
    """Besoin d'énergie avant une échéance (lot 3.4) : véhicule électrique, ballon piloté…"""

    name: str  # nom de l'équipement, celui de l'élément du plan
    energy_kwh: float
    earliest_hour: int
    deadline_hour: int  # énergie fournie avant cette heure
    max_kw: float
    steps: bool = False  # tout ou rien à la puissance maximale
    daily: bool = True  # sinon demandé par une tâche du jour : pas repris les jours suivants


# La filtration de la v1 : celle d'une entrée au format de la v1 (les 13 états capturés).
V1_POOL = Runtime(
    name=POOL,
    speeds=(("silence", 0.130), ("eco", 0.415)),
    minimum_hours={"summer": 2, "mid_season": 1, "winter": 0},
    skip_days={"summer": 1, "mid_season": 2, "winter": 365},
)


@dataclass(frozen=True)
class RecentHistory:
    last_full_charge: date | None = None
    days: int | None = None
    days_without_filtration: int = 0


@dataclass(frozen=True)
class PlanningInput:
    day: date
    first_hour: int  # heure d'exécution : rien n'est décidé avant
    net_kwh: Mapping[int, float]  # production moins ligne de base, signé, toutes les heures
    production_kwh: Mapping[int, float]
    battery: Battery
    due_tasks: tuple[TaskRequest, ...] = ()
    waiting_tasks: tuple[TaskRequest, ...] = ()
    assignments: Mapping[str, date] | None = None  # tâche en attente (uid) → jour choisi
    # Départs choisis par l'utilisateur pour aujourd'hui (``planning.choices``) : appareil →
    # minutes depuis minuit, imposés au calcul.
    chosen_starts: Mapping[str, int] = field(default_factory=dict)
    cycle_profiles: Mapping[str, CycleProfile] = field(default_factory=dict)
    daily_profiles: Mapping[str, DailyProfile | None] = field(default_factory=dict)
    profile_status: Mapping[str, str] = field(default_factory=dict)  # pour les avertissements
    frozen: tuple[FrozenCycle, ...] = ()
    real_segments: Mapping[str, tuple[Segment, ...]] = field(default_factory=dict)
    real_updated_at: datetime | None = None
    # Durées de fonctionnement à placer (lot 3.4) ; la filtration de la v1 par défaut.
    runtimes: tuple[Runtime, ...] = field(default_factory=lambda: (V1_POOL,))
    southern: bool = False  # hémisphère sud : saisons décalées de six mois
    needs: tuple[Need, ...] = ()  # besoins d'énergie du jour (lot 3.4)
    # Contraintes horaires (lot 3.5), par nom d'élément du plan (tâche, besoin, durée).
    constraints: Mapping[str, tuple[TimeConstraint, ...]] = field(default_factory=dict)
    # Tolérance de report (jours) des tâches en attente, par nom (lot 3.5) ; sinon 2 jours.
    max_delay_days: Mapping[str, int] = field(default_factory=dict)
    # Tarif de la maison (lot 3.2) ; celui de la v1 par défaut (entrée au format de la v1).
    tariff: Tariff = field(default_factory=lambda: V1_TARIFF)
    tariff_context: TariffContext = field(default_factory=TariffContext)  # lu dans HA
    co2: Co2Context = field(default_factory=Co2Context)  # intensité du réseau (lot 3.6)
    history: RecentHistory | None = None
    measured_production_kwh: float | None = None  # production mesurée au relevé
    measured_at_hour: float | None = None  # heure du relevé (fractionnaire)
    forecast_warnings: tuple[dict[str, Any], ...] = ()


def _date(value: Any) -> date | None:
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _strict_day(value: Any) -> date | None:
    """Échéance d'une tâche : date ISO exacte, sinon None (tâche non datée)."""
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value) if isinstance(value, str) and value else None
    except ValueError:
        return None


def _day_prefix(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _task(raw: Mapping[str, Any]) -> TaskRequest:
    description = raw.get("description") or {}
    return TaskRequest(
        name=raw["summary"],
        uid=raw.get("uid"),
        due=_strict_day(raw.get("due")),
        on_demand=description.get("type") == "a_la_demande",
        depends_on=description.get("depend_de"),
        needed_since=_day_prefix(description.get("besoin_detecte")),
        rule=description.get("regle") if description.get("type") == "recurrent" else None,
    )


def from_v1(state: Mapping[str, Any]) -> PlanningInput:
    """Entrée typée à partir de l'entrée de ``calculer_planning`` (v1)."""
    cycle_profiles: dict[str, CycleProfile] = {}
    for name, profile in (state.get("profils_cycles") or {}).items():
        if (profile or {}).get("status") == "ok":
            cycle_profiles[name] = CycleProfile(
                profile["energie_kwh"], profile["duree_min"], profile.get("forme_quart_heure")
            )
    daily_profiles: dict[str, DailyProfile | None] = {}
    status: dict[str, str] = {}
    for name, profile in (state.get("profils_equipements") or {}).items():
        status[name] = (profile or {}).get("status") or "absent"
        if status[name] != "ok":
            daily_profiles[name] = None
            continue
        consumption = profile.get("daily_consumption_kwh") or {}
        daily_profiles[name] = DailyProfile(
            daily_kwh=tuple(
                d["kwh"] for d in consumption.get("details") or [] if d.get("kwh") is not None
            ),
            max_kwh=consumption.get("max"),
            avg_kwh=consumption.get("avg"),
            total_kwh=consumption.get("total_over_period"),
        )
    real = state.get("cycles_reels") or {}
    try:
        updated_at: datetime | None = datetime.fromisoformat(real["heure_maj_iso"])
    except (KeyError, TypeError, ValueError):
        updated_at = None
    segments = {
        name: tuple(
            Segment(
                datetime.fromisoformat(s["debut_iso"]),
                datetime.fromisoformat(s["fin_iso"]),
                s.get("energie_kwh", 0.0),
                bool(s.get("en_cours")),
            )
            for s in segs or []
        )
        for name, segs in (real.get("segments") or {}).items()
    }
    measured = state.get("rendements_batterie") or {}
    history = state.get("historique_recent")
    return PlanningInput(
        day=_date(state["date_cible"]) or date.min,
        first_hour=state.get("heure_execution", 0),
        net_kwh={h: (state.get("net_horaire_signe") or {}).get(h, 0.0) for h in range(24)},
        production_kwh={
            h: (state.get("production_solaire_horaire") or {}).get(h, 0.0) for h in range(24)
        },
        battery=Battery(
            capacity_kwh=state["capacite_batterie_kwh"],
            stored_kwh=state["stored_energy_kwh"],
            soc_percent=state["soc_percent"],
            charge_max_w=state["puissance_charge_max_w"],
            discharge_max_w=state["puissance_decharge_max_w"],
            round_trip_percent=state.get("rendement_round_trip_percent"),
            charge_efficiency_percent=measured.get("rendement_charge_percent")
            if measured.get("status") == "ok"
            else None,
            discharge_efficiency_percent=measured.get("rendement_decharge_percent")
            if measured.get("status") == "ok"
            else None,
            efficiency_days=measured.get("nb_jours"),
            schedules=tuple(
                (
                    s.get("mode", 0),
                    s["start"]["heure"],
                    s["end"]["heure"],
                    s["end"]["minute"],
                )
                for s in state.get("schedules_batterie_actifs") or []
                if s.get("start") and s.get("end")
            ),
        ),
        due_tasks=tuple(_task(t) for t in state.get("taches_placees") or []),
        waiting_tasks=tuple(_task(t) for t in state.get("taches_en_attente") or []),
        assignments=(
            {
                uid: day
                for uid, a in state["affectations"].items()
                if (day := _date((a or {}).get("jour"))) is not None
            }
            if state.get("affectations")
            else None
        ),
        cycle_profiles=cycle_profiles,
        daily_profiles=daily_profiles,
        profile_status=status,
        frozen=tuple(
            FrozenCycle(
                name=item["equipement"],
                start_hour=item["heure_debut"],
                end_hour=item["heure_fin"],
                energy_kwh=item.get("energie_kwh", 0.0),
                start_min=item.get("debut_min"),
                end_min=item.get("fin_min"),
                cycle_min=item.get("duree_cycle_min"),
                shape=item.get("forme_quart_heure"),
                priority=item.get("priorite", 3),
            )
            for item in state.get("equipements_geles") or []
        ),
        real_segments=segments,
        real_updated_at=updated_at,
        runtimes=(
            replace(
                V1_POOL,
                past={int(h): mode for h, mode in (state.get("piscine_passee") or {}).items()},
            ),
        ),
        history=RecentHistory(
            last_full_charge=_date(history.get("derniere_charge_complete")),
            days=history.get("nb_jours"),
            days_without_filtration=history.get("jours_sans_filtration", 0),
        )
        if history
        else None,
        measured_production_kwh=state.get("production_reelle_cumul_kwh"),
        measured_at_hour=state.get("heure_releve"),
        forecast_warnings=tuple(state.get("avertissements_prevision") or []),
    )
