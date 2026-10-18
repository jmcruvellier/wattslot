"""Modèles prêts à l'emploi (lot 4.3, point n° 2) : réglages de
la configuration à appliquer à la maison détectée, sans toucher à ses équipements ni à ses
capteurs.

Un modèle est un **fichier de données** (``templates/*.json``), pas du code : réglages par type
d'équipement (type propre de l'installation, sinon type de la bibliothèque), liens exprimés par
type (« après le lave-linge »), tarif, objectif et, s'il en a, batterie. Un réglage prévu pour un
type absent de la maison ne s'applique pas. Les valeurs propres à une maison (réglages de la
batterie, vitesses de la piscine, entités du tarif) restent aux défauts : les entités du tarif
Tempo ou dynamique sont données à l'application du modèle.
"""

import json
from importlib import resources
from typing import Any, Literal

from pydantic import BaseModel

from wattslot import configuration
from wattslot.battery_settings import BatterySettings
from wattslot.configuration import (
    OBSERVED,
    Automation,
    Behavior,
    Configuration,
    DeviceSettings,
    Issue,
)
from wattslot.energy_need import EnergyNeed
from wattslot.home_model import HomeDevice, HomeModel
from wattslot.objective_settings import ObjectiveSettings
from wattslot.recurrence_settings import Recurrence
from wattslot.runtime_settings import RuntimeSettings
from wattslot.tariff import Tariff
from wattslot.time_constraints import TimeConstraint

FORMAT = "wattslot/template"
VERSION = 1


class DeviceTemplate(BaseModel):
    """Réglages d'un type d'équipement : ``type`` est la clé d'un type propre ou un type de la
    bibliothèque (``WaterHeater``) ; ``after`` désigne aussi un type."""

    type: str
    behavior: Behavior
    automation: Automation | None = None  # aucun : celui du comportement par défaut
    runtime: RuntimeSettings | None = None
    energy: EnergyNeed | None = None
    constraints: list[TimeConstraint] = []
    after: str | None = None
    max_delay_days: int | None = None
    recurrence: Recurrence | None = None


class Template(BaseModel):
    key: str
    name: dict[str, str]  # par langue
    description: dict[str, str]
    devices: list[DeviceTemplate] = []
    tariff: Tariff
    objective: ObjectiveSettings | None = None
    battery: BatterySettings | None = None


class TariffEntities(BaseModel):
    """Entités du tarif, propres à chaque maison : données à l'application du modèle."""

    color_entity: str | None = None
    color_tomorrow_entity: str | None = None
    price_entity: str | None = None
    export_entity: str | None = None


class Change(BaseModel):
    part: Literal["device", "tariff", "objective", "battery"]
    device: str | None = None  # clé de l'équipement
    before: Any = None
    after: Any = None


class Preview(BaseModel):
    template: str
    configuration: Configuration  # configuration obtenue, réglages par défaut compris
    changes: list[Change]
    issues: list[Issue]  # vide : le modèle peut être appliqué


def names() -> list[str]:
    folder = resources.files("wattslot.templates")
    return sorted(
        p.name.removesuffix(".json") for p in folder.iterdir() if p.name.endswith(".json")
    )


def load(key: str) -> Template:
    """Modèle ``key`` ; ``KeyError`` s'il n'existe pas."""
    if key not in names():
        raise KeyError(key)
    folder = resources.files("wattslot.templates")
    raw = json.loads(folder.joinpath(f"{key}.json").read_text("utf-8"))
    if raw.get("format") != FORMAT or raw.get("version") != VERSION:
        raise ValueError(f"modèle {key} : format inconnu")
    return Template.model_validate({**raw, "key": key})


def all_templates() -> list[Template]:
    return [load(key) for key in names()]


def _type_of(device: HomeDevice) -> list[str]:
    """Types sous lesquels chercher les réglages d'un équipement, le plus précis d'abord."""
    return [t for t in (device.custom_type, device.kind.value) if t]


def _single(home: HomeModel, type_key: str) -> str | None:
    """Clé de l'unique équipement de ce type ; ``None`` s'il y en a zéro ou plusieurs."""
    found = [d.key for d in home.devices if type_key in _type_of(d)]
    return found[0] if len(found) == 1 else None


def device_settings(
    template: Template, home: HomeModel, device: HomeDevice
) -> DeviceSettings | None:
    """Réglages que le modèle donne à cet équipement ; ``None`` s'il ne connaît pas son type ou
    si le comportement n'est pas possible pour ce type."""
    by_type = {t.type: t for t in template.devices}
    found = next((by_type[t] for t in _type_of(device) if t in by_type), None)
    if found is None or found.behavior not in configuration.BEHAVIORS[device.kind]:
        return None
    automation = found.automation or (
        Automation.INFORM if found.behavior in OBSERVED else Automation.RECOMMEND
    )
    after = _single(home, found.after) if found.after else None
    return DeviceSettings(
        key=device.key,
        behavior=found.behavior,
        automation=automation,
        runtime=found.runtime,
        energy=found.energy,
        constraints=found.constraints,
        after=after if after != device.key else None,
        max_delay_days=found.max_delay_days,
        recurrence=found.recurrence,
    )


def apply(
    template: Template,
    home: HomeModel,
    saved: Configuration,
    entities: TariffEntities | None = None,
) -> Configuration:
    """Configuration obtenue : réglages du modèle pour les équipements dont il connaît le type,
    réglages enregistrés pour les autres ; tarif du modèle (entités données), objectif et batterie
    du modèle s'il en a, enregistrés sinon."""
    devices = []
    for device in home.devices:
        settings = device_settings(template, home, device) or saved.of(device.key)
        if settings is not None:
            devices.append(settings.model_copy(update={"default": False}))
    given = (entities or TariffEntities()).model_dump(exclude_none=True)
    return Configuration(
        devices=devices,
        tariff=template.tariff.model_copy(update=given),
        battery=template.battery or saved.battery,
        objective=template.objective or saved.objective,
    )


def _dump(value: BaseModel | None) -> Any:
    return value.model_dump(mode="json", exclude={"default"}) if value is not None else None


def changes(home: HomeModel, before: Configuration, after: Configuration) -> list[Change]:
    """Ce qui change, équipement par équipement, puis tarif, objectif et batterie (réglages
    effectifs : un réglage par défaut et le même réglage enregistré ne diffèrent pas)."""
    old, new = configuration.effective(home, before), configuration.effective(home, after)
    found = []
    for device in home.devices:
        was, will = _dump(old.of(device.key)), _dump(new.of(device.key))
        if was != will:
            found.append(Change(part="device", device=device.key, before=was, after=will))
    for part in ("tariff", "objective", "battery"):
        was, will = _dump(getattr(before, part)), _dump(getattr(after, part))
        if was != will:
            found.append(Change(part=part, before=was, after=will))
    return found


def preview(
    template: Template,
    home: HomeModel,
    saved: Configuration,
    entities: TariffEntities | None = None,
) -> Preview:
    result = apply(template, home, saved, entities)
    return Preview(
        template=template.key,
        configuration=configuration.effective(home, result),
        changes=changes(home, saved, result),
        issues=configuration.validate(home, result),
    )
