"""Planification annulée par l'utilisateur pour le jour (« Annuler » de la frise et de
« Prochaine action ») : l'équipement n'est plus placé par les calculs de ce jour, ni sa tâche,
ni son besoin d'énergie, ni sa durée à placer ; un cycle déjà lancé reste, car les mesures
réelles ne s'effacent pas. Gardé en base jusqu'au jour suivant (``cancelled_tasks``) ;
« Rétablir » le rend au calcul. L'annulation d'un autre jour ne sert plus.
"""

import sqlite3
from collections.abc import Iterable
from dataclasses import replace
from datetime import UTC, date, datetime

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from wattslot.planning.inputs import PlanningInput


def load(database: sqlite3.Connection, day: date) -> set[str]:
    """Équipements dont la planification du jour est annulée."""
    rows = database.execute("SELECT device FROM cancelled_tasks WHERE day = ?", (day.isoformat(),))
    return {str(row[0]) for row in rows}


def cancel(database: sqlite3.Connection, day: date, device: str, now: datetime) -> None:
    with database:
        database.execute("DELETE FROM cancelled_tasks WHERE day < ?", (day.isoformat(),))
        database.execute(
            "INSERT INTO cancelled_tasks VALUES (?, ?, ?) ON CONFLICT(day, device) DO NOTHING",
            (day.isoformat(), device, now.astimezone(UTC).isoformat()),
        )


def restore(database: sqlite3.Connection, day: date, device: str) -> bool:
    """Rend l'équipement au calcul ; False s'il n'était pas annulé."""
    with database:
        cursor = database.execute(
            "DELETE FROM cancelled_tasks WHERE day = ? AND device = ?", (day.isoformat(), device)
        )
    return cursor.rowcount > 0


def without_cancelled(data: PlanningInput, names: Iterable[str]) -> PlanningInput:
    """Entrée du calcul sans les équipements annulés du jour : la tâche reste dans la liste de
    Home Assistant, le calcul de demain la replacera."""
    cancelled = set(names)
    if not cancelled:
        return data
    return replace(
        data,
        due_tasks=tuple(t for t in data.due_tasks if t.name not in cancelled),
        waiting_tasks=tuple(t for t in data.waiting_tasks if t.name not in cancelled),
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
    cancel(request.app.state.database, _today(request), body.device, datetime.now(UTC))
    return body


@router.delete("/api/planning/cancelled/{device}", status_code=204)
def remove_cancelled(request: Request, device: str) -> Response:
    """Rend l'appareil au calcul ; 404 s'il n'était pas annulé."""
    if not restore(request.app.state.database, _today(request), device):
        raise HTTPException(status_code=404, detail="not_cancelled")
    return Response(status_code=204)
