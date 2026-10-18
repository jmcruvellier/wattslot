"""Configuration de la maison : ce que l'utilisateur règle sur ses équipements (phase 3).

Socle du modèle de personnalisation (lot 3.1). Pour chaque équipement
du modèle de la maison (``home_model.py``) : son **comportement** pour le calcul (un des types
génériques), son **niveau d'automatisation** et sa prise en
compte par le calcul ; le tarif (``tariff.py``, lot 3.2). Les lots suivants y ajoutent batterie,
réglages par type, contraintes et objectifs.

Enregistrée en RDF dans un graphe à part (décision 12) : réenregistrer le modèle de la maison ne
l'efface pas. Un équipement sans réglages prend ceux par défaut de son type ; des réglages pour un
équipement absent du modèle de la maison sont ignorés à la lecture et refusés à l'écriture.

Validation en Python sur le modèle typé, avec des anomalies codées (traduites par l'interface) :
l'API n'écrit que ce modèle. SHACL viendra avec le designer d'ontologie (phase 2 ter), qui modifie
le graphe directement.
"""

from enum import StrEnum

from pydantic import BaseModel, Field
from pyoxigraph import Literal, NamedNode, Triple

from wattslot.battery_settings import DEFAULT as DEFAULT_BATTERY
from wattslot.battery_settings import BatterySettings
from wattslot.battery_settings import load as load_battery
from wattslot.battery_settings import problems as battery_problems
from wattslot.battery_settings import to_triples as battery_triples
from wattslot.detection import DeviceKind, slug
from wattslot.energy_need import EnergyNeed
from wattslot.energy_need import load as load_need
from wattslot.energy_need import problems as need_problems
from wattslot.energy_need import to_triples as need_triples
from wattslot.home_model import RDF_TYPE, XSD_BOOLEAN, HomeModel, vocab
from wattslot.objective_settings import ObjectiveSettings
from wattslot.objective_settings import load as load_objective
from wattslot.objective_settings import problems as objective_problems
from wattslot.objective_settings import to_triples as objective_triples
from wattslot.ontology import GRAPH_CONFIGURATION, HOME, VOCAB
from wattslot.recurrence_settings import Recurrence
from wattslot.recurrence_settings import load as load_recurrence
from wattslot.recurrence_settings import problems as recurrence_problems
from wattslot.recurrence_settings import to_triples as recurrence_triples
from wattslot.runtime_settings import RuntimeSettings
from wattslot.runtime_settings import load as load_runtime
from wattslot.runtime_settings import problems as runtime_problems
from wattslot.runtime_settings import to_triples as runtime_triples
from wattslot.solar_panels import SolarPanels
from wattslot.solar_panels import load as load_panels
from wattslot.solar_panels import to_triples as panels_triples
from wattslot.storage.graph import GraphStore
from wattslot.tariff import DEFAULT as DEFAULT_TARIFF
from wattslot.tariff import Tariff, problems
from wattslot.tariff import load as load_tariff
from wattslot.tariff import to_triples as tariff_triples
from wattslot.time_constraints import TimeConstraint
from wattslot.time_constraints import load as load_constraints
from wattslot.time_constraints import problems as constraint_problems
from wattslot.time_constraints import to_triples as constraint_triples

VERSION = 1
CONFIGURATION_IRI = NamedNode(f"{HOME}configuration")
XSD_INTEGER = NamedNode("http://www.w3.org/2001/XMLSchema#integer")


class Behavior(StrEnum):
    CYCLE = "CycleBehavior"  # cycle à démarrer : lave-linge, sèche-linge, lave-vaisselle
    ENERGY_BY_DEADLINE = "EnergyByDeadlineBehavior"  # chauffe-eau, véhicule électrique
    RUNTIME = "RuntimeBehavior"  # durée à placer : filtration, déshumidificateur
    STORAGE = "StorageBehavior"  # batterie
    UNCONTROLLED = "UncontrolledBehavior"  # consommation non pilotable
    PRODUCTION = "ProductionBehavior"  # production solaire
    GRID = "GridBehavior"  # raccordement au réseau


