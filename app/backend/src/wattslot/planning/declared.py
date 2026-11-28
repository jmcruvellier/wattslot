"""Lancements déclarés par l'utilisateur (« C'est lancé » de « Prochaine action ») : l'appareil
n'est plus à lancer ce jour-là. « Prochaine action » passe à l'appareil suivant, sur tous les
navigateurs et après chaque nouveau calcul ; ni rappel ni notification « à lancer » ne partent
plus pour lui. Le plan n'en est pas changé : seul un cycle reconnu dans les mesures cale son
créneau. Une exception : déclaré pendant que l'appareil tourne déjà, un cycle qui n'est pas le
premier de la journée est une seconde charge lancée derrière la première ; l'activité mesurée
est coupée à la pause d'avant (``journal.real_cycles``), et le cycle est reconnu. Gardé en base
jusqu'au jour suivant (``declared_launches``) ; un retour en arrière rend l'appareil à
« Prochaine action » tant que son cycle n'est pas reconnu.

Une déclaration vaut pour une demande (``request`` : uid de la tâche du cycle déclaré, lu dans
le plan gardé) : quand elle est close, la déclaration ne vaut plus (``forget_request``,
``forget_closed``). Attachée au seul nom de l'appareil, celle d'un sèche-linge annulé valait
encore pour le sèche-linge redemandé ensuite, aussitôt dit « marqué comme lancé » (constaté le
21/11/2026).

Une demande faite n'efface pourtant pas l'instant déclaré : la ligne est seulement close
(``closed``). Effacée, la coupure des mesures disparaissait avec elle : deux séchages enchaînés,
bien séparés tant que leurs demandes étaient ouvertes, redevenaient une seule activité dès
« Fait », et le second était dit « pas lancé » (constaté le 28/11/2026). ``load`` ne rend que
les déclarations en vigueur, ``moments`` tous les instants de la journée. Une demande annulée
efface la sienne.
"""

import sqlite3
from collections.abc import Collection
from datetime import UTC, date, datetime

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from wattslot.planning.choices import request_of
from wattslot.planning.store import PlanStore


def load(database: sqlite3.Connection, day: date) -> set[str]:
    """Appareils déclarés lancés ce jour-là, dont la demande n'est pas close."""
    rows = database.execute(
        "SELECT device FROM declared_launches WHERE day = ? AND closed = 0", (day.isoformat(),)
    )
    return {str(row[0]) for row in rows}


def moments(database: sqlite3.Connection, day: date) -> dict[str, datetime]:
    """Instant de chaque lancement déclaré ce jour-là, par cycle, demandes closes comprises :
    le cycle a bien été lancé à cet instant."""
    rows = database.execute(
        "SELECT device, created_at FROM declared_launches WHERE day = ?", (day.isoformat(),)
    )
    return {str(device): datetime.fromisoformat(str(at)) for device, at in rows}


def declare(
    database: sqlite3.Connection,
    day: date,
    device: str,
    now: datetime,
    request: str | None = None,
) -> None:
    """Déclare ``device`` lancé le jour ``day``. ``request`` : uid de la demande de son cycle,
    si connu ; déjà déclaré, il garde son instant et prend cette demande. Sur une déclaration
    close (demande précédente faite), c'est un nouveau lancement : son instant est repris."""
    with database:
        database.execute("DELETE FROM declared_launches WHERE day < ?", (day.isoformat(),))
        database.execute(
            "INSERT INTO declared_launches (day, device, created_at, request) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(day, device) DO UPDATE SET request = excluded.request, "
            "created_at = CASE WHEN closed = 1 THEN excluded.created_at ELSE created_at END, "
            "closed = 0",
            (day.isoformat(), device, now.astimezone(UTC).isoformat(), request),
        )


def forget_request(database: sqlite3.Connection, request: str, keep_moment: bool = False) -> int:
    """La demande ``request`` est close : ses déclarations ne valent plus. ``keep_moment`` (demande
    faite) : l'instant déclaré reste pour la journée, il sépare les cycles dans les mesures ;
    sinon (demande annulée) la déclaration est effacée. Renvoie leur nombre."""
    with database:
        cursor = database.execute(
            "UPDATE declared_launches SET closed = 1 WHERE request = ? AND closed = 0"
            if keep_moment
            else "DELETE FROM declared_launches WHERE request = ?",
            (request,),
        )
    return cursor.rowcount


def forget_closed(database: sqlite3.Connection, day: date, open_requests: Collection[str]) -> int:
    """Clôt les déclarations de ``day`` dont la demande n'est plus ouverte (uid absent de
    ``open_requests``) ; celles sans demande connue restent. L'instant déclaré est gardé : le
    plus souvent, la demande est close parce que son cycle a tourné. Renvoie leur nombre."""
    rows = database.execute(
        "SELECT device, request FROM declared_launches "
        "WHERE day = ? AND request IS NOT NULL AND closed = 0",
        (day.isoformat(),),
    ).fetchall()
    closed = [str(device) for device, request in rows if str(request) not in open_requests]
    with database:
        database.executemany(
            "UPDATE declared_launches SET closed = 1 WHERE day = ? AND device = ?",
            [(day.isoformat(), device) for device in closed],
        )
    return len(closed)


def withdraw(database: sqlite3.Connection, day: date, device: str) -> bool:
    """Retour en arrière : l'appareil est de nouveau à lancer ; False s'il n'était pas déclaré
    (ou si sa demande est close)."""
    with database:
        cursor = database.execute(
            "DELETE FROM declared_launches WHERE day = ? AND device = ? AND closed = 0",
            (day.isoformat(), device),
        )
    return cursor.rowcount > 0


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
    database, today = request.app.state.database, _today(request)
    stored = PlanStore(database).load("today")
    planning = stored.content.get("planning", []) if stored and stored.day == today else []
    declare(database, today, body.device, datetime.now(UTC), request_of(planning, body.device))
    return body


@router.delete("/api/planning/launched/{device}", status_code=204)
def remove_declared(request: Request, device: str) -> Response:
    """Retour en arrière après un « C'est lancé » ; 404 si l'appareil n'était pas déclaré."""
    if not withdraw(request.app.state.database, _today(request), device):
        raise HTTPException(status_code=404, detail="not_declared")
    return Response(status_code=204)
