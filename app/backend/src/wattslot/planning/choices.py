"""Départs choisis par l'utilisateur (« Prochaine action », Planning) parmi les autres départs
que le plan propose, ou à une heure de son choix : un par appareil et par jour, gardés en base et
imposés au calcul de ce jour (``PlanningInput.chosen_starts``). Aujourd'hui, demain ou un jour de
l'horizon (jusqu'à J+6) : le calcul de demain et celui de l'horizon les prennent aussi. « Revenir
au choix du calcul » l'efface. Un choix d'un jour passé ne sert plus.
"""

import sqlite3
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

DAY_MIN = 24 * 60
LAST_DAY = 6  # J+6, dernier jour de l'horizon


def load(database: sqlite3.Connection, day: date) -> dict[str, int]:
    """Départs choisis d'un jour : appareil → minutes depuis minuit."""
    rows = database.execute(
        "SELECT device, start_min FROM chosen_starts WHERE day = ?", (day.isoformat(),)
    )
    return {str(device): int(start) for device, start in rows}


def load_days(database: sqlite3.Connection, days: Iterable[date]) -> dict[date, dict[str, int]]:
    """Départs choisis de plusieurs jours (horizon) ; jours sans choix absents."""
    found = {day: load(database, day) for day in days}
    return {day: chosen for day, chosen in found.items() if chosen}


def choose(
    database: sqlite3.Connection,
    day: date,
    device: str,
    start_min: int,
    now: datetime,
    today: date | None = None,
) -> None:
    """Impose ``start_min`` à ``device`` le jour ``day`` ; les choix d'avant ``today`` (par
    défaut ``day``) sont oubliés."""
    with database:
        database.execute("DELETE FROM chosen_starts WHERE day < ?", ((today or day).isoformat(),))
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
    day: date | None = None  # aucun : aujourd'hui


def _today(request: Request) -> date:
    return datetime.now(UTC).astimezone(request.app.state.raw.zone).date()


def _day(request: Request, day: date | None) -> date:
    """Jour d'un choix, d'aujourd'hui à J+6 ; 422 en dehors."""
    today = _today(request)
    if day is None:
        return today
    if not today <= day <= today + timedelta(days=LAST_DAY):
        raise HTTPException(status_code=422, detail="day_out_of_horizon")
    return day


@router.get("/api/planning/choices")
def list_choices(request: Request, day: date | None = None) -> list[Choice]:
    """Départs choisis d'un jour (par défaut aujourd'hui)."""
    found = load(request.app.state.database, _day(request, day))
    return [
        Choice(device=device, start_min=start, day=day) for device, start in sorted(found.items())
    ]


@router.post("/api/planning/choices", status_code=201)
def add_choice(request: Request, body: Choice) -> Choice:
    """Impose un départ à un appareil pour un jour d'aujourd'hui à J+6 ; le calcul suivant le
    prend en compte (la page relance le calcul aussitôt)."""
    day = _day(request, body.day)
    choose(
        request.app.state.database,
        day,
        body.device,
        body.start_min,
        datetime.now(UTC),
        today=_today(request),
    )
    return body


@router.delete("/api/planning/choices/{device}", status_code=204)
def remove_choice(request: Request, device: str, day: date | None = None) -> Response:
    """Rend le départ de l'appareil au calcul ; 404 s'il n'y avait pas de choix."""
    if not clear(request.app.state.database, _day(request, day), device):
        raise HTTPException(status_code=404, detail="no_choice")
    return Response(status_code=204)