class Automation(StrEnum):
    INFORM = "InformAutomation"
    RECOMMEND = "RecommendAutomation"  # la v1 et la première version publique (décision 7)
    CONFIRM = "ConfirmAutomation"
    CONTROL = "ControlAutomation"


# Comportements possibles par type d'équipement, le premier par défaut.
BEHAVIORS: dict[DeviceKind, tuple[Behavior, ...]] = {
    DeviceKind.SOLAR: (Behavior.PRODUCTION,),
    DeviceKind.GRID: (Behavior.GRID,),
    DeviceKind.BATTERY: (Behavior.STORAGE,),
    # Ballon sur contacteur : chauffe jusqu'à la coupure du thermostat, comme un cycle ; en
    # besoin d'énergie s'il est piloté en puissance (routeur solaire).
    DeviceKind.WATER_HEATER: (Behavior.CYCLE, Behavior.ENERGY_BY_DEADLINE, Behavior.UNCONTROLLED),
    DeviceKind.WASHING_MACHINE: (Behavior.CYCLE, Behavior.UNCONTROLLED),
    DeviceKind.DRYER: (Behavior.CYCLE, Behavior.UNCONTROLLED),
    DeviceKind.DISHWASHER: (Behavior.CYCLE, Behavior.UNCONTROLLED),
    DeviceKind.POOL_PUMP: (Behavior.RUNTIME, Behavior.UNCONTROLLED),
    DeviceKind.OTHER_LOAD: (
        Behavior.UNCONTROLLED,
        Behavior.CYCLE,
        Behavior.ENERGY_BY_DEADLINE,
        Behavior.RUNTIME,
    ),
}
# Équipements que l'application ne fait qu'observer : pas de niveau d'automatisation à régler.
OBSERVED = frozenset({Behavior.PRODUCTION, Behavior.GRID, Behavior.UNCONTROLLED})
# Comportements placés par le calcul, auxquels s'appliquent les contraintes horaires.
CONSTRAINED = frozenset({Behavior.CYCLE, Behavior.ENERGY_BY_DEADLINE, Behavior.RUNTIME})


class DeviceSettings(BaseModel):
    key: str  # clé de l'équipement dans le modèle de la maison
    behavior: Behavior
    automation: Automation = Automation.RECOMMEND
    planned: bool = True  # pris en compte par le calcul
    default: bool = False  # réglages par défaut (rien d'enregistré pour cet équipement)
    # Durée de fonctionnement à placer (lot 3.4) : vitesses, durées par saison ; aucun : défaut.
    runtime: RuntimeSettings | None = None
    # Panneaux d'une installation solaire (lot 4.4) : prévision Open-Meteo de repli.
    panels: SolarPanels | None = None
    # Besoin d'énergie avant une échéance (lot 3.4) ; aucun : traité comme un cycle à démarrer.
    energy: EnergyNeed | None = None
    # Contraintes horaires (lot 3.5) : cycles, besoins d'énergie et durées à placer.
    constraints: list[TimeConstraint] = []
    # Cycle à démarrer (lot 3.5) : après la fin du cycle de cet équipement (clé), le même jour ;
    # tolérance de report d'une tâche en attente (jours ; aucune : 2).
    after: str | None = None
    max_delay_days: int | None = Field(default=None, ge=0, le=14)
    # Cycle à démarrer (lot 3.5) : récurrence ; les tâches récurrentes de HA sont alors ignorées.
    recurrence: Recurrence | None = None


