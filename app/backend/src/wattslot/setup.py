"""Mise en route (lot 4.1) : ce qu'il reste à faire pour obtenir
un premier plan, calculé par l'application à chaque demande.

Une liste plutôt qu'un assistant à pages (décision 1) : rien ne bloque, et la liste reste vraie
dans la durée (une étape faite redevient « à faire » si HA se déconnecte ou si la prévision
disparaît). Chaque étape dit son état, la raison en clair (code traduit par l'interface) et le
formulaire où y remédier ; les étapes indispensables viennent en tête.
"""

import sqlite3
from datetime import UTC, datetime
from enum import StrEnum
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from wattslot import configuration, home_model, notifications
from wattslot.aggregation import Aggregator
from wattslot.detection import DeviceKind
from wattslot.home_assistant import ConnectionState, HomeAssistantClient
from wattslot.planning import open_meteo
from wattslot.planning.sources import (
    Forecasts,
    ForecastUnavailable,
    has_production,
    load_settings,
)
from wattslot.planning.store import PlanStore
from wattslot.storage.graph import GraphStore


class StepState(StrEnum):
    DONE = "done"
    TODO = "todo"  # à faire par l'utilisateur
    WAITING = "waiting"  # en cours, rien à faire (reprise de l'historique)
    BLOCKED = "blocked"  # impossible tant qu'une étape précédente n'est pas faite
    NOT_APPLICABLE = "not_applicable"


# États d'une étape indispensable qui ne bloquent pas le premier plan.
APPLIED = frozenset({StepState.DONE, StepState.NOT_APPLICABLE})


class Step(BaseModel):
    key: str
    state: StepState
    required: bool  # indispensable au premier plan
    reason: str | None = None  # code traduit par l'interface (setup.reason.*)
    params: dict[str, str] = {}
    target: str | None = None  # page de l'interface où y remédier, ancre comprise


class Setup(BaseModel):
    steps: list[Step]
    ready: bool  # toutes les étapes indispensables faites


def _step(
    key: str,
    state: StepState,
    required: bool,
    reason: str | None = None,
    target: str | None = None,
    **params: str,
) -> Step:
    return Step(
        key=key, state=state, required=required, reason=reason, params=params, target=target
    )


async def setup_status(
    client: HomeAssistantClient | None,
    graph: GraphStore,
    database: sqlite3.Connection,
    aggregator: Aggregator | None,
    zone: ZoneInfo,
) -> Setup:
    connected = client is not None and client.status.state is ConnectionState.CONNECTED
    steps: list[Step] = []

    # 1. Connexion à HA.
    if client is None:
        steps.append(_step("connection", StepState.TODO, True, "ha_not_configured", "connection"))
    elif not connected:
        error = client.status.error or ""
        steps.append(
            _step("connection", StepState.TODO, True, "ha_disconnected", "connection", error=error)
        )
    else:
        steps.append(_step("connection", StepState.DONE, True))

    # 2. Tableau Énergie de HA.
    if not connected or client is None:
        steps.append(_step("energy_dashboard", StepState.BLOCKED, True, "needs_connection"))
    elif not (client.snapshot.energy_preferences or {}).get("energy_sources"):
        steps.append(_step("energy_dashboard", StepState.TODO, True, "no_energy_dashboard"))
    else:
        steps.append(_step("energy_dashboard", StepState.DONE, True))

    # 3. Maison validée.
    home = home_model.load(graph)
    if not home.devices:
        steps.append(_step("home", StepState.TODO, True, "home_not_saved", "home"))
    else:
        steps.append(_step("home", StepState.DONE, True, target="home"))

    # 4. Prévision solaire.
    forecast_ok = False
    if home.devices and not has_production(home):
        # Maison sans solaire (lot 7.4) : production nulle, rien à prévoir.
        forecast_ok = True
        steps.append(_step("forecast", StepState.NOT_APPLICABLE, True))
    elif not connected or client is None:
        steps.append(_step("forecast", StepState.BLOCKED, True, "needs_connection"))
    else:
        today = datetime.now(UTC).astimezone(zone).date()
        try:
            fallback = open_meteo.fallback_for(database, configuration.load(graph), client)
            await Forecasts(client, zone, load_settings(database), fallback).hourly(today)
            forecast_ok = True
            steps.append(_step("forecast", StepState.DONE, True))
        except ForecastUnavailable:
            steps.append(_step("forecast", StepState.TODO, True, "no_forecast", "home#solar"))

    # 5. Historique repris des statistiques de HA (automatique).
    if aggregator is None:
        steps.append(_step("history", StepState.BLOCKED, False, "needs_connection"))
    else:
        pending = aggregator.status().history.pending
        if pending:
            steps.append(
                _step(
                    "history",
                    StepState.WAITING,
                    False,
                    "history_importing",
                    count=str(len(pending)),
                )
            )
        else:
            steps.append(_step("history", StepState.DONE, False, target="diagnostic"))

    # 6. Premier plan.
    if PlanStore(database).load("today") is not None:
        steps.append(_step("first_plan", StepState.DONE, True, target="dashboard"))
    elif connected and home.devices and forecast_ok:
        steps.append(_step("first_plan", StepState.TODO, True, "no_plan_yet"))
    else:
        steps.append(_step("first_plan", StepState.BLOCKED, True, "needs_previous_steps"))

    # 7. Modèle prêt à l'emploi (lot 4.3) : proposé tant que rien n'est réglé.
    settings = configuration.load(graph)
    if not home.devices:
        steps.append(_step("template", StepState.BLOCKED, False, "needs_home"))
    elif not settings.devices and settings.tariff is None:
        steps.append(_step("template", StepState.TODO, False, "template_suggested", "home#models"))
    else:
        steps.append(_step("template", StepState.DONE, False, target="home#models"))

    # 8. Tarif et batterie : réglages par défaut valables, à ajuster.
    if settings.tariff is None:
        steps.append(_step("tariff", StepState.TODO, False, "tariff_default", "home#tariff"))
    else:
        steps.append(_step("tariff", StepState.DONE, False, target="home#tariff"))
    if not any(d.kind is DeviceKind.BATTERY for d in home.devices):
        steps.append(_step("battery", StepState.NOT_APPLICABLE, False))
    elif settings.battery is None:
        steps.append(_step("battery", StepState.TODO, False, "battery_default", "home#battery"))
    else:
        steps.append(_step("battery", StepState.DONE, False, target="home#battery"))

    # 9. Notifications (lot 4.2, réglages du lot 5.6) : facultative, faite dès qu'une
    # notification est activée avec un appareil.
    if not notifications.load(database).active():
        steps.append(
            _step("notification", StepState.TODO, False, "no_notification", "settings#notification")
        )
    else:
        steps.append(_step("notification", StepState.DONE, False, target="settings#notification"))

    steps.sort(key=lambda s: not s.required)  # indispensables d'abord, ordre gardé sinon
    ready = all(s.state in APPLIED for s in steps if s.required)
    return Setup(steps=steps, ready=ready)
