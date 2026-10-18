"""Modèle de la maison : équipements, capteurs, rôles, liaisons aux entités HA.

Enregistré en RDF dans le graphe de la maison (décision 12), avec la bibliothèque
« Énergie domestique » (``ontology/library/home-energy.ttl``). Les identifiants d'entités HA ne
vivent que dans le magasin de l'installation, jamais dans le dépôt (décision 2).
"""

from importlib import resources

from pydantic import BaseModel
from pyoxigraph import Literal, NamedNode, Triple

from wattslot.detection import DeviceKind, Role, slug
from wattslot.ontology import (
    BASE,
    GRAPH_HOME,
    GRAPH_LIBRARY,
    GRAPH_SCHEMA,
    HOME,
    VOCAB,
)
from wattslot.storage.graph import GraphStore

RDF_TYPE = NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")
RDFS_LABEL = NamedNode("http://www.w3.org/2000/01/rdf-schema#label")
RDFS_SUBCLASS_OF = NamedNode("http://www.w3.org/2000/01/rdf-schema#subClassOf")
OWL_CLASS = NamedNode("http://www.w3.org/2002/07/owl#Class")
XSD_DOUBLE = NamedNode("http://www.w3.org/2001/XMLSchema#double")
XSD_BOOLEAN = NamedNode("http://www.w3.org/2001/XMLSchema#boolean")
HOME_IRI = NamedNode(HOME)


def vocab(name: str) -> NamedNode:
    return NamedNode(f"{VOCAB}{name}")


class HomeSensor(BaseModel):
    entity_id: str
    role: Role
    resets_daily: bool = False


class HomeDevice(BaseModel):
    key: str
    kind: DeviceKind
    name: str
    sensors: list[HomeSensor]
    capacity_kwh: float | None = None
    # Type propre (clé d'un ``HomeModel.types``), sous-type de ``kind`` ; ``kind`` reste le type
    # de la bibliothèque, celui que lit le calcul.
    custom_type: str | None = None


class DeviceType(BaseModel):
    """Type d'équipement propre à l'installation (lot 2t.1) : sous-classe d'un type de la
    bibliothèque, dont ses équipements prennent les comportements et les règles de mesure."""

    key: str
    name: str
    parent: DeviceKind


class HomeModel(BaseModel):
    devices: list[HomeDevice] = []
    types: list[DeviceType] = []  # types propres à l'installation


# Types de la bibliothèque qui peuvent avoir des sous-types propres : tous sauf le raccordement
# au réseau (un seul par maison).
TYPE_PARENTS = tuple(kind for kind in DeviceKind if kind is not DeviceKind.GRID)


# Rôles qu'on attend des capteurs d'un équipement de chaque type (indication de la bibliothèque,
# lot 2t.2 : ce que le calcul sait lire).
_APPLIANCE = (Role.POWER_CONSUMED, Role.ENERGY_CONSUMED)
EXPECTED_ROLES: dict[DeviceKind, tuple[Role, ...]] = {
    DeviceKind.SOLAR: (Role.ENERGY_PRODUCED, Role.POWER_PRODUCED),
    DeviceKind.GRID: (Role.ENERGY_IMPORTED, Role.ENERGY_EXPORTED),
    DeviceKind.BATTERY: (Role.ENERGY_CHARGED, Role.ENERGY_DISCHARGED, Role.STATE_OF_CHARGE),
    DeviceKind.WATER_HEATER: _APPLIANCE,
    DeviceKind.WASHING_MACHINE: _APPLIANCE,
    DeviceKind.DRYER: _APPLIANCE,
    DeviceKind.DISHWASHER: _APPLIANCE,
    DeviceKind.POOL_PUMP: _APPLIANCE,
    DeviceKind.OTHER_LOAD: _APPLIANCE,
}


def problems(model: HomeModel) -> list[tuple[str, str | None, dict[str, str]]]:
    """Anomalies du modèle (code, équipement ou type, paramètres) : clés en double, type propre
    inconnu ou d'un autre parent que le type de l'équipement."""
    found: list[tuple[str, str | None, dict[str, str]]] = []
    device_keys = [d.key for d in model.devices]
    for key in sorted({k for k in device_keys if device_keys.count(k) > 1}):
        found.append(("duplicate_device", key, {}))
    type_keys = [t.key for t in model.types]
    for key in sorted({k for k in type_keys if type_keys.count(k) > 1}):
        found.append(("duplicate_type", key, {}))
    types = {t.key: t for t in model.types}
    for device_type in model.types:
        if device_type.parent not in TYPE_PARENTS:
            found.append(("type_parent_not_allowed", device_type.key, {}))
    for device in model.devices:
        if device.custom_type is None:
            continue
        own = types.get(device.custom_type)
        if own is None:
            found.append(("type_unknown", device.key, {"type": device.custom_type}))
        elif own.parent is not device.kind:
            params = {"type": own.name, "parent": own.parent.value, "kind": device.kind.value}
            found.append(("type_kind_mismatch", device.key, params))
    return found


def type_key(name: str, existing: list[DeviceType]) -> str:
    """Clé d'un nouveau type, tirée de son nom, unique dans la maison."""
    base = slug(name) or "type"
    key, n = base, 2
    while any(t.key == key for t in existing):
        key, n = f"{base}-{n}", n + 1
    return key


VOCABULARY_FILES = {GRAPH_LIBRARY: "library/home-energy.ttl", GRAPH_SCHEMA: "schema.ttl"}


