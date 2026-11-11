"""Propositions de rôles pour les entités de la maison, à partir de l'instantané de HA.

Point de départ : le tableau Énergie (sources et appareils suivis). Chaque entité proposée est
contrôlée (unité, classe), et les manques sont signalés plutôt qu'ignorés. Contrôles tirés de la
lecture d'une vraie installation le 15/10/2026 :

- une entité de coût ou de puissance peut être déclarée comme compteur d'énergie ;
- un compteur peut être quotidien (remis à zéro chaque nuit) ;
- la capacité de la batterie peut manquer ;
- les appareils n'ont souvent qu'un compteur d'énergie : la puissance, indispensable à la
  détection des cycles, est cherchée sur le même appareil HA ;
- beaucoup d'appareils sont sans intérêt pour la planification (consommation non pilotable).

Les problèmes sont structurés (code + paramètres) et traduits à l'affichage, comme les
avertissements de la v1.
"""

import re
import unicodedata
from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from wattslot.home_assistant import HomeSnapshot

ENERGY_UNITS = {"Wh", "kWh", "MWh"}
POWER_UNITS = {"W", "kW"}


class DeviceKind(StrEnum):
    SOLAR = "SolarInstallation"
    GRID = "GridConnection"
    BATTERY = "Battery"
    WATER_HEATER = "WaterHeater"
    WASHING_MACHINE = "WashingMachine"
    DRYER = "Dryer"
    DISHWASHER = "Dishwasher"
    POOL_PUMP = "PoolPump"
    OTHER_LOAD = "OtherLoad"


class Supply(StrEnum):
    """Alimentation de la maison par le réseau."""

    SINGLE = "SinglePhaseSupply"
    THREE = "ThreePhaseSupply"


class Phase(StrEnum):
    """Branchement d'un équipement dans une maison en triphasé : une phase, ou les trois
    (équipement triphasé, réparti à parts égales)."""

    L1 = "PhaseL1"
    L2 = "PhaseL2"
    L3 = "PhaseL3"
    ALL = "ThreePhases"


class Role(StrEnum):
    ENERGY_PRODUCED = "EnergyProduced"
    POWER_PRODUCED = "PowerProduced"
    ENERGY_IMPORTED = "EnergyImported"
    ENERGY_EXPORTED = "EnergyExported"
    ENERGY_CHARGED = "EnergyCharged"
    ENERGY_DISCHARGED = "EnergyDischarged"
    STATE_OF_CHARGE = "StateOfCharge"
    ENERGY_CONSUMED = "EnergyConsumed"
    POWER_CONSUMED = "PowerConsumed"


ENERGY_ROLES = {
    Role.ENERGY_PRODUCED,
    Role.ENERGY_IMPORTED,
    Role.ENERGY_EXPORTED,
    Role.ENERGY_CHARGED,
    Role.ENERGY_DISCHARGED,
    Role.ENERGY_CONSUMED,
}
POWER_ROLES = {Role.POWER_PRODUCED, Role.POWER_CONSUMED}

# Équipements reconnus par leur nom (français, anglais), mots entiers, du plus spécifique au plus
# général : « lave-vaisselle » avant « lave-linge » (« dishwasher » contient « washer »),
# « sèche-linge » avant « lave-linge », mais « lave-linge séchant » reste un lave-linge.
KIND_KEYWORDS: tuple[tuple[DeviceKind, tuple[str, ...]], ...] = (
    (DeviceKind.DISHWASHER, ("lave vaisselle", "dishwasher")),
    (DeviceKind.DRYER, ("seche linge", "dryer", "tumble dryer")),
    (DeviceKind.WASHING_MACHINE, ("lave linge", "washing machine", "washer")),
    (DeviceKind.WATER_HEATER, ("chauffe eau", "ballon", "cumulus", "water heater", "boiler")),
    (DeviceKind.POOL_PUMP, ("piscine", "filtration", "pool")),
)
DAILY_HINTS = ("daily", "today", "quotidien", "journalier", "jour")
# Mots (entiers, sans accents) qui désignent la capacité d'une batterie.
CAPACITY_WORDS = ("capacity", "capacite", "total energy", "energie totale", "rated energy")
# Mots (entiers, sans accents) qui trahissent un coût plutôt qu'une énergie.
COST_WORDS = (
    "cout",
    "couts",
    "cost",
    "costs",
    "prix",
    "price",
    "tarif",
    "tariff",
    "abonnement",
    "subscription",
    "facture",
    "bill",
    "eur",
    "euro",
    "euros",
)


