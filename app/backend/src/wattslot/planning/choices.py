"""Départs choisis par l'utilisateur (« Prochaine action », Planning) parmi les autres départs
que le plan propose : un par appareil et par jour, gardés en base et imposés au calcul de ce jour
(``PlanningInput.chosen_starts``). « Revenir au choix du calcul » l'efface. Un choix d'un autre
jour ne sert plus.
"""

import sqlite3
from datetime import UTC, date, datetime

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

DAY_MIN = 24 * 60


def load(database: sqlite3.Connection, day: date) -> dict[str, int]:
    """Départs choisis d'un jour : appareil → minutes depuis minuit."""
    rows = database.execute(
        "SELECT device, start_min FROM chosen_starts WHERE day = ?", (day.isoformat(),)
    )
    return {str(device): int(start) for device, start in rows}


def choose(
    database: sqlite3.Connection, day: date, device: str, start_min: int, now: datetime
) -> None:
    with database:
        database.execute("DELETE FROM chosen_starts WHERE day < ?", (day.isoformat(),))
        database.execute(
            "INSERT INTO chosen_starts VALUES (?, ?, ?, ?) ON CONFLICT(day, device) "
            "DO UPDATE SET start_min = excluded.start_min, created_at = excluded.created_at",
            (day.isoformat(), device, start_min, now.astimezone(UTC).isoformat()),
        )


def clear(database: sqlite3.Connection, day: date, device: str) -> bool:
    """Oublie le départ choisi ; False s'il n'y en avait pas."""
    with database:
        cursor = database.execute(
            "DELETE FROM chosen_starts WHERE day = ? AND device = ?", (day.isoformat(), device)
        )
    return cursor.rowcount > 0


# --- Routes ------------------------------------------------------------------------------------

router = APIRouter()


class Choice(BaseModel):
    device: str  # nom de l'appareil dans le plan du jour
    start_min: int = Field(ge=0, lt=DAY_MIN)


def _today(request: Request) -> date:
    return datetime.now(UTC).astimezone(request.app.state.raw.zone).date()


@router.get("/api/planning/choices")
def list_choices(request: Request) -> list[Choice]:
    """Départs choisis aujourd'hui."""
    found = load(request.app.state.database, _today(request))
    return [Choice(device=device, start_min=start) for device, start in sorted(found.items())]


@router.post("/api/planning/choices", status_code=201)
def add_choice(request: Request, body: Choice) -> Choice:
    """Impose un départ à un appareil pour aujourd'hui ; le calcul suivant le prend en compte
    (la page relance le calcul aussitôt)."""
    choose(
        request.app.state.database, _today(request), body.device, body.start_min, datetime.now(UTC)
    )
    return body


@router.delete("/api/planning/choices/{device}", status_code=204)
def remove_choice(request: Request, device: str) -> Response:
    """Rend le départ de l'appareil au calcul ; 404 s'il n'y avait pas de choix."""
    if not clear(request.app.state.database, _today(request), device):
        raise HTTPException(status_code=404, detail="no_choice")
    return Response(status_code=204)
