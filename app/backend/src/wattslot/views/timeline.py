"""Frise des équipements d'une vue (lot 5.1, PR 2) : barres prévues et réelles, bilan des
équipements (à l'heure, décalé, aucun cycle, hors planning).

Reprend ``_construire_lignes_gantt`` et ``_equipements_prevus`` de la v1 (Python) ainsi que
``afficherEquipementsReels`` et ``majBandeauEquipements`` (JavaScript de la page, exécuté dans le
navigateur), désormais calculés côté serveur.
"""

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from wattslot.planning.reference import ident, task_key
from wattslot.views.display import BATTERY, Context, find_item, is_runtime

SHIFT_MIN = 15  # écart de démarrage toléré (« à l'heure »)
ENERGY_GAP_PERCENT = 10  # écart d'énergie signalé au-delà
CYCLE_FRACTION = 0.3  # part de l'énergie prévue pour reconnaître un cycle
MIDNIGHT_HOURS = 0.25  # activité en cours à minuit : la suite du cycle de la veille
# Un cycle qui en suit un autre a pu démarrer un peu avant la fin mesurée de celui-ci (fin
# reconnue avec retard) : tolérance de la liaison entre les deux.
LINK_TOLERANCE_HOURS = SHIFT_MIN / 60


class Bar(BaseModel):
    start_hour: float  # heures depuis minuit, fractionnaires
    end_hour: float
    energy_kwh: float
    action: Literal["charge", "discharge"] | None = None  # batterie
    mode: str | None = None  # vitesse de la filtration
    # Fin d'un cycle commencé la veille avant minuit (débordement) : de 0 h à sa fin, rien à
    # lancer. Un cycle qui déborde a, lui, ``end_hour`` au-delà de 24.
    carried: bool = False
    # Barre prévue d'un cycle : son identité (``reference.ident``), le nom de l'équipement ou,
    # à partir de son deuxième cycle de la journée, ce nom et son rang (« Lave-linge #2 »).
    # C'est elle que prennent le départ choisi, « Annuler » et « C'est lancé ».
    cycle: str | None = None


class BatteryTrack(BaseModel):
    """Une batterie sous la ligne de la batterie de la maison, ou de son groupe : ses charges
    et décharges mesurées. Pas de prévision : le plan n'en a que par groupe."""

    key: str
    name: str
    actual: list[Bar]


class TimelineRow(BaseModel):
    device: str  # nom de l'équipement dans le plan
    kind: Literal["battery", "cycle", "runtime"]
    planned: list[Bar]
    actual: list[Bar]
    # Batteries d'une même phase (calcul par phase) : 1, 2 ou 3 ; 0 : celles qui compensent
    # le total. ``None`` : la batterie de la maison, ou un autre équipement.
    phase: int | None = None
    # Ligne d'une batterie qui en réunit plusieurs : le mesuré de chacune. Vide sinon.
    batteries: list[BatteryTrack] = []
    # Type de l'équipement dans la maison (``DeviceKind`` : « WashingMachine », « Dryer »…),
    # pour l'icône de la ligne. ``None`` : une batterie, ou un équipement que la maison n'a plus.
    type: str | None = None
    # Équipement que celui-ci suit (« démarre après la fin de »), quand il a aussi sa ligne :
    # la ligne est alors placée juste après la sienne.
    follows: str | None = None


class Link(BaseModel):
    """Liaison entre deux cycles de la journée : celui de la ligne ``target`` vient après celui
    de la ligne ``source`` (sèche-linge après lave-linge). Tracée de la fin du cycle suivi au
    début de celui qui le suit."""

    source: str  # ligne (équipement) du cycle suivi
    target: str  # ligne du cycle qui le suit
    from_hour: float  # fin du cycle suivi : mesurée s'il a tourné, prévue sinon
    to_hour: float  # début du cycle qui le suit : mesuré s'il est lancé, prévu sinon
    started: bool  # cycle qui suit lancé ou fini : trait plein ; prévu ou pas lancé : pointillé