# Marques d'une phase dans le nom d'une entité ou d'un appareil de HA, en mots entiers une
# fois le nom normalisé : « l1 », « phase 1 », « phase a », « channel a » (pince d'un compteur
# triphasé). Pas « channel 1 » : les deux pinces d'un compteur monophasé se nomment ainsi.
_PHASE_MARKS: tuple[tuple[Phase, tuple[str, ...]], ...] = (
    (Phase.L1, ("l1", "phase 1", "phase a", "channel a")),
    (Phase.L2, ("l2", "phase 2", "phase b", "channel b")),
    (Phase.L3, ("l3", "phase 3", "phase c", "channel c")),
)
# Mots qui désignent l'énergie rendue au réseau dans le nom d'un compteur par phase.
EXPORT_WORDS = ("returned", "return", "export", "exported", "injection", "injecte", "to grid")


def phase_of(*texts: str | None) -> Phase | None:
    """Phase que nomme une entité ou son appareil, s'ils en nomment une et une seule."""
    text = f" {_normalize(' '.join(t for t in texts if t))} "
    found = {phase for phase, marks in _PHASE_MARKS if any(f" {mark} " in text for mark in marks)}
    return found.pop() if len(found) == 1 else None


class Issue(BaseModel):
    code: str
    params: dict[str, str] = {}


class SensorProposal(BaseModel):
    entity_id: str
    role: Role
    name: str | None = None
    unit: str | None = None
    resets_daily: bool = False
    excluded: bool = False  # proposé exclu du modèle (l'utilisateur peut le reprendre)
    issues: list[Issue] = []
    # Capteur du réseau qui ne mesure qu'une phase, d'après son nom ; ``None`` : le total.
    phase: Phase | None = None


class DeviceProposal(BaseModel):
    key: str
    kind: DeviceKind
    name: str
    sensors: list[SensorProposal]
    capacity_kwh: float | None = None
    capacity_source: str | None = None  # entité HA dont la capacité a été lue
    issues: list[Issue] = []
    phase: Phase | None = None  # phase que nomme l'équipement ou son compteur dans HA


class HomeProposal(BaseModel):
    energy_dashboard: bool
    devices: list[DeviceProposal] = []
    # Triphasé quand un capteur ou un équipement de HA nomme une phase ; ``None`` : rien ne
    # le dit (monophasé, ou triphasé sans nom qui le montre).
    supply: Supply | None = None


