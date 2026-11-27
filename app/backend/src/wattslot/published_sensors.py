"""Capteurs que WattSlot publie dans Home Assistant (expérimental, désactivé par défaut).

Premier lot : la prévision de consommation de la maison, pour qu'une autre intégration (pilotage
d'une batterie…) la lise au lieu d'estimer la sienne. Trois capteurs en kWh : le reste de la
journée, la journée entière et demain ; les mêmes nombres que les courbes des vues (consommation
habituelle plus équipements placés).

Les états sont écrits par l'API REST de HA (``POST /api/states/<entité>``), avec la connexion que
l'application a déjà : rien à installer chez l'utilisateur, dans les deux modes. HA réserve cet
appel à un administrateur. Un état écrit ainsi n'a ni identifiant unique ni appareil, et HA ne
le garde pas à son redémarrage : il est réécrit à chaque connexion, après chaque calcul et tous
les quarts d'heure (le reste de la journée diminue avec l'heure).

Sans ``state_class`` : une prévision n'est pas une mesure, HA n'en tire pas de statistiques à
long terme. Les entités ``sensor.wattslot_*`` ne sont jamais proposées comme capteurs de la
maison (``detection.sensor_choices``) : l'application ne relit pas ce qu'elle publie.

https://developers.home-assistant.io/docs/api/rest
"""

import asyncio
import contextlib
import json
import logging
import sqlite3
import urllib.error
import urllib.request
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from pydantic import BaseModel

from wattslot.runtime import HomeAssistantTarget

logger = logging.getLogger(__name__)

SETTINGS_KEY = "published_sensors"
# Préfixe de toutes les entités publiées : écartées des capteurs proposés pour la maison.
PREFIX = "sensor.wattslot_"
REMAINING_TODAY = f"{PREFIX}home_consumption_forecast_remaining_today"
TODAY = f"{PREFIX}home_consumption_forecast_today"
TOMORROW = f"{PREFIX}home_consumption_forecast_tomorrow"
CONSUMPTION_FORECAST = (REMAINING_TODAY, TODAY, TOMORROW)
# Noms fixes, en anglais : un état écrit par l'API n'est pas traduit par HA.
NAMES = {
    REMAINING_TODAY: "WattSlot home consumption forecast remaining today",
    TODAY: "WattSlot home consumption forecast today",
    TOMORROW: "WattSlot home consumption forecast tomorrow",
}
UNAVAILABLE = "unavailable"
PERIOD = timedelta(minutes=15)
AFTER_PERIOD_S = 5.0  # juste après le quart d'heure, pas dessus
TIMEOUT_S = 15

ErrorCode = Literal["refused", "unreachable", "unknown"]


class PublishedSensorsSettings(BaseModel):
    consumption_forecast: bool = False


class PublishedSensorsState(BaseModel):
    """Réponse de l'API : le réglage, les entités qu'il publie, et la dernière écriture."""

    consumption_forecast: bool
    entities: list[str]
    available: bool  # faux : pas de connexion à HA réglée
    published_at: datetime | None = None
    # ``refused`` : HA refuse l'écriture (compte non administrateur) ; ``unreachable`` : HA ne
    # répond pas ; ``unknown`` : autre réponse.
    error: ErrorCode | None = None


def load(database: sqlite3.Connection) -> PublishedSensorsSettings:
    row = database.execute(
        "SELECT value FROM app_settings WHERE key = ?", (SETTINGS_KEY,)
    ).fetchone()
    if not row:
        return PublishedSensorsSettings()
    return PublishedSensorsSettings.model_validate(json.loads(row[0]))


def save(database: sqlite3.Connection, settings: PublishedSensorsSettings) -> None:
    with database:
        database.execute(
            "INSERT INTO app_settings VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (SETTINGS_KEY, settings.model_dump_json()),
        )


def is_published(entity_id: str) -> bool:
    """Entité publiée par WattSlot : jamais un capteur de la maison."""
    return entity_id.startswith(PREFIX)


