"""Rappels « Me le rappeler » (lot 6b.3, point n° 8 de la phase 6 bis).

Depuis l'écran Aujourd'hui, l'utilisateur demande un rappel pour le prochain appareil à lancer.
Le rappel est gardé par appareil et par jour (migration 10), sans heure : il part à l'heure de
début que le plan du moment donne à l'appareil, et suit donc un plan qui le déplace. Il est
envoyé une fois, par le service de la notification « appareil à lancer » (lot 5.6), même si
celle-ci est désactivée ; un appareil déjà lancé ferme son rappel sans l'envoyer. Une boucle
d'une minute s'en charge, tant que Home Assistant est connecté.
"""

import asyncio
import contextlib
import logging
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from wattslot import notification_events as events
from wattslot import notifications
from wattslot.home_assistant import ConnectionState, HomeAssistantClient
from wattslot.languages import Language, number
from wattslot.planning.store import PlanStore
from wattslot.views.day import build_day
from wattslot.views.display import Context

logger = logging.getLogger(__name__)

INTERVAL_S = 60


def ask(database: sqlite3.Connection, device: str, day: date, now: datetime) -> None:
    """Pose (ou repose) le rappel d'un appareil pour ce jour."""
    with database:
        database.execute(
            "INSERT INTO reminders (device, day, created_at, sent_at) VALUES (?, ?, ?, NULL) "
            "ON CONFLICT(device, day) DO UPDATE SET created_at = excluded.created_at, "
            "sent_at = NULL",
            (device, day.isoformat(), now.isoformat()),
        )


def cancel(database: sqlite3.Connection, device: str, day: date) -> bool:
    with database:
        cursor = database.execute(
            "DELETE FROM reminders WHERE device = ? AND day = ? AND sent_at IS NULL",
            (device, day.isoformat()),
        )
    return cursor.rowcount > 0


def pending(database: sqlite3.Connection, day: date) -> set[str]:
    rows = database.execute(
        "SELECT device FROM reminders WHERE day = ? AND sent_at IS NULL", (day.isoformat(),)
    )
    return {row[0] for row in rows}


def _close(database: sqlite3.Connection, device: str, day: date, now: datetime) -> None:
    with database:
        database.execute(
            "UPDATE reminders SET sent_at = ? WHERE device = ? AND day = ?",
            (now.isoformat(), device, day.isoformat()),
        )


@dataclass(frozen=True)
class Due:
    device: str
    start_min: int
    message: str


def due(
    plan: Mapping[str, Any], waiting: set[str], local: datetime, zone: ZoneInfo, lang: Language
) -> tuple[list[Due], list[str]]:
    """Rappels à envoyer maintenant, et appareils déjà lancés (rappels à fermer sans envoi)."""
    view = build_day(plan, "today", Context(zone=zone), lang)
    now_min = local.hour * 60 + local.minute
    to_send: list[Due] = []
    launched: list[str] = []
    for status in view.timeline.statuses:
        if status.device not in waiting:
            continue
        if status.status in ("on_time", "shifted"):
            launched.append(status.device)
        elif status.status == "planned" and now_min >= status.planned_start_min:
            message = events.text(
                lang,
                "device_now",
                device=status.device,
                time=events.clock(status.planned_start_min, lang),
                kwh=number(status.planned_kwh, lang, 1),
            )
            to_send.append(Due(status.device, status.planned_start_min, message))
    return to_send, launched


async def send_due(
    client: HomeAssistantClient, database: sqlite3.Connection, now: datetime, zone: ZoneInfo
) -> list[str]:
    """Envoie les rappels arrivés à leur heure ; renvoie les appareils rappelés."""
    local = now.astimezone(zone)
    waiting = pending(database, local.date())
    if not waiting:
        return []
    plan = PlanStore(database).load("today")
    if plan is None or plan.day != local.date():
        return []
    settings = notifications.load(database)
    service = settings.service_of("device_now")
    if service is None:
        return []  # rappel gardé : il partira si un service est choisi avant l'heure
    to_send, launched = await asyncio.to_thread(
        due, plan.content, waiting, local, zone, settings.language
    )
    for device in launched:
        _close(database, device, local.date(), now)
    sent: list[str] = []
    for found in to_send:
        await notifications.send(client, service, "device_now", found.message, settings.language)
        _close(database, found.device, local.date(), now)
        # Noté aussi comme la notification « appareil à lancer » : elle ne repart pas en double.
        notifications.record(
            database,
            "device_now",
            f"{found.device}@{found.start_min}",
            now,
            str(plan.content.get("date_cible")),
            found.message,
        )
        sent.append(found.device)
    return sent


class ReminderLoop:
    """Toutes les minutes, les rappels arrivés à leur heure, si HA est connecté."""

    def __init__(
        self, client: HomeAssistantClient, database: sqlite3.Connection, zone: ZoneInfo
    ) -> None:
        self._client = client
        self._database = database
        self._zone = zone
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _loop(self) -> None:
        while True:
            if self._client.status.state is ConnectionState.CONNECTED:
                try:
                    await send_due(self._client, self._database, datetime.now(UTC), self._zone)
                except Exception:  # nouvel essai à la minute suivante
                    logger.exception("Rappel impossible")
            await asyncio.sleep(INTERVAL_S)


# --- Routes -----------------------------------------------------------------------------------

router = APIRouter()


class ReminderRequest(BaseModel):
    device: str  # nom de l'appareil dans le plan du jour (prochaine action)


class Reminder(BaseModel):
    device: str
    day: date


def _today_plan(request: Request) -> tuple[Any, datetime]:
    state = request.app.state
    now = datetime.now(UTC)
    plan = PlanStore(state.database).load("today")
    if plan is None or plan.day != now.astimezone(state.raw.zone).date():
        raise HTTPException(status_code=404, detail="no_plan")
    return plan, now


@router.post("/api/reminders", status_code=201)
def ask_reminder(request: Request, body: ReminderRequest) -> Reminder:
    """Rappel du jour pour un appareil à cycle encore à lancer d'après le plan du jour ; 404
    sans plan du jour, 422 « not_planned » pour un appareil qui n'est pas à venir."""
    plan, now = _today_plan(request)
    zone = request.app.state.raw.zone
    view = build_day(plan.content, "today", Context(zone=zone), "fr")
    cycles = {row.device for row in view.timeline.rows if row.kind == "cycle"}
    upcoming = {
        status.device
        for status in view.timeline.statuses
        if status.device in cycles and status.status == "planned"
    }
    if body.device not in upcoming:
        raise HTTPException(status_code=422, detail="not_planned")
    ask(request.app.state.database, body.device, plan.day, now)
    return Reminder(device=body.device, day=plan.day)


@router.delete("/api/reminders/{device}", status_code=204)
def cancel_reminder(request: Request, device: str) -> None:
    """Retire le rappel du jour d'un appareil ; 404 s'il n'y en a pas (ou s'il est parti)."""
    plan, _ = _today_plan(request)
    if not cancel(request.app.state.database, device, plan.day):
        raise HTTPException(status_code=404, detail="no_reminder")