def _normalize(text: str) -> str:
    """Minuscules sans accents, séparateurs (``_ . -``) remplacés par des espaces."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[_.\-]+", " ", text.lower())


def _daily_reset(entity_id: str, attributes: dict[str, Any]) -> bool:
    """Compteur remis à zéro chaque jour : ``state_class: total`` avec ``last_reset``, ou nom."""
    return (attributes.get("state_class") == "total" and "last_reset" in attributes) or any(
        hint in _normalize(entity_id) for hint in DAILY_HINTS
    )


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _normalize(text)).strip("-") or "x"


WORD = r"\b{}\b"  # mot entier


def _has_word(text: str, words: tuple[str, ...]) -> bool:
    normalized = _normalize(text)
    return any(re.search(WORD.format(re.escape(word)), normalized) for word in words)


def classify_appliance(*names: str | None) -> DeviceKind:
    text = " ".join(n for n in names if n)
    for kind, keywords in KIND_KEYWORDS:
        if _has_word(text, keywords):
            return kind
    return DeviceKind.OTHER_LOAD


# Noms donnés au réseau et à une batterie sans nom dans HA, dans la langue de Home Assistant
# (enregistrés avec la maison, puis modifiables).
DEFAULT_NAMES: dict[str, dict[str, str]] = {
    "fr": {"grid": "Réseau", "battery": "Batterie"},
    "en": {"grid": "Grid", "battery": "Battery"},
    "de": {"grid": "Netz", "battery": "Batterie"},
    "nl": {"grid": "Net", "battery": "Batterij"},
    "es": {"grid": "Red", "battery": "Batería"},
    "it": {"grid": "Rete", "battery": "Batteria"},
}


class _Detector:
    def __init__(self, snapshot: HomeSnapshot) -> None:
        self.snapshot = snapshot
        self.used: set[str] = set()

    def default_name(self, key: str) -> str:
        language = str(self.snapshot.config.get("language") or "en").split("-")[0]
        return DEFAULT_NAMES.get(language, DEFAULT_NAMES["en"])[key]

    def attributes(self, entity_id: str) -> dict[str, Any]:
        state = self.snapshot.states.get(entity_id) or {}
        return dict(state.get("attributes") or {})

    def friendly_name(self, entity_id: str) -> str | None:
        return self.attributes(entity_id).get("friendly_name")

    def device_name(self, entity_id: str) -> str | None:
        device_id = (self.snapshot.entities.get(entity_id) or {}).get("device_id")
        device = self.snapshot.devices.get(device_id or "") or {}
        return device.get("name_by_user") or device.get("name")

    def sensor(self, entity_id: str, role: Role) -> SensorProposal:
        self.used.add(entity_id)
        attributes = self.attributes(entity_id)
        unit = attributes.get("unit_of_measurement")
        device_class = attributes.get("device_class")
        issues: list[Issue] = []
        if entity_id not in self.snapshot.states:
            issues.append(Issue(code="entity_missing", params={"entity": entity_id}))
        elif role in ENERGY_ROLES:
            if unit not in ENERGY_UNITS:
                issues.append(
                    Issue(code="not_energy_unit", params={"entity": entity_id, "unit": unit or ""})
                )
            elif device_class not in (None, "energy"):
                issues.append(
                    Issue(
                        code="unexpected_device_class",
                        params={"entity": entity_id, "device_class": str(device_class)},
                    )
                )
        elif role in POWER_ROLES and unit not in POWER_UNITS:
            issues.append(
                Issue(code="not_power_unit", params={"entity": entity_id, "unit": unit or ""})
            )
        elif role is Role.STATE_OF_CHARGE and unit != "%":
            issues.append(
                Issue(code="not_percent_unit", params={"entity": entity_id, "unit": unit or ""})
            )
        resets_daily = role in ENERGY_ROLES and _daily_reset(entity_id, attributes)
        # Un compteur artificiel peut servir à faire apparaître un coût (abonnement) dans le
        # tableau Énergie, avec une unité d'énergie : constaté le 15/10/2026. Proposé exclu.
        excluded = role in ENERGY_ROLES and _has_word(
            f"{entity_id} {self.friendly_name(entity_id) or ''}", COST_WORDS
        )
        if excluded:
            issues.append(Issue(code="name_suggests_cost", params={"entity": entity_id}))
        return SensorProposal(
            entity_id=entity_id,
            role=role,
            name=self.friendly_name(entity_id),
            unit=unit,
            resets_daily=resets_daily,
            excluded=excluded,
            issues=issues,
        )

    def phase(self, *entity_ids: str | None) -> Phase | None:
        """Phase que nomment ces entités ou leur appareil HA, d'après leurs noms."""
        names: list[str | None] = []
        for entity_id in entity_ids:
            if entity_id:
                names += [entity_id, self.friendly_name(entity_id), self.device_name(entity_id)]
        return phase_of(*names)

    def phase_meters(self, grid: list[SensorProposal]) -> list[SensorProposal]:
        """Compteurs par phase du même appareil HA que les compteurs du réseau (compteur
        triphasé, pinces sur chaque phase) : au plus un de soutirage et un d'injection par
        phase, que le tableau Énergie ne connaît pas."""
        devices = {
            (self.snapshot.entities.get(sensor.entity_id) or {}).get("device_id") for sensor in grid
        } - {None}
        taken = {(sensor.role, sensor.phase) for sensor in grid if sensor.phase is not None}
        found: list[SensorProposal] = []
        for entity_id, entry in sorted(self.snapshot.entities.items()):
            if entry.get("device_id") not in devices or entity_id in self.used:
                continue
            if not entity_id.startswith("sensor."):
                continue
            attributes = self.attributes(entity_id)
            counter = attributes.get("state_class") in ("total", "total_increasing")
            if attributes.get("unit_of_measurement") not in ENERGY_UNITS or not counter:
                continue
            name = f"{entity_id} {attributes.get('friendly_name') or ''}"
            phase = phase_of(name)
            role = Role.ENERGY_EXPORTED if _has_word(name, EXPORT_WORDS) else Role.ENERGY_IMPORTED
            if phase is None or (role, phase) in taken:
                continue
            taken.add((role, phase))
            found.append(self.sensor(entity_id, role).model_copy(update={"phase": phase}))
        return found

    def sibling_capacity(self, entity_id: str) -> tuple[str, float] | None:
        """Capacité (kWh) lue sur une entité du même appareil HA qu'une entité de la batterie.

        Entité d'énergie qui n'est pas un compteur cumulé, dont le nom évoque une capacité ou
        une énergie totale (exemple : ``…_battery_total_energy`` d'une Marstek, déclarée
        ``state_class: total`` et utilisée comme capacité par son intégration).
        """
        device_id = (self.snapshot.entities.get(entity_id) or {}).get("device_id")
        if not device_id:
            return None
        for other_id, entry in self.snapshot.entities.items():
            if entry.get("device_id") != device_id:
                continue
            state = self.snapshot.states.get(other_id) or {}
            attributes = dict(state.get("attributes") or {})
            unit = attributes.get("unit_of_measurement")
            # Les intégrations Marstek déclarent la capacité en « total » : seuls les vrais
            # compteurs (croissants, ou remis à zéro) sont écartés.
            counter = attributes.get("state_class") == "total_increasing" or (
                attributes.get("state_class") == "total" and "last_reset" in attributes
            )
            if unit not in ("Wh", "kWh") or counter:
                continue
            name = f"{other_id} {attributes.get('friendly_name') or ''}"
            if not _has_word(name, CAPACITY_WORDS):
                continue
            try:
                value = float(state.get("state", ""))
            except ValueError:
                continue
            kwh = value / 1000 if unit == "Wh" else value
            if kwh > 0:
                return other_id, round(kwh, 3)
        return None

    def sibling_power(self, entity_id: str) -> str | None:
        """Entité de puissance du même appareil HA qu'un compteur d'énergie."""
        device_id = (self.snapshot.entities.get(entity_id) or {}).get("device_id")
        if not device_id:
            return None
        for other_id, entry in self.snapshot.entities.items():
            if other_id == entity_id or entry.get("device_id") != device_id:
                continue
            # Une mesure seulement : un ``number.`` en W est un réglage (limite d'onduleur…).
            if not other_id.startswith("sensor."):
                continue
            attributes = self.attributes(other_id)
            if (
                attributes.get("device_class") == "power"
                or attributes.get("unit_of_measurement") in POWER_UNITS
            ):
                return other_id
        return None

    def with_power(
        self, energy_id: str, power_id: str | None, energy_role: Role, power_role: Role
    ) -> tuple[list[SensorProposal], list[Issue]]:
        sensors = [self.sensor(energy_id, energy_role)]
        power = power_id or self.sibling_power(energy_id)
        if power:
            sensors.append(self.sensor(power, power_role))
            return sensors, []
        return sensors, [Issue(code="no_power_sensor", params={"entity": energy_id})]