class Configuration(BaseModel):
    version: int = VERSION
    devices: list[DeviceSettings] = []
    tariff: Tariff | None = None  # aucun : tarif par défaut (``tariff.DEFAULT``)
    battery: BatterySettings | None = None  # aucun : réglages par défaut (lot 3.3)
    # Objectif du calcul (lot 3.6) ; aucun : le réglage du calcul (coût par défaut).
    objective: ObjectiveSettings | None = None

    def of(self, key: str) -> DeviceSettings | None:
        return next((d for d in self.devices if d.key == key), None)


class Issue(BaseModel):
    code: str  # clé de traduction sous « configuration.issue »
    device: str | None = None
    params: dict[str, str] = {}


def default_settings(key: str, kind: DeviceKind) -> DeviceSettings:
    behavior = BEHAVIORS[kind][0]
    automation = Automation.INFORM if behavior in OBSERVED else Automation.RECOMMEND
    return DeviceSettings(key=key, behavior=behavior, automation=automation, default=True)


def effective(home: HomeModel, saved: Configuration) -> Configuration:
    """Réglages de chaque équipement du modèle de la maison : enregistrés, sinon par défaut."""
    devices = []
    for device in home.devices:
        found = saved.of(device.key)
        devices.append(
            found.model_copy(update={"default": False})
            if found is not None
            else default_settings(device.key, device.kind)
        )
    return Configuration(
        version=saved.version,
        devices=devices,
        tariff=saved.tariff,
        battery=saved.battery,
        objective=saved.objective,
    )


# Comportements des équipements à cycles (mesurés, leurs tâches placées) et de ceux que le
# calcul planifie (leur consommation est retirée de la ligne de base).
CYCLES = frozenset({Behavior.CYCLE, Behavior.ENERGY_BY_DEADLINE})
SCHEDULED = CYCLES | {Behavior.RUNTIME}


def keys_with(
    home: HomeModel, configuration: Configuration, behaviors: frozenset[Behavior]
) -> set[str]:
    """Clés des équipements pris en compte par le calcul dont le comportement est l'un de
    ``behaviors`` (réglages enregistrés, sinon ceux par défaut de leur type)."""
    return {
        settings.key
        for settings in effective(home, configuration).devices
        if settings.planned and settings.behavior in behaviors
    }


def battery_of(configuration: Configuration | None) -> BatterySettings:
    """Réglages de la batterie, ou ceux par défaut s'ils ne sont pas configurés."""
    if configuration is None or configuration.battery is None:
        return DEFAULT_BATTERY
    return configuration.battery


def tariff_of(configuration: Configuration | None) -> Tariff:
    """Tarif de la maison, ou celui par défaut s'il n'est pas configuré."""
    if configuration is None or configuration.tariff is None:
        return DEFAULT_TARIFF
    return configuration.tariff