def load_vocabulary(graph: GraphStore) -> None:
    """Bibliothèque et schéma, chacun dans son graphe, remplacés à chaque démarrage."""
    folder = resources.files("wattslot.ontology")
    for graph_iri, name in VOCABULARY_FILES.items():
        turtle = folder.joinpath(name).read_bytes()
        graph.replace_graph_turtle(graph_iri, turtle, base_iri=BASE)


def _device_iri(key: str) -> NamedNode:
    return NamedNode(f"{HOME}device/{slug(key)}")


def sensor_iri(device_key: str, entity_id: str) -> str:
    """IRI du capteur d'un équipement (partagée avec les relevés bruts)."""
    return f"{HOME}sensor/{slug(device_key)}/{slug(entity_id)}"


def _type_iri(key: str) -> NamedNode:
    return NamedNode(f"{HOME}type/{slug(key)}")


def to_triples(model: HomeModel) -> list[Triple]:
    triples = [Triple(HOME_IRI, RDF_TYPE, vocab("Home"))]
    for device_type in model.types:
        type_iri = _type_iri(device_type.key)
        triples += [
            Triple(type_iri, RDF_TYPE, OWL_CLASS),
            Triple(type_iri, RDFS_SUBCLASS_OF, vocab(device_type.parent)),
            Triple(type_iri, RDFS_LABEL, Literal(device_type.name)),
            Triple(type_iri, vocab("typeKey"), Literal(device_type.key)),
        ]
    for device in model.devices:
        device_iri = _device_iri(device.key)
        triples += [
            Triple(HOME_IRI, vocab("hasDevice"), device_iri),
            Triple(device_iri, RDF_TYPE, vocab(device.kind)),
            Triple(device_iri, RDFS_LABEL, Literal(device.name)),
            Triple(device_iri, vocab("key"), Literal(device.key)),
        ]
        if device.custom_type is not None:
            triples.append(Triple(device_iri, RDF_TYPE, _type_iri(device.custom_type)))
        if device.capacity_kwh is not None:
            triples.append(
                Triple(
                    device_iri,
                    vocab("capacityKwh"),
                    Literal(str(device.capacity_kwh), datatype=XSD_DOUBLE),
                )
            )
        for sensor in device.sensors:
            sensor_node = NamedNode(sensor_iri(device.key, sensor.entity_id))
            triples += [
                Triple(device_iri, vocab("hasSensor"), sensor_node),
                Triple(sensor_node, RDF_TYPE, vocab("Sensor")),
                Triple(sensor_node, vocab("role"), vocab(sensor.role)),
                Triple(sensor_node, vocab("haEntity"), Literal(sensor.entity_id)),
                Triple(
                    sensor_node,
                    vocab("resetsDaily"),
                    Literal(str(sensor.resets_daily).lower(), datatype=XSD_BOOLEAN),
                ),
            ]
    return triples


def save(graph: GraphStore, model: HomeModel) -> None:
    graph.replace_graph(GRAPH_HOME, to_triples(model))


def load(graph: GraphStore) -> HomeModel:
    rows = graph.select(
        f"""
        PREFIX wattslot: <{VOCAB}>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT ?device ?key ?kind ?name ?capacity ?entity ?role ?daily ?own WHERE {{
          GRAPH <{GRAPH_HOME}> {{
            <{HOME}> wattslot:hasDevice ?device .
            ?device a ?kind ; rdfs:label ?name ; wattslot:key ?key .
            FILTER (STRSTARTS(STR(?kind), "{VOCAB}"))
            OPTIONAL {{ ?device a ?type . ?type wattslot:typeKey ?own }}
            OPTIONAL {{ ?device wattslot:capacityKwh ?capacity }}
            OPTIONAL {{
              ?device wattslot:hasSensor ?sensor .
              ?sensor wattslot:haEntity ?entity ; wattslot:role ?role ;
                wattslot:resetsDaily ?daily .
            }}
          }}
        }}
        """
    )
    devices: dict[str, HomeDevice] = {}
    for row in rows:
        key = row["key"]
        if key not in devices:
            capacity = row.get("capacity")
            devices[key] = HomeDevice(
                key=key,
                kind=DeviceKind(row["kind"].removeprefix(VOCAB)),
                name=row["name"],
                sensors=[],
                capacity_kwh=float(capacity) if capacity else None,
                custom_type=row.get("own"),
            )
        if "entity" in row:
            devices[key].sensors.append(
                HomeSensor(
                    entity_id=row["entity"],
                    role=Role(row["role"].removeprefix(VOCAB)),
                    resets_daily=row["daily"] == "true",
                )
            )
    for device in devices.values():
        device.sensors.sort(key=lambda s: (s.role, s.entity_id))
    return HomeModel(
        devices=sorted(devices.values(), key=lambda d: (d.kind, d.key)), types=_types(graph)
    )


def _types(graph: GraphStore) -> list[DeviceType]:
    rows = graph.select(
        f"""
        PREFIX wattslot: <{VOCAB}>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT ?key ?name ?parent WHERE {{
          GRAPH <{GRAPH_HOME}> {{
            ?type wattslot:typeKey ?key ; rdfs:label ?name ; rdfs:subClassOf ?parent .
          }}
        }}
        """
    )
    return sorted(
        (
            DeviceType(
                key=r["key"], name=r["name"], parent=DeviceKind(r["parent"].removeprefix(VOCAB))
            )
            for r in rows
        ),
        key=lambda t: t.key,
    )