class EntityChoice(BaseModel):
    """Entité de HA qu'on peut lier à un équipement, ajouté à la main (lot 2t.2) ou en
    remplaçant un capteur d'un équipement suivi."""

    entity_id: str
    name: str | None = None
    unit: str | None = None
    roles: list[Role]  # rôles possibles d'après l'unité
    resets_daily: bool = False  # compteur d'énergie remis à zéro chaque jour


def sensor_choices(snapshot: HomeSnapshot) -> list[EntityChoice]:
    """Capteurs de HA utilisables par le calcul, avec les rôles que leur unité permet : énergie
    (compteurs), puissance, pourcentage (état de charge)."""
    found = []
    for entity_id, state in sorted(snapshot.states.items()):
        if not entity_id.startswith("sensor."):
            continue
        attributes = state.get("attributes") or {}
        unit = attributes.get("unit_of_measurement")
        if unit in ENERGY_UNITS:
            roles = sorted(ENERGY_ROLES)
        elif unit in POWER_UNITS:
            roles = sorted(POWER_ROLES)
        elif unit == "%":
            roles = [Role.STATE_OF_CHARGE]
        else:
            continue
        found.append(
            EntityChoice(
                entity_id=entity_id,
                name=attributes.get("friendly_name"),
                unit=unit,
                roles=roles,
                resets_daily=unit in ENERGY_UNITS and _daily_reset(entity_id, attributes),
            )
        )
    return found


