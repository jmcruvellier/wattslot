"""Lancements déclarés par l'utilisateur (« C'est lancé » de « Prochaine action ») : l'appareil
n'est plus à lancer ce jour-là. « Prochaine action » passe à l'appareil suivant, sur tous les
navigateurs et après chaque nouveau calcul ; ni rappel ni notification « à lancer » ne partent
plus pour lui. Le plan n'en est pas changé : seul un cycle reconnu dans les mesures cale son
créneau. Gardé en base jusqu'au jour suivant (``declared_launches``).
"""

import sqlite3
from datetime import UTC, date, datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel


def load(database: sqlite3.Connection, day: date) -> set[str]:
    """Appareils déclarés lancés ce jour-là."""
    rows = database.execute(
        "SELECT device FROM declared_launches WHERE day = ?", (day.isoformat(),)
    )
    return {str(row[0]) for row in rows}


def declare(database: sqlite3.Connection, day: date, device: str, now: datetime) -> None:
    with database:
        database.execute("DELETE FROM declared_launches WHERE day < ?", (day.isoformat(),))
        database.execute(
            "INSERT INTO declared_launches VALUES (?, ?, ?) ON CONFLICT(day, device) DO NOTHING",
            (day.isoformat(), device, now.astimezone(UTC).isoformat()),
        )


# --- Routes ------------------------------------------------------------------------------------

router = APIRouter()


class Declared(BaseModel):
    device: str  # nom de l'appareil dans le plan du jour


def _today(request: Request) -> date:
    return datetime.now(UTC).astimezone(request.app.state.raw.zone).date()


@router.get("/api/planning/launched")
def list_declared(request: Request) -> list[Declared]:
    """Appareils déclarés lancés aujourd'hui."""
    return [
        Declared(device=device)
        for device in sorted(load(request.app.state.database, _today(request)))
    ]


@router.post("/api/planning/launched", status_code=201)
def add_declared(request: Request, body: Declared) -> Declared:
    """« C'est lancé » : l'appareil n'est plus proposé aujourd'hui par « Prochaine action »."""
    declare(request.app.state.database, _today(request), body.device, datetime.now(UTC))
    return body