def rest_url(websocket_url: str) -> str:
    """Adresse de l'API REST de HA d'après celle du WebSocket : ``ws://hote:8123/api/websocket``
    → ``http://hote:8123/api`` ; par le Supervisor, ``ws://supervisor/core/websocket`` →
    ``http://supervisor/core/api``."""
    parts = urlsplit(websocket_url)
    scheme = "https" if parts.scheme == "wss" else "http"
    path = parts.path.removesuffix("/websocket")
    if not path.endswith("/api"):
        path += "/api"
    return urlunsplit((scheme, parts.netloc, path, "", ""))


@dataclass(frozen=True)
class Forecast:
    """Consommation prévue d'un jour, heure par heure (kWh), et l'heure de son calcul."""

    day: date
    hours: tuple[float, ...]
    computed_at: datetime | None = None


@dataclass(frozen=True)
class SensorState:
    state: str
    attributes: dict[str, Any]


def remaining_kwh(hours: tuple[float, ...], local: datetime) -> float:
    """De ``local`` à minuit : le reste de l'heure en cours, puis les heures suivantes."""
    left = sum(hours[local.hour + 1 :])
    if local.hour < len(hours):
        left += hours[local.hour] * (60 - local.minute) / 60
    return left


def _sensor(entity_id: str, kwh: float | None, forecast: Forecast | None) -> SensorState:
    attributes: dict[str, Any] = {
        "unit_of_measurement": "kWh",
        "device_class": "energy",
        "friendly_name": NAMES[entity_id],
        "icon": "mdi:home-lightning-bolt-outline",
    }
    if kwh is None or forecast is None:
        return SensorState(UNAVAILABLE, attributes)
    attributes["forecast_date"] = forecast.day.isoformat()
    if forecast.computed_at is not None:
        attributes["computed_at"] = forecast.computed_at.isoformat()
    return SensorState(f"{kwh:.2f}", attributes)


def consumption_states(
    today: Forecast | None, tomorrow: Forecast | None, local: datetime
) -> dict[str, SensorState]:
    """États des trois capteurs à l'heure locale ``local``. Un plan absent, ou gardé pour un
    autre jour (juste après minuit, avant le premier calcul), donne « indisponible » plutôt
    qu'une prévision du mauvais jour."""
    if today is not None and today.day != local.date():
        today = None
    if tomorrow is not None and tomorrow.day != local.date() + timedelta(days=1):
        tomorrow = None
    return {
        REMAINING_TODAY: _sensor(
            REMAINING_TODAY, remaining_kwh(today.hours, local) if today else None, today
        ),
        TODAY: _sensor(TODAY, sum(today.hours) if today else None, today),
        TOMORROW: _sensor(TOMORROW, sum(tomorrow.hours) if tomorrow else None, tomorrow),
    }


class Unreachable(Exception):
    """HA n'a pas répondu."""


# (méthode, adresse, jeton, corps) → code HTTP ; ``Unreachable`` sans réponse.
Send = Callable[[str, str, str, dict[str, Any] | None], Awaitable[int]]
Forecasts = Callable[[], Awaitable[tuple[Forecast | None, Forecast | None]]]


async def send_request(method: str, url: str, token: str, body: dict[str, Any] | None) -> int:
    def send() -> int:
        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
                return int(response.status)
        except urllib.error.HTTPError as exc:
            return int(exc.code)
        except OSError as exc:
            raise Unreachable(str(exc)) from exc

    return await asyncio.to_thread(send)


def _error_of(status: int) -> ErrorCode | None:
    if status in (200, 201):
        return None
    return "refused" if status in (401, 403) else "unknown"