def propose(snapshot: HomeSnapshot) -> HomeProposal:
    preferences = snapshot.energy_preferences
    if preferences is None:
        return HomeProposal(energy_dashboard=False)

    detector = _Detector(snapshot)
    devices: list[DeviceProposal] = []
    grid_sensors: list[SensorProposal] = []

    for source in preferences.get("energy_sources", []):
        kind = source.get("type")
        if kind == "solar":
            energy = source["stat_energy_from"]
            sensors, issues = detector.with_power(
                energy, source.get("stat_rate"), Role.ENERGY_PRODUCED, Role.POWER_PRODUCED
            )
            name = detector.device_name(energy) or detector.friendly_name(energy) or energy
            devices.append(
                DeviceProposal(
                    key=f"solar-{slug(energy)}",
                    kind=DeviceKind.SOLAR,
                    name=name,
                    sensors=sensors,
                    issues=issues,
                    phase=detector.phase(energy),
                )
            )
        elif kind == "grid":
            imports = [source.get("stat_energy_from")] + [
                f.get("stat_energy_from") for f in source.get("flow_from", [])
            ]
            exports = [source.get("stat_energy_to")] + [
                f.get("stat_energy_to") for f in source.get("flow_to", [])
            ]
            grid_sensors += [detector.sensor(e, Role.ENERGY_IMPORTED) for e in imports if e]
            grid_sensors += [detector.sensor(e, Role.ENERGY_EXPORTED) for e in exports if e]
        elif kind == "battery":
            discharge = source["stat_energy_from"]
            sensors = [
                detector.sensor(source["stat_energy_to"], Role.ENERGY_CHARGED),
                detector.sensor(discharge, Role.ENERGY_DISCHARGED),
            ]
            if source.get("stat_soc"):
                sensors.append(detector.sensor(source["stat_soc"], Role.STATE_OF_CHARGE))
            capacity = source.get("capacity")
            capacity_source = None
            if not capacity:
                # Absente du tableau Énergie : cherchée sur l'appareil HA de la batterie.
                candidates = [source.get("stat_soc"), discharge, source["stat_energy_to"]]
                for entity_id in filter(None, candidates):
                    found = detector.sibling_capacity(entity_id)
                    if found:
                        capacity_source, capacity = found
                        break
            issues = [] if capacity else [Issue(code="battery_capacity_missing")]
            if not source.get("stat_soc"):
                issues.append(Issue(code="battery_soc_missing"))
            devices.append(
                DeviceProposal(
                    key=f"battery-{slug(discharge)}",
                    kind=DeviceKind.BATTERY,
                    name=detector.device_name(discharge) or detector.default_name("battery"),
                    sensors=sensors,
                    capacity_kwh=capacity,
                    capacity_source=capacity_source,
                    issues=issues,
                    phase=detector.phase(discharge, source.get("stat_soc")),
                )
            )

    if grid_sensors:
        # Compteurs du tableau Énergie qui nomment une phase (le nom de l'entité seulement : celui
        # de l'appareil ne dit pas ce que mesure ce capteur), puis ceux du même appareil HA.
        grid_sensors = [
            sensor
            if sensor.excluded
            else sensor.model_copy(
                update={
                    "phase": phase_of(sensor.entity_id, detector.friendly_name(sensor.entity_id))
                }
            )
            for sensor in grid_sensors
        ]
        grid_sensors += detector.phase_meters(grid_sensors)
        devices.append(
            DeviceProposal(
                key="grid",
                kind=DeviceKind.GRID,
                name=detector.default_name("grid"),
                sensors=grid_sensors,
            )
        )

    for device in preferences.get("device_consumption", []):
        energy = device["stat_consumption"]
        name = device.get("name") or detector.friendly_name(energy) or energy
        kind = classify_appliance(name, detector.device_name(energy), energy)
        sensors, issues = detector.with_power(
            energy, device.get("stat_rate"), Role.ENERGY_CONSUMED, Role.POWER_CONSUMED
        )
        if kind is DeviceKind.OTHER_LOAD:
            issues = []  # La puissance ne sert qu'aux équipements planifiés (cycles).
        devices.append(
            DeviceProposal(
                key=f"{slug(kind)}-{slug(energy)}",
                kind=kind,
                name=name,
                sensors=sensors,
                issues=issues,
                phase=detector.phase(energy),
            )
        )

    named = any(
        device.phase is not None or any(sensor.phase is not None for sensor in device.sensors)
        for device in devices
    )
    return HomeProposal(
        energy_dashboard=True, devices=devices, supply=Supply.THREE if named else None
    )
