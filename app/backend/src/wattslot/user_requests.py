"""Demandes déclarées dans l'application (lot 4.5, point n° 5).

« Faire tourner tel équipement », sans date ou au plus tard tel jour : ce que la liste de tâches
de HA permet, sans avoir à en créer une. Une demande ouverte devient pour le calcul la même
tâche « à la demande » qu'une tâche de HA (affectation à un jour, report toléré, « après » de la
configuration). Si la liste de HA demande déjà le même équipement, c'est elle qui compte. Quand
un calcul constate le lancement d'une demande, elle reste ouverte jusqu'au lendemain (le plan du
jour garde le cycle lancé, comme une tâche de HA pas encore cochée), puis devient faite ; on peut
aussi la clore à la main. Rien n'est écrit dans HA.

Plusieurs demandes peuvent être ouvertes pour le même équipement (deux lessives le même jour) :
chacune est une tâche du calcul, qui les place l'une après l'autre et n'attribue un cycle réel
qu'à une seule (``planning.occurrences``). Redemander un équipement change par défaut la date de
sa demande ouverte pas encore lancée ; une demande de plus s'ouvre si toutes sont déjà lancées
(elles sont alors faites), ou si on le demande (``another``).

Une demande peut porter une heure limite (``finish_hour`` : « terminé avant 12 h »), qui vaut
le jour où son cycle tourne : le jour de son échéance si elle en a une, sinon le jour que le
calcul lui choisit, parmi ceux où un cycle peut finir avant cette heure. Elle est souple : si
aucun créneau ne la tient, le cycle est placé quand même et le plan le dit (issue 273).
"""

import sqlite3
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence, Set
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from wattslot import configuration, home_model
from wattslot.planning.inputs import TaskRequest
from wattslot.planning.journal import Appliance, CycleJournal, cycle_appliances
from wattslot.planning.reference import ident, task_key

UID_PREFIX = "app-"
KEPT_DAYS = 7  # demandes closes encore montrées


class Status(StrEnum):
    OPEN = "open"
    DONE = "done"
    CANCELLED = "cancelled"


class UserRequest(BaseModel):
    id: int
    device: str  # clé de l'équipement
    created_at: datetime
    latest: date | None = None  # au plus tard ; aucun : dès que possible
    # Terminé avant cette heure (1 à 24) le jour où le cycle tourne ; aucune : pas de limite.
    finish_hour: int | None = None
    status: Status = Status.OPEN
    launched_on: date | None = None  # lancement constaté par un calcul
    closed_at: datetime | None = None
    # Demande placée dans le plan du jour : l'identité de son cycle (« Sèche-linge #2 »), et si
    # l'utilisateur l'a déclaré lancé (« C'est lancé »). Remplis par ``with_cycles``.
    cycle: str | None = None
    declared: bool = False


def _row(row: Sequence[object]) -> UserRequest:
    return UserRequest(
        id=int(str(row[0])),
        device=str(row[1]),
        created_at=datetime.fromisoformat(str(row[2])),
        latest=date.fromisoformat(str(row[3])) if row[3] else None,
        status=Status(str(row[4])),
        launched_on=date.fromisoformat(str(row[5])) if row[5] else None,
        closed_at=datetime.fromisoformat(str(row[6])) if row[6] else None,
        finish_hour=int(str(row[7])) if row[7] is not None else None,
    )


COLUMNS = "id, device, created_at, latest, status, launched_on, closed_at, finish_hour"


def open_requests(database: sqlite3.Connection) -> list[UserRequest]:
    rows = database.execute(
        f"SELECT {COLUMNS} FROM requests WHERE status = 'open' ORDER BY id"
    ).fetchall()
    return [_row(r) for r in rows]


def recent(database: sqlite3.Connection, now: datetime) -> list[UserRequest]:
    """Demandes ouvertes, puis celles closes depuis ``KEPT_DAYS`` jours."""
    since = (now - timedelta(days=KEPT_DAYS)).isoformat()
    rows = database.execute(
        f"SELECT {COLUMNS} FROM requests WHERE status = 'open' OR closed_at >= ? "
        "ORDER BY status != 'open', id DESC",
        (since,),
    ).fetchall()
    return [_row(r) for r in rows]


