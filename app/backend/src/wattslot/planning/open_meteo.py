"""Prévision solaire Open-Meteo calculée par l'application (lot 4.4,
point n° 4), à défaut de celle du tableau Énergie de HA et des entités de repli.

Même méthode que la bibliothèque ``open-meteo-solar-forecast`` (MIT, celle de l'intégration HA
« Open-Meteo Solar Forecast »), sans ses dépendances : Open-Meteo calcule l'irradiance sur le plan
des panneaux (``global_tilted_irradiance``, au quart d'heure) d'après leur inclinaison et leur
orientation ; la puissance en découle par

    P = kWc * GTI / 1000 * (1 - 0,004 * (T_cellule - 25)) * rendement,
    T_cellule = T_air + 0,0342 * GTI (modèle de Ross, panneaux « pas très bien ventilés »),

sommée sur les champs et plafonnée à la puissance de l'onduleur. Sans atténuation du matin et du
soir, ni horizon, ni neige.

Une requête par champ, gardée une heure en base (un redémarrage ne relance pas les appels) ; en
cas d'échec, la dernière réponse de moins d'un jour sert encore. La position de HA est arrondie au
centième de degré (environ 1 km) : rien d'autre ne sort de la maison. Les 7 jours passés servent à
comparer la prévision à la production mesurée.
"""

import asyncio
import hashlib
import json
import sqlite3
import urllib.parse
import urllib.request
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from wattslot import __version__
from wattslot.configuration import Behavior, Configuration
from wattslot.detection import Role
from wattslot.home_assistant import HomeAssistantClient
from wattslot.home_model import HomeModel
from wattslot.planning import past
from wattslot.planning.past import AggregateReader
from wattslot.solar_panels import PanelArray, SolarPanels

URL = "https://api.open-meteo.com/v1/forecast"
PAST_DAYS = 7
FORECAST_DAYS = 8  # aujourd'hui et l'horizon de 7 jours
CACHE_SECONDS = 3600
STALE_SECONDS = 86400
CACHE_PREFIX = "open_meteo:"

ALPHA_TEMP = -0.004  # par °C
G_STC = 1000.0  # W/m²
TEMP_STC_CELL = 25.0  # °C
ROSS = 0.0342  # « not so well cooled »

Fetch = Callable[[str], Awaitable[dict[str, Any]]]


class OpenMeteoUnavailable(Exception):
    """Ni réponse d'Open-Meteo ni réponse récente en cache."""


def power_w(gti: float, temperature: float, kwp: float, efficiency: float) -> float:
    """Puissance (W) d'un champ pour une irradiance sur son plan (W/m²) et une température de
    l'air (°C)."""
    cell = temperature + gti * ROSS
    power = kwp * 1000 * gti / G_STC * (1 + ALPHA_TEMP * (cell - TEMP_STC_CELL)) * efficiency
    return max(0.0, power)


def query(latitude: float, longitude: float, array: PanelArray) -> str:
    """URL de la requête d'un champ ; azimut d'Open-Meteo : 0 sud, -90 est, 90 ouest."""
    params = {
        "latitude": f"{latitude:.2f}",
        "longitude": f"{longitude:.2f}",
        "tilt": f"{array.tilt:g}",
        "azimuth": f"{array.azimuth - 180:g}",
        "minutely_15": "temperature_2m,global_tilted_irradiance",
        "past_days": str(PAST_DAYS),
        "forecast_days": str(FORECAST_DAYS),
        "timezone": "UTC",
        "timeformat": "unixtime",
    }
    return f"{URL}?{urllib.parse.urlencode(params)}"


async def fetch(url: str) -> dict[str, Any]:
    def get() -> dict[str, Any]:
        request = urllib.request.Request(url, headers={"User-Agent": f"wattslot/{__version__}"})
        with urllib.request.urlopen(request, timeout=20) as response:
            found: dict[str, Any] = json.loads(response.read())
            return found

    return await asyncio.to_thread(get)


def quarter_hours(
    responses: list[tuple[PanelArray, dict[str, Any]]], panels: SolarPanels
) -> dict[datetime, float]:
    """Puissance (W) de l'installation par quart d'heure, indexée par le début du quart d'heure
    (UTC) : Open-Meteo donne l'irradiance moyenne du quart d'heure qui précède l'instant."""
    watts: dict[datetime, float] = defaultdict(float)
    for array, data in responses:
        block = data.get("minutely_15") or {}
        times = block.get("time") or []
        gti = block.get("global_tilted_irradiance") or []
        temperature = block.get("temperature_2m") or []
        for moment, g, t in zip(times, gti, temperature, strict=False):
            if g is None or t is None:
                continue
            start = datetime.fromtimestamp(moment, UTC) - timedelta(minutes=15)
            watts[start] += power_w(g, t, array.kwp, panels.efficiency)
    if panels.inverter_kw is not None:
        ceiling = panels.inverter_kw * 1000
        return {moment: min(w, ceiling) for moment, w in watts.items()}
    return dict(watts)