def validate(home: HomeModel, configuration: Configuration) -> list[Issue]:
    kinds = {device.key: device.kind for device in home.devices}
    issues: list[Issue] = []
    if configuration.version != VERSION:
        issues.append(
            Issue(
                code="unsupported_version",
                params={"version": str(configuration.version), "expected": str(VERSION)},
            )
        )
    seen: set[str] = set()
    for settings in configuration.devices:
        if settings.key in seen:
            issues.append(Issue(code="duplicate_device", device=settings.key))
            continue
        seen.add(settings.key)
        kind = kinds.get(settings.key)
        if kind is None:
            issues.append(Issue(code="unknown_device", device=settings.key))
            continue
        allowed = BEHAVIORS[kind]
        if settings.behavior not in allowed:
            issues.append(
                Issue(
                    code="behavior_not_allowed",
                    device=settings.key,
                    params={
                        "behavior": settings.behavior,
                        "kind": kind,
                        "allowed": ", ".join(allowed),
                    },
                )
            )
        if settings.behavior in OBSERVED and settings.automation is not Automation.INFORM:
            issues.append(Issue(code="observed_automation", device=settings.key))
        if settings.automation in (Automation.CONFIRM, Automation.CONTROL):
            # Pilotage : après la première publication (décision 7).
            issues.append(Issue(code="automation_not_available", device=settings.key))
        if settings.panels is not None and settings.behavior is not Behavior.PRODUCTION:
            issues.append(Issue(code="panels_not_used", device=settings.key))
        if settings.energy is not None:
            if settings.behavior is not Behavior.ENERGY_BY_DEADLINE:
                issues.append(Issue(code="need_not_used", device=settings.key))
            issues += [
                Issue(code=code, device=settings.key, params=params)
                for code, params in need_problems(settings.energy)
            ]
        if settings.constraints:
            if settings.behavior not in CONSTRAINED:
                issues.append(Issue(code="constraints_not_used", device=settings.key))
            issues += [
                Issue(code=code, device=settings.key, params=params)
                for code, params in constraint_problems(settings.constraints)
            ]
        if settings.after is not None:
            if settings.behavior is not Behavior.CYCLE:
                issues.append(Issue(code="after_not_used", device=settings.key))
            if settings.after == settings.key or settings.after not in kinds:
                issues.append(
                    Issue(
                        code="after_unknown", device=settings.key, params={"after": settings.after}
                    )
                )
        if settings.recurrence is not None:
            if settings.behavior is not Behavior.CYCLE:
                issues.append(Issue(code="recurrence_not_used", device=settings.key))
            issues += [
                Issue(code=code, device=settings.key, params=params)
                for code, params in recurrence_problems(settings.recurrence)
            ]
        if settings.max_delay_days is not None and settings.behavior is not Behavior.CYCLE:
            issues.append(Issue(code="delay_not_used", device=settings.key))
        if settings.runtime is not None:
            if settings.behavior is not Behavior.RUNTIME:
                issues.append(Issue(code="runtime_not_used", device=settings.key))
            issues += [
                Issue(code=code, device=settings.key, params=params)
                for code, params in runtime_problems(settings.runtime)
            ]
    if configuration.objective is not None:
        issues += [
            Issue(code=code, params=params)
            for code, params in objective_problems(configuration.objective)
        ]
    if configuration.battery is not None:
        issues += [
            Issue(code=code, params=params)
            for code, params in battery_problems(configuration.battery)
        ]
    if configuration.tariff is not None:
        issues += [
            Issue(code=code, params=params) for code, params in problems(configuration.tariff)
        ]
    return issues


def _settings_iri(key: str) -> NamedNode:
    return NamedNode(f"{HOME}configuration/device/{slug(key)}")


def _device_iri(key: str) -> NamedNode:
    return NamedNode(f"{HOME}device/{slug(key)}")


def to_triples(configuration: Configuration) -> list[Triple]:
    triples = [
        Triple(NamedNode(HOME), vocab("hasConfiguration"), CONFIGURATION_IRI),
        Triple(CONFIGURATION_IRI, RDF_TYPE, vocab("Configuration")),
        Triple(
            CONFIGURATION_IRI,
            vocab("configurationVersion"),
            Literal(str(configuration.version), datatype=XSD_INTEGER),
        ),
    ]
    if configuration.tariff is not None:
        triples += tariff_triples(CONFIGURATION_IRI, configuration.tariff)
    if configuration.battery is not None:
        triples += battery_triples(CONFIGURATION_IRI, configuration.battery)
    if configuration.objective is not None:
        triples += objective_triples(CONFIGURATION_IRI, configuration.objective)
    for settings in configuration.devices:
        node = _settings_iri(settings.key)
        triples += [
            Triple(CONFIGURATION_IRI, vocab("hasDeviceSettings"), node),
            Triple(node, RDF_TYPE, vocab("DeviceSettings")),
            Triple(node, vocab("forDevice"), _device_iri(settings.key)),
            Triple(node, vocab("key"), Literal(settings.key)),
            Triple(node, vocab("behavior"), vocab(settings.behavior)),
            Triple(node, vocab("automation"), vocab(settings.automation)),
            Triple(
                node,
                vocab("planned"),
                Literal(str(settings.planned).lower(), datatype=XSD_BOOLEAN),
            ),
        ]
        if settings.runtime is not None:
            triples += runtime_triples(node, settings.runtime)
        if settings.panels is not None:
            triples += panels_triples(node, settings.panels)
        if settings.energy is not None:
            triples += need_triples(node, settings.energy)
        triples += constraint_triples(node, settings.constraints)
        if settings.recurrence is not None:
            triples += recurrence_triples(node, settings.recurrence)
        if settings.after is not None:
            triples.append(Triple(node, vocab("startsAfterKey"), Literal(settings.after)))
        if settings.max_delay_days is not None:
            triples.append(
                Triple(
                    node,
                    vocab("maxDelayDays"),
                    Literal(str(settings.max_delay_days), datatype=XSD_INTEGER),
                )
            )
    return triples