def with_cycles(
    requests: Sequence[UserRequest],
    planning: Iterable[Mapping[str, object]],
    declared: Set[str],
) -> list[UserRequest]:
    """Demandes ouvertes complétées du cycle qui les porte dans le plan du jour (``planning``,
    blocs du plan gardé) et de sa déclaration (``declared``, cycles déclarés lancés) : « Mes
    demandes » propose « C'est lancé » comme « Prochaine action »."""
    cycles: dict[str, str] = {}
    for item in planning:
        name, rank, uid = item.get("equipement"), item.get("rang"), item.get("demande")
        if isinstance(name, str) and isinstance(uid, str):
            cycles[uid] = ident(name, rank if isinstance(rank, int) else None)
    found = []
    for request in requests:
        cycle = cycles.get(f"{UID_PREFIX}{request.id}") if request.status == Status.OPEN else None
        if cycle is not None:
            request = request.model_copy(update={"cycle": cycle, "declared": cycle in declared})
        found.append(request)
    return found


def ask(
    database: sqlite3.Connection,
    device: str,
    latest: date | None,
    now: datetime,
    another: bool = False,
    finish_hour: int | None = None,
) -> UserRequest:
    """Demande pour ``device`` ; sa demande ouverte pas encore lancée (la plus récente) change
    seulement de date et d'heure limite (``finish_hour``, aucune : sans limite d'heure).
    Sinon, ou avec ``another`` (un cycle de plus), une demande est ouverte ;
    sans ``another``, ses demandes déjà lancées sont alors faites : leur cycle a tourné, et
    les clore à la main ne doit pas toucher à la nouvelle."""
    with database:
        row = (
            None
            if another
            else database.execute(
                "SELECT id FROM requests WHERE device = ? AND status = 'open' "
                "AND launched_on IS NULL ORDER BY id DESC",
                (device,),
            ).fetchone()
        )
        if row is None and not another:
            database.execute(
                "UPDATE requests SET status = ?, closed_at = ? "
                "WHERE device = ? AND status = 'open' AND launched_on IS NOT NULL",
                (Status.DONE.value, now.isoformat(), device),
            )
        if row:
            database.execute(
                "UPDATE requests SET latest = ?, finish_hour = ? WHERE id = ?",
                (latest.isoformat() if latest else None, finish_hour, row[0]),
            )
            found = int(row[0])
        else:
            cursor = database.execute(
                "INSERT INTO requests (device, created_at, latest, finish_hour) "
                "VALUES (?, ?, ?, ?)",
                (device, now.isoformat(), latest.isoformat() if latest else None, finish_hour),
            )
            found = int(cursor.lastrowid or 0)
    request = get(database, found)
    assert request is not None
    return request


def waiting(database: sqlite3.Connection, device: str) -> bool:
    """``device`` a-t-il une demande ouverte pas encore lancée : redemander change alors sa
    date, sauf à ajouter un cycle (``ask`` avec ``another``)."""
    row = database.execute(
        "SELECT 1 FROM requests WHERE device = ? AND status = 'open' AND launched_on IS NULL",
        (device,),
    ).fetchone()
    return row is not None


def placeable(
    candidates: Sequence[Appliance],
    needs: Collection[str],
    profile_ok: Callable[[Appliance], bool] | None,
) -> dict[str, bool]:
    """Par clé d'équipement : le calcul saura-t-il placer sa demande ? Un besoin d'énergie
    (``needs``) toujours ; un cycle à démarrer seulement si son cycle est connu
    (``profile_ok`` : profil du journal). Sans journal, on ne peut pas juger : supposé connu.

    Le formulaire acceptait un équipement dont le cycle n'est pas connu : la demande restait
    ouverte sans jamais apparaître dans un plan (constaté le 20/11/2026)."""
    return {a.key: a.key in needs or profile_ok is None or profile_ok(a) for a in candidates}