def hourly_kwh(quarters: dict[datetime, float], day: date, zone: ZoneInfo) -> dict[int, float]:
    """kWh par heure locale de ``day``."""
    hourly: dict[int, float] = defaultdict(float)
    for moment, watts in quarters.items():
        local = moment.astimezone(zone)
        if local.date() == day:
            hourly[local.hour] += watts * 0.25 / 1000
    return dict(hourly)


class OpenMeteo:
    """Prévision des installations solaires décrites, à une position donnée."""

    def __init__(
        self,
        database: sqlite3.Connection,
        installations: list[SolarPanels],
        latitude: float,
        longitude: float,
        get: Fetch = fetch,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._database = database
        self._installations = installations
        self._latitude = latitude
        self._longitude = longitude
        self._get = get
        self._now = now
        self._quarters: dict[datetime, float] | None = None

    async def _response(self, url: str) -> dict[str, Any]:
        key = CACHE_PREFIX + hashlib.sha256(url.encode()).hexdigest()[:16]
        row = self._database.execute(
            "SELECT value FROM app_settings WHERE key = ?", (key,)
        ).fetchone()
        cached = json.loads(row[0]) if row else None
        age = (
            (self._now() - datetime.fromisoformat(cached["fetched_at"])).total_seconds()
            if cached
            else None
        )
        if cached and age is not None and age < CACHE_SECONDS:
            return dict(cached["data"])
        try:
            data = await self._get(url)
        except Exception as exc:
            if cached and age is not None and age < STALE_SECONDS:
                return dict(cached["data"])
            raise OpenMeteoUnavailable(str(exc)) from exc
        with self._database:
            self._database.execute(
                "INSERT INTO app_settings VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps({"fetched_at": self._now().isoformat(), "data": data})),
            )
        return data

    async def quarters(self) -> dict[datetime, float]:
        """Puissance (W) de toutes les installations par quart d'heure, des 7 jours passés aux
        7 jours à venir."""
        if self._quarters is None:
            total: dict[datetime, float] = defaultdict(float)
            for panels in self._installations:
                responses = [
                    (array, await self._response(query(self._latitude, self._longitude, array)))
                    for array in panels.arrays
                ]
                for moment, watts in quarter_hours(responses, panels).items():
                    total[moment] += watts
            self._quarters = dict(total)
        return self._quarters

    async def hourly(self, day: date, zone: ZoneInfo) -> dict[int, float]:
        return hourly_kwh(await self.quarters(), day, zone)


def installations(configuration: Configuration | None) -> list[SolarPanels]:
    """Panneaux décrits sur les installations solaires de la configuration."""
    if configuration is None:
        return []
    return [
        d.panels
        for d in configuration.devices
        if d.panels is not None and d.behavior is Behavior.PRODUCTION and d.planned
    ]


def position(client: HomeAssistantClient | None) -> tuple[float, float] | None:
    config = (getattr(getattr(client, "snapshot", None), "config", None) or {}) if client else {}
    latitude, longitude = config.get("latitude"), config.get("longitude")
    if isinstance(latitude, int | float) and isinstance(longitude, int | float):
        return float(latitude), float(longitude)
    return None


def fallback_for(
    database: sqlite3.Connection,
    configuration: Configuration | None,
    client: HomeAssistantClient | None,
    get: Fetch | None = None,
) -> OpenMeteo | None:
    """Prévision Open-Meteo de la maison ; ``None`` sans panneaux décrits ou sans position."""
    found = installations(configuration)
    where = position(client)
    if not found or where is None:
        return None
    return OpenMeteo(database, found, where[0], where[1], get or fetch)


class DayComparison(BaseModel):
    day: date
    forecast_kwh: float
    measured_kwh: float | None  # aucun relevé de production ce jour-là


class Comparison(BaseModel):
    """Prévision Open-Meteo des jours passés comparée à la production mesurée (diagnostic)."""

    available: bool
    reason: str | None = None  # no_panels, no_position, unavailable
    days: list[DayComparison] = []
    ratio: float | None = None  # production mesurée / prévue, sur les jours qui ont les deux


async def compare(
    source: OpenMeteo, model: HomeModel, reader: AggregateReader, today: date, zone: ZoneInfo
) -> Comparison:
    try:
        quarters = await source.quarters()
    except OpenMeteoUnavailable:
        return Comparison(available=False, reason="unavailable")
    start, end = past.window(today, PAST_DAYS, zone)
    produced = past.series(reader, past.sensors(model, [Role.ENERGY_PRODUCED]), start, end, zone)
    days = []
    for offset in range(PAST_DAYS, 0, -1):
        day = today - timedelta(days=offset)
        forecast = sum(hourly_kwh(quarters, day, zone).values())
        measured = produced.get(day)
        days.append(
            DayComparison(
                day=day,
                forecast_kwh=round(forecast, 2),
                measured_kwh=round(sum(measured.values()), 2) if measured else None,
            )
        )
    both = [d for d in days if d.measured_kwh is not None and d.forecast_kwh > 0]
    total = sum(d.forecast_kwh for d in both)
    ratio = round(sum(d.measured_kwh or 0 for d in both) / total, 2) if total else None
    return Comparison(available=True, days=days, ratio=ratio)
