"""Ce qui ne va pas, en clair (lot 4.8) : le premier niveau du
diagnostic, calculé par l'application pour que le rapport et les tests le partagent.

Chaque problème a un code (traduit par l'interface sous ``problems.code``), des paramètres (noms
d'équipements plutôt qu'identifiants d'entités quand c'est possible), une gravité, et le geste à
faire : une page de l'application (``target``) ou la documentation de HA concernée (``doc``).
Sources : la mise en route, la maison enregistrée confrontée à HA, l'état des composants
(ingestion, agrégation, maintenance, calcul), les ressources (disque, mémoire) et la
configuration.
"""

from datetime import timedelta
from enum import StrEnum

from pydantic import BaseModel

from wattslot import configuration
from wattslot.configuration import Configuration
from wattslot.diagnostic import Diagnostic
from wattslot.home_assistant import HomeAssistantClient
from wattslot.home_model import HomeModel
from wattslot.ingestion import silent_entities
from wattslot.resources import disk_low_free, memory_alert
from wattslot.setup import Setup, StepState

STALE_PLAN = timedelta(hours=2)
PENDING_MAX = 1000
# Ressources : seuils dans ``resources`` (ligne rouge des courbes). Toutes « à surveiller » : les
# autres gravités parlent du plan.
SLOW_PLAN = timedelta(minutes=10)  # durée d'un calcul du plan (jour, lendemain, horizon)
# Alertes de ressources, notifiées à part (réglage « resources » des notifications).
RESOURCE_ALERTS = frozenset(
    {"disk_low", "backup_space", "memory_high", "memory_heavy", "plan_slow"}
)
SAMPLE_ALERT = {"free": "1.5", "percent": "4"}  # exemple de « disk_low » pour un envoi d'essai
UNAVAILABLE = {"unavailable", "unknown"}

DOCS = {
    "token": "https://www.home-assistant.io/docs/authentication/#your-account-profile",
    "energy": "https://www.home-assistant.io/docs/energy/",
    "forecast": "https://www.home-assistant.io/integrations/forecast_solar/",
    "statistics": "https://data.home-assistant.io/docs/statistics/",
    "issues": "https://github.com/jmcruvellier/wattslot/issues",
}


class Severity(StrEnum):
    BLOCKING = "blocking"  # pas de plan
    DEGRADED = "degraded"  # plan moins juste
    WATCH = "watch"  # à surveiller


class Problem(BaseModel):
    code: str
    severity: Severity
    params: dict[str, str] = {}
    target: str | None = None  # page de l'application où agir, ancre comprise
    doc: str | None = None  # documentation de HA (ou tickets du projet)
    # Étape de la mise en route avant le premier plan : la pastille dit « Mise en route », pas
    # « Le calcul est bloqué » (essai d'installation du 21/10/2026).
    setup: bool = False


def _problem(
    code: str,
    severity: Severity,
    target: str | None = None,
    doc: str | None = None,
    **params: str,
) -> Problem:
    return Problem(code=code, severity=severity, params=params, target=target, doc=doc)


def _setup_problems(setup: Setup) -> list[Problem]:
    first_plan = any(s.key == "first_plan" and s.state is StepState.DONE for s in setup.steps)
    found = []
    for step in setup.steps:
        if step.state is not StepState.TODO or not step.required:
            continue
        if step.key == "connection":
            found.append(
                _problem(
                    step.reason or "ha_disconnected",
                    Severity.BLOCKING,
                    target=step.target,
                    doc=DOCS["token"],
                    **step.params,
                )
            )
        elif step.key == "energy_dashboard":
            found.append(_problem("no_energy_dashboard", Severity.BLOCKING, doc=DOCS["energy"]))
        elif step.key == "home":
            found.append(_problem("home_not_saved", Severity.BLOCKING, target="home"))
        elif step.key == "forecast":
            found.append(
                _problem(
                    "no_forecast", Severity.BLOCKING, target="home#solar", doc=DOCS["forecast"]
                )
            )
    for problem in found:
        problem.setup = not first_plan
    return found