def requestable(state: Any) -> list[tuple[Appliance, bool]]:
    """Équipements qu'on peut demander (cycles à démarrer et besoins d'énergie de la maison),
    chacun avec ``placeable`` : pour le formulaire et pour l'assistant, qui déposait encore la
    demande d'un appareil au cycle inconnu. ``state`` : l'état de l'application."""
    model, saved = home_model.load(state.graph), configuration.load(state.graph)
    found = cycle_appliances(model, saved)
    needs = {
        settings.key
        for settings in configuration.effective(model, saved).devices
        if settings.behavior is configuration.Behavior.ENERGY_BY_DEADLINE
        and settings.energy is not None
    }
    profile_ok = None
    if state.aggregator is not None:
        cycle_journal = CycleJournal(state.database, state.raw, state.aggregator)
        today = datetime.now(UTC).astimezone(state.raw.zone).date()

        def profile_ok(appliance: Appliance) -> bool:
            return cycle_journal.profile(appliance, today).ok

    known = placeable(found, needs, profile_ok)
    return [(appliance, known[appliance.key]) for appliance in found]


def get(database: sqlite3.Connection, request_id: int) -> UserRequest | None:
    row = database.execute(f"SELECT {COLUMNS} FROM requests WHERE id = ?", (request_id,)).fetchone()
    return _row(row) if row else None


def close(
    database: sqlite3.Connection, request_id: int, status: Status, now: datetime
) -> UserRequest | None:
    """Clôt une demande ouverte (faite ou annulée) ; ``None`` si elle n'existe pas."""
    with database:
        database.execute(
            "UPDATE requests SET status = ?, closed_at = ? WHERE id = ? AND status = 'open'",
            (status.value, now.isoformat(), request_id),
        )
    return get(database, request_id)


def tasks(
    database: sqlite3.Connection,
    candidates: Sequence[Appliance],
    ha_tasks: Iterable[TaskRequest],
    zone_today: date,
) -> tuple[list[TaskRequest], list[TaskRequest]]:
    """(tâches datées, tâches en attente) des demandes ouvertes, au format des tâches « à la
    demande » de HA ; une demande dont l'équipement est déjà demandé par HA est ignorée."""
    by_key = {a.key: a for a in candidates}
    from_ha = {task_key(t.name) for t in ha_tasks}
    due: list[TaskRequest] = []
    waiting: list[TaskRequest] = []
    for request in open_requests(database):
        appliance = by_key.get(request.device)
        if appliance is None or task_key(appliance.name) in from_ha:
            continue
        # Échéance passée sans lancement : dès aujourd'hui. Le calcul ne place une tâche datée
        # que le jour de son échéance ; la demande restait sinon ouverte sans plus jamais
        # être planifiée, et le formulaire la disait « en attente » (constaté le 19/11/2026).
        due_day = request.latest
        if due_day is not None and due_day < zone_today:
            due_day = zone_today
        task = TaskRequest(
            name=appliance.name,
            uid=f"{UID_PREFIX}{request.id}",
            due=due_day,
            on_demand=True,
            needed_since=min(request.created_at.date(), zone_today),
            asked_at=request.created_at,
            finish_hour=request.finish_hour,
        )
        (due if request.latest is not None else waiting).append(task)
    return due, waiting


def mark_launched(database: sqlite3.Connection, launched: Iterable[str], today: date) -> list[int]:
    """Note le lancement constaté aujourd'hui des demandes ouvertes dont la tâche est lancée
    (uid de ``assignment.launched_uids``) : le calcul n'attribue un cycle réel qu'à une seule
    tâche, la demande suivante du même équipement n'est donc pas marquée par lui."""
    uids = set(launched)
    found = [
        r.id
        for r in open_requests(database)
        if r.launched_on is None and f"{UID_PREFIX}{r.id}" in uids
    ]
    with database:
        for request_id in found:
            database.execute(
                "UPDATE requests SET launched_on = ? WHERE id = ?", (today.isoformat(), request_id)
            )
    return found


def settle(database: sqlite3.Connection, today: date, now: datetime) -> list[int]:
    """Clôt (faites) les demandes lancées un jour précédent."""
    done = [
        r.id for r in open_requests(database) if r.launched_on is not None and r.launched_on < today
    ]
    for request_id in done:
        close(database, request_id, Status.DONE, now.astimezone(UTC))
    return done
