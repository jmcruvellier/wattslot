"""Planification annulée par l'utilisateur pour le jour (« Annuler » de la frise et de
« Prochaine action ») : l'équipement n'est plus placé par les calculs de ce jour, ni sa tâche,
ni son besoin d'énergie, ni sa durée à placer ; un cycle déjà lancé reste, car les mesures
réelles ne s'effacent pas. Gardé en base jusqu'au jour suivant (``cancelled_tasks``) ;
« Rétablir » le rend au calcul. L'annulation d'un autre jour ne sert plus.

Une annulation vaut pour une demande (``request`` : uid de la tâche du cycle annulé, lu dans le
plan gardé) : quand elle est close, l'annulation est oubliée (``forget_request``,
``forget_closed``). Attachée au seul nom de l'appareil, elle écartait aussi du calcul la demande
suivante du même appareil, faite le même jour.
"""

import sqlite3
from collections.abc import Collection, Iterable
from dataclasses import replace
from datetime import UTC, date, datetime

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from wattslot.planning.choices import request_of
from wattslot.planning.inputs import PlanningInput
from wattslot.planning.store import PlanStore


def load(database: sqlite3.Connection, day: date) -> set[str]:
    """Équipements dont la planification du jour est annulée."""
    rows = database.execute("SELECT device FROM cancelled_tasks WHERE day = ?", (day.isoformat(),))
    return {str(row[0]) for row in rows}


def cancel(
    database: sqlite3.Connection,
    day: date,
    device: str,
    now: datetime,
    request: str | None = None,
) -> None:
    """Annule la planification de ``device`` le jour ``day``. ``request`` : uid de la demande de
    son cycle, si connu ; déjà annulé, il garde sa demande (son bloc a quitté le plan)."""
    with database:
        database.execute("DELETE FROM cancelled_tasks WHERE day < ?", (day.isoformat(),))
        database.execute(
            "INSERT INTO cancelled_tasks (day, device, created_at, request) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(day, device) DO NOTHING",
            (day.isoformat(), device, now.astimezone(UTC).isoformat(), request),
        )


def forget_request(database: sqlite3.Connection, request: str) -> int:
    """Oublie les annulations de la demande ``request`` (close : faite ou annulée)."""
    with database:
        cursor = database.execute("DELETE FROM cancelled_tasks WHERE request = ?", (request,))
    return cursor.rowcount


def forget_closed(database: sqlite3.Connection, day: date, open_requests: Collection[str]) -> int:
    """Oublie les annulations de ``day`` dont la demande n'est plus ouverte (uid absent de
    ``open_requests``) ; celles sans demande connue restent. Renvoie leur nombre."""
    rows = database.execute(
        "SELECT device, request FROM cancelled_tasks WHERE day = ? AND request IS NOT NULL",
        (day.isoformat(),),
    ).fetchall()
    closed = [str(device) for device, request in rows if str(request) not in open_requests]
    with database:
        database.executemany(
            "DELETE FROM cancelled_tasks WHERE day = ? AND device = ?",
            [(day.isoformat(), device) for device in closed],
        )
    return len(closed)


def restore(database: sqlite3.Connection, day: date, device: str) -> bool:
    """Rend l'équipement au calcul ; False s'il n'était pas annulé."""
    with database:
        cursor = database.execute(
            "DELETE FROM cancelled_tasks WHERE day = ? AND device = ?", (day.isoformat(), device)
        )
    return cursor.rowcount > 0


def without_cancelled(data: PlanningInput, names: Iterable[str]) -> PlanningInput:
    """Entrée du calcul sans les planifications annulées du jour : la tâche reste dans la liste
    de Home Assistant, le calcul de demain la replacera. Un cycle est désigné par son identité
    (``TaskRequest.ident`` : l'équipement, et son rang à partir de son deuxième cycle du jour) :
    annuler le second cycle laisse le premier."""
    cancelled = set(names)
    if not cancelled:
        return data
    return replace(
        data,
        due_tasks=tuple(t for t in data.due_tasks if t.ident not in cancelled),
        waiting_tasks=tuple(t for t in data.waiting_tasks if t.ident not in cancelled),
        needs=tuple(n for n in data.needs if n.name not in cancelled),
        runtimes=tuple(r for r in data.runtimes if r.name not in cancelled),
    )


# --- Routes ------------------------------------------------------------------------------------

router = APIRouter()


class Cancelled(BaseModel):
    device: str  # nom de l'appareil dans le plan du jour


def _today(request: Request) -> date:
    return datetime.now(UTC).astimezone(request.app.state.raw.zone).date()


@router.get("/api/planning/cancelled")
def list_cancelled(request: Request) -> list[Cancelled]:
    """Planifications annulées aujourd'hui."""
    return [
        Cancelled(device=device)
        for device in sorted(load(request.app.state.database, _today(request)))
    ]


@router.post("/api/planning/cancelled", status_code=201)
def add_cancelled(request: Request, body: Cancelled) -> Cancelled:
    """Annule la planification d'un appareil pour aujourd'hui ; le calcul suivant ne le place
    plus (la page relance le calcul aussitôt)."""
    database, today = request.app.state.database, _today(request)
    stored = PlanStore(database).load("today")
    planning = stored.content.get("planning", []) if stored and stored.day == today else []
    cancel(database, today, body.device, datetime.now(UTC), request_of(planning, body.device))
    return body


@router.delete("/api/planning/cancelled/{device}", status_code=204)
def remove_cancelled(request: Request, device: str) -> Response:
    """Rend l'appareil au calcul ; 404 s'il n'était pas annulé."""
    if not restore(request.app.state.database, _today(request), device):
        raise HTTPException(status_code=404, detail="not_cancelled")
    return Response(status_code=204)
