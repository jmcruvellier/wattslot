"""Entrées du calcul lues en direct dans HA : prévision solaire, tâches, réglages du calcul.

- **Prévision solaire** (point n° 2) : d'abord les prévisions déclarées dans
  le tableau Énergie (``energy/solar_forecast`` : Forecast.Solar, Solcast…), sans réglage ;
  sinon l'attribut ``forecast`` d'entités choisies dans les réglages, au format de Helios
  (points datés en W, moyennés par heure) ; sinon Open-Meteo pour les panneaux décrits. Sans
  aucune, le calcul ne peut pas se faire : ``ForecastUnavailable``. Une maison enregistrée
  sans installation solaire (lot 7.4) n'en a pas besoin : production nulle à toute heure.
- **Tâches** : liste de tâches de HA choisie dans les réglages (``todo.get_items``), tâches à
  faire seulement ; échéance (date) et description JSON comme en v1 (type, règle de
  récurrence, dépendance, besoin détecté).
"""

import json
import sqlite3
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from wattslot.detection import DeviceKind
from wattslot.home_assistant import HomeAssistantClient
from wattslot.home_model import HomeModel
from wattslot.languages import Language
from wattslot.planning.engine import Objective
from wattslot.planning.inputs import TaskRequest, from_v1
from wattslot.planning.open_meteo import OpenMeteo, OpenMeteoUnavailable

SETTINGS_KEY = "planning"


class PlanningSettings(BaseModel):
    """Réglages du calcul (``/api/settings/planning``)."""

    objective: Objective = Objective.COST
    todo_entity: str | None = None  # liste de tâches de HA
    forecast_entities: list[str] = []  # repli sans prévision au tableau Énergie
    # Planificateur : un calcul chaque heure à cette minute (59, comme n8n en v1).
    scheduler_enabled: bool = True
    run_minute: int = Field(default=59, ge=0, le=59)
    # Données réelles du jour relues sur le brut toutes les N minutes entre deux calculs
    # (sans calcul) ; 0 : seulement au calcul horaire et au bouton « Rafraîchir ».
    actual_refresh_minutes: int = Field(default=15, ge=0, le=60)
    # Recommandation du jour envoyée après chaque calcul planifié par ce service de HA
    # (« notify.mobile_app_… ») ; aucun par défaut, pour ne pas doubler la v1.
    notify_service: str | None = Field(default=None, pattern=r"^notify\.[a-z0-9_]+$")
    notify_language: Language = "fr"


def load_settings(database: sqlite3.Connection) -> PlanningSettings:
    row = database.execute(
        "SELECT value FROM app_settings WHERE key = ?", (SETTINGS_KEY,)
    ).fetchone()
    return PlanningSettings.model_validate(json.loads(row[0])) if row else PlanningSettings()


def save_settings(database: sqlite3.Connection, settings: PlanningSettings) -> None:
    with database:
        database.execute(
            "INSERT INTO app_settings VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (SETTINGS_KEY, settings.model_dump_json()),
        )


class ForecastUnavailable(Exception):
    """Ni le tableau Énergie ni les entités choisies ne donnent de prévision pour ce jour."""


def energy_dashboard_forecast(result: Any, day: date, zone: ZoneInfo) -> dict[int, float]:
    """kWh par heure locale de ``day``, sommés sur les prévisions du tableau Énergie
    (``{entrée: {"wh_hours": {instant ISO: Wh}}}``)."""
    hourly: dict[int, float] = defaultdict(float)
    for forecast in (result or {}).values():
        for moment, wh in ((forecast or {}).get("wh_hours") or {}).items():
            local = datetime.fromisoformat(moment).astimezone(zone)
            if local.date() == day and wh is not None:
                hourly[local.hour] += float(wh) / 1000
    return dict(hourly)


def entity_forecast(
    states: Sequence[dict[str, Any]], entities: Sequence[str], day: date, zone: ZoneInfo
) -> dict[int, float]:
    """kWh par heure locale de ``day`` : attribut ``forecast`` (points ``datetime`` / ``watts``)
    des entités choisies, moyenne horaire des puissances, sommée sur les entités."""
    wanted = set(entities)
    hourly: dict[int, float] = defaultdict(float)
    for state in states:
        if state.get("entity_id") not in wanted:
            continue
        by_hour: dict[int, list[float]] = defaultdict(list)
        for point in (state.get("attributes") or {}).get("forecast") or []:
            try:
                local = datetime.fromisoformat(
                    str(point["datetime"]).replace("Z", "+00:00")
                ).astimezone(zone)
            except (KeyError, ValueError):
                continue
            if local.date() == day and point.get("watts") is not None:
                by_hour[local.hour].append(float(point["watts"]))
        for hour, watts in by_hour.items():
            hourly[hour] += sum(watts) / len(watts) / 1000
    return dict(hourly)