class DeviceStatus(BaseModel):
    """Bilan d'un cycle prévu, au dernier relevé. ``device`` : l'identité du cycle, le nom de
    l'équipement ou, à partir de son deuxième cycle de la journée, ce nom et son rang ;
    ``appliance`` : le nom de l'équipement (sa ligne de la frise)."""

    device: str
    appliance: str | None = None
    status: Literal["on_time", "shifted", "no_cycle", "planned"]
    planned_start_min: int
    planned_end_min: int
    planned_kwh: float
    actual_start_min: int | None = None
    actual_kwh: float | None = None
    running: bool = False
    energy_gap_percent: int | None = None  # au-delà de 10 %, cycle terminé seulement
    shift_min: int | None = None  # démarrage réel moins prévu


class Unplanned(BaseModel):
    """Équipement qui a tourné sans être prévu."""

    device: str
    start_min: int
    energy_kwh: float


class Timeline(BaseModel):
    rows: list[TimelineRow]  # lignes sans barre prévue ni réelle masquées
    empty: Literal["no_surplus", "nothing"] | None = None  # aucune barre prévue
    production_kwh: float  # prévue, pour le message d'une frise vide
    consumption_kwh: float
    statuses: list[DeviceStatus]
    unplanned: list[Unplanned]
    badge: Literal["on_time", "shifted"] | None = None  # au moins un équipement jugé
    cancelled: list[str] = []  # planifications annulées pour aujourd'hui (Aujourd'hui seule)
    links: list[Link] = []  # liaisons entre les cycles d'équipements qui se suivent


def _js_round(value: float) -> int:
    """``Math.round`` du JavaScript (demi vers le haut), pour les mêmes nombres que la page."""
    return math.floor(value + 0.5)


