"""Export et import de la maison (lot 3.8).

Un fichier JSON lisible et versionné porte le modèle de la maison et sa configuration : pour la
sauvegarder, la partager (forum, ticket) ou partir d'un profil d'exemple. Même forme qu'un profil
(``profiles``), le nom et la description en moins.

L'import est **vérifié avant d'être appliqué** : format, version (les versions précédentes sont
migrées pas à pas, ``MIGRATIONS``), modèle de la maison, anomalies de la configuration (celles de
l'onglet Maison). Les entités inconnues de HA ne bloquent pas : un profil d'exemple a des entités
génériques ; elles sont signalées. Valide, il **remplace** le modèle et la configuration.
"""

from collections.abc import Callable, Iterable
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from wattslot import configuration, home_model
from wattslot.configuration import Configuration, Issue
from wattslot.home_model import HomeModel

FORMAT: Literal["wattslot/home"] = "wattslot/home"
# Format d'avant le renommage en WattSlot (lot 7.1) : même contenu, encore accepté à l'import.
LEGACY_FORMAT = "energy-optimizer/home"
VERSION = 2


def _types(document: dict[str, Any]) -> dict[str, Any]:
    """Version 1 → 2 (lot 2t.1) : la maison a des types propres, aucun avant."""
    return {**document, "home": {**document.get("home", {}), "types": []}}


# Version n → n + 1, sur le document brut.
MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {1: _types}


class HomeExport(BaseModel):
    format: Literal["wattslot/home"] = FORMAT
    version: int = VERSION
    home: HomeModel
    configuration: Configuration


class ImportCheck(BaseModel):
    issues: list[Issue] = []  # bloquantes
    unknown_entities: list[str] = []  # absentes de HA : signalées seulement
    applied: bool = False


def export(home: HomeModel, settings: Configuration) -> HomeExport:
    return HomeExport(home=home, configuration=settings)


def migrate(document: dict[str, Any]) -> dict[str, Any]:
    """Document à la version courante ; ``ValueError`` pour une version inconnue."""
    version = document.get("version")
    if not isinstance(version, int) or version < 1:
        raise ValueError("version absente ou invalide")
    if version > VERSION:
        raise ValueError(f"version {version} plus récente que celle de l'application ({VERSION})")
    while version < VERSION:
        document = {**MIGRATIONS[version](document), "version": version + 1}
        version += 1
    return document


def check(
    document: Any, known_entities: Iterable[str] | None = None
) -> tuple[HomeExport | None, ImportCheck]:
    """Fichier importé, vérifié : (contenu s'il est valide, anomalies et entités inconnues)."""
    if not isinstance(document, dict) or document.get("format") not in (FORMAT, LEGACY_FORMAT):
        return None, ImportCheck(issues=[Issue(code="import_format")])
    document = {**document, "format": FORMAT}
    try:
        current = migrate(document)
    except ValueError as error:
        return None, ImportCheck(
            issues=[Issue(code="import_version", params={"reason": str(error)})]
        )
    try:
        found = HomeExport.model_validate(current)
    except ValidationError as error:
        first = error.errors()[0]
        where = ".".join(str(part) for part in first["loc"])
        return None, ImportCheck(
            issues=[Issue(code="import_invalid", params={"field": where, "reason": first["msg"]})]
        )
    issues = [
        Issue(code=code, device=key, params=params)
        for code, key, params in home_model.problems(found.home)
    ]
    issues += configuration.validate(found.home, found.configuration)
    unknown: list[str] = []
    if known_entities is not None:
        known = set(known_entities)
        unknown = sorted({s.entity_id for d in found.home.devices for s in d.sensors} - known)
    return (found if not issues else None), ImportCheck(issues=issues, unknown_entities=unknown)
