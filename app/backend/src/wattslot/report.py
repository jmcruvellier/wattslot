"""Rapport anonymisé pour un ticket (lot 4.8, point n° 7).

Ce qu'il faut pour comprendre un problème sans rien de l'installation : versions, état des
composants, problèmes, maison et configuration. Les équipements deviennent ``<type>_<n>``, chaque
capteur ``<équipement>.<rôle>``, les autres entités (tarif, objectif, réglages) ``entité_<n>``, les
types propres ``type_<n>`` ; la même table s'applique aux textes d'erreur, et toute autre chaîne
qui ressemble à un identifiant d'entité est masquée. Ni position, ni adresse de HA, ni jeton, ni
nom d'équipement.
"""

import re
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from wattslot import __version__
from wattslot.configuration import Configuration
from wattslot.diagnostic import Diagnostic
from wattslot.home_model import HomeModel
from wattslot.planning.sources import PlanningSettings
from wattslot.problems import Problem

FORMAT = "wattslot/report"
VERSION = 1
# Identifiant d'entité de HA (« domaine.objet ») resté dans un texte libre.
ENTITY = re.compile(r"\b[a-z_]+\.[a-z0-9_]+\b")


class Anonymizer:
    """Table des identifiants de l'installation vers leurs alias."""

    def __init__(self, home: HomeModel) -> None:
        self.aliases: dict[str, str] = {}
        self.keys: dict[str, str] = {}
        counts: dict[str, int] = defaultdict(int)
        for device in home.devices:
            counts[device.kind.value] += 1
            alias = f"{device.kind.value}_{counts[device.kind.value]}"
            self.keys[device.key] = alias
            self.aliases[device.name] = alias
            for sensor in device.sensors:
                self.aliases[sensor.entity_id] = f"{alias}.{sensor.role.value}"
        for index, own in enumerate(home.types, start=1):
            self.aliases[own.key] = f"type_{index}"
            self.aliases[own.name] = f"type_{index}"
        self._others = 0

    def key(self, key: str | None) -> str | None:
        return None if key is None else self.keys.get(key, "équipement")

    def entity(self, entity_id: str | None) -> str | None:
        """Alias d'une entité ; une entité hors de la maison reçoit ``entité_<n>``."""
        if not entity_id:
            return entity_id
        if entity_id not in self.aliases:
            self._others += 1
            self.aliases[entity_id] = f"entité_{self._others}"
        return self.aliases[entity_id]

    def text(self, value: str | None) -> str | None:
        """Texte libre (message d'erreur) : identifiants connus remplacés, puis toute chaîne qui
        ressemble à une entité masquée."""
        if value is None:
            return None
        for original in sorted(self.aliases, key=len, reverse=True):
            value = value.replace(original, self.aliases[original])
        known = set(self.aliases.values())
        return ENTITY.sub(lambda m: m.group(0) if m.group(0) in known else "entité", value)


def _home(home: HomeModel, names: Anonymizer) -> dict[str, Any]:
    return {
        "devices": [
            {
                "key": names.key(device.key),
                "kind": device.kind.value,
                "custom_type": names.aliases.get(device.custom_type)
                if device.custom_type
                else None,
                "capacity_kwh": device.capacity_kwh,
                "sensors": [
                    {"role": s.role.value, "resets_daily": s.resets_daily} for s in device.sensors
                ],
            }
            for device in home.devices
        ],
        "types": [
            {"key": names.aliases[own.key], "parent": own.parent.value} for own in home.types
        ],
    }


def _configuration(saved: Configuration, names: Anonymizer) -> dict[str, Any]:
    found = saved.model_dump(mode="json")
    for device in found["devices"]:
        device["key"] = names.key(device["key"])
        device["after"] = names.key(device.get("after"))
    tariff = found.get("tariff")
    if tariff:
        for field in ("color_entity", "color_tomorrow_entity", "price_entity", "export_entity"):
            tariff[field] = names.entity(tariff.get(field))
    objective = found.get("objective")
    if objective:
        objective["co2_entity"] = names.entity(objective.get("co2_entity"))
    return found


def _components(diagnostic: Diagnostic, names: Anonymizer) -> dict[str, Any]:
    ingestion, aggregation = diagnostic.ingestion, diagnostic.aggregation
    maintenance, planning = diagnostic.maintenance, diagnostic.planning
    return {
        "memory_bytes": diagnostic.memory_bytes,
        "written_bytes": diagnostic.written_bytes,
        "started_at": diagnostic.started_at.isoformat() if diagnostic.started_at else None,
        "ingestion": ingestion
        and {
            "running": ingestion.running,
            "entities": len(ingestion.entities),
            "received": ingestion.received,
            "written": ingestion.written,
            "pending": ingestion.pending,
            "last_batch_at": ingestion.last_batch_at.isoformat()
            if ingestion.last_batch_at
            else None,
            "last_error": names.text(ingestion.last_error),
        },
        "aggregation": aggregation
        and {
            "running": aggregation.running,
            "written": aggregation.written,
            "last_error": names.text(aggregation.last_error),
            "history_imported": aggregation.history.imported,
            "history_pending": len(aggregation.history.pending),
            "without_statistics": len(aggregation.history.without_statistics),
        },
        "maintenance": maintenance
        and {
            "running": maintenance.running,
            "last_error": names.text(maintenance.last_error),
            "last_run_removed_days": len(maintenance.last_run.removed_days)
            if maintenance.last_run
            else None,
            "disk": maintenance.disk.model_dump(mode="json"),
        },
        "planning": planning
        and {
            "enabled": planning.enabled,
            "running": planning.running,
            "last_success_at": planning.last_success_at.isoformat()
            if planning.last_success_at
            else None,
            "last_error": names.text(planning.last_error),
        },
    }


def _problem(problem: Problem, names: Anonymizer) -> dict[str, Any]:
    params = {}
    for name, value in problem.params.items():
        if name == "entity":
            params[name] = names.entity(value) or ""
        else:
            params[name] = names.text(value) or ""
    return {"code": problem.code, "severity": problem.severity.value, "params": params}


def build(
    *,
    mode: str,
    ha_version: str | None,
    ha_state: str,
    diagnostic: Diagnostic,
    problems: list[Problem],
    home: HomeModel,
    saved: Configuration,
    settings: PlanningSettings,
) -> dict[str, Any]:
    names = Anonymizer(home)
    return {
        "format": FORMAT,
        "version": VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "application": {"version": __version__, "mode": mode},
        "home_assistant": {"version": ha_version, "state": ha_state},
        "problems": [_problem(p, names) for p in problems],
        "components": _components(diagnostic, names),
        "home": _home(home, names),
        "configuration": _configuration(saved, names),
        "settings": {
            "todo_list": settings.todo_entity is not None,
            "notification": settings.notify_service is not None,
            "notify_language": settings.notify_language,
            "forecast_entities": len(settings.forecast_entities),
            "scheduler_enabled": settings.scheduler_enabled,
            "run_minute": settings.run_minute,
        },
    }