class SensorPublisher:
    """Écrit les capteurs activés dans HA ; ne lève jamais : l'échec est gardé pour l'interface
    (``state``) et noté au journal, une fois par panne."""

    def __init__(
        self,
        target: HomeAssistantTarget,
        database: sqlite3.Connection,
        forecasts: Forecasts,
        zone: Callable[[], ZoneInfo],
        send: Send = send_request,
    ) -> None:
        self._target = target
        self._database = database
        self._forecasts = forecasts
        self._zone = zone
        self._send = send
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self.published_at: datetime | None = None
        self.error: ErrorCode | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _loop(self) -> None:
        while True:
            now = datetime.now(UTC)
            elapsed = timedelta(
                minutes=now.minute % 15, seconds=now.second, microseconds=now.microsecond
            )
            await asyncio.sleep((PERIOD - elapsed).total_seconds() + AFTER_PERIOD_S)
            await self.publish()

    async def _token(self) -> str:
        provider = self._target.token_provider
        return await provider() if provider is not None else self._target.token

    def _url(self, entity_id: str) -> str:
        return f"{rest_url(self._target.websocket_url)}/states/{entity_id}"

    def _note(self, error: ErrorCode | None, detail: str = "") -> None:
        if error is not None and error != self.error:
            logger.warning("Capteurs non publiés dans Home Assistant : %s %s", error, detail)
        self.error = error

    async def publish(self, now: datetime | None = None) -> None:
        """Écrit les capteurs activés ; sans effet si rien n'est activé."""
        if not load(self._database).consumption_forecast:
            return
        async with self._lock:
            try:
                today, tomorrow = await self._forecasts()
                local = (now or datetime.now(UTC)).astimezone(self._zone())
                token = await self._token()
                for entity_id, found in consumption_states(today, tomorrow, local).items():
                    body = {"state": found.state, "attributes": found.attributes}
                    status = await self._send("POST", self._url(entity_id), token, body)
                    if (error := _error_of(status)) is not None:
                        self._note(error, f"(HTTP {status})")
                        return
            except Unreachable as exc:
                self._note("unreachable", str(exc))
                return
            except Exception as exc:  # ne doit arrêter ni la boucle ni un calcul
                logger.exception("Capteurs non publiés dans Home Assistant")
                self._note("unknown", type(exc).__name__)
                return
            self._note(None)
            self.published_at = (now or datetime.now(UTC)).astimezone(UTC)

    async def remove(self) -> None:
        """Retire de HA les capteurs publiés (réglage désactivé) ; au mieux : HA les oublie de
        toute façon à son redémarrage."""
        async with self._lock:
            try:
                token = await self._token()
                for entity_id in CONSUMPTION_FORECAST:
                    await self._send("DELETE", self._url(entity_id), token, None)
            except Exception as exc:  # noqa: BLE001 — au mieux
                logger.warning("Capteurs non retirés de Home Assistant : %s", exc)
            self.published_at = None
            self.error = None


def state_of(
    database: sqlite3.Connection, publisher: SensorPublisher | None
) -> PublishedSensorsState:
    settings = load(database)
    return PublishedSensorsState(
        consumption_forecast=settings.consumption_forecast,
        entities=list(CONSUMPTION_FORECAST),
        available=publisher is not None,
        published_at=publisher.published_at if publisher else None,
        error=publisher.error if publisher else None,
    )


router = APIRouter()


@router.get("/api/settings/sensors")
def get_sensors(request: Request) -> PublishedSensorsState:
    """Capteurs publiés dans HA : réglage, entités, dernière écriture."""
    state = request.app.state
    return state_of(state.database, state.published_sensors)


@router.put("/api/settings/sensors")
async def put_sensors(
    request: Request, settings: PublishedSensorsSettings
) -> PublishedSensorsState:
    """Enregistre le réglage ; activé, les capteurs sont écrits tout de suite (la réponse dit si
    HA les a acceptés) ; désactivé, ils sont retirés de HA."""
    state = request.app.state
    publisher: SensorPublisher | None = state.published_sensors
    before = load(state.database)
    save(state.database, settings)
    if publisher is not None:
        if settings.consumption_forecast:
            await publisher.publish()
        elif before.consumption_forecast:
            await publisher.remove()
    return state_of(state.database, publisher)