def _sensor_problems(
    home: HomeModel, client: HomeAssistantClient | None, diagnostic: Diagnostic
) -> list[Problem]:
    """Capteurs de la maison enregistrée : disparus de HA, indisponibles, ou muets avec une
    valeur figée suspecte (``ingestion.silent_entities``)."""
    found = []
    states = client.snapshot.states if client is not None else None
    silent = set(silent_entities(diagnostic.ingestion, diagnostic.today, diagnostic.generated_at))
    for device in home.devices:
        for sensor in device.sensors:
            params = {"device": device.name, "role": sensor.role.value, "entity": sensor.entity_id}
            if states is not None and sensor.entity_id not in states:
                found.append(
                    Problem(
                        code="sensor_missing",
                        severity=Severity.DEGRADED,
                        params=params,
                        target="home",
                    )
                )
                continue
            state = (states or {}).get(sensor.entity_id) or {}
            if str(state.get("state")) in UNAVAILABLE:
                found.append(
                    Problem(code="sensor_unavailable", severity=Severity.WATCH, params=params)
                )
                continue
            if sensor.entity_id in silent:
                found.append(Problem(code="sensor_silent", severity=Severity.WATCH, params=params))
    return found


def _names(home: HomeModel) -> dict[str, str]:
    """Nom de l'équipement de chaque entité de la maison."""
    return {sensor.entity_id: device.name for device in home.devices for sensor in device.sensors}


def _component_problems(diagnostic: Diagnostic, home: HomeModel) -> list[Problem]:
    found = []
    ingestion, aggregation = diagnostic.ingestion, diagnostic.aggregation
    errors = {
        "ingestion": ingestion.last_error if ingestion else None,
        "aggregation": aggregation.last_error if aggregation else None,
        "maintenance": diagnostic.maintenance.last_error if diagnostic.maintenance else None,
        # Sans prévision solaire : déjà signalé par « no_forecast », avec son geste.
        "planning": diagnostic.planning.last_error
        if diagnostic.planning and diagnostic.planning.last_error_code != "no_forecast"
        else None,
    }
    for component, error in errors.items():
        if error:
            found.append(
                _problem(
                    "internal_error",
                    Severity.DEGRADED,
                    doc=DOCS["issues"],
                    component=component,
                    error=error,
                )
            )
    if ingestion is not None and ingestion.pending > PENDING_MAX:
        found.append(_problem("writes_behind", Severity.WATCH, count=str(ingestion.pending)))
    if aggregation is not None and aggregation.history.without_statistics:
        names = _names(home)
        devices = sorted({names.get(e, e) for e in aggregation.history.without_statistics})
        found.append(
            _problem(
                "no_statistics",
                Severity.DEGRADED,
                doc=DOCS["statistics"],
                devices=", ".join(devices),
            )
        )
    planning = diagnostic.planning
    report = planning.last_report if planning is not None else None
    for impossible in report.impossible if report is not None else []:
        # Jour non calculé, consommation de base impossible (lot 7.3) : saut de compteur.
        params = {
            "day": impossible.day.isoformat(),
            "hour": str(impossible.hour),
            "kwh": f"{impossible.consumption_kwh:g}",
            "limit": f"{impossible.limit_kwh:g}",
        }
        if impossible.source_start is None:
            found.append(_problem("impossible_data_unknown", Severity.DEGRADED, **params))
            continue
        found.append(
            _problem(
                "impossible_data",
                Severity.DEGRADED,
                **params,
                device=impossible.device or "",
                entity=impossible.entity_id or "",
                when=impossible.source_start.date().isoformat(),
                when_hour=str(impossible.source_start.hour),
                source_kwh=f"{impossible.source_kwh:g}",
                until=impossible.until.isoformat() if impossible.until else "",
            )
        )
    if (
        planning is not None
        and planning.enabled
        and planning.running
        and planning.last_success_at is not None
        and diagnostic.generated_at - planning.last_success_at > STALE_PLAN
    ):
        found.append(
            _problem(
                "plan_stale",
                Severity.DEGRADED,
                target="start",
                since=planning.last_success_at.isoformat(),
            )
        )
    return found


def _gigabytes(value: int) -> str:
    return f"{value / 1e9:.1f}"