def has_production(model: HomeModel | None) -> bool:
    """Faux pour une maison enregistrée sans installation solaire : heures creuses, Tempo ou
    prix dynamiques seulement. Maison pas encore enregistrée : on ne sait pas, vrai."""
    if model is None or not model.devices:
        return True
    return any(device.kind is DeviceKind.SOLAR for device in model.devices)


class Forecasts:
    """Prévisions solaires d'un calcul : HA n'est interrogé qu'une fois pour tous les jours
    (le jour, l'affectation des tâches à 3 jours, l'horizon de 7 jours)."""

    def __init__(
        self,
        client: HomeAssistantClient,
        zone: ZoneInfo,
        settings: PlanningSettings,
        fallback: OpenMeteo | None = None,
        production: bool = True,
    ) -> None:
        self._client = client
        self._production = production  # faux : maison sans solaire, prévision nulle
        self._zone = zone
        self._settings = settings
        self._fallback = fallback  # prévision Open-Meteo des panneaux décrits (lot 4.4)
        self._dashboard: Any = None
        self._states: list[dict[str, Any]] | None = None

    async def hourly(self, day: date) -> tuple[dict[int, float], list[dict[str, Any]]]:
        """(kWh par heure, avertissements) ; ``ForecastUnavailable`` sans prévision."""
        if not self._production:
            return dict.fromkeys(range(24), 0.0), []
        if self._dashboard is None:
            try:
                self._dashboard = await self._client.command("energy/solar_forecast") or {}
            except Exception:  # noqa: BLE001 — tableau Énergie sans prévision : repli
                self._dashboard = {}
        hourly = energy_dashboard_forecast(self._dashboard, day, self._zone)
        if hourly:
            return hourly, []
        if self._settings.forecast_entities:
            if self._states is None:
                self._states = await self._client.command("get_states") or []
            hourly = entity_forecast(
                self._states, self._settings.forecast_entities, day, self._zone
            )
            if hourly:
                return hourly, []
        if self._fallback is not None:
            try:
                hourly = await self._fallback.hourly(day, self._zone)
            except OpenMeteoUnavailable:
                hourly = {}
            if hourly:
                return hourly, [{"code": "prevision_open_meteo", "params": {}}]
        raise ForecastUnavailable(day.isoformat())


async def solar_forecast(
    client: HomeAssistantClient, day: date, zone: ZoneInfo, settings: PlanningSettings
) -> tuple[dict[int, float], list[dict[str, Any]]]:
    """(kWh par heure, avertissements) ; ``ForecastUnavailable`` sans prévision."""
    return await Forecasts(client, zone, settings).hourly(day)


def _task(item: dict[str, Any]) -> dict[str, Any]:
    """Tâche de HA au format de la v1 (description JSON, échéance en date)."""
    try:
        description = json.loads(item.get("description") or "{}")
    except (TypeError, ValueError):
        description = {}
    task: dict[str, Any] = {
        "summary": item.get("summary") or "",
        "uid": item.get("uid"),
        "description": description if isinstance(description, dict) else {},
    }
    if item.get("due"):
        task["due"] = str(item["due"])[:10]
    return task


async def read_tasks(
    client: HomeAssistantClient, entity_id: str | None
) -> tuple[list[TaskRequest], list[TaskRequest]]:
    """(tâches datées, tâches en attente) de la liste de HA ; vides sans liste choisie."""
    if not entity_id:
        return [], []
    result = await client.command(
        "call_service",
        domain="todo",
        service="get_items",
        service_data={"status": ["needs_action"]},
        target={"entity_id": entity_id},
        return_response=True,
    )
    items = (((result or {}).get("response") or {}).get(entity_id) or {}).get("items") or []
    tasks = [_task(item) for item in items if item.get("summary")]
    data = from_v1(
        {
            "date_cible": date.today(),
            "taches_placees": [t for t in tasks if "due" in t],
            "taches_en_attente": [t for t in tasks if "due" not in t],
            "capacite_batterie_kwh": 0,
            "stored_energy_kwh": 0,
            "soc_percent": 0,
            "puissance_charge_max_w": 0,
            "puissance_decharge_max_w": 0,
        }
    )
    return list(data.due_tasks), list(data.waiting_tasks)