def save(graph: GraphStore, configuration: Configuration) -> None:
    """Enregistre les réglages (ceux par défaut ne sont pas écrits)."""
    explicit = Configuration(
        version=configuration.version,
        devices=[d for d in configuration.devices if not d.default],
        tariff=configuration.tariff,
        battery=configuration.battery,
        objective=configuration.objective,
    )
    graph.replace_graph(GRAPH_CONFIGURATION, to_triples(explicit))


def load(graph: GraphStore) -> Configuration:
    """Réglages enregistrés (sans ceux par défaut : voir ``effective``)."""
    version = VERSION
    for row in graph.select(
        f"""
        PREFIX wattslot: <{VOCAB}>
        SELECT ?version WHERE {{
          GRAPH <{GRAPH_CONFIGURATION}> {{
            <{CONFIGURATION_IRI.value}> wattslot:configurationVersion ?version
          }}
        }}
        """
    ):
        version = int(row["version"])
    devices = [
        DeviceSettings(
            key=row["key"],
            behavior=Behavior(row["behavior"].removeprefix(VOCAB)),
            automation=Automation(row["automation"].removeprefix(VOCAB)),
            planned=row["planned"] == "true",
            runtime=load_runtime(graph, GRAPH_CONFIGURATION, row["settings"], VOCAB),
            energy=load_need(graph, GRAPH_CONFIGURATION, row["settings"], VOCAB),
            panels=load_panels(graph, GRAPH_CONFIGURATION, row["settings"], VOCAB),
            constraints=load_constraints(graph, GRAPH_CONFIGURATION, row["settings"], VOCAB),
            after=row.get("after"),
            recurrence=load_recurrence(graph, GRAPH_CONFIGURATION, row["settings"], VOCAB),
            max_delay_days=int(row["delay"]) if "delay" in row else None,
        )
        for row in graph.select(
            f"""
            PREFIX wattslot: <{VOCAB}>
            SELECT ?settings ?key ?behavior ?automation ?planned ?after ?delay WHERE {{
              GRAPH <{GRAPH_CONFIGURATION}> {{
                <{CONFIGURATION_IRI.value}> wattslot:hasDeviceSettings ?settings .
                ?settings wattslot:key ?key ; wattslot:behavior ?behavior ;
                  wattslot:automation ?automation ;
                  wattslot:planned ?planned .
                OPTIONAL {{ ?settings wattslot:startsAfterKey ?after }}
                OPTIONAL {{ ?settings wattslot:maxDelayDays ?delay }}
              }}
            }}
            """
        )
    ]
    return Configuration(
        version=version,
        devices=sorted(devices, key=lambda d: d.key),
        tariff=load_tariff(graph, GRAPH_CONFIGURATION, CONFIGURATION_IRI, VOCAB),
        battery=load_battery(graph, GRAPH_CONFIGURATION, CONFIGURATION_IRI, VOCAB),
        objective=load_objective(graph, GRAPH_CONFIGURATION, CONFIGURATION_IRI, VOCAB),
    )