def battery_blocks(movements: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Mouvements horaires regroupés en blocs contigus de même action
    (``_grouper_mouvements_batterie`` de la v1)."""
    if not movements:
        return []
    ordered = sorted(movements, key=lambda m: m["heure"])
    blocks = [
        {
            "debut": ordered[0]["heure"],
            "fin": ordered[0]["heure"] + 1,
            "action": ordered[0]["action"],
            "energie_kwh": ordered[0]["energie_kwh"],
        }
    ]
    for movement in ordered[1:]:
        last = blocks[-1]
        if movement["action"] == last["action"] and movement["heure"] == last["fin"]:
            last["fin"] = movement["heure"] + 1
            last["energie_kwh"] += movement["energie_kwh"]
        else:
            blocks.append(
                {
                    "debut": movement["heure"],
                    "fin": movement["heure"] + 1,
                    "action": movement["action"],
                    "energie_kwh": movement["energie_kwh"],
                }
            )
    return blocks


def _device(plan: Mapping[str, Any]) -> str:
    """Nom de l'équipement d'un cycle prévu (``planned_devices``)."""
    return str(plan.get("equipement", plan["nom"]))


def _count(planned: Sequence[Mapping[str, Any]], name: str) -> int:
    return sum(1 for plan in planned if _device(plan) == name)


def cycle_bounds(item: Mapping[str, Any]) -> tuple[int, int]:
    """(début, fin) du cycle en minutes (``bornes_minutes`` de la v1)."""
    cycle_min = item.get("duree_cycle_min") or (item["heure_fin"] - item["heure_debut"]) * 60
    start = item.get("debut_min", item["heure_debut"] * 60)
    return start, item.get("fin_min", min(24 * 60, start + round(cycle_min)))


def asked_times(state: Mapping[str, Any]) -> dict[str, str]:
    """Moment où chaque demande de l'application a été faite (uid → ISO), d'après les tâches
    gardées avec le plan."""
    tasks = [*(state.get("taches_placees") or []), *(state.get("taches_en_attente") or [])]
    return {
        str(task["uid"]): str(task["demandee_iso"])
        for task in tasks
        if isinstance(task, Mapping) and task.get("uid") and task.get("demandee_iso")
    }


def planned_devices(
    planning: Sequence[Mapping[str, Any]],
    context: Context,
    asked: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Équipements prévus (créneau en minutes et énergie), la filtration résumée de son premier
    à son dernier segment (``_equipements_prevus`` de la v1). ``asked`` (``asked_times``) :
    chaque cycle porte le moment où sa demande a été faite (``depuis_iso``)."""
    found = []
    for item in planning:
        name = item["equipement"]
        if name == BATTERY:
            continue
        if is_runtime(item):
            segments = [s for s in item.get("segments", []) if s["mode"] != "off"]
            if not segments:
                continue
            energy = sum(
                (s["heure_fin"] - s["heure_debut"]) * context.speed_kw(s["mode"]) for s in segments
            )
            start = min(s["heure_debut"] for s in segments) * 60
            end = max(s["heure_fin"] for s in segments) * 60
        else:
            start, end = cycle_bounds(item)
            energy = item.get("energie_kwh", 0.0)
        # Identité du cycle : l'équipement et, à partir de son deuxième cycle de la journée,
        # son rang ; le nom de l'équipement est alors donné à part.
        cycle = ident(name, item.get("rang"))
        found.append(
            {
                "nom": cycle,
                **({"equipement": name} if cycle != name else {}),
                "debut_min": start,
                "fin_min": end,
                "energie_kwh": round(energy, 3),
                **(
                    {"depuis_iso": (asked or {})[item["demande"]]}
                    if item.get("demande") in (asked or {})
                    else {}
                ),
            }
        )
    return sorted(found, key=lambda p: p["debut_min"])


def _before_request(segment: Mapping[str, Any], plan: Mapping[str, Any], context: Context) -> bool:
    """L'activité a-t-elle commencé avant que la demande du cycle prévu soit faite ? Elle n'est
    alors pas son cycle, comme dans le calcul (``occurrences.attribute``). Une lessive faite à
    3 h passait pour le cycle de la lessive demandée à 8 h 21 : celle-ci était dite « lancée à
    3 h » et n'était plus proposée dans « Prochaine action » (constaté le 20/11/2026)."""
    since = plan.get("depuis_iso")
    if not since:
        return False
    try:
        return _local(segment["debut_iso"], context) < _local(str(since), context)
    except (TypeError, ValueError):  # heures avec et sans fuseau : l'activité est gardée
        return False


def _local(iso: str, context: Context) -> datetime:
    moment = datetime.fromisoformat(iso)
    return moment.astimezone(context.zone) if moment.tzinfo else moment


def _minutes(iso: str, context: Context) -> int:
    moment = _local(iso, context)
    return moment.hour * 60 + moment.minute


def _hours(iso: str, context: Context) -> float:
    moment = _local(iso, context)
    return moment.hour + moment.minute / 60 + moment.second / 3600


def _actual_bars(segments: Sequence[Mapping[str, Any]], context: Context) -> list[Bar]:
    bars = []
    for segment in segments:
        try:
            start, end = _hours(segment["debut_iso"], context), _hours(segment["fin_iso"], context)
        except (KeyError, TypeError, ValueError):
            continue
        action = {"charge": "charge", "decharge": "discharge"}.get(segment.get("action", ""))
        bars.append(
            Bar(
                start_hour=round(start, 4),
                end_hour=round(end, 4),
                energy_kwh=round(segment.get("energie_kwh", 0.0), 3),
                action=action,  # type: ignore[arg-type]
                mode=segment.get("mode"),
            )
        )
    return bars


def statuses(
    planned: Sequence[Mapping[str, Any]],
    actual: Mapping[str, Any] | None,
    reference_hour: float,
    runtime_names: set[str],
    context: Context,
) -> tuple[list[DeviceStatus], list[Unplanned], str | None]:
    """Bilan des équipements prévus au dernier relevé (``majBandeauEquipements`` de la v1)."""
    measured = (actual or {}).get("equipements_reels_horaire") or {}
    now_min = reference_hour * 60
    found: list[DeviceStatus] = []
    judged = shifted = 0
    # Plusieurs cycles du même équipement : chacun avec son cycle réel, dans l'ordre de la
    # journée (le premier prévu avec le premier mesuré) ; un seul, le plus proche de son départ.
    several = {name for name in {_device(p) for p in planned} if _count(planned, name) > 1}
    taken: dict[str, list[Any]] = {}  # activités déjà prises par un autre cycle de l'équipement
    for plan in planned:
        device = _device(plan)
        segments = measured.get(device) or []
        cycle: dict[str, Any] | None = None
        if device in runtime_names:
            if segments:
                cycle = {
                    "start": _minutes(segments[0]["debut_iso"], context),
                    "kwh": sum(s.get("energie_kwh") or 0 for s in segments),
                    "running": any(s.get("en_cours") for s in segments),
                }
        else:
            recognized = [
                s
                for s in segments
                if (
                    (s.get("energie_kwh") or 0) >= CYCLE_FRACTION * plan["energie_kwh"]
                    and (s.get("energie_kwh") or 0) > 0
                )
                or s.get("en_cours")
            ]
            recognized = [s for s in recognized if not _before_request(s, plan, context)]
            if device in several:
                used = taken.setdefault(device, [])
                recognized = [s for s in recognized if not any(s is other for other in used)]
                recognized.sort(key=lambda s: _minutes(s["debut_iso"], context))
                recognized = recognized[:1]
                used.extend(recognized)
            else:
                recognized.sort(
                    key=lambda s: abs(_minutes(s["debut_iso"], context) - plan["debut_min"])
                )
            if recognized:
                cycle = {
                    "start": _minutes(recognized[0]["debut_iso"], context),
                    "kwh": recognized[0].get("energie_kwh") or 0,
                    "running": bool(recognized[0].get("en_cours")),
                }
        common = {
            "device": plan["nom"],
            "appliance": device,
            "planned_start_min": plan["debut_min"],
            "planned_end_min": plan["fin_min"],
            "planned_kwh": plan["energie_kwh"],
        }
        if cycle is not None:
            judged += 1
            gap = cycle["start"] - plan["debut_min"]
            percent = None
            if not cycle["running"] and plan["energie_kwh"] > 0:
                value = _js_round((cycle["kwh"] - plan["energie_kwh"]) / plan["energie_kwh"] * 100)
                percent = value if abs(value) > ENERGY_GAP_PERCENT else None
            on_time = abs(gap) <= SHIFT_MIN
            shifted += 0 if on_time else 1
            found.append(
                DeviceStatus(
                    **common,
                    status="on_time" if on_time else "shifted",
                    actual_start_min=cycle["start"],
                    actual_kwh=round(cycle["kwh"], 3),
                    running=cycle["running"],
                    energy_gap_percent=percent,
                    shift_min=None if on_time else gap,
                )
            )
        elif actual and now_min >= plan["fin_min"]:
            judged += 1
            shifted += 1
            found.append(DeviceStatus(**common, status="no_cycle"))
        else:
            found.append(DeviceStatus(**common, status="planned"))
    names = {_device(p) for p in planned}
    unplanned = [
        Unplanned(
            device=name,
            start_min=_minutes(segments[0]["debut_iso"], context),
            energy_kwh=round(sum(s.get("energie_kwh") or 0 for s in segments), 3),
        )
        for name, segments in measured.items()
        if name not in names and segments
    ]
    badge = None if not judged else ("shifted" if shifted else "on_time")
    return found, unplanned, badge


@dataclass(frozen=True)
class DayCycle:
    """Cycle de la journée d'un équipement : une activité mesurée, ou un bloc prévu pas lancé."""

    start: float  # heures depuis minuit
    end: float
    started: bool


def day_cycles(row: TimelineRow, found: Sequence[DeviceStatus]) -> list[DayCycle]:
    """Cycles de la journée d'une ligne, dans l'ordre (comme ``cycleNames.ts`` de l'interface) :
    les activités mesurées qui sont des cycles — le démarrage d'un cycle prévu d'après le bilan,
    ou au moins ``CYCLE_FRACTION`` de la plus grosse activité de la journée (un réveil de veille
    n'est pas un cycle) —, les blocs prévus pas lancés, et la suite d'un cycle de la veille si
    elle n'est pas mesurée dès minuit."""
    own = [status for status in found if (status.appliance or status.device) == row.device]
    starts = [s.actual_start_min for s in own if s.actual_start_min is not None]
    launched = {status.device for status in own if status.actual_start_min is not None}
    biggest = max((bar.energy_kwh for bar in row.actual), default=0.0)
    cycles = [
        DayCycle(bar.start_hour, bar.end_hour, True)
        for bar in row.actual
        if any(abs(start - bar.start_hour * 60) < 1 for start in starts)
        or (bar.energy_kwh > 0 and bar.energy_kwh >= CYCLE_FRACTION * biggest)
    ]
    measured_at_midnight = any(cycle.start < MIDNIGHT_HOURS for cycle in cycles)
    for bar in row.planned:
        if bar.carried:
            if not measured_at_midnight:
                cycles.append(DayCycle(0.0, bar.end_hour, True))
        elif (bar.cycle or row.device) not in launched:
            cycles.append(DayCycle(bar.start_hour, bar.end_hour, False))
    return sorted(cycles, key=lambda cycle: cycle.start)


def _first_start(row: TimelineRow, cycles: Sequence[DayCycle]) -> float:
    """Premier lancement de la journée, prévu ou réel ; sans cycle, son premier bloc."""
    if cycles:
        return cycles[0].start
    return min((bar.start_hour for bar in [*row.planned, *row.actual]), default=math.inf)


def followed(state: Mapping[str, Any], context: Context) -> dict[str, str]:
    """Équipement suivi par chaque équipement réglé « démarre après la fin de » (clés
    ``task_key``) : le réglage de la maison, sinon la dépendance écrite dans les tâches gardées
    avec le plan (``depend_de``)."""
    found = {task_key(child): task_key(parent) for child, parent in context.follows.items()}
    tasks = [*(state.get("taches_placees") or []), *(state.get("taches_en_attente") or [])]
    for task in tasks:
        description = task.get("description") if isinstance(task, Mapping) else None
        if not isinstance(description, Mapping) or not description.get("depend_de"):
            continue
        child = task_key(str(task.get("summary", "")))
        found.setdefault(child, task_key(str(description["depend_de"])))
    return {child: parent for child, parent in found.items() if child and child != parent}


def ordered_rows(
    rows: Sequence[TimelineRow], cycles: Mapping[str, Sequence[DayCycle]]
) -> list[TimelineRow]:
    """Lignes dans l'ordre de la frise : les batteries, puis les équipements à cycles dans
    l'ordre de leur premier lancement de la journée (prévu ou réel ; à égalité, l'ordre du
    plan), un équipement qui en suit un autre juste après lui même s'il a tourné plus tôt,
    puis les durées à placer (la filtration, qui tourne par morceaux toute la journée)."""
    by_start = sorted(
        (row for row in rows if row.kind == "cycle"),
        key=lambda row: _first_start(row, cycles.get(row.device, ())),
    )
    children: dict[str, list[TimelineRow]] = defaultdict(list)
    for row in by_start:
        if row.follows is not None:
            children[row.follows].append(row)
    placed: list[TimelineRow] = []

    def place(row: TimelineRow) -> None:
        if any(row is other for other in placed):
            return
        placed.append(row)
        for child in children.get(row.device, ()):
            place(child)

    for row in by_start:
        if row.follows is None:
            place(row)
    for row in by_start:  # dépendances en boucle : aucune ligne n'est perdue
        place(row)
    return [
        *(row for row in rows if row.kind == "battery"),
        *placed,
        *(row for row in rows if row.kind == "runtime"),
    ]


def links(rows: Sequence[TimelineRow], cycles: Mapping[str, Sequence[DayCycle]]) -> list[Link]:
    """Liaisons entre les cycles d'un équipement et ceux de celui qu'il suit. Appariés dans
    l'ordre de la journée, comme dans le calcul (``occurrences.paired``) : chaque cycle prend
    le premier cycle de l'autre équipement, pas encore pris, fini avant son départ. Un cycle
    lancé avant la fin de tous ceux de l'autre équipement n'a pas de liaison."""
    found: list[Link] = []
    for row in rows:
        if row.follows is None:
            continue
        free = list(cycles.get(row.follows, ()))
        for cycle in cycles.get(row.device, ()):
            parent = next(
                (other for other in free if other.end <= cycle.start + LINK_TOLERANCE_HOURS), None
            )
            if parent is None:
                continue
            free.remove(parent)
            found.append(
                Link(
                    source=row.follows,
                    target=row.device,
                    from_hour=round(parent.end, 4),
                    to_hour=round(cycle.start, 4),
                    started=cycle.started,
                )
            )
    return found


# Mouvement de batterie affiché « 0,0 kWh » : quelques Wh au-dessus du plancher, pas montré.
MIN_BATTERY_BAR_KWH = 0.05


def build_timeline(
    state: Mapping[str, Any],
    actual: Mapping[str, Any] | None,
    reference_hour: float,
    production_kwh: float,
    consumption_kwh: float,
    context: Context,
) -> Timeline:
    """Frise d'un plan ; ``reference_hour`` : heure du dernier relevé (24 pour Hier)."""
    planning = state.get("planning", [])
    measured = dict((actual or {}).get("equipements_reels_horaire") or {})
    rows: list[TimelineRow] = []
    battery = find_item(planning, BATTERY)

    def battery_bars(movements: Sequence[Mapping[str, Any]]) -> list[Bar]:
        return [
            Bar(
                start_hour=b["debut"],
                end_hour=b["fin"],
                energy_kwh=round(b["energie_kwh"], 3),
                action="charge" if b["action"] == "charge" else "discharge",
            )
            for b in battery_blocks(movements)
            if b["energie_kwh"] >= MIN_BATTERY_BAR_KWH
        ]

    def tracks(phase: int | None) -> list[BatteryTrack]:
        """Batteries réunies sur une ligne (``phase`` : leur groupe ; ``None`` : toutes), avec
        le mesuré de chacune ; aucune quand la ligne n'en réunit qu'une."""
        found = [
            BatteryTrack(
                key=str(one.get("cle")),
                name=str(one.get("nom")),
                actual=_actual_bars(one.get("segments") or [], context),
            )
            for one in (actual or {}).get("batterie_reelle_segments_par_batterie") or []
            if phase is None or one.get("phase") == phase
        ]
        return found if len(found) > 1 else []

    groups = (battery or {}).get("groupes") or []
    if battery is not None and groups:
        # Calcul par phase : une ligne par groupe de batteries, avec sa propre prévision et ses
        # propres mesures, à la place de la ligne de toutes les batteries ensemble.
        measured_by_phase = {
            int(phase): segments
            for phase, segments in (
                (actual or {}).get("batterie_reelle_segments_par_phase") or {}
            ).items()
        }
        for group in sorted(groups, key=lambda g: g["phase"] or 9):
            rows.append(
                TimelineRow(
                    device=f"{BATTERY} {group['phase']}",
                    kind="battery",
                    planned=battery_bars(group.get("mouvements", [])),
                    actual=_actual_bars(measured_by_phase.get(group["phase"]) or [], context),
                    phase=group["phase"],
                    batteries=tracks(group["phase"]),
                )
            )
    elif battery is not None:
        rows.append(
            TimelineRow(
                device=BATTERY,
                kind="battery",
                planned=battery_bars(battery.get("mouvements", [])),
                actual=_actual_bars((actual or {}).get("batterie_reelle_segments") or [], context),
                batteries=tracks(None),
            )
        )
    rendered = set()
    for item in planning:
        if item["equipement"] == BATTERY or is_runtime(item):
            continue
        start, end = cycle_bounds(item)
        bar = Bar(
            start_hour=start / 60,
            end_hour=end / 60,
            energy_kwh=round(item.get("energie_kwh", 0.0), 3),
            cycle=ident(item["equipement"], item.get("rang")),
        )
        # Plusieurs cycles du même équipement dans la journée : une seule ligne, une barre
        # par cycle, dans l'ordre de la journée.
        row = next((r for r in rows if r.kind == "cycle" and r.device == item["equipement"]), None)
        if row is not None:
            row.planned = sorted([*row.planned, bar], key=lambda b: b.start_hour)
            continue
        rows.append(
            TimelineRow(
                device=item["equipement"],
                kind="cycle",
                planned=[bar],
                actual=_actual_bars(measured.get(item["equipement"]) or [], context),
            )
        )
        rendered.add(item["equipement"])
    for carried in state.get("suite_veille") or []:  # fins des cycles de la veille
        bar = Bar(
            start_hour=0,
            end_hour=round(carried["fin_min"] / 60, 4),
            energy_kwh=round(carried.get("energie_kwh", 0.0), 3),
            carried=True,
        )
        row = next((r for r in rows if r.device == carried["equipement"]), None)
        if row is not None:
            row.planned.insert(0, bar)
        else:
            rows.append(
                TimelineRow(
                    device=carried["equipement"],
                    kind="cycle",
                    planned=[bar],
                    actual=_actual_bars(measured.get(carried["equipement"]) or [], context),
                )
            )
            rendered.add(carried["equipement"])
    runtimes = [item for item in planning if is_runtime(item)]
    runtime_names = {item["equipement"] for item in runtimes}
    for name in context.appliances:
        if name not in rendered and name not in runtime_names:
            rows.append(
                TimelineRow(
                    device=name,
                    kind="cycle",
                    planned=[],
                    actual=_actual_bars(measured.get(name) or [], context),
                )
            )
    for item in runtimes:
        bars = [
            Bar(
                start_hour=s["heure_debut"],
                end_hour=s["heure_fin"],
                energy_kwh=round(
                    (s["heure_fin"] - s["heure_debut"]) * context.speed_kw(s["mode"]), 3
                ),
                mode=s["mode"],
            )
            for s in item.get("segments", [])
            if s["mode"] != "off"
        ]
        rows.append(
            TimelineRow(
                device=item["equipement"],
                kind="runtime",
                planned=bars,
                actual=_actual_bars(measured.get(item["equipement"]) or [], context),
            )
        )
    for row in rows:
        if row.kind != "battery":
            row.type = context.kinds.get(row.device)
    any_planned = any(row.planned for row in rows)
    empty = None
    if not any_planned:
        empty = "no_surplus" if production_kwh < consumption_kwh else "nothing"
    found, unplanned, badge = statuses(
        planned_devices(planning, context, asked_times(state)),
        actual,
        reference_hour,
        runtime_names,
        context,
    )
    # Lignes affichées : celles qui ont un bloc. Un équipement qui en suit un autre est relié
    # à lui si l'autre a aussi sa ligne.
    shown = [row for row in rows if row.planned or row.actual]
    devices = {task_key(row.device): row.device for row in shown if row.kind == "cycle"}
    for child, parent in followed(state, context).items():
        if child in devices and parent in devices:
            next(row for row in shown if row.device == devices[child]).follows = devices[parent]
    cycles = {row.device: day_cycles(row, found) for row in shown if row.kind == "cycle"}
    shown = ordered_rows(shown, cycles)
    return Timeline(
        rows=shown,
        empty=empty,  # type: ignore[arg-type]
        production_kwh=round(production_kwh, 3),
        consumption_kwh=round(consumption_kwh, 3),
        statuses=found,
        unplanned=unplanned,
        badge=badge,  # type: ignore[arg-type]
        links=links(shown, cycles),
    )