def _resource_problems(diagnostic: Diagnostic) -> list[Problem]:
    """Disque, mémoire et durée du calcul. Les nombres partent bruts (« 1.5 » Go, « 1100 » Mo,
    « 12 » min) : l'interface et l'assistant les écrivent dans leur langue."""
    found = []
    resources = diagnostic.resources
    if resources is not None and resources.disk_free_bytes is not None:
        free, total = resources.disk_free_bytes, resources.disk_total_bytes or 0
        needed = resources.disk_backup_bytes or 0
        if needed and free < needed:
            found.append(
                _problem(
                    "backup_space",
                    Severity.WATCH,
                    free=_gigabytes(free),
                    needed=_gigabytes(needed),
                )
            )
        elif free < disk_low_free(resources):
            found.append(
                _problem(
                    "disk_low",
                    Severity.WATCH,
                    free=_gigabytes(free),
                    percent=str(round(100 * free / total)) if total else "",
                )
            )
    floor = resources.memory_floor_bytes if resources is not None else None
    alert = memory_alert(resources) if resources is not None else None
    if resources is not None and floor is not None and alert is not None and floor >= alert:
        limit = resources.memory_limit_bytes
        used = str(round(floor / 1e6))
        if resources.memory_limit_source == "container" and limit:
            percent = str(round(100 * floor / limit))
            found.append(_problem("memory_high", Severity.WATCH, used=used, percent=percent))
        else:
            found.append(_problem("memory_heavy", Severity.WATCH, used=used))
    report = diagnostic.planning.last_report if diagnostic.planning else None
    if report is not None:
        seconds = (
            report.seconds_today + (report.seconds_tomorrow or 0) + (report.seconds_horizon or 0)
        )
        if seconds >= SLOW_PLAN.total_seconds():
            found.append(_problem("plan_slow", Severity.WATCH, minutes=str(round(seconds / 60))))
    return found


def _configuration_problems(home: HomeModel, saved: Configuration) -> list[Problem]:
    if not home.devices:
        return []
    names = {device.key: device.name for device in home.devices}
    return [
        Problem(
            code="configuration_issue",
            severity=Severity.DEGRADED,
            target="home",
            # Les paramètres de l'anomalie, puis le code et le nom de l'équipement (qui priment).
            params={
                **issue.params,
                "issue": issue.code,
                "device": names.get(issue.device or "", issue.device or ""),
            },
        )
        for issue in configuration.validate(home, configuration.effective(home, saved))
    ]


def _dashboard_problems(diagnostic: Diagnostic, home: HomeModel) -> list[Problem]:
    """Anomalies du tableau Énergie de HA (propositions de la détection). Celles d'un capteur
    portent déjà son entité dans leurs paramètres.

    Une fois la maison enregistrée, l'utilisateur a tranché : une anomalie sur un équipement ou
    un capteur qu'il n'a pas retenu n'est plus signalée, et l'équipement prend le nom qu'il lui a
    donné."""
    names = {device.key: device.name for device in home.devices}
    used = {sensor.entity_id for device in home.devices for sensor in device.sensors}
    found = []
    for item in diagnostic.issues or []:
        entity = item.entity_id or item.issue.params.get("entity", "")
        if home.devices and (
            (item.key is not None and item.key not in names) or (entity and entity not in used)
        ):
            continue
        if item.issue.code == "entity_missing" and entity in used:
            continue  # déjà signalé par « sensor_missing », avec son geste
        found.append(
            Problem(
                code="energy_dashboard_issue",
                severity=Severity.WATCH,
                doc=DOCS["energy"],
                params={
                    **item.issue.params,
                    "issue": item.issue.code,
                    "device": names.get(item.key or "", item.device),
                    "entity": entity,
                },
            )
        )
    return found


ORDER = {Severity.BLOCKING: 0, Severity.DEGRADED: 1, Severity.WATCH: 2}


def collect(
    setup: Setup,
    diagnostic: Diagnostic,
    home: HomeModel,
    saved: Configuration,
    client: HomeAssistantClient | None,
) -> list[Problem]:
    """Tous les problèmes, les plus graves d'abord."""
    found = (
        _setup_problems(setup)
        + _sensor_problems(home, client, diagnostic)
        + _component_problems(diagnostic, home)
        + _resource_problems(diagnostic)
        + _configuration_problems(home, saved)
        + _dashboard_problems(diagnostic, home)
    )
    return sorted(found, key=lambda p: ORDER[p.severity])
