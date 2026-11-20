"""Départs choisis par l'utilisateur (« Prochaine action », Planning) parmi les autres départs
que le plan propose, ou à une heure de son choix : un par appareil et par jour, gardés en base et
imposés au calcul de ce jour (``PlanningInput.chosen_starts``). Aujourd'hui, demain ou un jour de
l'horizon (jusqu'à J+6) : le calcul de demain et celui de l'horizon les prennent aussi. « Revenir
au choix du calcul » l'efface. Un choix d'un jour passé ne sert plus.

Un choix vaut pour une demande (``request`` : uid de la tâche du bloc choisi, lu dans le plan
gardé) : quand elle est close, il est oublié (``forget_closed``). Attaché au seul nom de
l'appareil, le départ choisi d'une lessive déjà faite valait encore pour la lessive demandée
ensuite, dont le calcul ne gelait plus le premier bloc (constaté le 20/11/2026).
"""

import sqlite3
from collections.abc import Collection, Iterable, Mapping
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from wattslot.planning.reference import ident
from wattslot.planning.store import PlanStore

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
    request: str | None = None,
) -> None:
    """Impose ``start_min`` à ``device`` le jour ``day`` ; les choix d'avant ``today`` (par
    défaut ``day``) sont oubliés. ``request`` : uid de la demande du bloc choisi, si connu."""
    with database:
        database.execute("DELETE FROM chosen_starts WHERE day < ?", ((today or day).isoformat(),))
        database.execute(
            "INSERT INTO chosen_starts (day, device, start_min, created_at, request) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(day, device) DO UPDATE SET "
            "start_min = excluded.start_min, created_at = excluded.created_at, "
            "request = excluded.request",
            (day.isoformat(), device, start_min, now.astimezone(UTC).isoformat(), request),
        )


def forget_closed(database: sqlite3.Connection, day: date, open_requests: Collection[str]) -> int:
    """Oublie les choix de ``day`` dont la demande n'est plus ouverte (uid absent de
    ``open_requests``) ; les choix sans demande connue restent. Renvoie leur nombre."""
    rows = database.execute(
        "SELECT device, request FROM chosen_starts WHERE day = ? AND request IS NOT NULL",
        (day.isoformat(),),
    ).fetchall()
    closed = [str(device) for device, request in rows if str(request) not in open_requests]
    with database:
        database.executemany(
            "DELETE FROM chosen_starts WHERE day = ? AND device = ?",
            [(day.isoformat(), device) for device in closed],
        )
    return len(closed)


def request_of(planning: Iterable[Mapping[str, object]], device: str) -> str | None:
    """Uid de la demande du bloc ``device`` (identité du cycle) dans un plan gardé."""
    for item in planning:
        name, rank = item.get("equipement"), item.get("rang")
        if isinstance(name, str) and ident(name, rank if isinstance(rank, int) else None) == device:
            found = item.get("demande")
            return found if isinstance(found, str) else None
    return None


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
    today = _today(request)
    # Plan gardé du jour choisi (aujourd'hui, demain) : la demande du bloc ; au-delà, inconnue.
    kind = "today" if day == today else "tomorrow" if day == today + timedelta(days=1) else None
    stored = PlanStore(request.app.state.database).load(kind) if kind else None
    planning = stored.content.get("planning", []) if stored and stored.day == day else []
    choose(
        request.app.state.database,
        day,
        body.device,
        body.start_min,
        datetime.now(UTC),
        today=today,
        request=request_of(planning, body.device),
    )
    return body


@router.delete("/api/planning/choices/{device}", status_code=204)
def remove_choice(request: Request, device: str, day: date | None = None) -> Response:
    """Rend le départ de l'appareil au calcul ; 404 s'il n'y avait pas de choix."""
    if not clear(request.app.state.database, _day(request, day), device):
        raise HTTPException(status_code=404, detail="no_choice")
    return Response(status_code=204)
