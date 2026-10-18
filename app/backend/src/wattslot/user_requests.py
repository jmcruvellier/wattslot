"""Demandes déclarées dans l'application (lot 4.5, point n° 5).

« Faire tourner tel équipement », sans date ou au plus tard tel jour : ce que la liste de tâches
de HA permet, sans avoir à en créer une. Une demande ouverte devient pour le calcul la même
tâche « à la demande » qu'une tâche de HA (affectation à un jour, report toléré, « après » de la
configuration). Une seule demande ouverte par équipement ; si la liste de HA demande déjà le même
équipement, c'est elle qui compte. Quand un calcul constate le lancement de l'équipement, la demande
reste ouverte jusqu'au lendemain (le plan du jour garde le cycle lancé, comme une tâche de HA pas
encore cochée), puis devient faite ; on peut aussi la clore à la main. Rien n'est écrit dans HA.
"""

import sqlite3
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel

from wattslot.planning.inputs import TaskRequest
from wattslot.planning.journal import Appliance
from wattslot.planning.reference import task_key

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
    status: Status = Status.OPEN
    launched_on: date | None = None  # lancement constaté par un calcul
    closed_at: datetime | None = None


def _row(row: Sequence[object]) -> UserRequest:
    return UserRequest(
        id=int(str(row[0])),
        device=str(row[1]),
        created_at=datetime.fromisoformat(str(row[2])),
        latest=date.fromisoformat(str(row[3])) if row[3] else None,
        status=Status(str(row[4])),
        launched_on=date.fromisoformat(str(row[5])) if row[5] else None,
        closed_at=datetime.fromisoformat(str(row[6])) if row[6] else None,
    )


COLUMNS = "id, device, created_at, latest, status, launched_on, closed_at"


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


def ask(
    database: sqlite3.Connection, device: str, latest: date | None, now: datetime
) -> UserRequest:
    """Demande pour ``device`` ; une demande déjà ouverte pour lui change seulement de date."""
    with database:
        row = database.execute(
            "SELECT id FROM requests WHERE device = ? AND status = 'open'", (device,)
        ).fetchone()
        if row:
            database.execute(
                "UPDATE requests SET latest = ? WHERE id = ?",
                (latest.isoformat() if latest else None, row[0]),
            )
            found = int(row[0])
        else:
            cursor = database.execute(
                "INSERT INTO requests (device, created_at, latest) VALUES (?, ?, ?)",
                (device, now.isoformat(), latest.isoformat() if latest else None),
            )
            found = int(cursor.lastrowid or 0)
    request = get(database, found)
    assert request is not None
    return request


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
        task = TaskRequest(
            name=appliance.name,
            uid=f"{UID_PREFIX}{request.id}",
            due=request.latest,
            on_demand=True,
            needed_since=min(request.created_at.date(), zone_today),
        )
        (due if request.latest is not None else waiting).append(task)
    return due, waiting


def mark_launched(
    database: sqlite3.Connection,
    candidates: Sequence[Appliance],
    launched: set[str],
    today: date,
) -> list[int]:
    """Note le lancement constaté aujourd'hui (clés de ``launched_keys``) des équipements
    demandés."""
    names = {a.key: task_key(a.name) for a in candidates}
    found = [
        r.id
        for r in open_requests(database)
        if r.launched_on is None and names.get(r.device) in launched
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
